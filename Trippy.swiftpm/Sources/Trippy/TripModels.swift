import SwiftUI
import MapKit

// MARK: - Airports (flights only carry IATA codes)

enum Airports {
    private static let table: [String: (city: String, lat: Double, lng: Double)] = [
        "ATL": ("Atlanta", 33.6407, -84.4277), "AUS": ("Austin", 30.1975, -97.6664),
        "BOS": ("Boston", 42.3656, -71.0096), "BWI": ("Baltimore", 39.1774, -76.6684),
        "CLT": ("Charlotte", 35.2144, -80.9473), "DCA": ("Washington", 38.8512, -77.0402),
        "DEN": ("Denver", 39.8561, -104.6737), "DFW": ("Dallas", 32.8998, -97.0403),
        "DTW": ("Detroit", 42.2162, -83.3554), "EWR": ("Newark", 40.6895, -74.1745),
        "FLL": ("Fort Lauderdale", 26.0742, -80.1506), "HNL": ("Honolulu", 21.3245, -157.9251),
        "IAD": ("Washington", 38.9531, -77.4565), "IAH": ("Houston", 29.9902, -95.3368),
        "JFK": ("New York", 40.6413, -73.7781), "LAS": ("Las Vegas", 36.0840, -115.1537),
        "LAX": ("Los Angeles", 33.9416, -118.4085), "LGA": ("New York", 40.7769, -73.8740),
        "MCO": ("Orlando", 28.4312, -81.3081), "MDW": ("Chicago", 41.7868, -87.7522),
        "MIA": ("Miami", 25.7959, -80.2870), "MSP": ("Minneapolis", 44.8848, -93.2223),
        "OAK": ("Oakland", 37.7126, -122.2197), "ORD": ("Chicago", 41.9742, -87.9073),
        "PDX": ("Portland", 45.5898, -122.5951), "PHL": ("Philadelphia", 39.8744, -75.2424),
        "PHX": ("Phoenix", 33.4352, -112.0101), "SAN": ("San Diego", 32.7338, -117.1933),
        "SEA": ("Seattle", 47.4502, -122.3088), "SFO": ("San Francisco", 37.6213, -122.3790),
        "SJC": ("San Jose", 37.3639, -121.9289), "SLC": ("Salt Lake City", 40.7899, -111.9791),
        "SMF": ("Sacramento", 38.6951, -121.5908), "YVR": ("Vancouver", 49.1967, -123.1815),
        "YYZ": ("Toronto", 43.6777, -79.6248), "MEX": ("Mexico City", 19.4361, -99.0719),
        "CUN": ("Cancún", 21.0365, -86.8771), "LHR": ("London", 51.4700, -0.4543),
        "LGW": ("London", 51.1537, -0.1821), "CDG": ("Paris", 49.0097, 2.5479),
        "AMS": ("Amsterdam", 52.3105, 4.7683), "FRA": ("Frankfurt", 50.0379, 8.5622),
        "MUC": ("Munich", 48.3537, 11.7750), "MAD": ("Madrid", 40.4983, -3.5676),
        "BCN": ("Barcelona", 41.2974, 2.0833), "FCO": ("Rome", 41.8003, 12.2389),
        "ZRH": ("Zurich", 47.4582, 8.5555), "DUB": ("Dublin", 53.4264, -6.2499),
        "LIS": ("Lisbon", 38.7742, -9.1342), "IST": ("Istanbul", 41.2753, 28.7519),
        "DXB": ("Dubai", 25.2532, 55.3657), "DOH": ("Doha", 25.2731, 51.6081),
        "DEL": ("Delhi", 28.5562, 77.1000), "BOM": ("Mumbai", 19.0896, 72.8656),
        "BLR": ("Bengaluru", 13.1986, 77.7066), "HYD": ("Hyderabad", 17.2403, 78.4294),
        "MAA": ("Chennai", 12.9941, 80.1709), "SIN": ("Singapore", 1.3644, 103.9915),
        "HKG": ("Hong Kong", 22.3080, 113.9185), "NRT": ("Tokyo", 35.7720, 140.3929),
        "HND": ("Tokyo", 35.5494, 139.7798), "KIX": ("Osaka", 34.4320, 135.2304),
        "ICN": ("Seoul", 37.4602, 126.4407), "TPE": ("Taipei", 25.0797, 121.2342),
        "PEK": ("Beijing", 40.0799, 116.6031), "PVG": ("Shanghai", 31.1443, 121.8083),
        "BKK": ("Bangkok", 13.6900, 100.7501), "SYD": ("Sydney", -33.9399, 151.1753),
        "MEL": ("Melbourne", -37.6690, 144.8410), "AKL": ("Auckland", -37.0082, 174.7850),
        "GRU": ("São Paulo", -23.4356, -46.4731), "EZE": ("Buenos Aires", -34.8222, -58.5358),
        "JNB": ("Johannesburg", -26.1367, 28.2411), "CPT": ("Cape Town", -33.9715, 18.6021),
        "PIT": ("Pittsburgh", 40.4915, -80.2329), "ANC": ("Anchorage", 61.1743, -149.9963),
        "FCA": ("Kalispell", 48.3105, -114.2560), "CMH": ("Columbus", 39.9980, -82.8919),
        "BER": ("Berlin", 52.3667, 13.5033), "VTZ": ("Visakhapatnam", 17.7212, 83.2245),
    ]

