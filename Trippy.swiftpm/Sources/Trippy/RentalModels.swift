import SwiftUI
import CoreLocation

// MARK: - Rental company branding

struct RentalBrand {
    let name: String
    let short: String
    let color: Color
    let foreground: Color

    static func forCompany(_ company: String) -> RentalBrand {
        switch company.lowercased().trimmingCharacters(in: .whitespaces) {
        case "avis": return RentalBrand(name: "Avis", short: "AV", color: Color(hex: 0xD4002A), foreground: .white)
        case "budget": return RentalBrand(name: "Budget", short: "BG", color: Color(hex: 0xF68621), foreground: Color(hex: 0x0B1F44))
        case "enterprise": return RentalBrand(name: "Enterprise", short: "EN", color: Color(hex: 0x169A5A), foreground: .white)
        case "national": return RentalBrand(name: "National", short: "NA", color: Color(hex: 0x0B7B53), foreground: .white)
        case "alamo": return RentalBrand(name: "Alamo", short: "AL", color: Color(hex: 0x0060A9), foreground: .white)
        case "hertz": return RentalBrand(name: "Hertz", short: "HZ", color: Color(hex: 0xFFD100), foreground: Color(hex: 0x111111))
        case "sixt": return RentalBrand(name: "Sixt", short: "SX", color: Color(hex: 0xFF5F00), foreground: .white)
        case "thrifty": return RentalBrand(name: "Thrifty", short: "TH", color: Color(hex: 0x0072CE), foreground: .white)
        case "dollar": return RentalBrand(name: "Dollar", short: "DR", color: Color(hex: 0xC8102E), foreground: .white)
        case "europcar": return RentalBrand(name: "Europcar", short: "EC", color: Color(hex: 0x00953A), foreground: Color(hex: 0xFFE600))
        case "fox", "fox rent a car": return RentalBrand(name: "Fox", short: "FX", color: Color(hex: 0xE35205), foreground: .white)
        case "payless": return RentalBrand(name: "Payless", short: "PL", color: Color(hex: 0x6C2C91), foreground: .white)
        case "turo": return RentalBrand(name: "Turo", short: "TU", color: Color(hex: 0x593CFB), foreground: .white)
        default:
            let letters = company.split(separator: " ").compactMap(\.first).prefix(2)
            return RentalBrand(name: company, short: letters.isEmpty ? "—" : String(letters).uppercased(),
                               color: Color(hex: 0x636366), foreground: .white)
        }
    }
}

struct CompanyBadge: View {
    let company: String
    var size: CGFloat = 34

    var body: some View {
        if let asset = BrandLogos.rental(company) {
            LogoTile(asset: asset, size: size)
        } else {
            letters
        }
    }

