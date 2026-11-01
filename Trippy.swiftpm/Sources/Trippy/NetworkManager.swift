import Foundation

// MARK: - Trip DTOs (aligned with app/schemas.py)

struct ApiTrip: Decodable, Identifiable {
    var id: Int
    var title: String
    var description: String?
    var native_album_id: String?
    var start_date: String?
    var end_date: String?
    var owner_id: Int?
    var group_id: Int?
    var flights: [ApiFlight]
    var expenses: [ApiExpense]
    var activities: [ApiActivity]
    var documents: [ApiDocument]
    var rental_cars: [ApiRentalCar]
    var participants: [ApiParticipant]
    var lodgings: [ApiLodging]
    var stay_cost_by_currency: [String: Double]
    /// Set when this trip is one leg of a journey (several trips linked into one long trip).
    var journey_id: Int?
    var journey_position: Int?
    /// Pinned to the top of *my* Trips list (pins are per user).
    var pinned: Bool
    /// The title is generated from the route and kept current; false once someone renames it.
    var title_auto: Bool = false

    enum CodingKeys: String, CodingKey {
        case id, title, description, native_album_id, start_date, end_date, owner_id, group_id
        case flights, expenses, activities, documents, rental_cars, participants
        case lodgings, stay_cost_by_currency, journey_id, journey_position, pinned, title_auto
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        title = try container.decode(String.self, forKey: .title)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        native_album_id = try container.decodeIfPresent(String.self, forKey: .native_album_id)
        start_date = try container.decodeIfPresent(String.self, forKey: .start_date)
        end_date = try container.decodeIfPresent(String.self, forKey: .end_date)
        owner_id = try container.decodeIfPresent(Int.self, forKey: .owner_id)
        group_id = try container.decodeIfPresent(Int.self, forKey: .group_id)
        // Soft defaults keep older / partial payloads resilient
        flights = (try? container.decode([ApiFlight].self, forKey: .flights)) ?? []
        expenses = (try? container.decode([ApiExpense].self, forKey: .expenses)) ?? []
        activities = (try? container.decode([ApiActivity].self, forKey: .activities)) ?? []
        documents = (try? container.decode([ApiDocument].self, forKey: .documents)) ?? []
        rental_cars = (try? container.decode([ApiRentalCar].self, forKey: .rental_cars)) ?? []
        participants = (try? container.decode([ApiParticipant].self, forKey: .participants)) ?? []
        lodgings = (try? container.decode([ApiLodging].self, forKey: .lodgings)) ?? []
        stay_cost_by_currency = (try? container.decode([String: Double].self, forKey: .stay_cost_by_currency)) ?? [:]
        journey_id = try? container.decodeIfPresent(Int.self, forKey: .journey_id)
        journey_position = try? container.decodeIfPresent(Int.self, forKey: .journey_position)
        pinned = (try? container.decodeIfPresent(Bool.self, forKey: .pinned)) ?? false
        title_auto = (try? container.decodeIfPresent(Bool.self, forKey: .title_auto)) ?? false
    }
}

struct ApiFlight: Codable, Identifiable {
    var id: Int
    var trip_id: Int?
    var airline: String
    var flight_number: String
    var departure_airport: String
    var arrival_airport: String
    var departure_time: String?
    var arrival_time: String?
    var aircraft_type: String?
    var aircraft_model: String?
    var aircraft_manufacturer: String?
    var delay_minutes: Int?
    var status: String
    var confirmation_number: String?
    var distance_miles: Double?
    var distance_km: Double?
    var duration_minutes: Int?
    var cost: Double?
    var currency: String?
    var seat: String?
    var cabin_class: String?
    var booking_source: String?
    var terminal: String?
    var gate: String?
    var notes: String?