    /// IANA zone per airport, so wall-clock times from different places sort by real time.
    private static let zones: [String: String] = [
        "ATL": "America/New_York", "AUS": "America/Chicago", "BOS": "America/New_York", "BWI": "America/New_York",
        "CLT": "America/New_York", "DCA": "America/New_York", "DEN": "America/Denver", "DFW": "America/Chicago",
        "DTW": "America/Detroit", "EWR": "America/New_York", "FLL": "America/New_York", "HNL": "Pacific/Honolulu",
        "IAD": "America/New_York", "IAH": "America/Chicago", "JFK": "America/New_York", "LAS": "America/Los_Angeles",
        "LAX": "America/Los_Angeles", "LGA": "America/New_York", "MCO": "America/New_York", "MDW": "America/Chicago",
        "MIA": "America/New_York", "MSP": "America/Chicago", "OAK": "America/Los_Angeles", "ORD": "America/Chicago",
        "PDX": "America/Los_Angeles", "PHL": "America/New_York", "PHX": "America/Phoenix", "SAN": "America/Los_Angeles",
        "SEA": "America/Los_Angeles", "SFO": "America/Los_Angeles", "SJC": "America/Los_Angeles", "SLC": "America/Denver",
        "SMF": "America/Los_Angeles", "YVR": "America/Vancouver", "YYZ": "America/Toronto", "MEX": "America/Mexico_City",
        "CUN": "America/Cancun", "LHR": "Europe/London", "LGW": "Europe/London", "CDG": "Europe/Paris",
        "AMS": "Europe/Amsterdam", "FRA": "Europe/Berlin", "MUC": "Europe/Berlin", "MAD": "Europe/Madrid",
        "BCN": "Europe/Madrid", "FCO": "Europe/Rome", "ZRH": "Europe/Zurich", "DUB": "Europe/Dublin",
        "LIS": "Europe/Lisbon", "IST": "Europe/Istanbul", "DXB": "Asia/Dubai", "DOH": "Asia/Qatar",
        "DEL": "Asia/Kolkata", "BOM": "Asia/Kolkata", "BLR": "Asia/Kolkata", "HYD": "Asia/Kolkata",
        "MAA": "Asia/Kolkata", "SIN": "Asia/Singapore", "HKG": "Asia/Hong_Kong", "NRT": "Asia/Tokyo",
        "HND": "Asia/Tokyo", "KIX": "Asia/Tokyo", "ICN": "Asia/Seoul", "TPE": "Asia/Taipei",
        "PEK": "Asia/Shanghai", "PVG": "Asia/Shanghai", "BKK": "Asia/Bangkok", "SYD": "Australia/Sydney",
        "MEL": "Australia/Melbourne", "AKL": "Pacific/Auckland", "GRU": "America/Sao_Paulo",
        "EZE": "America/Argentina/Buenos_Aires", "JNB": "Africa/Johannesburg", "CPT": "Africa/Johannesburg",
        "PIT": "America/New_York", "ANC": "America/Anchorage", "FCA": "America/Denver", "CMH": "America/New_York",
        "BER": "Europe/Berlin", "VTZ": "Asia/Kolkata",
    ]

    static func timeZone(_ code: String?) -> TimeZone? {
        guard let code, let id = zones[code.uppercased()] else { return nil }
        return TimeZone(identifier: id)
    }

