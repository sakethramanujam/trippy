import SwiftUI
import CoreLocation

// MARK: - Flight form validation & lookup logic

struct FlightFormValidation: Equatable {
    var valid: Bool
    var error: String?
    var normalizedNumber: String = ""
    var resolvedAirline: String = ""
    var fromCode: String = ""
    var toCode: String = ""
    var departureDate: Date = Date()
    var arrivalDate: Date = Date()
    var departureIso: String = ""
    var arrivalIso: String = ""
    var distanceMiles: Double? = nil
    var durationMinutes: Int? = nil
}

struct FlightLookupPrefill: Equatable {
    var airline: String? = nil
    var fromAirport: String? = nil
    var toAirport: String? = nil
    var departureHourMinute: (Int, Int)? = nil
    var arrivalHourMinute: (Int, Int)? = nil
    var nextDayArrival: Bool? = nil
    var terminalGate: String? = nil
    var message: String? = nil

    static func == (lhs: FlightLookupPrefill, rhs: FlightLookupPrefill) -> Bool {
        lhs.airline == rhs.airline
            && lhs.fromAirport == rhs.fromAirport
            && lhs.toAirport == rhs.toAirport
            && lhs.departureHourMinute?.0 == rhs.departureHourMinute?.0
            && lhs.departureHourMinute?.1 == rhs.departureHourMinute?.1
            && lhs.arrivalHourMinute?.0 == rhs.arrivalHourMinute?.0
            && lhs.arrivalHourMinute?.1 == rhs.arrivalHourMinute?.1
            && lhs.nextDayArrival == rhs.nextDayArrival
            && lhs.terminalGate == rhs.terminalGate
            && lhs.message == rhs.message
    }
}

enum FlightFormLogic {
    private static let carrierNames: [String: String] = [
        "UA": "United Airlines", "DL": "Delta Air Lines", "AA": "American Airlines",
        "WN": "Southwest Airlines", "AS": "Alaska Airlines", "B6": "JetBlue",
        "HA": "Hawaiian Airlines", "NK": "Spirit Airlines", "F9": "Frontier Airlines",
        "G4": "Allegiant Air", "AC": "Air Canada", "WS": "WestJet",
        "AM": "Aeromexico", "BA": "British Airways", "LH": "Lufthansa",
        "AF": "Air France", "KL": "KLM", "EK": "Emirates",
        "QR": "Qatar Airways", "EY": "Etihad Airways", "SQ": "Singapore Airlines",
        "NH": "ANA", "JL": "Japan Airlines", "QF": "Qantas",
        "TK": "Turkish Airlines", "IB": "Iberia", "VS": "Virgin Atlantic",
        "FR": "Ryanair", "U2": "easyJet", "DY": "Norwegian",
        "W6": "Wizz Air", "AI": "Air India", "6E": "IndiGo",
        "CX": "Cathay Pacific", "KE": "Korean Air", "BR": "EVA Air",
        "AY": "Finnair", "SK": "SAS", "EI": "Aer Lingus",
        "NZ": "Air New Zealand", "LX": "SWISS", "OS": "Austrian Airlines",
        "FI": "Icelandair", "CM": "Copa Airlines", "AV": "Avianca",
        "ET": "Ethiopian Airlines", "LO": "LOT Polish Airlines", "SV": "Saudia",
        "TP": "TAP Air Portugal",
    ]

