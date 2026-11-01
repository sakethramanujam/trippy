import SwiftUI

// MARK: - Search index (works on whatever is loaded, including the offline cache)

struct SearchHit: Identifiable, Hashable {
    enum Kind: Int, CaseIterable {
        case confirmation, trip, flight, stay, rental
        var title: String {
            switch self {
            case .confirmation: return "Confirmations"
            case .trip: return "Trips"
            case .flight: return "Flights"
            case .stay: return "Stays"
            case .rental: return "Rentals"
            }
        }
    }
    enum Target: Hashable { case trip(Int), flight(Int), stay(Int, trip: Int?), rental(Int) }

    let id: String
    let kind: Kind
    let icon: String
    let title: String
    let subtitle: String
    let target: Target
    /// Sorts newer items first inside a group.
    let date: Date?
}

enum TripSearch {
    /// Fold case and accents so "zurich" finds "Zürich" and "ua837" finds "UA 837".
    static func norm(_ s: String) -> String {
        s.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: nil)
            .lowercased()
    }
    static func squash(_ s: String) -> String { norm(s).filter { $0.isLetter || $0.isNumber } }

    static func matches(_ q: String, _ fields: [String?]) -> Bool {
        let nq = norm(q).trimmingCharacters(in: .whitespaces), sq = squash(q)
        guard !nq.isEmpty else { return false }
        return fields.contains { f in
            guard let f, !f.isEmpty else { return false }
            if norm(f).contains(nq) { return true }
            return sq.count >= 3 && squash(f).contains(sq)
        }
    }

    private static func city(_ code: String?) -> String? { code.flatMap { Airports.city($0) } }

    static func search(_ query: String, trips: [ApiTrip], rentals: [ApiRentalCar]) -> [(SearchHit.Kind, [SearchHit])] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else { return [] }
        var hits: [SearchHit] = []
        var seenRentals = Set<Int>()
        let tripTitle = Dictionary(trips.map { ($0.id, $0.displayTitle) }, uniquingKeysWith: { a, _ in a })

        func confirmation(_ code: String?, id: String, icon: String, what: String, target: SearchHit.Target, date: Date?) -> Bool {
            guard let code, !code.isEmpty, matches(q, [code]) else { return false }
            hits.append(SearchHit(id: "c-" + id, kind: .confirmation, icon: "number", title: code,
                                  subtitle: what, target: target, date: date))
            return true
        }

        for t in trips {
            let start = Fmt.parse(t.start_date)
            var places: [String?] = []
            for f in t.flights {
                places += [f.departure_airport, f.arrival_airport, city(f.departure_airport), city(f.arrival_airport)]
            }
            for l in t.lodgings { places += [l.city, l.country] }
            for r in t.rental_cars { places += [r.pickup_city, r.dropoff_city, r.pickup_code] }
            if matches(q, [t.displayTitle, t.description] + places) {
                let span = [Fmt.parse(t.start_date), Fmt.parse(t.end_date)].compactMap { $0 }
                    .map { $0.formatted(.dateTime.month(.abbreviated).day().year()) }
                hits.append(SearchHit(id: "t\(t.id)", kind: .trip, icon: "suitcase.rolling.fill", title: t.displayTitle,
                                      subtitle: span.isEmpty ? "Trip" : span.joined(separator: " – "),
                                      target: .trip(t.id), date: start))
            }
            for f in t.flights {
                let d = Fmt.parse(f.departure_time)
                let name = "\(f.airline) \(f.flight_number)"
                let route = "\(f.departure_airport) → \(f.arrival_airport)"
                let when = d.map { $0.formatted(.dateTime.month(.abbreviated).day().year()) } ?? ""
                if confirmation(f.confirmation_number, id: "f\(f.id)", icon: "airplane",
                                what: "\(name) · \(route) · \(tripTitle[t.id] ?? "")", target: .flight(f.id), date: d) { continue }
                if matches(q, [f.airline, f.flight_number, name, f.departure_airport, f.arrival_airport,
                               city(f.departure_airport), city(f.arrival_airport), f.aircraft_type]) {
                    hits.append(SearchHit(id: "f\(f.id)", kind: .flight, icon: "airplane", title: "\(name) · \(route)",
                                          subtitle: [when, t.displayTitle].filter { !$0.isEmpty }.joined(separator: " · "),
                                          target: .flight(f.id), date: d))
                }
            }
            for l in t.lodgings {
                let d = Fmt.parse(l.check_in)
                let when = d.map { $0.formatted(.dateTime.month(.abbreviated).day().year()) } ?? ""
                if confirmation(l.confirmation_number, id: "s\(l.id)", icon: "bed.double.fill",
                                what: "\(l.name) · \(t.displayTitle)", target: .stay(l.id, trip: t.id), date: d) { continue }
                if matches(q, [l.name, l.brand, l.city, l.country, l.address]) {
                    hits.append(SearchHit(id: "s\(l.id)", kind: .stay, icon: "bed.double.fill", title: l.name,
                                          subtitle: [l.city, when.isEmpty ? nil : when].compactMap { $0 }.joined(separator: " · "),
                                          target: .stay(l.id, trip: t.id), date: d))
                }
            }
        }
        // Rentals: the global list has every rental (with or without a trip).
        let allRentals = rentals.isEmpty ? trips.flatMap(\.rental_cars) : rentals
        for r in allRentals where seenRentals.insert(r.id).inserted {
            let d = Fmt.parse(r.pickup_time)
            let when = d.map { $0.formatted(.dateTime.month(.abbreviated).day().year()) } ?? ""
            let car = r.car_model ?? r.vehicle_class ?? "Rental"
            if confirmation(r.confirmation_number, id: "r\(r.id)", icon: "car.fill",
                            what: "\(r.rental_company) · \(car)", target: .rental(r.id), date: d) { continue }
            if confirmation(r.agreement_number, id: "ra\(r.id)", icon: "car.fill",
                            what: "Agreement · \(r.rental_company)", target: .rental(r.id), date: d) { continue }
            if matches(q, [r.rental_company, r.car_model, r.vehicle_make, r.pickup_location, r.dropoff_location,
                           r.pickup_city, r.dropoff_city, r.pickup_code, r.dropoff_code, r.license_plate]) {
                hits.append(SearchHit(id: "r\(r.id)", kind: .rental, icon: "car.fill", title: "\(r.rental_company) · \(car)",
                                      subtitle: [r.pickup_city ?? r.pickup_code, when].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "),
                                      target: .rental(r.id), date: d))
            }
        }
        let grouped = Dictionary(grouping: hits, by: \.kind)
        return SearchHit.Kind.allCases.compactMap { k in
            guard let list = grouped[k], !list.isEmpty else { return nil }
            return (k, list.sorted { ($0.date ?? .distantPast) > ($1.date ?? .distantPast) })
        }
    }
}

