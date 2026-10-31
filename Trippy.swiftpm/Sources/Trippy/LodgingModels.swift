import SwiftUI
import CoreLocation

// MARK: - Lodging DTO (app/schemas.py `Lodging`)

struct ApiLodging: Codable, Identifiable, Hashable {
    var id: Int
    var trip_id: Int?
    var name: String
    var address: String?
    /// Local wall-clock times at the property.
    var check_in: String?
    var check_out: String?
    var check_in_tz: String?
    var check_out_tz: String?
    var confirmation_number: String?
    /// Total including taxes.
    var cost: Double?
    var currency: String?
    var taxes_fees: Double?
    var booking_source: String?
    var notes: String?
    var brand: String?
    var property_type: String?
    var city: String?
    var country: String?
    var lat: Double?
    var lng: Double?
    var nights: Int?
    var room_type: String?
    var rooms: Int?
    var guests: Int?
    var loyalty_program: String?
    var loyalty_points: Int?
    var status: String?
    var stay_status: String?
    var night_count: Int?
    /// The source only had dates; the times are the brand's usual hours.
    var time_approx: Bool?

    var checkInDate: Date? { Fmt.parse(check_in) }
    var checkOutDate: Date? { Fmt.parse(check_out) }
    var isCancelled: Bool { (status ?? "").lowercased() == "cancelled" }

    /// Times a person should not read as booked: flagged by the server, or both exactly midnight
    /// (a date-only stay from an older server).
    var timesApprox: Bool { time_approx == true || dateOnly }

    private var dateOnly: Bool {
        guard time_approx != true, let a = checkInDate else { return false }
        let cal = Calendar.current
        let midnight = { (d: Date) in cal.component(.hour, from: d) == 0 && cal.component(.minute, from: d) == 0 }
        return midnight(a) && (checkOutDate.map(midnight) ?? true)
    }

    /// "3:00 PM", "~3:00 PM" when it's the usual hour, "Any time" when only the date is known.
    func timeText(_ d: Date?) -> String {
        guard let d else { return "—" }
        if dateOnly { return "Any time" }
        return (time_approx == true ? "~" : "") + Fmt.time(d)
    }

    /// Server-computed nights, else derived from the dates.
    var nightCount: Int {
        if let n = night_count ?? nights, n > 0 { return n }
        guard let a = checkInDate, let b = checkOutDate else { return 0 }
        let cal = Calendar.current
        return max(0, cal.dateComponents([.day], from: cal.startOfDay(for: a), to: cal.startOfDay(for: b)).day ?? 0)
    }

    var nightsLabel: String { nightCount == 1 ? "night" : "nights" }

    var coordinate: CLLocationCoordinate2D? {
        guard let lat, let lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    var costText: String? { cost.map { Fmt.money($0, currency, decimals: false) } }

    var place: String? {
        let parts = [city, country].compactMap { $0?.isEmpty == false ? $0 : nil }
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }

    /// "HYATT · TOKYO" — small label above the property name.
    var microLine: String {
        var parts: [String] = []
        if let b = brand, !b.isEmpty { parts.append(b) } else { parts.append(DisplayName.propertyType(property_type)) }
        if let c = city, !c.isEmpty { parts.append(c) }
        return parts.joined(separator: " · ").uppercased()
    }

    /// upcoming | in_progress | completed | cancelled
    func phase(at now: Date) -> String {
        if isCancelled { return "cancelled" }
        if let s = stay_status, !s.isEmpty, checkInDate == nil { return s }
        guard let a = checkInDate else { return "upcoming" }
        if now < a { return "upcoming" }
        if let b = checkOutDate, now < b { return "in_progress" }
        return "completed"
    }
}

struct ApiStayStats: Codable {
    var count: Int
    var nights: Int
    var total_cost_by_currency: [String: Double]?
    var top_brands: [ApiStatItem]?
    var top_booking_sources: [ApiStatItem]?
    var cities: Int?
}

extension DisplayName {
    static func propertyType(_ t: String?) -> String {
        switch (t ?? "").lowercased() {
        case "motel": return "Motel"
        case "rental": return "Rental"
        case "hostel": return "Hostel"
        default: return "Hotel"
        }
    }
}

// MARK: - Network

extension NetworkManager {
    /// Create on a trip (`POST /trips/{id}/lodgings/`) or standalone (`POST /lodgings/`).
    func createLodging(tripId: Int?, _ body: [String: Any]) async -> (ApiLodging?, String?) {
        let path = tripId.map { "/trips/\($0)/lodgings/" } ?? "/lodgings/"
        let r = await send("POST", path, json: body)
        if let err = r.error { return (nil, err) }
        let lodging = r.data.flatMap { try? JSONDecoder().decode(ApiLodging.self, from: $0) }
        await refreshTrip(tripId)
        return (lodging, nil)
    }