    static let wireFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    static let dayQueryFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Default date is the day after the last flight when the trip has flights, else the trip start date, else `now`.
    static func defaultDate(for trip: ApiTrip?, now: Date = Date()) -> Date {
        let cal = Calendar.current
        if let trip {
            let lastFlightDate = trip.flights.compactMap { $0.arrivalDate ?? $0.departureDate }.max()
            if let lastFlightDate, let next = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: lastFlightDate)) {
                return next
            }
            if let start = Fmt.parse(trip.start_date) {
                return cal.startOfDay(for: start)
            }
        }
        return cal.startOfDay(for: now)
    }

    static func defaultFromAirport(for trip: ApiTrip?) -> String {
        guard let trip else { return "" }
        let last = trip.flights.sorted { ($0.departure_time ?? "") < ($1.departure_time ?? "") }.last
        return last?.arrival_airport.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() ?? ""
    }

    static func normalizeFlightNumber(_ raw: String) -> String {
        let cleaned = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased()
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        let pattern = #"^([A-Z0-9]{2}|[A-Z]{3})\s*0*(\d{1,4})([A-Z]?)$"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: cleaned, range: NSRange(cleaned.startIndex..., in: cleaned)),
              let r1 = Range(match.range(at: 1), in: cleaned),
              let r2 = Range(match.range(at: 2), in: cleaned),
              let r3 = Range(match.range(at: 3), in: cleaned) else {
            return cleaned
        }
        return "\(cleaned[r1]) \(cleaned[r2])\(cleaned[r3])"
    }

    static func carrierPrefix(_ flightNumber: String) -> String? {
        let norm = normalizeFlightNumber(flightNumber)
        let parts = norm.split(separator: " ")
        if let first = parts.first, (2...3).contains(first.count), first.contains(where: \.isLetter) {
            return String(first)
        }
        let prefix = norm.prefix(2)
        if prefix.count == 2 && prefix.allSatisfy({ $0.isLetter || $0.isNumber }) && prefix.contains(where: \.isLetter) {
            return String(prefix)
        }
        return nil
    }

    static func inferAirline(flightNumber: String, explicitAirline: String = "") -> String {
        let trimmed = explicitAirline.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        guard let code = carrierPrefix(flightNumber) else { return "" }
        return carrierNames[code] ?? code
    }

    static func combine(day: Date, clock: Date, addDays: Int = 0, calendar: Calendar = .current) -> Date {
        let baseDay = calendar.date(byAdding: .day, value: addDays, to: calendar.startOfDay(for: day)) ?? day
        let comps = calendar.dateComponents([.hour, .minute], from: clock)
        return calendar.date(bySettingHour: comps.hour ?? 9, minute: comps.minute ?? 0, second: 0, of: baseDay) ?? baseDay
    }

    static func validate(
        flightNumber: String,
        airline: String,
        fromAirport: String,
        toAirport: String,
        date: Date,
        departureClock: Date,
        arrivalClock: Date,
        nextDayArrival: Bool
    ) -> FlightFormValidation {
        let normNumber = normalizeFlightNumber(flightNumber)
        if normNumber.isEmpty {
            return FlightFormValidation(valid: false, error: "Enter a flight number (e.g. UA 1580).")
        }
        if !normNumber.contains(where: \.isNumber) {
            return FlightFormValidation(valid: false, error: "Include the flight number digits (e.g. UA 1580).")
        }
        let resolvedAirline = inferAirline(flightNumber: normNumber, explicitAirline: airline)
        if resolvedAirline.isEmpty {
            return FlightFormValidation(valid: false, error: "Enter the airline name.")
        }

        let from = fromAirport.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let to = toAirport.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if from.count != 3 || !from.allSatisfy(\.isLetter) {
            return FlightFormValidation(valid: false, error: "From airport must be a 3-letter IATA code.")
        }
        if Airports.city(from) == nil {
            return FlightFormValidation(valid: false, error: "Unknown IATA code \"\(from)\".")
        }
        if to.count != 3 || !to.allSatisfy(\.isLetter) {
            return FlightFormValidation(valid: false, error: "To airport must be a 3-letter IATA code.")
        }
        if Airports.city(to) == nil {
            return FlightFormValidation(valid: false, error: "Unknown IATA code \"\(to)\".")
        }
        if from == to {
            return FlightFormValidation(valid: false, error: "Departure and arrival airports must be different.")
        }

        let depDate = combine(day: date, clock: departureClock, addDays: 0)
        let arrDate = combine(day: date, clock: arrivalClock, addDays: nextDayArrival ? 1 : 0)
        if arrDate <= depDate {
            return FlightFormValidation(valid: false, error: "Arrival must be after departure (turn on +1 day for overnight flights).")
        }

        var miles: Double? = nil
        if let c1 = Airports.coordinate(from), let c2 = Airports.coordinate(to) {
            let meters = CLLocation(latitude: c1.latitude, longitude: c1.longitude)
                .distance(from: CLLocation(latitude: c2.latitude, longitude: c2.longitude))
            miles = ((meters / 1609.344) * 10).rounded() / 10
        }

        var durationMins = Int(arrDate.timeIntervalSince(depDate) / 60)
        if let tzDep = Airports.timeZone(from), let tzArr = Airports.timeZone(to) {
            let shift = tzArr.secondsFromGMT(for: arrDate) - tzDep.secondsFromGMT(for: depDate)
            let realMinutes = Int((arrDate.timeIntervalSince(depDate) - Double(shift)) / 60)
            if realMinutes > 0 { durationMins = realMinutes }
        }

        return FlightFormValidation(
            valid: true,
            error: nil,
            normalizedNumber: normNumber,
            resolvedAirline: resolvedAirline,
            fromCode: from,
            toCode: to,
            departureDate: depDate,
            arrivalDate: arrDate,
            departureIso: wireFormatter.string(from: depDate),
            arrivalIso: wireFormatter.string(from: arrDate),
            distanceMiles: miles,
            durationMinutes: durationMins > 0 ? durationMins : nil
        )
    }

    static func parseLocalClock(_ raw: String?) -> (day: String, hour: Int, minute: Int)? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        let normalized = raw.replacingOccurrences(of: " ", with: "T")
        guard normalized.count >= 16 else { return nil }
        let dayPart = String(normalized.prefix(10))
        let timeStart = normalized.index(normalized.startIndex, offsetBy: 11)
        let timeEnd = normalized.index(normalized.startIndex, offsetBy: 16)
        let hm = normalized[timeStart..<timeEnd].split(separator: ":")
        guard hm.count == 2, let h = Int(hm[0]), let m = Int(hm[1]), (0..<24).contains(h), (0..<60).contains(m) else {
            return nil
        }
        return (dayPart, h, m)
    }

    static func parseLookupResponse(_ data: Data, flightNumber: String) -> FlightLookupPrefill {
        guard let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return FlightLookupPrefill(message: "Couldn't look this up, fill it in manually")
        }
        if let configured = root["configured"] as? Bool, !configured {
            return FlightLookupPrefill(message: "Couldn't look this up, fill it in manually")
        }
        let statusObj = (root["status"] as? [String: Any]) ?? root
        if root.keys.contains("status") && !(root["status"] is [String: Any]) {
            return FlightLookupPrefill(message: "Couldn't look this up, fill it in manually")
        }
        func str(_ keys: String...) -> String? {
            for k in keys {
                if let v = (statusObj[k] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !v.isEmpty { return v }
                if let v = (root[k] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !v.isEmpty { return v }
            }
            return nil
        }
        let depParsed = parseLocalClock(str("departure_scheduled", "departure_estimated", "departure_time"))
        let arrParsed = parseLocalClock(str("arrival_scheduled", "arrival_estimated", "arrival_time"))
        let from = str("departure_airport", "from_airport", "origin")?.uppercased()
        let to = str("arrival_airport", "to_airport", "destination")?.uppercased()
        let term = str("departure_terminal", "terminal")
        let gate = str("departure_gate", "gate")
        let termGateParts = [
            term.map { $0.allSatisfy(\.isNumber) ? "T\($0)" : $0 },
            gate
        ].compactMap { $0 }
        let termGate = termGateParts.isEmpty ? nil : termGateParts.joined(separator: " · ")

        if depParsed == nil && arrParsed == nil && from == nil && to == nil {
            return FlightLookupPrefill(message: "Couldn't look this up, fill it in manually")
        }
        let nextDay: Bool? = (depParsed != nil && arrParsed != nil) ? (arrParsed!.day > depParsed!.day) : nil
        return FlightLookupPrefill(
            airline: str("airline") ?? inferAirline(flightNumber: flightNumber),
            fromAirport: from,
            toAirport: to,
            departureHourMinute: depParsed.map { ($0.hour, $0.minute) },
            arrivalHourMinute: arrParsed.map { ($0.hour, $0.minute) },
            nextDayArrival: nextDay,
            terminalGate: termGate,
            message: nil
        )
    }

    /// Runs validation unit checks for `FlightFormLogic` (used by `-TrippyTestAddFlight YES` and CI).
    @discardableResult
    static func runValidationUnitTests() -> [String] {
        var failures: [String] = []
        func check(_ cond: Bool, _ msg: String) {
            if !cond { failures.append(msg) }
        }
        check(normalizeFlightNumber("ua01580") == "UA 1580", "normalizeFlightNumber UA 1580")
        check(inferAirline(flightNumber: "UA 1580") == "United Airlines", "inferAirline UA")
        check(inferAirline(flightNumber: "DL 42") == "Delta Air Lines", "inferAirline DL")
        check(inferAirline(flightNumber: "UA 1580", explicitAirline: "Custom") == "Custom", "explicit airline override")

        let cal = Calendar.current
        let day = cal.date(from: DateComponents(year: 2026, month: 11, day: 15))!
        let dep9 = cal.date(bySettingHour: 9, minute: 0, second: 0, of: day)!
        let arr17 = cal.date(bySettingHour: 17, minute: 30, second: 0, of: day)!
        let dep22 = cal.date(bySettingHour: 22, minute: 0, second: 0, of: day)!
        let arr6 = cal.date(bySettingHour: 6, minute: 15, second: 0, of: day)!

        let ok = validate(
            flightNumber: "UA 1580", airline: "", fromAirport: "SFO", toAirport: "JFK",
            date: day, departureClock: dep9, arrivalClock: arr17, nextDayArrival: false
        )
        check(ok.valid && ok.error == nil, "valid SFO->JFK flight")
        check((ok.distanceMiles ?? 0) > 2500, "SFO->JFK distance > 2500 mi")

        let badIata = validate(
            flightNumber: "UA 1580", airline: "", fromAirport: "SFO", toAirport: "ZZZ",
            date: day, departureClock: dep9, arrivalClock: arr17, nextDayArrival: false
        )
        check(!badIata.valid && (badIata.error ?? "").contains("Unknown IATA"), "reject unknown IATA")

        let badOrder = validate(
            flightNumber: "UA 1580", airline: "", fromAirport: "SFO", toAirport: "JFK",
            date: day, departureClock: dep22, arrivalClock: arr6, nextDayArrival: false
        )
        check(!badOrder.valid && (badOrder.error ?? "").contains("+1 day"), "reject arrival before departure without +1")

        let overnightOk = validate(
            flightNumber: "UA 1580", airline: "", fromAirport: "SFO", toAirport: "JFK",
            date: day, departureClock: dep22, arrivalClock: arr6, nextDayArrival: true
        )
        check(overnightOk.valid && overnightOk.arrivalIso.hasPrefix("2026-11-16T06:15:00"), "accept +1 day overnight arrival")
        return failures
    }
}