    /// Zone of the closest known airport (within ~300 mi), else a whole-hour guess from longitude.
    static func timeZone(near c: CLLocationCoordinate2D) -> TimeZone? {
        let here = CLLocation(latitude: c.latitude, longitude: c.longitude)
        let best = table.min { a, b in
            here.distance(from: CLLocation(latitude: a.value.lat, longitude: a.value.lng))
                < here.distance(from: CLLocation(latitude: b.value.lat, longitude: b.value.lng))
        }
        if let best, here.distance(from: CLLocation(latitude: best.value.lat, longitude: best.value.lng)) < 480_000,
           let tz = timeZone(best.key) { return tz }
        return TimeZone(secondsFromGMT: Int((c.longitude / 15).rounded()) * 3600)
    }

    static var all: [(code: String, city: String)] { table.map { ($0.key, $0.value.city) } }

    static func coordinate(_ code: String) -> CLLocationCoordinate2D? {
        table[code.uppercased()].map { CLLocationCoordinate2D(latitude: $0.lat, longitude: $0.lng) }
    }

    static func city(_ code: String) -> String? { table[code.uppercased()]?.city }
}

// MARK: - Phase

enum TripPhase: Int {
    case now, upcoming, past

    var label: String {
        switch self {
        case .now: return "Now"
        case .upcoming: return "Upcoming"
        case .past: return "Past"
        }
    }

    var color: Color {
        switch self {
        case .now: return Theme.green
        case .upcoming: return Theme.blue
        case .past: return Theme.textSecondary
        }
    }
}

// MARK: - Unified itinerary events

enum TripEventKind {
    case departure, arrival, pickup, dropoff, activity, stay

    var color: Color {
        switch self {
        case .departure, .arrival: return Theme.blue
        case .pickup, .dropoff: return Theme.green
        case .activity: return Theme.purple
        case .stay: return Theme.stay
        }
    }

    var icon: String {
        switch self {
        case .departure: return "airplane.departure"
        case .arrival: return "airplane.arrival"
        case .pickup: return "car.fill"
        case .dropoff: return "key.fill"
        case .activity: return "star.fill"
        case .stay: return "bed.double.fill"
        }
    }
}

struct TripEvent: Identifiable {
    let id: String
    let kind: TripEventKind
    let date: Date?
    let code: String
    let city: String?
    let coordinate: CLLocationCoordinate2D?
    /// Small uppercase line above the big time, e.g. "UNITED UA 837" or "PICK UP · HERTZ".
    let micro: String
    let title: String
    let subtitle: String?
    let highlight: String?
    let highlightIcon: String?
    var rental: ApiRentalCar? = nil
    /// Hotel stays render as one Flighty-style row (nights hero) instead of a time row.
    var lodging: ApiLodging? = nil
    /// Bundled airline / rental logo shown in place of the kind glyph.
    var brandAsset: String? = nil
    /// Where `date` (a local wall-clock time) happens; used to sort by real time.
    var zone: TimeZone? = nil

    /// The real instant: `date` is parsed as if it were in the device's zone.
    var instant: Date? {
        guard let date, let zone else { return date }
        let shift = zone.secondsFromGMT(for: date) - TimeZone.current.secondsFromGMT(for: date)
        return date.addingTimeInterval(TimeInterval(-shift))
    }
}

struct TripStop: Identifiable {
    var id: String { code }
    let code: String
    let city: String?
    let coordinate: CLLocationCoordinate2D?
}

extension ApiParticipant {
    var displayName: String { (username?.isEmpty == false ? username! : nil) ?? email ?? "Traveler \(id)" }
    var firstName: String { displayName.split(separator: " ").first.map(String.init) ?? displayName }
    var initials: String {
        let parts = displayName.split(whereSeparator: { $0 == " " || $0 == "." || $0 == "_" || $0 == "@" })
        let letters = parts.prefix(2).compactMap(\.first).map { String($0).uppercased() }
        return letters.joined().isEmpty ? "?" : letters.joined()
    }
    /// Placeholder addresses are generated for people added by name only.
    var realEmail: String? {
        guard let email, !email.hasSuffix("@travelers.trippy.local") else { return nil }
        return email
    }
    var avatarColor: Color {
        let palette = [Theme.blue, Theme.purple, Theme.green, Theme.orange, Theme.teal, Color(hex: 0xFF375F)]
        let sum = displayName.unicodeScalars.reduce(0) { $0 + Int($1.value) }
        return palette[sum % palette.count]
    }
}

