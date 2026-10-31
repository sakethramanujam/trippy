import SwiftUI
import UserNotifications
import BackgroundTasks
import WidgetKit
import ActivityKit

// MARK: - Live flight status (server-side provider; off unless the admin adds a key)

struct ApiLiveStatus: Decodable {
    struct Status: Decodable {
        var provider: String
        var status: String
        var departure_scheduled: String?
        var departure_estimated: String?
        var departure_actual: String?
        var departure_terminal: String?
        var departure_gate: String?
        var arrival_scheduled: String?
        var arrival_estimated: String?
        var arrival_actual: String?
        var arrival_terminal: String?
        var arrival_gate: String?
        var baggage_claim: String?
        var delay_minutes: Int?
        var fetched_at: String?
    }
    var configured: Bool
    var provider: String?
    var status: Status?
    var message: String?
}

struct LiveStatusCard: View {
    let flight: ApiFlight
    @State private var result: ApiLiveStatus?
    @State private var error: String?
    @State private var loading = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack {
                SectionHeader(title: "Live status")
                Spacer()
                if loading { ProgressView().controlSize(.small) }
                else if result?.configured == true {
                    Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain).foregroundStyle(Theme.blue).accessibilityLabel("Refresh live status")
                }
            }
            content
        }
        .task { await load() }
    }

    @ViewBuilder private var content: some View {
        if let s = result?.status {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Circle().fill(color(s)).frame(width: 9, height: 9)
                    Text(label(s)).type(.headline).foregroundStyle(.white)
                    Spacer()
                    if let f = s.fetched_at.flatMap(Self.utc) {
                        Text("Updated \(f.formatted(.relative(presentation: .named)))")
                            .type(.caption).foregroundStyle(Theme.textTertiary)
                    }
                }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 12) {
                    cell("Departure gate", [s.departure_terminal.map(Self.terminal), s.departure_gate].compactMap { $0 }.joined(separator: " · "))
                    cell("Arrival gate", [s.arrival_terminal.map(Self.terminal), s.arrival_gate].compactMap { $0 }.joined(separator: " · "))
                    cell("Expected departure", localTime(s.departure_actual ?? s.departure_estimated ?? s.departure_scheduled))
                    cell("Expected arrival", localTime(s.arrival_actual ?? s.arrival_estimated ?? s.arrival_scheduled))
                    if let b = s.baggage_claim { cell("Baggage belt", b) }
                }
                Text("From \(providerName(s.provider))").type(.caption).foregroundStyle(Theme.textTertiary)
            }
            .card(padding: Theme.s5)
        } else if let r = result, !r.configured {
            Label {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Live status isn't configured").type(.headline).foregroundStyle(.white)
                    Text("Your Trippy server can show gates, delays and baggage belts once its admin adds a flight data key (see SELF_HOSTING.md).")
                        .type(.footnote).foregroundStyle(Theme.textSecondary)
                }
            } icon: { Image(systemName: "antenna.radiowaves.left.and.right.slash").foregroundStyle(Theme.textTertiary) }
            .card(padding: Theme.s5)
        } else if let m = error ?? result?.message {
            Text(m).type(.footnote).foregroundStyle(Theme.textSecondary).card(padding: Theme.s5)
        }
    }

    /// "1" -> "T1"; "I" or "Intl" stay as written.
    static func terminal(_ t: String) -> String { t.allSatisfy(\.isNumber) ? "T\(t)" : "Terminal \(t)" }

    /// The server stamps fetched_at in UTC ("2026-10-31T06:07:00Z").
    static func utc(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        return f.date(from: s) ?? f.date(from: s + "Z")
    }

    private func cell(_ title: String, _ value: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            MicroLabel(text: title)
            Text((value?.isEmpty == false ? value : nil) ?? "—").type(.headline).foregroundStyle(.white)
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await APIClient.json("GET", "/flights/\(flight.id)/status", nil)
            result = try JSONDecoder().decode(ApiLiveStatus.self, from: data)
            error = nil
        } catch let e as APIError {
            error = e.status == 0 ? "Live status needs a connection." : e.message
        } catch {
            self.error = "Live status needs a connection."
        }
    }

    private func label(_ s: ApiLiveStatus.Status) -> String {
        let base = ["scheduled": "On schedule", "delayed": "Delayed", "departed": "Departed", "en_route": "In the air",
                    "landed": "Landed", "cancelled": "Cancelled", "diverted": "Diverted"][s.status] ?? "Status unknown"
        if let d = s.delay_minutes, d > 0, s.status != "cancelled" { return base + " · \(d)m late" }
        return base
    }

    private func color(_ s: ApiLiveStatus.Status) -> Color {
        switch s.status {
        case "cancelled", "diverted": return Theme.red
        case "delayed": return Theme.amber
        case "landed": return Theme.textSecondary
        default: return (s.delay_minutes ?? 0) > 15 ? Theme.amber : Theme.green
        }
    }

    /// Provider times are airport-local ("2026-11-01 11:45-07:00"); show the clock time there.
    private func localTime(_ s: String?) -> String? {
        guard let s else { return nil }
        let t = s.replacingOccurrences(of: " ", with: "T")
        for f in ["yyyy-MM-dd'T'HH:mmXXXXX", "yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ss.SSSXXXXX"] {
            let df = DateFormatter(); df.locale = Locale(identifier: "en_US_POSIX"); df.dateFormat = f
            if let d = df.date(from: t) {
                let off = t.suffix(6)
                let sign = off.first == "-" ? -1 : 1
                let parts = off.dropFirst().split(separator: ":").compactMap { Int($0) }
                let secs = parts.count == 2 ? sign * (parts[0] * 3600 + parts[1] * 60) : 0
                let out = DateFormatter(); out.timeStyle = .short; out.timeZone = TimeZone(secondsFromGMT: secs)
                return out.string(from: d)
            }
        }
        return Fmt.parse(s).map(Fmt.time)
    }

    private func providerName(_ p: String) -> String {
        ["aerodatabox": "AeroDataBox", "aviationstack": "aviationstack", "aeroapi": "FlightAware AeroAPI"][p] ?? p
    }
}