    enum CodingKeys: String, CodingKey {
        case id, trip_id, airline, flight_number, departure_airport, arrival_airport
        case departure_time, arrival_time, aircraft_type, aircraft_model, aircraft_manufacturer
        case delay_minutes, status, confirmation_number, distance_miles, distance_km
        case duration_minutes, cost, currency, seat, cabin_class, booking_source
        case terminal, gate, notes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        trip_id = try c.decodeIfPresent(Int.self, forKey: .trip_id)
        airline = try c.decode(String.self, forKey: .airline)
        flight_number = try c.decode(String.self, forKey: .flight_number)
        departure_airport = try c.decode(String.self, forKey: .departure_airport)
        arrival_airport = try c.decode(String.self, forKey: .arrival_airport)
        departure_time = try c.decodeIfPresent(String.self, forKey: .departure_time)
        arrival_time = try c.decodeIfPresent(String.self, forKey: .arrival_time)
        aircraft_type = try c.decodeIfPresent(String.self, forKey: .aircraft_type)
        aircraft_model = try c.decodeIfPresent(String.self, forKey: .aircraft_model)
        aircraft_manufacturer = try c.decodeIfPresent(String.self, forKey: .aircraft_manufacturer)
        delay_minutes = try c.decodeIfPresent(Int.self, forKey: .delay_minutes)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "Scheduled"
        confirmation_number = try c.decodeIfPresent(String.self, forKey: .confirmation_number)
        distance_miles = try c.decodeIfPresent(Double.self, forKey: .distance_miles)
        distance_km = try c.decodeIfPresent(Double.self, forKey: .distance_km)
        duration_minutes = try c.decodeIfPresent(Int.self, forKey: .duration_minutes)
        cost = try c.decodeIfPresent(Double.self, forKey: .cost)
        currency = try c.decodeIfPresent(String.self, forKey: .currency)
        seat = try c.decodeIfPresent(String.self, forKey: .seat)
        cabin_class = try c.decodeIfPresent(String.self, forKey: .cabin_class)
        booking_source = try c.decodeIfPresent(String.self, forKey: .booking_source)
        terminal = try c.decodeIfPresent(String.self, forKey: .terminal)
        gate = try c.decodeIfPresent(String.self, forKey: .gate)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
    }
}

struct ApiTimelineEvent: Codable, Identifiable {
    var id: Int
    var type: String
    var title: String
    var subtitle: String?
    var date: String?
}

struct ApiExpenseSplit: Codable, Identifiable {
    var id: Int
    var user_id: Int
    var amount_owed: Double
    var is_settled: Bool
    var amount_cents: Int?
    /// What was typed for exact ($), percent (%) or shares (weight) splits.
    var share: Double?

    var cents: Int { amount_cents ?? Int((amount_owed * 100).rounded()) }
}

struct ApiExpense: Codable, Identifiable {
    var id: Int
    var amount: Double
    var description: String
    var trip_id: Int?
    var group_id: Int?
    var payer_id: Int?
    var date: String?
    var currency: String?
    var native_receipt_link: String?
    var amount_cents: Int?
    var split_mode: String?
    var splits: [ApiExpenseSplit]

    var cents: Int { amount_cents ?? Int((amount * 100).rounded()) }

    enum CodingKeys: String, CodingKey {
        case id, amount, description, trip_id, group_id, payer_id, date, currency, native_receipt_link, amount_cents, split_mode, splits
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        amount = try container.decode(Double.self, forKey: .amount)
        description = try container.decode(String.self, forKey: .description)
        trip_id = try container.decodeIfPresent(Int.self, forKey: .trip_id)
        group_id = try container.decodeIfPresent(Int.self, forKey: .group_id)
        amount_cents = try container.decodeIfPresent(Int.self, forKey: .amount_cents)
        split_mode = try container.decodeIfPresent(String.self, forKey: .split_mode)
        payer_id = try container.decodeIfPresent(Int.self, forKey: .payer_id)
        date = try container.decodeIfPresent(String.self, forKey: .date)
        currency = try container.decodeIfPresent(String.self, forKey: .currency)
        native_receipt_link = try container.decodeIfPresent(String.self, forKey: .native_receipt_link)
        splits = (try? container.decode([ApiExpenseSplit].self, forKey: .splits)) ?? []
    }
}

struct ApiActivity: Decodable, Identifiable {
    var id: Int
    var trip_id: Int?
    var title: String
    var description: String?
    var start_time: String?
    var end_time: String?
    var location_map_link: String?

    enum CodingKeys: String, CodingKey {
        case id, trip_id, title, description, start_time, end_time, location_map_link
        // Legacy keys from earlier client drafts
        case name, location
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        trip_id = try c.decodeIfPresent(Int.self, forKey: .trip_id)
        if let t = try c.decodeIfPresent(String.self, forKey: .title) {
            title = t
        } else {
            title = try c.decodeIfPresent(String.self, forKey: .name) ?? "Activity"
        }
        description = try c.decodeIfPresent(String.self, forKey: .description)
        start_time = try c.decodeIfPresent(String.self, forKey: .start_time)
        end_time = try c.decodeIfPresent(String.self, forKey: .end_time)
        location_map_link = try c.decodeIfPresent(String.self, forKey: .location_map_link)
            ?? c.decodeIfPresent(String.self, forKey: .location)
    }
}

