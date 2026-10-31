import Foundation
import CoreLocation

// MARK: - Journeys (several trips linked into one long trip; GET /journeys/…)

struct ApiJourneyStats: Decodable, Hashable {
    var days: Int?
    var trips: Int
    var flights: Int
    var rentals: Int
    var stays: Int
    var nights: Int
    var flight_miles: Double
    var drive_miles: Double
    var miles: Double
    var places: Int
    var countries: Int
}

struct ApiJourneyLeg: Decodable, Hashable, Identifiable {
    var trip_id: Int
    var title: String
    var owner_id: Int?
    var start_date: String?
    var end_date: String?
    var places: [String]
    var route: [ApiStoryPlace]
    var cost_by_currency: [String: Double]
    var leg: Int
    var item_count: Int
    var id: Int { trip_id }
}

/// List rows come without legs/route/balances; the detail call fills them in.
struct ApiJourney: Decodable, Identifiable {
    var id: Int
    var owner_id: Int
    var title: String
    var description: String?
    var cover_photo: String?
    var is_owner: Bool
    var trip_ids: [Int]
    var trip_count: Int
    var start_date: String?
    var end_date: String?
    var places: [String]
    var stats: ApiJourneyStats
    var cost_by_currency: [String: Double]
    var legs: [ApiJourneyLeg]?
    var route: [ApiStoryPlace]?
    var travelers: [ApiStoryPerson]?
    var balances: ApiLedger?

    enum CodingKeys: String, CodingKey {
        case id, owner_id, title, description, cover_photo, is_owner, trip_ids, trip_count, start_date, end_date
        case places, stats, cost_by_currency, legs, route, travelers, balances
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        owner_id = try c.decode(Int.self, forKey: .owner_id)
        title = try c.decode(String.self, forKey: .title)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        cover_photo = try c.decodeIfPresent(String.self, forKey: .cover_photo)
        is_owner = (try? c.decode(Bool.self, forKey: .is_owner)) ?? true
        trip_ids = (try? c.decode([Int].self, forKey: .trip_ids)) ?? []
        trip_count = (try? c.decode(Int.self, forKey: .trip_count)) ?? trip_ids.count
        start_date = try c.decodeIfPresent(String.self, forKey: .start_date)
        end_date = try c.decodeIfPresent(String.self, forKey: .end_date)
        places = (try? c.decode([String].self, forKey: .places)) ?? []
        stats = try c.decode(ApiJourneyStats.self, forKey: .stats)
        cost_by_currency = (try? c.decode([String: Double].self, forKey: .cost_by_currency)) ?? [:]
        legs = try? c.decode([ApiJourneyLeg].self, forKey: .legs)
        route = try? c.decode([ApiStoryPlace].self, forKey: .route)
        travelers = try? c.decode([ApiStoryPerson].self, forKey: .travelers)
        balances = try? c.decode(ApiLedger.self, forKey: .balances)
    }

    var start: Date? { Fmt.parse(start_date) }
    var end: Date? { Fmt.parse(end_date) }

    var dateText: String {
        guard let s = start else { return "No dates" }
        guard let e = end, !Calendar.current.isDate(s, inSameDayAs: e) else { return Fmt.monthDayYear(s) }
        let cal = Calendar.current
        if cal.component(.year, from: s) != cal.component(.year, from: e) { return "\(Fmt.monthDayYear(s)) – \(Fmt.monthDayYear(e))" }
        return "\(Fmt.monthDay(s)) – \(Fmt.monthDay(e)), \(cal.component(.year, from: e))"
    }

    var costText: String? {
        let parts = cost_by_currency.filter { $0.value > 0 }.sorted { $0.value > $1.value }
        guard !parts.isEmpty else { return nil }
        return parts.map { Fmt.compactMoney($0.value, $0.key) }.joined(separator: " + ")
    }
}

struct ApiSuggestionTrip: Decodable, Hashable, Identifiable {
    var id: Int
    var title: String
    var start_date: String?
    var end_date: String?
}

struct ApiJourneySuggestion: Decodable, Identifiable, Hashable {
    var key: String
    var trip_ids: [Int]
    var trips: [ApiSuggestionTrip]
    var title: String
    var score: Double
    var confidence: String
    var reasons: [String]
    var journey_id: Int?
    var dismissed: Bool
    var id: String { key }
}

struct ApiSuggestionList: Decodable {
    var suggestions: [ApiJourneySuggestion]
}

/// A booking that can change trips: POST /items/move kinds.
struct ItemRef: Hashable, Identifiable {
    enum Kind: String { case flight, rental, lodging, expense }
    let kind: Kind
    let id: Int
    var key: String { "\(kind.rawValue)-\(id)" }

    /// Timeline event ids: "f12-d", "r5-p", "h3". Activities can't move.
    init?(eventId: String) {
        guard let first = eventId.first else { return nil }
        let digits = eventId.dropFirst().prefix { $0.isNumber }
        guard let n = Int(digits) else { return nil }
        switch first {
        case "f": kind = .flight
        case "r": kind = .rental
        case "h": kind = .lodging
        default: return nil
        }
        id = n
    }
    init(kind: Kind, id: Int) { self.kind = kind; self.id = id }
}