extension ApiTrip {
    static let autoMarker = "Auto-generated from rental history"

    var isAutoGenerated: Bool {
        (description ?? "").hasPrefix(Self.autoMarker) || title.hasSuffix("(auto)")
    }

    /// Title without the " (auto)" suffix (shown as a tag instead).
    var displayTitle: String {
        title.hasSuffix(" (auto)") ? String(title.dropLast(7)) : title
    }

    /// Rentals that belong to the trip: linked by trip_id, plus unassigned rentals whose pickup
    /// falls inside the trip window.
    func linkedRentals(from all: [ApiRentalCar]) -> [ApiRentalCar] {
        var byId: [Int: ApiRentalCar] = [:]
        for r in rental_cars { byId[r.id] = r }
        for r in all where r.trip_id == id { byId[r.id] = r }
        if let s = Fmt.parse(start_date), let e = Fmt.parse(end_date) {
            let window = s.addingTimeInterval(-12 * 3600)...e.addingTimeInterval(36 * 3600)
            for r in all where r.trip_id == nil {
                if let p = r.pickupDate, window.contains(p) { byId[r.id] = r }
            }
        }
        return byId.values.sorted { ($0.pickupDate ?? .distantFuture) < ($1.pickupDate ?? .distantFuture) }
    }

    func events(rentals all: [ApiRentalCar]) -> [TripEvent] {
        var out: [TripEvent] = []
        for f in flights {
            let dep = Fmt.parse(f.departure_time), arr = Fmt.parse(f.arrival_time)
            let airline = f.airline.uppercased()
            var depSub: [String] = []
            if let arr { depSub.append("Arrives \(f.arrival_airport) \(Fmt.time(arr))") }
            if let dep, let arr { depSub.append(Fmt.duration(arr.timeIntervalSince(dep))) }
            if let cabin = DisplayName.cabin(f.cabin_class) { depSub.append(cabin) }
            out.append(TripEvent(id: "f\(f.id)-d", kind: .departure, date: dep,
                                 code: f.departure_airport, city: Airports.city(f.departure_airport),
                                 coordinate: Airports.coordinate(f.departure_airport),
                                 micro: "\(airline) \(f.flight_number)".uppercased(),
                                 title: "Depart \(Airports.city(f.departure_airport) ?? f.departure_airport)",
                                 subtitle: depSub.isEmpty ? nil : depSub.joined(separator: " · "),
                                 highlight: f.seat.map { "Seat \($0)" } ?? f.confirmation_number,
                                 highlightIcon: f.seat != nil ? "carseat.right.fill" : "number",
                                 brandAsset: BrandLogos.airline(name: f.airline, flightNumber: f.flight_number),
                                 zone: Airports.timeZone(f.departure_airport)))
            out.append(TripEvent(id: "f\(f.id)-a", kind: .arrival, date: arr,
                                 code: f.arrival_airport, city: Airports.city(f.arrival_airport),
                                 coordinate: Airports.coordinate(f.arrival_airport),
                                 micro: "LAND · \(f.flight_number)".uppercased(),
                                 title: "Arrive \(Airports.city(f.arrival_airport) ?? f.arrival_airport)",
                                 subtitle: DisplayName.flightStatus(f.status),
                                 highlight: nil, highlightIcon: nil,
                                 zone: Airports.timeZone(f.arrival_airport)))
        }
        for r in linkedRentals(from: all) {
            let pCity = Airports.city(r.pickupDisplayCode) ?? r.pickupDisplayCity
            let dCity = Airports.city(r.dropoffDisplayCode) ?? r.dropoffDisplayCity
            let brand = RentalBrand.forCompany(r.rental_company).name.uppercased()
            out.append(TripEvent(id: "r\(r.id)-p", kind: .pickup, date: r.pickupDate,
                                 code: r.pickupDisplayCode, city: pCity, coordinate: r.pickupCoordinate ?? Airports.coordinate(r.pickupDisplayCode),
                                 micro: "PICK UP · \(brand)",
                                 title: r.vehicleName,
                                 subtitle: [pCity, r.rentalDays.map { $0 == 1 ? "1 day" : "\($0) days" }]
                                    .compactMap { $0 }.joined(separator: " · "),
                                 highlight: r.license_plate ?? r.confirmationText ?? DisplayName.vehicleClass(r.vehicle_class),
                                 highlightIcon: r.license_plate != nil ? "car.rear.fill" : "number",
                                 rental: r, brandAsset: BrandLogos.rental(r.rental_company),
                                 zone: Airports.timeZone(r.pickupDisplayCode)
                                    ?? r.pickupCoordinate.flatMap { Airports.timeZone(near: $0) }))
            if r.dropoffDate != nil || r.isOneWay {
                out.append(TripEvent(id: "r\(r.id)-d", kind: .dropoff, date: r.dropoffDate,
                                     code: r.dropoffDisplayCode, city: dCity, coordinate: r.dropoffCoordinate ?? Airports.coordinate(r.dropoffDisplayCode) ?? r.pickupCoordinate,
                                     micro: "RETURN · \(brand)",
                                     title: r.isOneWay ? "Drop off in \(dCity)" : "Return to \(r.dropoffDisplayCode)",
                                     subtitle: r.costText.map { "Total \($0)" },
                                     highlight: r.milesDriven.map { "\(Fmt.number($0)) mi" },
                                     highlightIcon: r.milesDriven != nil ? "gauge.with.dots.needle.67percent" : nil,
                                     rental: r,
                                     zone: Airports.timeZone(r.dropoffDisplayCode)
                                        ?? r.dropoffCoordinate.flatMap { Airports.timeZone(near: $0) }))
            }
        }
        for a in activities {
            out.append(TripEvent(id: "a\(a.id)", kind: .activity, date: Fmt.parse(a.start_time),
                                 code: "", city: nil, coordinate: nil,
                                 micro: "PLAN", title: a.title, subtitle: a.description,
                                 highlight: nil, highlightIcon: nil))
        }
        // Stays: one row at check-in. code "" keeps them off the flight/drive route.
        for h in lodgings {
            out.append(TripEvent(id: "h\(h.id)", kind: .stay, date: h.checkInDate,
                                 code: "", city: h.city, coordinate: h.coordinate,
                                 micro: h.microLine, title: h.name, subtitle: nil,
                                 highlight: nil, highlightIcon: nil, lodging: h,
                                 zone: h.check_in_tz.flatMap(TimeZone.init(identifier:))
                                    ?? h.coordinate.flatMap { Airports.timeZone(near: $0) }))
        }
        return Self.timelineOrder(out)
    }

