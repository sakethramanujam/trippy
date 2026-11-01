import SwiftUI
import UIKit
import CoreLocation

// MARK: - API models (GET/PUT /trips/{id}/story, GET /stories/year)

struct ApiStoryPlace: Codable, Hashable {
    let code: String?
    let city: String?
    let country: String?
    let lat: Double?
    let lng: Double?

    var label: String { city ?? code ?? "" }
    var coordinate: CLLocationCoordinate2D? {
        guard let lat, let lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }
}

struct ApiStoryPerson: Codable, Hashable, Identifiable {
    let id: Int
    let name: String
    var initials: String {
        name.split(separator: " ").prefix(2).compactMap(\.first).map(String.init).joined().uppercased()
    }
}

struct ApiStoryItem: Codable, Hashable, Identifiable {
    var id: String { key }
    let key: String
    let kind: String              // flight | rental | drive | lodging | expenses | travelers
    let date: String?
    let end_date: String?
    let title: String
    let subtitle: String?
    let place: ApiStoryPlace?
    let from_place: ApiStoryPlace?
    let to_place: ApiStoryPlace?
    let metric: String?
    let miles: Double?
    let brand: String?
    let code: String?
    let people: [ApiStoryPerson]?
    let money: Bool?
    let day: Int?
    var hidden: Bool
    var note: String?
    var photos: [String]
    /// Drive items (Google Maps Timeline): the day's paths, [[[lat, lng]]].
    let paths: [[[Double]]]?
    let drive_ids: [Int]?

    var start: Date? { Fmt.parse(date) }

    var icon: String {
        switch kind {
        case "flight": return "airplane"
        case "rental": return "car.fill"
        case "drive": return "steeringwheel"
        case "lodging": return "bed.double.fill"
        case "expenses": return "creditcard.fill"
        case "travelers": return "person.2.fill"
        default: return "mappin"
        }
    }

    var tint: Color {
        switch kind {
        case "flight": return Theme.route
        case "rental": return Theme.green
        case "drive": return Theme.teal
        case "lodging": return Theme.stay
        case "expenses": return Theme.teal
        default: return Theme.purple
        }
    }

    var kindLabel: String {
        switch kind {
        case "flight": return "FLIGHT"
        case "rental": return "ROAD TRIP"
        case "drive": return "DRIVE"
        case "lodging": return "STAY"
        case "expenses": return "SPENT"
        case "travelers": return "CREW"
        default: return kind.uppercased()
        }
    }
}

struct ApiStoryHighlight: Codable, Hashable {
    let icon: String
    let label: String
    let value: String
    let detail: String?
    let money: Bool?
}

struct ApiStoryStats: Codable, Hashable {
    let days: Int?
    let places: Int
    let countries: Int
    let flights: Int
    let rentals: Int
    let stays: Int
    let nights: Int
    let flight_miles: Int
    let drive_miles: Int
    let distance_miles: Int
    let travelers: Int
    let drives: Int?
    let timeline_miles: Int?
    let spend: [String: Double]
    let spend_text: String?
    let cities: [String]
}

struct ApiStory: Codable, Hashable {
    let trip_id: Int
    let generated_title: String
    let start_date: String?
    let end_date: String?
    var items: [ApiStoryItem]
    let route: [ApiStoryPlace]
    let travelers: [ApiStoryPerson]
    let highlights: [ApiStoryHighlight]
    let stats: ApiStoryStats
    var title: String
    var subtitle: String?
    var theme: String
    var cover_photo: String?
    /// Your trip photos (thumbnails on your server), each placed on a story day/item.
    let trip_photos: [ApiTripPhoto]?
    let edited: Bool
    let updated_at: String?

    var visibleItems: [ApiStoryItem] { items.filter { !$0.hidden } }
    var start: Date? { Fmt.parse(start_date) }
    var end: Date? { Fmt.parse(end_date) }