// MARK: - Search screen

/// Search across trips, cities, airports, airlines, flight numbers, hotels, rental companies
/// and confirmation numbers. Works offline (it searches what's on the phone).
struct TripSearchView: View {
    @ObservedObject var network: NetworkManager
    @Environment(\.dismiss) private var dismiss
    @State private var query = UserDefaults.standard.string(forKey: "TrippySearch") ?? ""
    @State private var active = true
    @State private var openStay: StayRef?

    struct StayRef: Identifiable { let stay: ApiLodging; let tripId: Int?; var id: Int { stay.id } }

    private var results: [(SearchHit.Kind, [SearchHit])] {
        TripSearch.search(query, trips: network.trips, rentals: network.rentals)
    }

    var body: some View {
        NavigationStack {
            List {
                if query.trimmingCharacters(in: .whitespaces).count < 2 {
                    Section {
                        Text("Search trips, cities, airports, airlines, flight numbers, hotels, rental companies and confirmation numbers.")
                            .font(.footnote).foregroundStyle(Theme.textSecondary)
                            .listRowBackground(Color.clear)
                    } footer: { SyncedCaption().padding(.top, 4) }
                } else if results.isEmpty {
                    ContentUnavailableView.search(text: query).listRowBackground(Color.clear)
                } else {
                    ForEach(results, id: \.0) { kind, hits in
                        Section {
                            ForEach(hits.prefix(kind == .trip ? 30 : 50)) { hit in row(hit) }
                        } header: {
                            Text("\(kind.title) · \(hits.count)")
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.canvas.ignoresSafeArea())
            .navigationTitle("Search")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, isPresented: $active, placement: .navigationBarDrawer(displayMode: .always),
                        prompt: "Trips, flights, hotels, PNRs…")
            .autocorrectionDisabled()
            .textInputAutocapitalization(.never)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
            }
            .navigationDestination(for: SearchHit.Target.self) { destination($0) }
            .sheet(item: $openStay) { ref in StayDetailSheet(network: network, stay: ref.stay, tripId: ref.tripId) }
        }
        .preferredColorScheme(.dark)
    }

    @ViewBuilder
    private func row(_ hit: SearchHit) -> some View {
        let label = HStack(spacing: 12) {
            Image(systemName: hit.icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(color(hit.kind))
                .frame(width: 30, height: 30)
                .background(color(hit.kind).opacity(0.16), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(hit.title)
                    .font(hit.kind == .confirmation ? .system(.body, design: .monospaced).weight(.semibold) : .body.weight(.semibold))
                    .foregroundStyle(.white).lineLimit(1)
                Text(hit.subtitle).font(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(1)
            }
        }
        if case .stay(let sid, let tid) = hit.target {
            Button {
                if let s = network.trips.first(where: { $0.id == tid })?.lodgings.first(where: { $0.id == sid }) {
                    openStay = StayRef(stay: s, tripId: tid)
                }
            } label: { HStack { label; Spacer(); Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.textTertiary) } }
            .listRowBackground(Theme.surface)
        } else {
            NavigationLink(value: hit.target) { label }.listRowBackground(Theme.surface)
        }
    }

    private func color(_ k: SearchHit.Kind) -> Color {
        switch k {
        case .confirmation: return Theme.stay
        case .trip: return Theme.blue
        case .flight: return Theme.blue
        case .stay: return Theme.purple
        case .rental: return Theme.green
        }
    }

    @ViewBuilder
    private func destination(_ t: SearchHit.Target) -> some View {
        switch t {
        case .trip(let id):
            if let trip = network.trips.first(where: { $0.id == id }) { TripDetailView(trip: trip, network: network) }
        case .flight(let id):
            if let f = network.trips.flatMap(\.flights).first(where: { $0.id == id }) ?? network.flights.first(where: { $0.id == id }) {
                FlightDetailView(network: network, flight: f)
            }
        case .rental(let id):
            if let r = network.rentals.first(where: { $0.id == id }) ?? network.trips.flatMap(\.rental_cars).first(where: { $0.id == id }) {
                RentalDetailView(rental: r)
            }
        case .stay:
            EmptyView()
        }
    }
}