struct ApiDocument: Decodable, Identifiable {
    var id: Int
    var trip_id: Int?
    var title: String
    var url: String

    enum CodingKeys: String, CodingKey {
        case id, trip_id, title, url
        case name, file_url
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        trip_id = try c.decodeIfPresent(Int.self, forKey: .trip_id)
        if let t = try c.decodeIfPresent(String.self, forKey: .title) {
            title = t
        } else {
            title = try c.decodeIfPresent(String.self, forKey: .name) ?? "Document"
        }
        if let u = try c.decodeIfPresent(String.self, forKey: .url) {
            url = u
        } else {
            url = try c.decodeIfPresent(String.self, forKey: .file_url) ?? ""
        }
    }
}

struct ApiRentalCar: Decodable, Identifiable {
    var id: Int
    var trip_id: Int?
    var rental_company: String
    var car_model: String?
    var pickup_location: String
    var dropoff_location: String
    var pickup_time: String?
    var dropoff_time: String?
    var mileage_driven: Double?
    var confirmation_number: String?
    var cost: Double?
    var currency: String?
    var vehicle_class: String?
    var fuel_type: String?
    var pickup_odometer: Double?
    var dropoff_odometer: Double?
    var booking_source: String?
    // Rental tracker (v2) — all optional so older servers still decode.
    var external_id: String?
    var agreement_number: String?
    var vehicle_make: String?
    var vehicle_year: Int?
    var vehicle_color: String?
    var license_plate: String?
    var photo_url: String?
    var pickup_code: String?
    var pickup_city: String?
    var pickup_lat: Double?
    var pickup_lng: Double?
    var dropoff_code: String?
    var dropoff_city: String?
    var dropoff_lat: Double?
    var dropoff_lng: Double?
    var date_approx: Bool?
    var notes: String?

    enum CodingKeys: String, CodingKey {
        case id, trip_id, rental_company, car_model
        case pickup_location, dropoff_location, pickup_time, dropoff_time
        case mileage_driven, confirmation_number, cost, currency
        case vehicle_class, fuel_type, pickup_odometer, dropoff_odometer, booking_source
        case external_id, agreement_number, vehicle_make, vehicle_year, vehicle_color, license_plate, photo_url
        case pickup_code, pickup_city, pickup_lat, pickup_lng
        case dropoff_code, dropoff_city, dropoff_lat, dropoff_lng
        case date_approx, notes
        case company // legacy client key
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        trip_id = try c.decodeIfPresent(Int.self, forKey: .trip_id)
        if let company = try c.decodeIfPresent(String.self, forKey: .rental_company) {
            rental_company = company
        } else {
            rental_company = try c.decodeIfPresent(String.self, forKey: .company) ?? "Unknown"
        }
        car_model = try c.decodeIfPresent(String.self, forKey: .car_model)
        pickup_location = try c.decodeIfPresent(String.self, forKey: .pickup_location) ?? ""
        dropoff_location = try c.decodeIfPresent(String.self, forKey: .dropoff_location) ?? ""
        pickup_time = try c.decodeIfPresent(String.self, forKey: .pickup_time)
        dropoff_time = try c.decodeIfPresent(String.self, forKey: .dropoff_time)
        mileage_driven = try c.decodeIfPresent(Double.self, forKey: .mileage_driven)
        confirmation_number = try c.decodeIfPresent(String.self, forKey: .confirmation_number)
        cost = try c.decodeIfPresent(Double.self, forKey: .cost)
        currency = try c.decodeIfPresent(String.self, forKey: .currency)
        vehicle_class = try c.decodeIfPresent(String.self, forKey: .vehicle_class)
        fuel_type = try c.decodeIfPresent(String.self, forKey: .fuel_type)
        pickup_odometer = try c.decodeIfPresent(Double.self, forKey: .pickup_odometer)
        dropoff_odometer = try c.decodeIfPresent(Double.self, forKey: .dropoff_odometer)
        booking_source = try c.decodeIfPresent(String.self, forKey: .booking_source)
        external_id = try c.decodeIfPresent(String.self, forKey: .external_id)
        agreement_number = try c.decodeIfPresent(String.self, forKey: .agreement_number)
        vehicle_make = try c.decodeIfPresent(String.self, forKey: .vehicle_make)
        vehicle_year = try c.decodeIfPresent(Int.self, forKey: .vehicle_year)
        vehicle_color = try c.decodeIfPresent(String.self, forKey: .vehicle_color)
        license_plate = try c.decodeIfPresent(String.self, forKey: .license_plate)
        photo_url = try c.decodeIfPresent(String.self, forKey: .photo_url)
        pickup_code = try c.decodeIfPresent(String.self, forKey: .pickup_code)
        pickup_city = try c.decodeIfPresent(String.self, forKey: .pickup_city)
        pickup_lat = try c.decodeIfPresent(Double.self, forKey: .pickup_lat)
        pickup_lng = try c.decodeIfPresent(Double.self, forKey: .pickup_lng)
        dropoff_code = try c.decodeIfPresent(String.self, forKey: .dropoff_code)
        dropoff_city = try c.decodeIfPresent(String.self, forKey: .dropoff_city)
        dropoff_lat = try c.decodeIfPresent(Double.self, forKey: .dropoff_lat)
        dropoff_lng = try c.decodeIfPresent(Double.self, forKey: .dropoff_lng)
        date_approx = try c.decodeIfPresent(Bool.self, forKey: .date_approx)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
    }
}