// MARK: - Local reminders (no push needed)

enum TripReminders {
    static let enabledKey = "TrippyRemindersOn"
    static var enabled: Bool { UserDefaults.standard.bool(forKey: enabledKey) }

    static func requestAndEnable() async -> Bool {
        let ok = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        UserDefaults.standard.set(ok, forKey: enabledKey)
        return ok
    }

    static func disable() {
        UserDefaults.standard.set(false, forKey: enabledKey)
        Task { await clear() }
    }

    private static func clear() async {
        let center = UNUserNotificationCenter.current()
        let ids = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix("trippy.") }
        center.removePendingNotificationRequests(withIdentifiers: ids)
    }

    struct Planned { let id: String; let title: String; let body: String; let at: Date }

    /// Check-in opens, 3 hours before departure, and the morning of hotel check-in, for the next 14 days.
    static func plan(trips: [ApiTrip], now: Date = .now) -> [Planned] {
        let horizon = now.addingTimeInterval(14 * 86400)
        var out: [Planned] = []
        for f in trips.flatMap(\.flights) {
            guard let dep = f.departureDate, dep > now, dep < horizon else { continue }
            let route = "\(f.departure_airport) → \(f.arrival_airport)"
            if let open = AirlineCheckIn.opensAt(f), open > now {
                out.append(Planned(id: "trippy.checkin.\(f.id)", title: "Check in for \(f.flight_number)",
                                   body: "Online check-in usually opens now for \(route).", at: open))
            }
            let soon = dep.addingTimeInterval(-3 * 3600)
            if soon > now {
                out.append(Planned(id: "trippy.depart.\(f.id)", title: "\(f.flight_number) departs in 3 hours",
                                   body: "\(route) at \(Fmt.time(dep)). Directions to \(f.departure_airport) are in the flight.", at: soon))
            }
        }
        for s in trips.flatMap(\.lodgings) {
            guard let ci = s.checkInDate, ci > now, ci < horizon else { continue }
            let morning = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: ci) ?? ci
            guard morning > now, morning < ci else { continue }
            out.append(Planned(id: "trippy.stay.\(s.id)", title: "Check in at \(s.name) today",
                               body: s.address ?? "Your stay starts today.", at: morning))
        }
        return Array(out.sorted { $0.at < $1.at }.prefix(60))  // iOS keeps 64 pending
    }

    static func reschedule(trips: [ApiTrip]) async {
        guard enabled else { return }
        await clear()
        let center = UNUserNotificationCenter.current()
        for p in plan(trips: trips) {
            let content = UNMutableNotificationContent()
            content.title = p.title
            content.body = p.body
            content.sound = .default
            let comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: p.at)
            try? await center.add(UNNotificationRequest(identifier: p.id, content: content,
                                                        trigger: UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)))
        }
    }
}

// MARK: - Background refresh + widget snapshot

enum BackgroundRefresh {
    static let taskId = "samalabs.trippy.refresh"