extension NetworkManager {
    func fetchJourneys() async {
        let r = await send("GET", "/journeys/")
        if let d = r.data, r.error == nil, let list = try? JSONDecoder().decode([ApiJourney].self, from: d) {
            journeys = list
        }
    }

    func fetchJourney(_ id: Int) async -> Result<ApiJourney, StoryError> {
        let r = await send("GET", "/journeys/\(id)")
        if let err = r.error { return .failure(StoryError(message: err)) }
        do { return .success(try JSONDecoder().decode(ApiJourney.self, from: r.data ?? Data())) }
        catch { return .failure(StoryError(message: "Couldn't read this journey: \(error.localizedDescription)")) }
    }

    func fetchJourneySuggestions() async {
        let r = await send("GET", "/journeys/suggestions")
        if let d = r.data, r.error == nil, let s = try? JSONDecoder().decode(ApiSuggestionList.self, from: d) {
            journeySuggestions = s.suggestions
        }
    }

    func suggestJourneyTitle(_ tripIds: [Int]) async -> String? {
        let r = await send("POST", "/journeys/title", json: ["trip_ids": tripIds])
        return (r.data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })?["title"] as? String
    }

    /// Returns (journey id, error).
    func createJourney(title: String?, tripIds: [Int]) async -> (Int?, String?) {
        var body: [String: Any] = ["trip_ids": tripIds]
        if let title, !title.trimmingCharacters(in: .whitespaces).isEmpty { body["title"] = title }
        let r = await send("POST", "/journeys/", json: body)
        let id = (r.data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })?["id"] as? Int
        await afterJourneyChange()
        return (id, r.error)
    }

    func addTrips(_ tripIds: [Int], toJourney id: Int) async -> String? {
        let r = await send("POST", "/journeys/\(id)/trips", json: ["trip_ids": tripIds])
        await afterJourneyChange()
        return r.error
    }

    func removeTrip(_ tripId: Int, fromJourney id: Int) async -> String? {
        let r = await send("DELETE", "/journeys/\(id)/trips/\(tripId)")
        await afterJourneyChange()
        return r.error
    }

    func reorderJourney(_ id: Int, tripIds: [Int]) async -> String? {
        let r = await send("PUT", "/journeys/\(id)/order", json: ["trip_ids": tripIds])
        await afterJourneyChange()
        return r.error
    }

    func renameJourney(_ id: Int, title: String) async -> String? {
        let r = await send("PATCH", "/journeys/\(id)", json: ["title": title])
        await afterJourneyChange()
        return r.error
    }

    func dismissJourneySuggestion(_ s: ApiJourneySuggestion) async {
        journeySuggestions.removeAll { $0.key == s.key }
        _ = await send("POST", "/journeys/suggestions/dismiss", json: ["trip_ids": s.trip_ids])
    }

    /// Links a suggestion: into its existing journey when some trips are already linked, else a new one.
    func acceptJourneySuggestion(_ s: ApiJourneySuggestion) async -> (Int?, String?) {
        if let j = s.journey_id {
            let err = await addTrips(s.trip_ids, toJourney: j)
            return (j, err)
        }
        return await createJourney(title: s.title, tripIds: s.trip_ids)
    }

    /// Destructive: moves everything from `source` into `target` and deletes `source`.
    func mergeTrip(_ source: Int, into target: Int) async -> String? {
        let r = await send("POST", "/trips/\(target)/merge", json: ["source_trip_id": source, "confirm": true])
        if r.error == nil { trips.removeAll { $0.id == source }; applyTrip(r.data) }
        await fetchTrips()
        await fetchRentals()
        await fetchJourneys()
        return r.error
    }

    /// Moves bookings to another trip (`nil` takes them off any trip).
    func moveItems(_ items: [ItemRef], to tripId: Int?) async -> String? {
        let body: [String: Any] = ["trip_id": tripId as Any? ?? NSNull(),
                                   "items": items.map { ["kind": $0.kind.rawValue, "id": $0.id] }]
        let r = await send("POST", "/items/move", json: body)
        await fetchTrips()
        await fetchRentals()
        await fetchExpenses()
        await fetchJourneys()
        return r.error
    }

    func fetchJourneyStory(_ id: Int) async -> Result<ApiStory, StoryError> {
        let r = await send("GET", "/journeys/\(id)/story")
        if let err = r.error { return .failure(StoryError(message: err)) }
        do { return .success(try JSONDecoder().decode(ApiStory.self, from: r.data ?? Data())) }
        catch { return .failure(StoryError(message: "Couldn't read this story: \(error.localizedDescription)")) }
    }

    private func afterJourneyChange() async {
        await fetchTrips()
        await fetchJourneys()
        await fetchJourneySuggestions()
    }

    func journey(of trip: ApiTrip) -> ApiJourney? {
        guard let jid = trip.journey_id else { return nil }
        return journeys.first { $0.id == jid }
    }
}
