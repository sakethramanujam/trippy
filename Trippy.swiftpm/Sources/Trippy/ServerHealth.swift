import SwiftUI

/// What a Trippy server reports at `GET /health` (unauthenticated).
struct ServerHealth: Decodable, Equatable {
    var status: String
    var service: String?
    var version: String?
    var signup: String?          // "open" | "invite" | "closed"
    var password_reset: String?  // "email" | "server-log"

    /// Servers before 0.2 answer only {"status","auth"}; accept those, reject anything that names
    /// a different service.
    var isTrippy: Bool { status == "healthy" && (service == nil || service == "trippy") }

    /// A one-line description for the server row and settings sheet.
    var summary: String {
        guard service != nil else { return "Trippy (older server)" }
        var parts = ["Trippy \(version ?? "")".trimmingCharacters(in: .whitespaces)]
        switch signup {
        case "invite": parts.append("invite-only sign-up")
        case "closed": parts.append("sign-up closed")
        default: parts.append("open sign-up")
        }
        return parts.joined(separator: " · ")
    }

    enum CheckError: LocalizedError {
        case badURL, notTrippy, http(Int), unreachable(String)
        var errorDescription: String? {
            switch self {
            case .badURL: return "That isn't a valid URL. Try https://trippy.example.com or http://192.168.1.20:8000."
            case .notTrippy: return "Something answered, but it isn't a Trippy server."
            case .http(let code): return "The server answered HTTP \(code)."
            case .unreachable(let why): return "Can't reach the server. \(why)"
            }
        }
    }

    /// Calls `<base>/health` and checks the response really came from Trippy.
    static func check(_ base: String) async -> Result<ServerHealth, CheckError> {
        guard let base = APIConfig.normalize(base), let url = URL(string: base + "/health") else {
            return .failure(.badURL)
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 6
        request.cachePolicy = .reloadIgnoringLocalCacheData
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard code == 200 else { return .failure(.http(code)) }
            guard let health = try? JSONDecoder().decode(ServerHealth.self, from: data), health.isTrippy else {
                return .failure(.notTrippy)
            }
            return .success(health)
        } catch {
            return .failure(.unreachable(error.localizedDescription))
        }
    }
}

/// Checks the current server and remembers the answer, so sign-up can show invite-only notes.
@MainActor
final class ServerStatus: ObservableObject {
    enum State: Equatable { case checking, ok(ServerHealth), failed(String) }
    @Published private(set) var state: State = .checking
    @Published private(set) var baseURL = APIConfig.baseURL

    var health: ServerHealth? { if case .ok(let h) = state { return h } else { return nil } }

    func refresh() async {
        baseURL = APIConfig.baseURL
        state = .checking
        switch await ServerHealth.check(baseURL) {
        case .success(let h): state = .ok(h)
        case .failure(let e): state = .failed(e.localizedDescription)
        }
    }

    /// Host and port without the scheme, for compact display.
    var displayHost: String {
        baseURL.replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "http://", with: "")
    }
}

/// "● trippy.example.com · Trippy 1.0 · open sign-up   Change" — shown on Welcome, Sign up and Log in.
struct ServerStatusRow: View {
    @ObservedObject var status: ServerStatus
    @State private var showSettings = false

    var body: some View {
        Button { showSettings = true } label: {
            HStack(spacing: 8) {
                Circle().fill(dotColor).frame(width: 8, height: 8)
                VStack(alignment: .leading, spacing: 1) {
                    Text(status.displayHost)
                        .type(.mono)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1).truncationMode(.middle)
                    Text(detail)
                        .type(.label)
                        .foregroundStyle(Theme.textTertiary)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                Text("Server")
                    .type(.footnoteStrong)
                    .foregroundStyle(Theme.blue)
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.05)))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Server \(status.displayHost), \(detail). Change server")
        .sheet(isPresented: $showSettings) {
            ServerSettingsView(onSaved: { Task { await status.refresh() } })
        }
        .task { if status.health == nil { await status.refresh() } }
    }

    private var dotColor: Color {
        switch status.state {
        case .checking: return Theme.textTertiary
        case .ok: return Theme.green
        case .failed: return Theme.orange
        }
    }

    private var detail: String {
        switch status.state {
        case .checking: return "Checking…"
        case .ok(let h): return h.summary
        case .failed: return "Not reachable · tap to change"
        }
    }
}