struct ApiParticipant: Codable, Identifiable {
    var id: Int
    var username: String?
    var email: String?
    /// Added to a trip but hasn't signed up yet: can be sent an invite code.
    var is_placeholder: Bool = false

    enum CodingKeys: String, CodingKey {
        case id, username, email, is_placeholder
    }

    init(id: Int, username: String?, email: String? = nil) {
        self.id = id
        self.username = username
        self.email = email
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        username = try container.decodeIfPresent(String.self, forKey: .username)
        email = try container.decodeIfPresent(String.self, forKey: .email)
        is_placeholder = try container.decodeIfPresent(Bool.self, forKey: .is_placeholder) ?? false
    }
}

// MARK: - Stats / Passport

struct ApiStatItem: Codable, Identifiable {
    var id: String { name }
    var name: String
    var count: Int
}

struct ApiFlightStats: Codable {
    var count: Int
    var airports: Int
    var distance_miles: Double
    var distance_km: Double
    var duration_minutes: Int
    var total_cost_by_currency: [String: Double]
    var top_aircraft: [ApiStatItem]
    var top_airlines: [ApiStatItem]
}

struct ApiRentalStats: Codable {
    var count: Int
    var mileage_driven: Double
    var duration_days: Double
    var total_cost_by_currency: [String: Double]
    var top_cars: [ApiStatItem]
    var top_rental_companies: [ApiStatItem]
    var top_vehicle_classes: [ApiStatItem]
}

struct ApiStats: Codable {
    var year: Int?
    var flights: ApiFlightStats?
    var rentals: ApiRentalStats?
    var stays: ApiStayStats?
    var total_trips: Int
    var total_expenses_by_currency: [String: Double]?
    // Flat aliases (backward compatible with pre-PR3 / mock payloads)
    var total_expenses: Double
    var total_flights: Int
    var total_airports: Int
    var top_aircraft: [ApiStatItem]?
    var top_airlines: [ApiStatItem]?
    var top_cars: [ApiStatItem]?
    var top_rental_companies: [ApiStatItem]?

    var displayFlightCount: Int { flights?.count ?? total_flights }
    var displayAirports: Int { flights?.airports ?? total_airports }
    var displayFlightMiles: Double { flights?.distance_miles ?? 0 }
    var displayRentalCount: Int { rentals?.count ?? 0 }
    var displayRentalMiles: Double { rentals?.mileage_driven ?? 0 }
    var displayRentalDays: Double { rentals?.duration_days ?? 0 }

    var logbookAircraft: [ApiStatItem] {
        flights?.top_aircraft ?? top_aircraft ?? []
    }
    var logbookAirlines: [ApiStatItem] {
        flights?.top_airlines ?? top_airlines ?? []
    }
    var logbookCars: [ApiStatItem] {
        rentals?.top_cars ?? top_cars ?? []
    }
    var logbookRentalCompanies: [ApiStatItem] {
        rentals?.top_rental_companies ?? top_rental_companies ?? []
    }
    var logbookVehicleClasses: [ApiStatItem] {
        rentals?.top_vehicle_classes ?? []
    }

    var usdExpenses: Double {
        if let map = total_expenses_by_currency, let usd = map["USD"] {
            return usd
        }
        return total_expenses
    }
}

struct ApiStatsYears: Codable {
    var years: [Int]
}

