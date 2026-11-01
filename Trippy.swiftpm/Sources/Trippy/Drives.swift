import SwiftUI
import CoreLocation

// MARK: - API models (GET /drives, /drives/rental-suggestions; see IMPORTERS.md → Google Maps Timeline)

struct ApiDrivePlace: Codable, Hashable {
    let name: String?
    let lat: Double?
    let lng: Double?
}

struct ApiDriveStop: Codable, Hashable {
    let name: String?
    let lat: Double?
    let lng: Double?
    let minutes: Int?
}

/// One of your Google Maps Timeline drives. Drives are private to you; `path` is [[lat, lng], …].
struct ApiDrive: Codable, Hashable, Identifiable {
    let id: Int
    let trip_id: Int?
    let journey_id: Int?
    let rental_id: Int?
    let start_time: String?
    let end_time: String?
    let date: String?
    let distance_miles: Double
    let duration_minutes: Int?
    let start_place: ApiDrivePlace?
    let end_place: ApiDrivePlace?
    let stops: [ApiDriveStop]?
    let path: [[Double]]?

    var start: Date? { Fmt.parse(start_time) }
    var end: Date? { Fmt.parse(end_time) }
}

struct ApiDriveRentalSuggestion: Codable, Hashable, Identifiable {
    struct Rental: Codable, Hashable {
        let id: Int
        let company: String?
        let car: String?
        let pickup_location: String?
        let dropoff_location: String?
    }
    let drive_id: Int
    let rental_id: Int
    let match: String          // pickup | dropoff
    let reason: String
    let drive: ApiDrive
    let rental: Rental
    var id: String { "\(drive_id)-\(rental_id)-\(match)" }
}

/// Mirrors the server's counted_miles: Timeline miles that a rental's odometer/mileage hasn't
/// already recorded (linked to, or during, a rental with miles) so nothing is counted twice.
enum DriveMiles {
    static func counted(_ drives: [ApiDrive], rentals: [ApiRentalCar]) -> Double {
        let withMiles = rentals.filter { ($0.milesDriven ?? 0) > 0 }
        let covered = withMiles.compactMap { r -> (Date, Date)? in
            guard let a = r.pickupDate, let b = r.dropoffDate else { return nil }
            return (a, b)
        }
        let ids = Set(withMiles.map(\.id))
        return drives.reduce(0) { total, d in
            if let rid = d.rental_id, ids.contains(rid) { return total }
            if let s = d.start, covered.contains(where: { $0.0 <= s && s <= $0.1 }) { return total }
            return total + d.distance_miles
        }
    }

    /// Days you drove, newest last.
    static func days(_ drives: [ApiDrive]) -> [String] {
        Array(Set(drives.compactMap { $0.date ?? $0.start_time.map { String($0.prefix(10)) } })).sorted()
    }
}

extension NetworkManager {
    func fetchDrives(tripId: Int? = nil, journeyId: Int? = nil, year: Int? = nil, withPath: Bool = true) async -> [ApiDrive] {
        var q: [String] = ["with_path=\(withPath)"]
        if let tripId { q.append("trip_id=\(tripId)") }
        if let journeyId { q.append("journey_id=\(journeyId)") }
        if let year { q.append("year=\(year)") }
        let r = await send("GET", "/drives?" + q.joined(separator: "&"))
        guard let data = r.data, r.error == nil else { return [] }
        return (try? JSONDecoder().decode([ApiDrive].self, from: data)) ?? []
    }

    func fetchDriveRentalSuggestions() async -> [ApiDriveRentalSuggestion] {
        let r = await send("GET", "/drives/rental-suggestions")
        guard let data = r.data, r.error == nil else { return [] }
        return (try? JSONDecoder().decode([ApiDriveRentalSuggestion].self, from: data)) ?? []
    }

    /// Accept: links the drive to the rental. Nothing is linked until you accept.
    func linkDrive(_ driveId: Int, rentalId: Int?) async -> String? {
        await send("POST", "/drives/\(driveId)/rental", json: ["rental_id": rentalId ?? NSNull()]).error
    }

    func dismissDriveRental(_ driveId: Int, rentalId: Int) async -> String? {
        await send("POST", "/drives/\(driveId)/rental/dismiss", json: ["rental_id": rentalId]).error
    }

    func deleteDrive(_ driveId: Int) async -> String? {
        await send("DELETE", "/drives/\(driveId)").error
    }
}

// MARK: - Path art