    /// Real-time order (each wall-clock time in its own zone). A hotel check-in never sorts above
    /// a flight landing the same local day: you check in after you land.
    static func timelineOrder(_ events: [TripEvent]) -> [TripEvent] {
        let cal = Calendar.current
        var key: [String: Date] = [:]
        for e in events { key[e.id] = e.instant ?? .distantFuture }
        // A landing never sorts above its own takeoff, even when the data's times or zones disagree.
        for e in events where e.kind == .arrival {
            let dep = String(e.id.dropLast(2)) + "-d"
            if let d = key[dep], let a = key[e.id], a <= d { key[e.id] = d.addingTimeInterval(1) }
        }
        for e in events where e.kind == .stay {
            guard let d = e.date else { continue }
            let landings = events.filter { $0.kind == .arrival && $0.date.map { cal.isDate($0, inSameDayAs: d) } == true }
            if let last = landings.compactMap({ key[$0.id] }).max(), let mine = key[e.id], mine <= last {
                key[e.id] = last.addingTimeInterval(1)
            }
        }
        return events.enumerated().sorted { a, b in
            let ka = key[a.element.id] ?? .distantFuture, kb = key[b.element.id] ?? .distantFuture
            return ka != kb ? ka < kb : a.offset < b.offset
        }.map(\.element)
    }

    /// Booked stays that aren't cancelled.
    var activeLodgings: [ApiLodging] { lodgings.filter { !$0.isCancelled } }

    /// Ordered distinct places (consecutive duplicates collapsed).
    func stops(events: [TripEvent]) -> [TripStop] {
        var out: [TripStop] = []
        for e in events where !e.code.isEmpty {
            let coord = e.coordinate ?? Airports.coordinate(e.code)
            if let last = out.last, last.code == e.code {
                if last.coordinate == nil, coord != nil {
                    out[out.count - 1] = TripStop(code: e.code, city: last.city ?? e.city, coordinate: coord)
                }
                continue
            }
            out.append(TripStop(code: e.code, city: e.city ?? Airports.city(e.code), coordinate: coord))
        }
        return out
    }

    func startDate(events: [TripEvent]) -> Date? {
        Fmt.parse(start_date) ?? events.compactMap(\.date).min()
    }