    /// "Mar 1 – 8, 2026"
    var dateText: String {
        guard let s = start else { return "" }
        guard let e = end, !Calendar.current.isDate(s, inSameDayAs: e) else { return Fmt.monthDayYear(s) }
        let cal = Calendar.current
        if cal.component(.year, from: s) != cal.component(.year, from: e) {
            return "\(Fmt.monthDayYear(s)) – \(Fmt.monthDayYear(e))"
        }
        if cal.component(.month, from: s) == cal.component(.month, from: e) {
            return "\(Fmt.monthDay(s)) – \(cal.component(.day, from: e)), \(cal.component(.year, from: e))"
        }
        return "\(Fmt.monthDay(s)) – \(Fmt.monthDay(e)), \(cal.component(.year, from: e))"
    }

    var year: Int? { start.map { Calendar.current.component(.year, from: $0) } }

    /// Route stops with coordinates, in order (for maps).
    var routeCoordinates: [CLLocationCoordinate2D] { route.compactMap(\.coordinate) }

    /// "SFO · TYO · KYOTO" style codes for card strips.
    var routeCodes: [String] {
        route.map { p in
            if let c = p.code, !c.isEmpty { return c }
            return String((p.city ?? "").uppercased().prefix(3))
        }
    }

    var themeGradient: StoryTheme { StoryTheme(rawValue: theme) ?? .indigo }
}

struct ApiYearPoint: Codable, Hashable {
    let code: String?
    let city: String?
    let country: String?
    let lat: Double?
    let lng: Double?
    let visits: Int
}

struct ApiYearArc: Codable, Hashable {
    let from: [Double]
    let to: [Double]
    let count: Int
}

struct ApiYearInTravel: Codable, Hashable {
    struct Destination: Codable, Hashable { let city: String; let visits: Int }
    struct Longest: Codable, Hashable { let title: String; let days: Int }
    struct Home: Codable, Hashable { let code: String?; let city: String?; let lat: Double?; let lng: Double? }

    let year: Int
    let trips: Int
    let days_away: Int
    let flights: Int
    let rentals: Int
    let cities: Int
    let countries: Int
    let country_codes: [String]
    let flight_miles: Int
    let drive_miles: Int
    let miles: Int
    let around_earth: Double
    let top_destinations: [Destination]
    let top_airline: String?
    let top_rental_company: String?
    let longest_trip: Longest?
    let home: Home?
    let points: [ApiYearPoint]
    let arcs: [ApiYearArc]
}

// MARK: - Themes

enum StoryTheme: String, CaseIterable, Identifiable {
    case indigo, sunset, ocean, forest, rose
    var id: String { rawValue }

    var name: String { rawValue.capitalized }

    /// Top → bottom gradient stops.
    var colors: [Color] {
        switch self {
        case .indigo: return [Color(hex: 0x3B2BB8), Color(hex: 0x241673), Color(hex: 0x0D0730)]
        case .sunset: return [Color(hex: 0xFF8A3D), Color(hex: 0xC2335B), Color(hex: 0x2B0B2E)]
        case .ocean: return [Color(hex: 0x1E9BD7), Color(hex: 0x14508F), Color(hex: 0x061632)]
        case .forest: return [Color(hex: 0x2FB67C), Color(hex: 0x116149), Color(hex: 0x04201A)]
        case .rose: return [Color(hex: 0xF0629B), Color(hex: 0x8E2A7A), Color(hex: 0x220A2C)]
        }
    }

    var accent: Color {
        switch self {
        case .indigo: return Color(hex: 0xA99BFF)
        case .sunset: return Color(hex: 0xFFC36B)
        case .ocean: return Color(hex: 0x7FD6FF)
        case .forest: return Color(hex: 0x8CF0BE)
        case .rose: return Color(hex: 0xFFB0D2)
        }
    }

    var gradient: LinearGradient {
        LinearGradient(colors: colors, startPoint: .top, endPoint: .bottom)
    }
}

// MARK: - Networking

extension NetworkManager {
    func fetchStory(tripId: Int) async -> Result<ApiStory, StoryError> {
        let r = await send("GET", "/trips/\(tripId)/story")
        return decodeStory(r)
    }