// MARK: - NetworkManager flight creation & lookup

extension NetworkManager {
    func createFlight(tripId: Int, _ body: [String: Any]) async -> (ApiFlight?, String?) {
        let r = await send("POST", "/trips/\(tripId)/flights/", json: body)
        if r.status == 0 {
            return (nil, "You're offline. Connect to your Trippy server to save this flight.")
        }
        if let err = r.error {
            return (nil, err)
        }
        let created = r.data.flatMap { try? JSONDecoder().decode(ApiFlight.self, from: $0) }
        await refreshTrip(tripId)
        return (created, nil)
    }

    func lookupFlightSchedule(flightNumber: String, date: Date) async -> FlightLookupPrefill {
        let norm = FlightFormLogic.normalizeFlightNumber(flightNumber)
        guard !norm.isEmpty, norm.contains(where: \.isNumber) else {
            return FlightLookupPrefill(message: "Enter a flight number like UA 1580 first.")
        }
        let qNum = norm.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? norm
        let qDate = FlightFormLogic.dayQueryFormatter.string(from: date)
        let r = await send("GET", "/flights/lookup?flight_number=\(qNum)&date=\(qDate)")
        guard r.error == nil, (200..<300).contains(r.status), let data = r.data else {
            return FlightLookupPrefill(message: "Couldn't look this up, fill it in manually")
        }
        return FlightFormLogic.parseLookupResponse(data, flightNumber: norm)
    }
}

