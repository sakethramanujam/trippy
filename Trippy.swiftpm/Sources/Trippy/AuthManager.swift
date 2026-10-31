import Foundation
import SwiftUI

struct AuthProfile: Codable, Equatable {
    let id: Int
    let email: String
    let name: String
    let initials: String
    let home_airport: String?
}

struct AuthResponse: Decodable {
    let access_token: String
    let refresh_token: String
    let expires_in: Int?
    let user: AuthProfile
    let claimed: [String]?
}

/// An error with a message that can go straight into the UI.
struct APIError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }

    /// FastAPI's `detail` is a string for our own errors and a list for validation errors.
    static func from(status: Int, data: Data) -> APIError {
        let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let detail = obj?["detail"] as? String { return APIError(status: status, message: detail) }
        if let list = obj?["detail"] as? [[String: Any]], let first = list.first?["msg"] as? String {
            return APIError(status: status, message: first.replacingOccurrences(of: "Value error, ", with: ""))
        }
        switch status {
        case 401: return APIError(status: status, message: "Your session has ended. Log in again.")
        case 429: return APIError(status: status, message: "Too many attempts. Wait a minute and try again.")
        case 500...: return APIError(status: status, message: "The Trippy server had a problem (\(status)).")
        default: return APIError(status: status, message: "Request failed (\(status)).")
        }
    }

    static func network(_ error: Error) -> APIError {
        if let e = error as? APIError { return e }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCannotFindHost, NSURLErrorCannotConnectToHost, NSURLErrorTimedOut,
                 NSURLErrorNetworkConnectionLost, NSURLErrorNotConnectedToInternet:
                return APIError(status: 0, message: "Can't reach the Trippy server at \(APIConfig.baseURL). Check your connection, or change the server on the sign-in screen.")
            default: break
            }
        }
        return APIError(status: 0, message: error.localizedDescription)
    }
}

/// Session state: tokens in the Keychain, the signed-in profile, sign up / log in / log out.
@MainActor
final class AuthManager: ObservableObject {
    static let shared = AuthManager()

    enum State: Equatable { case signedOut, signedIn(AuthProfile), devBypass }

    @Published private(set) var state: State
    /// Shown once after sign-up, e.g. "existing Trippy data (first account on this server)".
    @Published var claimedOnSignup: [String] = []

    private var refreshTask: Task<Bool, Never>?
    private static let accessKey = "access", refreshKey = "refresh", profileKey = "TrippyProfile"

    /// `-TrippyAuthBypass YES` (screenshots against a server started with TRIPPY_DEV_AUTH_BYPASS=1).
    static var bypassRequested: Bool { UserDefaults.standard.bool(forKey: "TrippyAuthBypass") }

    private init() {
        if Self.bypassRequested {
            state = .devBypass
        } else if KeychainStore.get(Self.refreshKey) != nil,
                  let data = UserDefaults.standard.data(forKey: Self.profileKey),
                  let profile = try? JSONDecoder().decode(AuthProfile.self, from: data) {
            state = .signedIn(profile)
        } else {
            state = .signedOut
        }
        Self.applyScope(state)
    }

    private static func applyScope(_ state: State) {
        switch state {
        case .signedIn(let p): OfflineStore.shared.setScope("u\(p.id)")
        case .devBypass: OfflineStore.shared.setScope("dev")
        case .signedOut: OfflineStore.shared.setScope("anon")
        }
    }

    var profile: AuthProfile? {
        if case .signedIn(let p) = state { return p }
        return nil
    }

    var isSignedIn: Bool { state != .signedOut }
    var accessToken: String? { KeychainStore.get(Self.accessKey) }

    // MARK: Flows

    func signUp(name: String, email: String, password: String, homeAirport: String?, inviteCode: String? = nil) async throws {
        var body: [String: Any] = ["name": name, "email": email, "password": password]
        if let inviteCode, !inviteCode.trimmingCharacters(in: .whitespaces).isEmpty {
            body["invite_code"] = inviteCode.trimmingCharacters(in: .whitespaces)
        }
        if let homeAirport, !homeAirport.isEmpty { body["home_airport"] = homeAirport.uppercased() }
        let r: AuthResponse = try await Self.post("/auth/signup", body)
        claimedOnSignup = r.claimed ?? []
        apply(r)
    }

    func logIn(email: String, password: String) async throws {
        let r: AuthResponse = try await Self.post("/auth/login", ["email": email, "password": password])
        apply(r)
    }

    /// Returns the server's message, and the code itself when the server runs in dev mode.
    func requestReset(email: String) async throws -> (message: String, devCode: String?) {
        let (data, _) = try await Self.raw("POST", "/auth/forgot", ["email": email])
        let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        return (obj["detail"] as? String ?? "If that email has an account, a reset code is on its way.",
                obj["dev_reset_token"] as? String)
    }

    func resetPassword(code: String, newPassword: String) async throws {
        let r: AuthResponse = try await Self.post("/auth/reset", ["token": code.trimmingCharacters(in: .whitespacesAndNewlines),
                                                                  "password": newPassword])
        apply(r)
    }

    func updateProfile(name: String, homeAirport: String) async throws {
        let body: [String: Any] = ["name": name, "home_airport": homeAirport.uppercased()]
        let data = try await APIClient.json("PATCH", "/me", body)
        let p = try JSONDecoder().decode(AuthProfile.self, from: data)
        if case .signedIn = state { setProfile(p) }
    }