/// Draws one or more [[lat, lng]] paths fitted into the view (no map tiles: works offline and
/// in rendered cards). Start is a filled dot, the end a white dot.
struct DrivePathView: View {
    let paths: [[[Double]]]
    var tint: Color = Theme.teal
    var lineWidth: CGFloat = 3

    var body: some View {
        Canvas { ctx, size in
            let pts = paths.flatMap { $0 }.filter { $0.count == 2 }
            guard !pts.isEmpty else { return }
            // Equirectangular with longitude scaled by cos(latitude) so shapes don't stretch.
            let lat0 = pts.map { $0[0] }.reduce(0, +) / Double(pts.count)
            let k = cos(lat0 * .pi / 180)
            let xs = pts.map { $0[1] * k }, ys = pts.map { -$0[0] }
            let minX = xs.min()!, maxX = xs.max()!, minY = ys.min()!, maxY = ys.max()!
            let inset: CGFloat = 18
            let w = max(maxX - minX, 1e-6), h = max(maxY - minY, 1e-6)
            let scale = min((size.width - 2 * inset) / w, (size.height - 2 * inset) / h)
            let ox = (size.width - w * scale) / 2, oy = (size.height - h * scale) / 2
            func pt(_ p: [Double]) -> CGPoint {
                CGPoint(x: ox + (p[1] * k - minX) * scale, y: oy + (-p[0] - minY) * scale)
            }
            for path in paths where path.count > 1 {
                var line = Path()
                line.move(to: pt(path[0]))
                for p in path.dropFirst() where p.count == 2 { line.addLine(to: pt(p)) }
                ctx.stroke(line, with: .color(tint.opacity(0.25)), style: StrokeStyle(lineWidth: lineWidth * 3, lineCap: .round, lineJoin: .round))
                ctx.stroke(line, with: .color(tint), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
            }
            if let first = paths.first(where: { !$0.isEmpty })?.first, first.count == 2 {
                let c = pt(first)
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - 5, y: c.y - 5, width: 10, height: 10)), with: .color(tint))
            }
            if let last = paths.last(where: { !$0.isEmpty })?.last, last.count == 2 {
                let c = pt(last)
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - 5, y: c.y - 5, width: 10, height: 10)), with: .color(.white))
            }
        }
        .background(LinearGradient(colors: [Color(hex: 0x0C1E2E), .black], startPoint: .top, endPoint: .bottom))
    }
}

// MARK: - Trip: driving days

/// "Driving days" on a trip: one card per day you drove, with the day's paths drawn.
struct TripDrivesSection: View {
    @ObservedObject var network: NetworkManager
    let tripId: Int
    @State private var drives: [ApiDrive] = []

    private var byDay: [(day: String, drives: [ApiDrive])] {
        Dictionary(grouping: drives) { $0.date ?? String(($0.start_time ?? "").prefix(10)) }
            .map { ($0.key, $0.value.sorted { ($0.start_time ?? "") < ($1.start_time ?? "") }) }
            .sorted { $0.day < $1.day }
    }

    var body: some View {
        Group {
            if !drives.isEmpty {
                VStack(alignment: .leading, spacing: Theme.s3) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("Driving Days").type(.title3).foregroundStyle(.white)
                        Spacer()
                        MicroLabel(text: "\(Fmt.number(drives.reduce(0) { $0 + $1.distance_miles })) MI")
                    }
                    ForEach(byDay, id: \.day) { day in
                        DrivingDayCard(day: day.day, drives: day.drives)
                    }
                }
            }
        }
        .task(id: tripId) { drives = await network.fetchDrives(tripId: tripId) }
    }
}

struct DrivingDayCard: View {
    let day: String
    let drives: [ApiDrive]

    private var title: String {
        let a = drives.first?.start_place?.name, b = drives.last?.end_place?.name
        if let a, let b, a != b { return "\(a) → \(b)" }
        return "Driving day"
    }