// MARK: - Network

@MainActor
class NetworkManager: ObservableObject {
    @Published var trips: [ApiTrip] = []
    @Published var flights: [ApiFlight] = []
    @Published var expenses: [ApiExpense] = []
    @Published var stats: ApiStats?
    @Published var statsYears: [Int] = []
    @Published var rentals: [ApiRentalCar] = []
    @Published var rentalsLoaded = false
    @Published var rentalsError: String?
    /// Everyone the backend knows (trip owners + travelers), for names and avatars.
    @Published var users: [ApiParticipant] = []
    @Published var groups: [ApiGroup] = []
    @Published var journeys: [ApiJourney] = []
    @Published var journeySuggestions: [ApiJourneySuggestion] = []
    /// Forwarded-email log: unseen entries (badge) and whether the server has email-in turned on.
    @Published var inboundUnread = 0
    @Published var inboundEnabled = false

    func fetchTrips() async {
        guard let url = APIConfig.url("/trips/?limit=500") else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            let decoded = try JSONDecoder().decode([ApiTrip].self, from: data)
            self.trips = decoded
        } catch {
            print("Error fetching trips: \(error)")
        }
    }

    func fetchRentals() async {
        guard let url = APIConfig.url("/rental_cars/?limit=1000") else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            self.rentals = try JSONDecoder().decode([ApiRentalCar].self, from: data)
            self.rentalsError = nil
        } catch {
            print("Error fetching rentals: \(error)")
            self.rentalsError = error.localizedDescription
        }
        self.rentalsLoaded = true
    }

    func fetchFlights() async {
        guard let url = APIConfig.url("/flights/") else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            self.flights = try JSONDecoder().decode([ApiFlight].self, from: data)
        } catch {
            print("Error fetching flights: \(error)")
        }
    }

    func fetchExpenses() async {
        guard let url = APIConfig.url("/expenses/") else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            self.expenses = try JSONDecoder().decode([ApiExpense].self, from: data)
        } catch {
            print("Error fetching expenses: \(error)")
        }
    }

    func fetchStatsYears() async {
        guard let url = APIConfig.url("/stats/years") else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            let decoded = try JSONDecoder().decode(ApiStatsYears.self, from: data)
            self.statsYears = decoded.years
        } catch {
            print("Error fetching stats years: \(error)")
        }
    }

    func fetchStats(year: Int? = nil) async {
        var path = "/stats/"
        if let year {
            path += "?year=\(year)"
        }
        guard let url = APIConfig.url(path) else { return }
        do {
            let (data, _) = try await APIClient.data(from: url)
            self.stats = try JSONDecoder().decode(ApiStats.self, from: data)
        } catch {
            print("Error fetching stats (likely ATS block): \(error)")
            // Fallback for Simulator when API is unreachable
            let mockJson = """
            {
                "year": null,
                "flights": {
                    "count": 12,
                    "airports": 8,
                    "distance_miles": 24500.0,
                    "distance_km": 39428.9,
                    "duration_minutes": 2100,
                    "total_cost_by_currency": {"USD": 4200.0},
                    "top_aircraft": [
                        {"name": "Boeing 737", "count": 5},
                        {"name": "Airbus A320", "count": 4},
                        {"name": "Boeing 787", "count": 2}
                    ],
                    "top_airlines": [
                        {"name": "Delta Air Lines", "count": 6},
                        {"name": "United Airlines", "count": 4}
                    ]
                },
                "rentals": {
                    "count": 4,
                    "mileage_driven": 980.0,
                    "duration_days": 18.0,
                    "total_cost_by_currency": {"USD": 860.0},
                    "top_cars": [
                        {"name": "Tesla Model 3", "count": 3},
                        {"name": "Toyota RAV4", "count": 1}
                    ],
                    "top_rental_companies": [
                        {"name": "Hertz", "count": 2},
                        {"name": "Enterprise", "count": 2}
                    ],
                    "top_vehicle_classes": [
                        {"name": "full_size", "count": 2},
                        {"name": "suv", "count": 2}
                    ]
                },
                "total_trips": 4,
                "total_expenses_by_currency": {"USD": 1450.0},
                "total_expenses": 1450.0,
                "total_flights": 12,
                "total_airports": 8,
                "top_aircraft": [
                    {"name": "Boeing 737", "count": 5},
                    {"name": "Airbus A320", "count": 4},
                    {"name": "Boeing 787", "count": 2}
                ],
                "top_airlines": [
                    {"name": "Delta Air Lines", "count": 6},
                    {"name": "United Airlines", "count": 4}
                ],
                "top_cars": [
                    {"name": "Tesla Model 3", "count": 3},
                    {"name": "Toyota RAV4", "count": 1}
                ],
                "top_rental_companies": [
                    {"name": "Hertz", "count": 2},
                    {"name": "Enterprise", "count": 2}
                ]
            }
            """
            if let data = mockJson.data(using: .utf8),
               let mockStats = try? JSONDecoder().decode(ApiStats.self, from: data) {
                self.stats = mockStats
                if self.statsYears.isEmpty {
                    self.statsYears = [2026, 2025]
                }
            }
        }
    }

    func createTrip(title: String, description: String) async {
        guard let url = APIConfig.url("/trips/") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = ["title": title, "description": description]
        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (_, _) = try await APIClient.data(for: request)
            await fetchTrips()
        } catch {
            print("Error creating trip: \(error)")
        }
    }

    func addParticipant(tripId: Int, userId: Int) async {
        guard let url = APIConfig.url("/trips/\(tripId)/participants/\(userId)") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            let (_, _) = try await APIClient.data(for: request)
            await fetchTrips()
        } catch {
            print("Error adding participant: \(error)")
        }
    }

    func fetchTimeline(tripId: Int) async -> [ApiTimelineEvent] {
        guard let url = APIConfig.url("/trips/\(tripId)/timeline") else { return [] }
        do {
            let (data, _) = try await APIClient.data(from: url)
            return try JSONDecoder().decode([ApiTimelineEvent].self, from: data)
        } catch {
            print("Error fetching timeline: \(error)")
            return []
        }
    }

    // MARK: - Travelers (people on a trip)

    /// Result of a write call: nil on success, otherwise a message suitable for the UI.
    func send(_ method: String, _ path: String, json: [String: Any]? = nil) async -> (data: Data?, status: Int, error: String?) {
        guard let url = APIConfig.url(path) else { return (nil, 0, "Bad URL \(path)") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let json { request.httpBody = try? JSONSerialization.data(withJSONObject: json) }
        do {
            let (data, response) = try await APIClient.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            if (200..<300).contains(status) { return (data, status, nil) }
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            return (data, status, detail ?? "Request failed (\(status))")
        } catch {
            return (nil, 0, error.localizedDescription)
        }
    }

    /// Replace one trip in place from a returned Trip payload (instant UI update), then refresh.
    func applyTrip(_ data: Data?) {
        guard let data, let trip = try? JSONDecoder().decode(ApiTrip.self, from: data),
              let i = trips.firstIndex(where: { $0.id == trip.id }) else { return }
        var updated = trip
        updated.pinned = trips[i].pinned
        trips[i] = updated
    }

    func fetchUsers() async -> [ApiParticipant] {
        guard let url = APIConfig.url("/users/?limit=500") else { return [] }
        do {
            let (data, _) = try await APIClient.data(from: url)
            return try JSONDecoder().decode([ApiParticipant].self, from: data)
        } catch {
            print("Error fetching users: \(error)")
            return []
        }
    }

    /// Adds a person by name (+ optional email); the backend reuses or creates the user.
    func addTraveler(tripId: Int, name: String, email: String?) async -> String? {
        var body: [String: Any] = ["name": name]
        if let email, !email.isEmpty { body["email"] = email }
        let r = await send("POST", "/trips/\(tripId)/travelers", json: body)
        if r.error == nil { applyTrip(r.data) }
        return r.error
    }

    /// Returns (error, needsForce). A 409 means the person still has unsettled splits.
    func removeTraveler(tripId: Int, userId: Int, force: Bool = false) async -> (error: String?, conflict: Bool) {
        let r = await send("DELETE", "/trips/\(tripId)/participants/\(userId)" + (force ? "?force=true" : ""))
        if r.error == nil { applyTrip(r.data) }
        return (r.error, r.status == 409)
    }

    /// Renames a trip. A hand-picked title is never replaced by the auto route title again.
    func renameTrip(_ id: Int, title: String) async -> String? {
        let r = await send("PATCH", "/trips/\(id)", json: ["title": title])
        if r.error == nil { applyTrip(r.data) }
        return r.error
    }

    /// Moves the trip to Recently Deleted (restorable for 30 days) and offers Undo.
    func deleteTrip(id: Int, force: Bool = false) async -> String? {
        await trashTrips([id]).error
    }


}