    func changePassword(current: String, new: String) async throws {
        let data = try await APIClient.json("POST", "/me/password", ["current_password": current, "new_password": new])
        apply(try JSONDecoder().decode(AuthResponse.self, from: data))
    }

    func deleteAccount(password: String) async throws {
        _ = try await APIClient.json("DELETE", "/me", ["password": password])
        clear()
    }

    func logOut() async {
        if case .signedIn = state {
            _ = try? await APIClient.json("POST", "/auth/logout", nil)  // ends sessions on every device
        }
        clear()
    }

    func reloadProfile() async {
        guard case .signedIn = state, let data = try? await APIClient.json("GET", "/me", nil),
              let p = try? JSONDecoder().decode(AuthProfile.self, from: data) else { return }
        setProfile(p)
    }

    /// Called by APIClient after a 401. Concurrent callers share one refresh.
    func refresh() async -> Bool {
        if let refreshTask { return await refreshTask.value }
        guard let token = KeychainStore.get(Self.refreshKey) else { return false }
        let task = Task<Bool, Never> {
            do {
                let r: AuthResponse = try await Self.post("/auth/refresh", ["refresh_token": token])
                apply(r)
                return true
            } catch let e as APIError where e.status == 401 {
                clear()  // refresh token revoked or expired: back to the login screen
                return false
            } catch {
                return false  // offline: keep the session and try again later
            }
        }
        refreshTask = task
        let ok = await task.value
        refreshTask = nil
        return ok
    }

    // MARK: Private

    private func apply(_ r: AuthResponse) {
        KeychainStore.set(r.access_token, for: Self.accessKey)
        KeychainStore.set(r.refresh_token, for: Self.refreshKey)
        setProfile(r.user)
    }

    private func setProfile(_ p: AuthProfile) {
        UserDefaults.standard.set(try? JSONEncoder().encode(p), forKey: Self.profileKey)
        state = .signedIn(p)
        Self.applyScope(state)
    }

    private func clear() {
        KeychainStore.set(nil, for: Self.accessKey)
        KeychainStore.set(nil, for: Self.refreshKey)
        UserDefaults.standard.removeObject(forKey: Self.profileKey)
        if state != .devBypass {
            OfflineStore.shared.signedOut()  // no one else's trips stay on this phone
            state = .signedOut
            Self.applyScope(state)
        }
    }

    /// Unauthenticated JSON call (auth endpoints).
    private static func raw(_ method: String, _ path: String, _ body: [String: Any]) async throws -> (Data, Int) {
        guard let url = APIConfig.url(path) else { throw APIError(status: 0, message: "Bad server URL") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 20
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let data: Data, response: URLResponse
        do { (data, response) = try await URLSession.shared.data(for: req) } catch { throw APIError.network(error) }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw APIError.from(status: status, data: data) }
        return (data, status)
    }

    private static func post<T: Decodable>(_ path: String, _ body: [String: Any]) async throws -> T {
        let (data, _) = try await raw("POST", path, body)
        return try JSONDecoder().decode(T.self, from: data)
    }
}

/// Every app request goes through here: adds the Bearer token and, on a 401, refreshes
/// the session once and retries.
enum APIClient {
    static func data(from url: URL) async throws -> (Data, URLResponse) {
        try await data(for: URLRequest(url: url))
    }

    static func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        let first = try await send(request)
        guard (first.1 as? HTTPURLResponse)?.statusCode == 401 else { return first }
        guard await AuthManager.shared.refresh() else { return first }
        return try await send(request)
    }

    /// JSON request that throws APIError for non-2xx answers.
    static func json(_ method: String, _ path: String, _ body: [String: Any]?) async throws -> Data {
        guard let url = APIConfig.url(path) else { throw APIError(status: 0, message: "Bad server URL") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 60
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let data: Data, response: URLResponse
        do { (data, response) = try await Self.data(for: req) } catch { throw APIError.network(error) }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw APIError.from(status: status, data: data) }
        return data
    }

    /// Reads (GET) are saved to the offline cache and served from it when the server can't be
    /// reached. Writes are refused while offline with a clear message instead of being lost.
    private static func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        var req = request
        let isRead = (req.httpMethod ?? "GET").uppercased() == "GET"
        let store = OfflineStore.shared
        func cached() -> (Data, URLResponse)? {
            guard isRead, let url = req.url, let data = ResponseCache.read(url),
                  let resp = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil,
                                             headerFields: ["X-Trippy-Cache": "offline"]) else { return nil }
            return (data, resp)
        }
        guard await store.canTryNetwork else {
            await store.markOffline()
            if let hit = cached() { return hit }
            if !isRead { await store.blockedWrite(); throw APIError(status: 0, message: OfflineStore.blockedMessage) }
            throw URLError(.notConnectedToInternet)
        }
        if let token = await AuthManager.shared.accessToken {
            req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        }
        // Fail over to the saved copy quickly instead of spinning for a minute.
        if isRead, req.timeoutInterval > 15 { req.timeoutInterval = 15 }
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let ok = (200..<300).contains(status)
            if isRead, ok, let url = req.url { ResponseCache.write(data, for: url) }
            await store.markOnline(synced: isRead && ok)
            return (data, resp)
        } catch where OfflineStore.isConnectivity(error) {
            await store.markOffline()
            if let hit = cached() { return hit }
            if !isRead { await store.blockedWrite(); throw APIError(status: 0, message: OfflineStore.blockedMessage) }
            throw error
        }
    }
}