    func updateLodging(_ id: Int, tripId: Int?, _ body: [String: Any]) async -> (ApiLodging?, String?) {
        let r = await send("PATCH", "/lodgings/\(id)", json: body)
        if let err = r.error { return (nil, err) }
        let lodging = r.data.flatMap { try? JSONDecoder().decode(ApiLodging.self, from: $0) }
        await refreshTrip(tripId)
        return (lodging, nil)
    }

    func deleteLodging(_ id: Int, tripId: Int?) async -> String? {
        let r = await send("DELETE", "/lodgings/\(id)")
        if let err = r.error { return err }
        await refreshTrip(tripId)
        return nil
    }

    /// Reloads one trip in place so the timeline, map and totals update without a full refetch.
    func refreshTrip(_ tripId: Int?) async {
        guard let tripId else { await fetchTrips(); return }
        let r = await send("GET", "/trips/\(tripId)")
        if r.error == nil { applyTrip(r.data) } else { await fetchTrips() }
    }

    /// The `stays` block of `/stats/` for one year, without touching the published `stats`.
    func fetchStayStats(year: Int?) async -> ApiStayStats? {
        let r = await send("GET", year.map { "/stats/?year=\($0)" } ?? "/stats/")
        guard let data = r.data, r.error == nil else { return nil }
        return (try? JSONDecoder().decode(ApiStats.self, from: data))?.stays
    }
}

// MARK: - Glyphs + badges

/// The bed / plane / car glyphs from the passport-stamp logo (template PDFs).
enum TripGlyph: String {
    case bed = "GlyphBed", plane = "GlyphPlane", car = "GlyphCar"
}

struct GlyphImage: View {
    let glyph: TripGlyph
    var size: CGFloat = 16
    var color: Color = Theme.stay
    var body: some View {
        Image(glyph.rawValue)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .foregroundStyle(color)
            .accessibilityHidden(true)
    }
}

/// Chain logo when bundled, else a colored letter badge (brand, or the property's first letter).
struct HotelBadge: View {
    let brand: String?
    let name: String
    var size: CGFloat = 30

    var body: some View {
        if let asset = BrandLogos.hotel(brand) {
            LogoTile(asset: asset, size: size)
        } else {
            Text(letter)
                .font(.system(size: size * 0.5, weight: .heavy, design: .rounded))
                .foregroundStyle(.white)
                .frame(width: size, height: size)
                .background(tint, in: RoundedRectangle(cornerRadius: size * 0.26, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: size * 0.26, style: .continuous)
                    .strokeBorder(.white.opacity(0.12), lineWidth: 0.5))
                .accessibilityHidden(true)
        }
    }

    private var source: String { (brand?.isEmpty == false ? brand! : name) }

    private var letter: String {
        let skip: Set<String> = ["the", "hotel", "hotels", "&"]
        let word = source.split(separator: " ").first { !skip.contains($0.lowercased()) } ?? Substring(source)
        return word.first.map { String($0).uppercased() } ?? "H"
    }

    /// Known chains get their house color; everything else a neutral raised tile.
    private var tint: Color {
        let k = (brand ?? "").lowercased()
        let table: [(String, UInt32)] = [("marriott", 0x9E1B32), ("ritz", 0x3B2F2A), ("westin", 0x5A6F3C), ("sheraton", 0x1F3D7A),
                                       ("hilton", 0x104C97), ("conrad", 0x1B1B1B), ("waldorf", 0x2B2B2B),
                                       ("hyatt", 0x2B5D8C), ("ihg", 0x2E6B3A), ("intercontinental", 0x1E3A2F),
                                       ("holiday inn", 0x2C7A3F), ("accor", 0x1E1852), ("airbnb", 0xE0484F),
                                       ("wyndham", 0x0067B1), ("best western", 0x003C7E), ("four seasons", 0x2A2A2A),
                                       ("aman", 0x5B4A3A), ("mandarin", 0x6B1E2A)]
        if let hit = table.first(where: { k.contains($0.0) }) { return Color(hex: hit.1) }
        return Theme.surfaceHigh
    }
}