// MARK: - Add Flight Sheet

struct AddFlightView: View {
    @ObservedObject var network: NetworkManager
    let trip: ApiTrip
    @Environment(\.dismiss) private var dismiss

    @State private var flightNumber = ""
    @State private var airline = ""
    @State private var date = Date()
    @State private var fromAirport = ""
    @State private var toAirport = ""
    @State private var departureClock = Date()
    @State private var arrivalClock = Date()
    @State private var nextDayArrival = false
    @State private var confirmation = ""
    @State private var seat = ""
    @State private var terminalGate = ""
    @State private var cabinClass = ""
    @State private var notes = ""

    @State private var lookingUp = false
    @State private var lookupNotice: String?
    @State private var saving = false
    @State private var submitError: String?
    @State private var loaded = false

    private var validation: FlightFormValidation {
        FlightFormLogic.validate(
            flightNumber: flightNumber,
            airline: airline,
            fromAirport: fromAirport,
            toAirport: toAirport,
            date: date,
            departureClock: departureClock,
            arrivalClock: arrivalClock,
            nextDayArrival: nextDayArrival
        )
    }

    private var inferredAirline: String {
        FlightFormLogic.inferAirline(flightNumber: flightNumber, explicitAirline: airline)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    previewCard
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }

                Section {
                    HStack(spacing: 10) {
                        TextField("Flight number", text: $flightNumber, prompt: Text("e.g. UA 1580"))
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .font(TType.font(.mono, size: 16))
                            .onChange(of: flightNumber) { _, newValue in
                                let up = newValue.uppercased()
                                if up != newValue { flightNumber = up }
                                lookupNotice = nil
                                submitError = nil
                            }
                        Button {
                            Task { await performLookup() }
                        } label: {
                            HStack(spacing: 5) {
                                if lookingUp {
                                    ProgressView().controlSize(.small).tint(Theme.stay)
                                } else {
                                    Image(systemName: "magnifyingglass")
                                }
                                Text("Look up")
                            }
                            .type(.footnoteStrong)
                            .foregroundStyle(Theme.stay)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(Theme.stay.opacity(0.16), in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .disabled(lookingUp)
                    }

                    if let lookupNotice {
                        Label(lookupNotice, systemImage: "info.circle.fill")
                            .type(.footnote)
                            .foregroundStyle(Theme.textSecondary)
                    }

                    TextField("Airline", text: $airline, prompt: Text(inferredAirline.isEmpty ? "Airline, e.g. United Airlines" : inferredAirline))
                        .onChange(of: airline) { _, _ in submitError = nil }

                    DatePicker("Date", selection: $date, displayedComponents: .date)
                        .onChange(of: date) { _, _ in submitError = nil }
                } header: { formHeader("Flight") }

                Section {
                    HStack {
                        TextField("From (IATA)", text: $fromAirport, prompt: Text("SFO"))
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .font(TType.font(.mono, size: 17))
                            .onChange(of: fromAirport) { _, newValue in
                                let trimmed = String(newValue.uppercased().filter(\.isLetter).prefix(3))
                                if trimmed != newValue { fromAirport = trimmed }
                                submitError = nil
                            }
                        Spacer()
                        airportBadge(fromAirport)
                    }

                    HStack {
                        TextField("To (IATA)", text: $toAirport, prompt: Text("JFK"))
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .font(TType.font(.mono, size: 17))
                            .onChange(of: toAirport) { _, newValue in
                                let trimmed = String(newValue.uppercased().filter(\.isLetter).prefix(3))
                                if trimmed != newValue { toAirport = trimmed }
                                submitError = nil
                            }
                        Spacer()
                        airportBadge(toAirport)
                    }

                    DatePicker("Departs (local)", selection: $departureClock, displayedComponents: .hourAndMinute)
                        .onChange(of: departureClock) { _, _ in submitError = nil }

                    DatePicker("Arrives (local)", selection: $arrivalClock, displayedComponents: .hourAndMinute)
                        .onChange(of: arrivalClock) { _, _ in submitError = nil }

                    Toggle("Arrives next day (+1)", isOn: $nextDayArrival)
                        .tint(Theme.stay)
                        .onChange(of: nextDayArrival) { _, _ in submitError = nil }
                } header: { formHeader("Route & Times") } footer: {
                    Text("Departure and arrival times are local to each airport.")
                }

                Section {
                    TextField("Confirmation code", text: $confirmation, prompt: Text("Optional, e.g. ABC123"))
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .font(TType.font(.mono, size: 16))
                    TextField("Seat", text: $seat, prompt: Text("Optional, e.g. 14A"))
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .font(TType.font(.mono, size: 16))
                    TextField("Terminal / gate", text: $terminalGate, prompt: Text("Optional, e.g. T3 · Gate F12"))
                    Picker("Cabin", selection: $cabinClass) {
                        Text("Not set").tag("")
                        Text("Economy").tag("economy")
                        Text("Premium Economy").tag("premium_economy")
                        Text("Business").tag("business")
                        Text("First").tag("first")
                    }
                    TextField("Notes", text: $notes, prompt: Text("Optional notes"), axis: .vertical)
                } header: { formHeader("Booking Details") }

                if let err = submitError ?? (hasStartedTyping ? validation.error : nil) {
                    Section {
                        Label(err, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(Theme.red)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle("Add Flight")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Save") {
                        Task { await save() }
                    }
                    .fontWeight(.bold)
                    .disabled(!validation.valid || saving)
                }
            }
            .onAppear(perform: loadDefaults)
        }
        .tint(Theme.stay)
        .presentationDetents([.large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private var hasStartedTyping: Bool {
        !flightNumber.isEmpty || !fromAirport.isEmpty || !toAirport.isEmpty
    }

    private var previewCard: some View {
        let dispAirline = inferredAirline.isEmpty ? "Airline" : inferredAirline
        let dispNumber = FlightFormLogic.normalizeFlightNumber(flightNumber).isEmpty ? "XX 000" : FlightFormLogic.normalizeFlightNumber(flightNumber)
        let depCode = fromAirport.isEmpty ? "FROM" : fromAirport
        let arrCode = toAirport.isEmpty ? "TO" : toAirport
        let depDate = FlightFormLogic.combine(day: date, clock: departureClock, addDays: 0)
        let arrDate = FlightFormLogic.combine(day: date, clock: arrivalClock, addDays: nextDayArrival ? 1 : 0)
        let captionParts = [
            validation.durationMinutes.map { Fmt.duration(Double($0) * 60) },
            validation.distanceMiles.map { "\(Fmt.number($0)) mi" }
        ].compactMap { $0 }

        return VStack(alignment: .leading, spacing: Theme.s4) {
            HStack(spacing: Theme.s3) {
                AirlineBadge(airline: dispAirline, flightNumber: dispNumber, size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text(dispAirline).type(.headline).foregroundStyle(.white).lineLimit(1)
                    Text(dispNumber).type(.mono).foregroundStyle(Theme.textSecondary).lineLimit(1)
                }
                Spacer()
                StatusPill(text: nextDayArrival ? "+1 Day" : "Scheduled", color: Theme.stay)
            }
            HStack(alignment: .top, spacing: Theme.s3) {
                FlightEndpoint(code: depCode, date: depDate, alignment: .leading)
                FlightRouteLine(
                    progress: 0,
                    caption: captionParts.isEmpty ? nil : captionParts.joined(separator: " · "),
                    color: Theme.stay
                )
                .frame(maxWidth: .infinity)
                .padding(.top, 14)
                FlightEndpoint(code: arrCode, date: arrDate, alignment: .trailing)
            }
        }
        .card()
    }

    @ViewBuilder
    private func airportBadge(_ code: String) -> some View {
        let up = code.trimmingCharacters(in: .whitespaces).uppercased()
        if let city = Airports.city(up) {
            Text(city)
                .type(.footnoteStrong)
                .foregroundStyle(Theme.green)
        } else if up.count == 3 {
            Text("Unknown IATA")
                .type(.caption)
                .foregroundStyle(Theme.red)
        }
    }

    private func formHeader(_ text: String) -> some View {
        Text(text.uppercased()).type(.label).tracking(0.5).foregroundStyle(Theme.textSecondary)
    }

    private func loadDefaults() {
        guard !loaded else { return }
        loaded = true
        let failures = FlightFormLogic.runValidationUnitTests()
        assert(failures.isEmpty, "FlightFormLogic unit test failures: \(failures)")
        let cal = Calendar.current
        let defDay = FlightFormLogic.defaultDate(for: trip)
        date = defDay
        fromAirport = FlightFormLogic.defaultFromAirport(for: trip)
        departureClock = cal.date(bySettingHour: 9, minute: 0, second: 0, of: defDay) ?? defDay
        arrivalClock = cal.date(bySettingHour: 12, minute: 0, second: 0, of: defDay) ?? defDay

        let d = UserDefaults.standard
        if let fn = d.string(forKey: "TrippyDebugFlightNumber"), !fn.isEmpty { flightNumber = fn }
        if let fr = d.string(forKey: "TrippyDebugFromAirport"), !fr.isEmpty { fromAirport = fr }
        if let to = d.string(forKey: "TrippyDebugToAirport"), !to.isEmpty { toAirport = to }
        if let st = d.string(forKey: "TrippyDebugFlightSeat"), !st.isEmpty { seat = st }
        if let cf = d.string(forKey: "TrippyDebugFlightConf"), !cf.isEmpty { confirmation = cf }
        if let cb = d.string(forKey: "TrippyDebugFlightCabin"), !cb.isEmpty { cabinClass = cb }
        if d.bool(forKey: "TrippyDebugLookupFlight") {
            Task { await performLookup() }
        }
    }

    private func performLookup() async {
        lookingUp = true
        lookupNotice = nil
        let res = await network.lookupFlightSchedule(flightNumber: flightNumber, date: date)
        lookingUp = false
        if let msg = res.message {
            lookupNotice = msg
            return
        }
        if let a = res.airline, airline.trimmingCharacters(in: .whitespaces).isEmpty { airline = a }
        if let f = res.fromAirport { fromAirport = f }
        if let t = res.toAirport { toAirport = t }
        let cal = Calendar.current
        if let (h, m) = res.departureHourMinute,
           let d = cal.date(bySettingHour: h, minute: m, second: 0, of: date) {
            departureClock = d
        }
        if let (h, m) = res.arrivalHourMinute,
           let d = cal.date(bySettingHour: h, minute: m, second: 0, of: date) {
            arrivalClock = d
        }
        if let nd = res.nextDayArrival { nextDayArrival = nd }
        if let tg = res.terminalGate, terminalGate.trimmingCharacters(in: .whitespaces).isEmpty {
            terminalGate = tg
        }
        lookupNotice = "Prefilled from live schedule."
    }

    private func save() async {
        let v = validation
        guard v.valid else {
            submitError = v.error
            return
        }
        saving = true
        submitError = nil
        func opt(_ s: String) -> Any {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? NSNull() : t
        }
        var body: [String: Any] = [
            "airline": v.resolvedAirline,
            "flight_number": v.normalizedNumber,
            "departure_airport": v.fromCode,
            "arrival_airport": v.toCode,
            "departure_time": v.departureIso,
            "arrival_time": v.arrivalIso,
            "status": "Scheduled",
            "confirmation_number": opt(confirmation.uppercased()),
            "seat": opt(seat.uppercased()),
            "cabin_class": opt(cabinClass),
            "booking_source": "manual",
        ]
        if let miles = v.distanceMiles { body["distance_miles"] = miles }
        if let mins = v.durationMinutes { body["duration_minutes"] = mins }
        let (_, err) = await network.createFlight(tripId: trip.id, body)
        saving = false
        if let err {
            submitError = err
        } else {
            Haptics.success()
            dismiss()
        }
    }
}