    func endDate(events: [TripEvent]) -> Date? {
        Fmt.parse(end_date) ?? events.compactMap(\.date).max()
    }

    func phase(events: [TripEvent], now: Date) -> TripPhase {
        guard let s = startDate(events: events) else { return .upcoming }
        if now < s { return .upcoming }
        let e = endDate(events: events) ?? s
        return now <= Calendar.current.startOfDay(for: e).addingTimeInterval(86_400) ? .now : .past
    }

    /// Whole days covered, counting both ends ("Nov 1 – 15" = 15 days).
    func dayCount(events: [TripEvent]) -> Int? {
        guard let s = startDate(events: events) else { return nil }
        let e = endDate(events: events) ?? s
        let cal = Calendar.current
        let d = cal.dateComponents([.day], from: cal.startOfDay(for: s), to: cal.startOfDay(for: e)).day ?? 0
        return max(1, d + 1)
    }

    var expenseTotal: Double { expenses.reduce(0) { $0 + $1.amount } }

    /// Expenses when logged; otherwise what the bookings themselves cost.
    func spend(rentals: [ApiRentalCar]) -> (amount: Double, isBookings: Bool) {
        if !expenses.isEmpty { return (expenseTotal, false) }
        let bookings = rentals.reduce(0) { $0 + ($1.cost ?? 0) } + flights.reduce(0) { $0 + ($1.cost ?? 0) }
            + activeLodgings.reduce(0) { $0 + ($1.cost ?? 0) }
        return (bookings, true)
    }

    func dateRange(events: [TripEvent], withYear: Bool = false) -> String? {
        guard let s = startDate(events: events) else { return nil }
        let e = endDate(events: events) ?? s
        let cal = Calendar.current
        let tail = withYear ? ", \(cal.component(.year, from: e))" : ""
        if cal.isDate(s, inSameDayAs: e) { return Fmt.monthDay(s) + tail }
        if cal.isDate(s, equalTo: e, toGranularity: .month) {
            return "\(Fmt.monthDay(s))–\(cal.component(.day, from: e))" + tail
        }
        return "\(Fmt.monthDay(s)) – \(Fmt.monthDay(e))" + tail
    }
}

/// One trip with everything derived from it (computed once per render).
struct TripSnapshot: Identifiable {
    let trip: ApiTrip
    let rentals: [ApiRentalCar]
    let events: [TripEvent]
    let stops: [TripStop]
    let start: Date?
    let end: Date?
    let phase: TripPhase

    var id: Int { trip.id }

    init(trip: ApiTrip, allRentals: [ApiRentalCar], now: Date) {
        self.trip = trip
        self.rentals = trip.linkedRentals(from: allRentals)
        self.events = trip.events(rentals: allRentals)
        self.stops = trip.stops(events: events)
        self.start = trip.startDate(events: events)
        self.end = trip.endDate(events: events)
        self.phase = trip.phase(events: events, now: now)
    }

    var routeCodes: String {
        var codes = stops.map(\.code)
        if codes.isEmpty {
            // Hotel-only trips: show the stay cities in check-in order.
            var seen = Set<String>()
            codes = trip.activeLodgings.sorted { ($0.check_in ?? "") < ($1.check_in ?? "") }
                .compactMap { $0.city?.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty && seen.insert($0).inserted }
        }
        if codes.isEmpty { return "No places yet" }
        if codes.count <= 4 { return codes.joined(separator: " → ") }
        return codes.prefix(3).joined(separator: " → ") + " → +\(codes.count - 3)"
    }

    var days: Int? { trip.dayCount(events: events) }
    var year: Int { start.map { Calendar.current.component(.year, from: $0) } ?? 0 }
    var dateRange: String? { trip.dateRange(events: events) }
    var spend: (amount: Double, isBookings: Bool) { trip.spend(rentals: rentals) }

    /// Days until start (upcoming) or days left (now).
    func countdownDays(now: Date) -> Int {
        let cal = Calendar.current
        let target = phase == .upcoming ? start : end
        guard let target else { return 0 }
        return max(0, cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: target)).day ?? 0)
    }

    func dayOfTrip(now: Date) -> Int {
        guard let start else { return 1 }
        let cal = Calendar.current
        return (cal.dateComponents([.day], from: cal.startOfDay(for: start), to: cal.startOfDay(for: now)).day ?? 0) + 1
    }
}