    /// Partial update: pass only what changed. `items` maps item key → {hidden, note, photos}.
    func saveStory(tripId: Int, title: String? = nil, subtitle: String? = nil, theme: String? = nil,
                   coverPhoto: String?? = nil, order: [String]? = nil,
                   items: [String: [String: Any]]? = nil) async -> Result<ApiStory, StoryError> {
        var body: [String: Any] = [:]
        if let title { body["title"] = title }
        if let subtitle { body["subtitle"] = subtitle }
        if let theme { body["theme"] = theme }
        if let coverPhoto { body["cover_photo"] = coverPhoto ?? NSNull() }
        if let order { body["order"] = order }
        if let items { body["items"] = items }
        let r = await send("PUT", "/trips/\(tripId)/story", json: body)
        return decodeStory(r)
    }

    func resetStory(tripId: Int) async -> Result<ApiStory, StoryError> {
        let r = await send("DELETE", "/trips/\(tripId)/story")
        return decodeStory(r)
    }

    func fetchYearInTravel(_ year: Int) async -> ApiYearInTravel? {
        let r = await send("GET", "/stories/year?year=\(year)")
        guard let data = r.data, r.error == nil else { return nil }
        return try? JSONDecoder().decode(ApiYearInTravel.self, from: data)
    }

    private func decodeStory(_ r: (data: Data?, status: Int, error: String?)) -> Result<ApiStory, StoryError> {
        if let error = r.error { return .failure(StoryError(message: error)) }
        guard let data = r.data else { return .failure(StoryError(message: "Empty response")) }
        do { return .success(try JSONDecoder().decode(ApiStory.self, from: data)) } catch {
            return .failure(StoryError(message: "Couldn't read the story (\(error.localizedDescription))"))
        }
    }
}

struct StoryError: Error, Identifiable {
    var id: String { message }
    let message: String
}

// MARK: - Photos (kept on device; the server stores only their ids)

/// Story photos live in Application Support/StoryPhotos/<uuid>.jpg. The ids travel with the
/// story edits, so captions and order sync while the pixels stay on the phone that added them.
enum StoryPhotoStore {
    static var folder: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("StoryPhotos", isDirectory: true)
        if !FileManager.default.fileExists(atPath: dir.path) {
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }

    private static let cache = NSCache<NSString, UIImage>()

    static func url(_ id: String) -> URL { folder.appendingPathComponent("\(id).jpg") }

    /// Downscales to 2048 px on the long side and stores a JPEG. Returns the new id.
    static func save(_ data: Data) -> String? {
        guard let image = UIImage(data: data) else { return nil }
        let scaled = image.scaledToFit(maxSide: 2048)
        guard let jpeg = scaled.jpegData(compressionQuality: 0.86) else { return nil }
        let id = UUID().uuidString.lowercased()
        do {
            try jpeg.write(to: url(id), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } catch { return nil }
        cache.setObject(scaled, forKey: id as NSString)
        return id
    }

    static func image(_ id: String) -> UIImage? {
        if let hit = cache.object(forKey: id as NSString) { return hit }
        guard let img = UIImage(contentsOfFile: url(id).path) else { return nil }
        cache.setObject(img, forKey: id as NSString)
        return img
    }

    static func exists(_ id: String) -> Bool { FileManager.default.fileExists(atPath: url(id).path) }

    static func delete(_ id: String) {
        cache.removeObject(forKey: id as NSString)
        try? FileManager.default.removeItem(at: url(id))
    }
}

extension UIImage {
    func scaledToFit(maxSide: CGFloat) -> UIImage {
        let longest = max(size.width, size.height)
        guard longest > maxSide else { return normalizedOrientation() }
        let k = maxSide / longest
        let target = CGSize(width: (size.width * k).rounded(), height: (size.height * k).rounded())
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            draw(in: CGRect(origin: .zero, size: target))
        }
    }

    private func normalizedOrientation() -> UIImage {
        guard imageOrientation != .up else { return self }
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = scale
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in draw(at: .zero) }
    }
}