    private var letters: some View {
        let brand = RentalBrand.forCompany(company)
        return Text(brand.short)
            .font(.system(size: size * 0.36, weight: .heavy, design: .rounded))
            .foregroundStyle(brand.foreground)
            .frame(width: size, height: size)
            .background(
                RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                    .fill(LinearGradient(colors: [brand.color, brand.color.opacity(0.78)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            )
    }
}

// MARK: - Rental status

enum RentalPhase: Equatable {
    case upcoming, active, overdue, returned

    var label: String {
        switch self {
        case .upcoming: return "Upcoming"
        case .active: return "On the road"
        case .overdue: return "Overdue"
        case .returned: return "Returned"
        }
    }

    var color: Color {
        switch self {
        case .upcoming: return Theme.blue
        case .active: return Theme.green
        case .overdue: return Theme.red
        case .returned: return Theme.textSecondary
        }
    }

    var icon: String {
        switch self {
        case .upcoming: return "clock.fill"
        case .active: return "car.fill"
        case .overdue: return "exclamationmark.triangle.fill"
        case .returned: return "checkmark"
        }
    }
}

extension ApiRentalCar {
    var pickupDate: Date? { Fmt.parse(pickup_time) }
    var dropoffDate: Date? { Fmt.parse(dropoff_time) }
    var isApproximate: Bool { date_approx ?? false }

    func phase(at now: Date = Date()) -> RentalPhase {
        if isApproximate { return .returned }  // receipt-only rentals have already ended
        guard let start = pickupDate else { return .returned }
        if now < start { return .upcoming }
        if let end = dropoffDate {
            if now < end { return .active }
            return .returned
        }
        // No recorded return: treat as on the road for 3 days after pickup.
        return now.timeIntervalSince(start) < 3 * 86_400 ? .active : .returned
    }

    /// Fraction of the rental elapsed (0…1) — drives the progress bar.
    func progress(at now: Date = Date()) -> Double {
        guard let start = pickupDate, let end = dropoffDate, end > start else {
            return phase(at: now) == .returned ? 1 : 0
        }
        return min(max(now.timeIntervalSince(start) / end.timeIntervalSince(start), 0), 1)
    }

    /// Flighty-style countdown line: "Pickup in 2d 3h", "Return in 1d 4h", "Returned 12 days ago".
    func countdown(at now: Date = Date()) -> String {
        switch phase(at: now) {
        case .upcoming:
            return "Pickup in " + Fmt.duration(pickupDate!.timeIntervalSince(now))
        case .active, .overdue:
            if let end = dropoffDate { return "Return in " + Fmt.duration(end.timeIntervalSince(now)) }
            return "Return time not set"
        case .returned:
            guard let end = dropoffDate ?? pickupDate else { return "Returned" }
            let days = Calendar.current.dateComponents([.day], from: end, to: now).day ?? 0
            if days == 0 { return "Returned today" }
            if days == 1 { return "Returned yesterday" }
            if days < 45 { return "Returned \(days) days ago" }
            return "Returned " + Fmt.monthDayYear(end)
        }
    }

    /// Billable days (rounded up, at least 1).
    var rentalDays: Int? {
        guard let secs = rentalDuration else { return nil }
        // An hour of grace, like most counters.
        return max(1, Int(((secs - 3_600) / 86_400).rounded(.up)))
    }

    var rentalDuration: TimeInterval? {
        guard let s = pickupDate, let e = dropoffDate, e > s else { return nil }
        return e.timeIntervalSince(s)
    }

    /// Station code shown in big type: IATA code, else initials of the city/station.
    var pickupDisplayCode: String { Self.stationCode(code: pickup_code, city: pickup_city, location: pickup_location) }
    var dropoffDisplayCode: String { Self.stationCode(code: dropoff_code ?? pickup_code, city: dropoff_city ?? pickup_city, location: dropoff_location) }

    var pickupDisplayCity: String { Self.cityName(pickup_city, fallback: pickup_location) ?? "Pickup" }
    var dropoffDisplayCity: String { Self.cityName(dropoff_city ?? pickup_city, fallback: dropoff_location) ?? pickupDisplayCity }

    var isOneWay: Bool {
        let a = pickupDisplayCode, b = dropoffDisplayCode
        return a != b && a != "···" && b != "···"
    }

    /// Display name of the car ("Toyota Corolla"), without "or similar".
    var vehicleName: String {
        let raw = (car_model ?? "").trimmingCharacters(in: .whitespaces)
        if raw.isEmpty {
            if let make = vehicle_make, !make.isEmpty { return make }
            if let cls = DisplayName.vehicleClass(vehicle_class) { return "\(cls) car" }
            return "Rental car"
        }
        return raw.replacingOccurrences(of: #"\s+or [Ss]imilar$"#, with: "", options: .regularExpression)
    }

    /// True when only the booked class ("… or similar") is known, not the actual car.
    var isSimilarModel: Bool {
        (car_model ?? "").range(of: "or similar", options: .caseInsensitive) != nil
    }

    var vehicleSubtitle: String {
        var parts: [String] = []
        if let y = vehicle_year { parts.append(String(y)) }
        if isSimilarModel { parts.append("or similar") }
        if let c = vehicle_color, !c.isEmpty, c != "Per Mfg Spec" { parts.append(c.capitalized) }
        if let cls = DisplayName.vehicleClass(vehicle_class) { parts.append(cls) }
        return parts.joined(separator: " · ")
    }

    var costText: String? {
        guard let cost else { return nil }
        return Fmt.money(cost, currency)
    }

    var confirmationText: String? {
        let c = (confirmation_number?.isEmpty == false ? confirmation_number : agreement_number)
        return c?.isEmpty == false ? c : nil
    }

    var milesDriven: Double? {
        if let m = mileage_driven, m > 0 { return m }
        if let a = pickup_odometer, let b = dropoff_odometer, b > a { return b - a }
        return nil
    }

    var pickupCoordinate: CLLocationCoordinate2D? {
        guard let lat = pickup_lat, let lng = pickup_lng else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    var dropoffCoordinate: CLLocationCoordinate2D? {
        guard let lat = dropoff_lat, let lng = dropoff_lng else { return pickupCoordinate }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    var pickupYear: Int? {
        pickupDate.map { Calendar.current.component(.year, from: $0) }
    }

    // MARK: helpers

    static func stationCode(code: String?, city: String?, location: String) -> String {
        if let code, !code.isEmpty { return code.uppercased() }
        // An airport code already in the location text, e.g. "LHR Airport"
        if let m = location.range(of: #"\b[A-Z]{3}(?=\s+(Airport|Intl|International)\b)"#, options: .regularExpression) {
            return String(location[m])
        }
        let source = (city?.isEmpty == false ? city! : location)
            .split(separator: ",").first.map(String.init) ?? ""
        let words = source
            .replacingOccurrences(of: #"[^A-Za-z ]"#, with: " ", options: .regularExpression)
            .split(separator: " ").map(String.init)
        guard !words.isEmpty else { return "···" }
        let code: String
        if words.count >= 3 {
            code = words.prefix(3).compactMap(\.first).map(String.init).joined()
        } else if words.count == 2 {
            code = String(words[0].prefix(2)) + String(words[1].prefix(1))
        } else {
            code = String(words[0].prefix(3))
        }
        return code.uppercased()
    }

    static func cityName(_ city: String?, fallback: String) -> String? {
        if let city, !city.isEmpty { return city.split(separator: ",").first.map { String($0).trimmingCharacters(in: .whitespaces) } }
        let f = fallback.split(separator: "·").first.map { String($0).trimmingCharacters(in: .whitespaces) } ?? ""
        return f.isEmpty ? nil : f.capitalized
    }
}

// MARK: - Aggregates for the Rentals header & Passport

struct RentalSummary {
    struct CompanyRow: Identifiable {
        var id: String { company }
        let company: String
        let count: Int
        let days: Double
        let spend: Double
    }

    let count: Int
    let days: Double
    let miles: Double
    let spend: Double
    let byCompany: [CompanyRow]
    let topCars: [(name: String, count: Int)]
    let byYear: [(year: Int, count: Int, spend: Double)]

    init(_ rentals: [ApiRentalCar]) {
        count = rentals.count
        days = rentals.reduce(0) { $0 + ($1.rentalDuration ?? 0) / 86_400 }
        miles = rentals.reduce(0) { $0 + ($1.milesDriven ?? 0) }
        spend = rentals.filter { ($0.currency ?? "USD") == "USD" }.reduce(0) { $0 + ($1.cost ?? 0) }

        var companies: [String: (Int, Double, Double)] = [:]
        for r in rentals {
            var row = companies[r.rental_company] ?? (0, 0, 0)
            row.0 += 1
            row.1 += (r.rentalDuration ?? 0) / 86_400
            row.2 += r.cost ?? 0
            companies[r.rental_company] = row
        }
        byCompany = companies
            .map { CompanyRow(company: $0.key, count: $0.value.0, days: $0.value.1, spend: $0.value.2) }
            .sorted { $0.count == $1.count ? $0.spend > $1.spend : $0.count > $1.count }

        var cars: [String: Int] = [:]
        for r in rentals where !r.isSimilarModel && r.car_model?.isEmpty == false && (r.car_model?.contains(" ") ?? false) {
            cars[r.vehicleName, default: 0] += 1
        }
        topCars = cars.map { ($0.key, $0.value) }.sorted { $0.1 == $1.1 ? $0.0 < $1.0 : $0.1 > $1.1 }

        var years: [Int: (Int, Double)] = [:]
        for r in rentals {
            guard let y = r.pickupYear else { continue }
            var row = years[y] ?? (0, 0)
            row.0 += 1
            row.1 += r.cost ?? 0
            years[y] = row
        }
        byYear = years.map { ($0.key, $0.value.0, $0.value.1) }.sorted { $0.0 < $1.0 }
    }
}