    static var permitted: Bool {
        (Bundle.main.object(forInfoDictionaryKey: "BGTaskSchedulerPermittedIdentifiers") as? [String])?.contains(taskId) == true
    }

    /// Call once at launch (before the app finishes launching).
    static func register() {
        guard permitted else { return }
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskId, using: nil) { task in
            schedule()
            let work = Task { @MainActor in
                let network = NetworkManager()
                await network.fetchTrips()
                if !network.trips.isEmpty {
                    await TripReminders.reschedule(trips: network.trips)
                    WidgetSnapshot.write(trips: network.trips)
                }
                task.setTaskCompleted(success: !network.trips.isEmpty)
            }
            task.expirationHandler = { work.cancel() }
        }
    }

    static func schedule() {
        guard permitted else { return }
        let req = BGAppRefreshTaskRequest(identifier: taskId)
        req.earliestBeginDate = Date().addingTimeInterval(3 * 3600)
        try? BGTaskScheduler.shared.submit(req)
    }
}

enum WidgetSnapshot {
    static var url: URL? { WidgetSnapshotData.fileURL }

    static func make(trips: [ApiTrip], now: Date = .now) -> WidgetSnapshotData {
        let upcoming = trips.compactMap { t -> (ApiTrip, Date)? in
            guard let s = t.start_date.flatMap(Fmt.parse) else { return nil }
            let end = t.end_date.flatMap(Fmt.parse) ?? s
            return end >= Calendar.current.startOfDay(for: now) ? (t, s) : nil
        }.sorted { $0.1 < $1.1 }.first
        let flight = trips.flatMap(\.flights).filter { ($0.arrivalDate ?? $0.departureDate ?? .distantPast) > now }
            .min { ($0.departureDate ?? .distantFuture) < ($1.departureDate ?? .distantFuture) }
        return WidgetSnapshotData(
            nextTrip: upcoming.map { .init(title: $0.0.title, start: $0.1, end: $0.0.end_date.flatMap(Fmt.parse)) },
            nextFlight: flight.flatMap { f in f.departureDate.map {
                .init(number: f.flight_number, airline: f.airline, from: f.departure_airport, to: f.arrival_airport,
                      departs: $0, arrives: f.arrivalDate, confirmation: f.confirmation_number) } },
            written: now)
    }

    static func write(trips: [ApiTrip]) {
        guard let url, let data = try? JSONEncoder().encode(make(trips: trips)) else { return }
        try? data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        WidgetCenter.shared.reloadAllTimelines()
    }
}

extension NetworkManager {
    /// Changes when anything the widgets or reminders show changes.
    var tripsSignature: Int {
        var h = Hasher()
        for t in trips {
            h.combine(t.id); h.combine(t.title); h.combine(t.start_date)
            for f in t.flights { h.combine(f.id); h.combine(f.departure_time); h.combine(f.flight_number) }
            for l in t.lodgings { h.combine(l.id); h.combine(l.check_in) }
        }
        return h.finalize()
    }
}

// MARK: - Live Activity (started and updated by the app; no push updates on free provisioning)

enum FlightActivity {
    static var supported: Bool {
        Bundle.main.object(forInfoDictionaryKey: "NSSupportsLiveActivities") as? Bool == true
            && ActivityAuthorizationInfo().areActivitiesEnabled
    }

    static func isRunning(_ flight: ApiFlight) -> Bool {
        Activity<FlightActivityAttributes>.activities.contains { $0.attributes.number == flight.flight_number && $0.activityState == .active }
    }

    static func eligible(_ flight: ApiFlight, now: Date = .now) -> Bool {
        guard let dep = flight.departureDate else { return false }
        return dep.timeIntervalSince(now) < 24 * 3600 && (flight.arrivalDate ?? dep) > now
    }

    static func start(_ flight: ApiFlight) -> String? {
        guard supported, let dep = flight.departureDate else { return "Live Activities are off for Trippy in Settings." }
        let state = FlightActivityAttributes.ContentState(status: DisplayName.flightStatus(flight.status) ?? "Scheduled",
                                                          gate: nil, departs: dep, arrives: flight.arrivalDate)
        do {
            _ = try Activity.request(attributes: FlightActivityAttributes(number: flight.flight_number, from: flight.departure_airport,
                                                                         to: flight.arrival_airport),
                                     content: .init(state: state, staleDate: flight.arrivalDate))
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    static func stop(_ flight: ApiFlight) {
        for a in Activity<FlightActivityAttributes>.activities where a.attributes.number == flight.flight_number {
            Task { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }
}