    private var subtitle: String {
        let mins = drives.compactMap(\.duration_minutes).reduce(0, +)
        let stops = drives.compactMap { $0.stops?.count }.reduce(0, +) + max(drives.count - 1, 0)
        var parts: [String] = []
        if title != "Driving day" { parts.append("Driving day") }
        if drives.count > 1 { parts.append("\(drives.count) drives") }
        if mins > 0 { parts.append(Fmt.duration(TimeInterval(mins * 60))) }
        if stops > 0 { parts.append("\(stops) stop\(stops == 1 ? "" : "s")") }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            DrivePathView(paths: drives.compactMap(\.path))
                .frame(height: 140)
            HStack(spacing: 12) {
                Image(systemName: "car.side.fill")
                    .foregroundStyle(Theme.teal)
                    .frame(width: 36, height: 36)
                    .background(Theme.teal.opacity(0.16), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    if let d = Fmt.parse(day) {
                        Text(Fmt.dayYear(d).uppercased()).type(.label).foregroundStyle(Theme.textSecondary)
                    }
                    Text(title).type(.headline).foregroundStyle(.white).lineLimit(2)
                    if !subtitle.isEmpty { Text(subtitle).type(.footnote).foregroundStyle(Theme.textSecondary) }
                }
                Spacer(minLength: 6)
                Text("\(Fmt.number(drives.reduce(0) { $0 + $1.distance_miles })) mi")
                    .type(.numberSmall).foregroundStyle(Theme.teal)
            }
            .padding(14)
        }
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.hairline))
    }
}

// MARK: - Driver's Log: Timeline section

/// Timeline drives in the Driver's Log: miles counted (rentals with odometer miles aren't
/// counted twice), driving days, longest day and "is this your rental pickup?" suggestions.
struct DriverLogTimelineSection: View {
    @ObservedObject var network: NetworkManager
    let year: Int?
    @State private var drives: [ApiDrive] = []
    @State private var suggestions: [ApiDriveRentalSuggestion] = []
    @State private var errorText: String?

    var body: some View {
        Group {
            if !drives.isEmpty || !shown.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Image(systemName: "point.topleft.down.to.point.bottomright.curvepath.fill").foregroundStyle(Theme.teal)
                        Text("Timeline drives").type(.title3).foregroundStyle(.white)
                    }
                    let days = DriveMiles.days(drives)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("\(drives.count)").type(.heroSmall).foregroundStyle(.white)
                        Text(drives.count == 1 ? "drive" : "drives").type(.title3).foregroundStyle(Theme.textSecondary)
                    }
                    Text("\(Fmt.number(DriveMiles.counted(drives, rentals: network.rentals))) mi counted · \(days.count) driving day\(days.count == 1 ? "" : "s")")
                        .type(.calloutStrong).foregroundStyle(Theme.teal)
                    if let best = longestDay {
                        Text("Longest day: \(Fmt.number(best.miles)) mi on \(best.label)")
                            .type(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                    Text("Drives during a rental with recorded miles aren't counted twice.")
                        .type(.caption).foregroundStyle(Theme.textTertiary)
                    if let errorText { Text(errorText).type(.caption).foregroundStyle(Theme.red) }
                    ForEach(shown) { s in suggestionRow(s) }
                }
                .card(padding: 16)
            }
        }
        .task(id: year) { await load() }
    }

    private var shown: [ApiDriveRentalSuggestion] {
        suggestions.filter { s in
            guard let year else { return true }
            return s.drive.start.map { Calendar.current.component(.year, from: $0) } == year
        }
    }

    private var longestDay: (miles: Double, label: String)? {
        let groups = Dictionary(grouping: drives) { $0.date ?? "" }
        guard let best = groups.max(by: { $0.value.reduce(0) { $0 + $1.distance_miles } < $1.value.reduce(0) { $0 + $1.distance_miles } }),
              let d = Fmt.parse(best.key) else { return nil }
        return (best.value.reduce(0) { $0 + $1.distance_miles }, Fmt.monthDay(d))
    }

    private func suggestionRow(_ s: ApiDriveRentalSuggestion) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Is this your \(s.rental.company ?? "rental") \(s.match)?").type(.calloutStrong).foregroundStyle(.white)
            Text(s.reason).type(.footnote).foregroundStyle(Theme.textSecondary)
            HStack(spacing: 10) {
                Button("Link drive") { Task { await act(s, accept: true) } }.buttonStyle(TintedButtonStyle(tint: Theme.green))
                Button("Not this") { Task { await act(s, accept: false) } }.buttonStyle(TintedButtonStyle(tint: Theme.textSecondary))
            }
        }
        .padding(12)
        .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func act(_ s: ApiDriveRentalSuggestion, accept: Bool) async {
        let err = accept ? await network.linkDrive(s.drive_id, rentalId: s.rental_id)
                         : await network.dismissDriveRental(s.drive_id, rentalId: s.rental_id)
        errorText = err
        if err == nil { await load() }
    }

    private func load() async {
        async let d = network.fetchDrives(year: year, withPath: false)
        async let s = network.fetchDriveRentalSuggestions()
        drives = await d
        suggestions = await s
    }
}
