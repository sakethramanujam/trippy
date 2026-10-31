import Foundation
import Network
import SwiftUI
import CryptoKit

/// Last good copy of every GET the app makes, as raw JSON in Application Support.
/// Lets the app open instantly and keep working with no connection (or with the
/// self-hosted server unreachable). Scoped per server + signed-in user.
enum ResponseCache {
    /// Set by OfflineStore on the main actor; read from any thread.
    nonisolated(unsafe) static var scope = "anon"

    static var root: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("TrippyCache", isDirectory: true)
    }

    private static func file(for url: URL) -> URL {
        let key = (url.path + "?" + (url.query ?? ""))
        let name = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined().prefix(32)
        let scoped = SHA256.hash(data: Data((APIConfig.baseURL + "|" + scope).utf8))
            .map { String(format: "%02x", $0) }.joined().prefix(16)
        return root.appendingPathComponent(String(scoped), isDirectory: true)
            .appendingPathComponent(String(name) + ".json")
    }

    static func write(_ data: Data, for url: URL) {
        let f = file(for: url)
        try? FileManager.default.createDirectory(at: f.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: f, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    static func read(_ url: URL) -> Data? { try? Data(contentsOf: file(for: url)) }

    static func read(path: String) -> Data? { APIConfig.url(path).flatMap(read) }

    static func wipe() { try? FileManager.default.removeItem(at: root) }
}

/// Connectivity + sync state shown in the offline banner and "Synced …" captions.
@MainActor
final class OfflineStore: ObservableObject {
    static let shared = OfflineStore()

    /// True when the last request couldn't reach the server (or the device has no network).
    @Published private(set) var isOffline = false
    /// When fresh data last arrived from the server.
    @Published private(set) var lastSynced: Date?
    /// A short message after an edit was refused while offline.
    @Published var notice: String?

    /// `-TrippyOffline YES` simulates no connection (screenshots / testing).
    let forced = UserDefaults.standard.bool(forKey: "TrippyOffline")
    private(set) var pathUp = true
    private let monitor = NWPathMonitor()
    private var noticeTask: Task<Void, Never>?

    static let blockedMessage = "You're offline. Changes can't be saved until Trippy reconnects."

    private init() {
        lastSynced = UserDefaults.standard.object(forKey: syncKey) as? Date
        if forced { isOffline = true }
        monitor.pathUpdateHandler = { path in
            let up = path.status == .satisfied
            Task { @MainActor in
                let store = OfflineStore.shared
                store.pathUp = up
                if !up { store.isOffline = true }
            }
        }
        monitor.start(queue: DispatchQueue(label: "trippy.path"))
    }

    private var syncKey: String { "TrippyLastSynced." + ResponseCache.scope }

    /// Call whenever the signed-in user changes.
    func setScope(_ scope: String) {
        ResponseCache.scope = scope
        lastSynced = UserDefaults.standard.object(forKey: syncKey) as? Date
    }

    var canTryNetwork: Bool { !forced && pathUp }

    func markOnline(synced: Bool) {
        if isOffline { isOffline = false }
        if synced {
            let now = Date()
            lastSynced = now
            UserDefaults.standard.set(now, forKey: syncKey)
        }
    }

    func markOffline() { if !isOffline { isOffline = true } }

    func blockedWrite() {
        notice = Self.blockedMessage
        Haptics.warning()
        noticeTask?.cancel()
        noticeTask = Task {
            try? await Task.sleep(for: .seconds(4))
            if !Task.isCancelled { notice = nil }
        }
    }

    func signedOut() {
        ResponseCache.wipe()
        UserDefaults.standard.removeObject(forKey: syncKey)
        lastSynced = nil
    }

    /// Network failures that mean "can't reach the server" rather than a server answer.
    nonisolated static func isConnectivity(_ error: Error) -> Bool {
        let ns = error as NSError
        guard ns.domain == NSURLErrorDomain else { return false }
        return [NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorCannotConnectToHost,
                NSURLErrorCannotFindHost, NSURLErrorTimedOut, NSURLErrorDNSLookupFailed,
                NSURLErrorInternationalRoamingOff, NSURLErrorDataNotAllowed, NSURLErrorSecureConnectionFailed]
            .contains(ns.code)
    }
}

extension Date {
    /// "just now", "5 min ago", "Yesterday 3:04 PM".
    var syncedText: String {
        let s = Date().timeIntervalSince(self)
        if s < 60 { return "just now" }
        if s < 3600 { return "\(Int(s / 60)) min ago" }
        if Calendar.current.isDateInToday(self) { return formatted(date: .omitted, time: .shortened) }
        if Calendar.current.isDateInYesterday(self) { return "yesterday " + formatted(date: .omitted, time: .shortened) }
        return formatted(.dateTime.month(.abbreviated).day().hour().minute())
    }
}

/// Top-of-screen pill: offline state, last sync, and refused edits.
struct OfflineBanner: View {
    @ObservedObject var store = OfflineStore.shared

    var body: some View {
        VStack(spacing: 6) {
            if store.isOffline {
                HStack(spacing: 6) {
                    Image(systemName: "wifi.slash").font(.system(size: 11, weight: .bold))
                    Text(store.lastSynced.map { "Offline · synced \($0.syncedText)" } ?? "Offline · no saved copy yet")
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(Capsule().fill(Color(red: 0.55, green: 0.33, blue: 0.05).opacity(0.95)))
                .accessibilityElement(children: .combine)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
            if let note = store.notice {
                Text(note)
                    .font(.system(size: 13, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Theme.surfaceHigh))
                    .shadow(color: .black.opacity(0.4), radius: 10, y: 3)
                    .padding(.horizontal, 24)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.snappy, value: store.isOffline)
        .animation(.snappy, value: store.notice)
        .allowsHitTesting(false)
    }
}

/// "Synced 5 min ago" caption for list headers.
struct SyncedCaption: View {
    @ObservedObject var store = OfflineStore.shared
    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { _ in
            if let d = store.lastSynced {
                Label(store.isOffline ? "Offline · synced \(d.syncedText)" : "Synced \(d.syncedText)",
                      systemImage: store.isOffline ? "wifi.slash" : "arrow.triangle.2.circlepath")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(store.isOffline ? Color.orange : Theme.textTertiary)
                    .labelStyle(.titleAndIcon)
            }
        }
    }
}

extension NetworkManager {
    /// Fill the lists from the offline cache so the app opens instantly; the usual fetches
    /// then replace them with fresh data.
    @MainActor
    func primeFromCache() {
        _ = AuthManager.shared  // sets the cache scope for the signed-in user
        let dec = JSONDecoder()
        if trips.isEmpty, let d = ResponseCache.read(path: "/trips/?limit=500"),
           let v = try? dec.decode([ApiTrip].self, from: d) { trips = v }
        if rentals.isEmpty, let d = ResponseCache.read(path: "/rental_cars/?limit=1000"),
           let v = try? dec.decode([ApiRentalCar].self, from: d) { rentals = v; rentalsLoaded = true }
        if flights.isEmpty, let d = ResponseCache.read(path: "/flights/"),
           let v = try? dec.decode([ApiFlight].self, from: d) { flights = v }
        if expenses.isEmpty, let d = ResponseCache.read(path: "/expenses/"),
           let v = try? dec.decode([ApiExpense].self, from: d) { expenses = v }
        if journeys.isEmpty, let d = ResponseCache.read(path: "/journeys/"),
           let v = try? dec.decode([ApiJourney].self, from: d) { journeys = v }
        if groups.isEmpty, let d = ResponseCache.read(path: "/groups"),
           let v = try? dec.decode([ApiGroup].self, from: d) { groups = v }
    }

    /// Pull to refresh on the main lists.
    func refreshAll() async {
        await fetchTrips()
        await fetchRentals()
        await fetchFlights()
        await fetchJourneys()
        await fetchJourneySuggestions()
    }
}
