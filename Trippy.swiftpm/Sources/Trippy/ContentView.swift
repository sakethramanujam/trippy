import SwiftUI

/// "Today": what matters right now — the car you're driving (or the next one),
/// the trip coming up and its next flight, plus quick actions.
struct ContentView: View {
    @ObservedObject var network: NetworkManager
    var switchToExpenses: () -> Void
    var switchToRentals: () -> Void = {}
    var switchToTrips: () -> Void = {}
    @EnvironmentObject private var auth: AuthManager
    @State private var showServer = false
    /// `-TrippyOpen profile|import` opens a sheet on launch (screenshots).
    @State private var showProfile = UserDefaults.standard.string(forKey: "TrippyOpen") == "profile"
    @State private var showImport = UserDefaults.standard.string(forKey: "TrippyOpen") == "import"
    /// Flight shown in the detail sheet. `-TrippyOpenFlight <id>` opens one on launch (screenshots).
    @State private var openFlight: ApiFlight?

    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: .now, by: 60)) { context in
                let now = context.date
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: Theme.sectionGap) {
                        HStack(alignment: .top) {
                            ScreenHeader(title: "Today", subtitle: Fmt.dayYear(now))
                            Spacer()
                            Button { showProfile = true } label: {
                                InitialsAvatar(initials: auth.profile?.initials ?? "DEV", size: 38)
                                    .overlay(alignment: .topTrailing) {
                                        if network.inboundUnread > 0 {
                                            Circle().fill(Theme.red).frame(width: 11, height: 11)
                                                .overlay(Circle().strokeBorder(Theme.canvas, lineWidth: 2))
                                                .offset(x: 2, y: -2)
                                                .accessibilityLabel("\(network.inboundUnread) new forwarded emails")
                                        }
                                    }
                            }
                            .buttonStyle(.plain)
                            .padding(.top, 6)
                        }
                        .padding(.top, 8)

                        tripSection(now: now)
                        rentalSection(now: now)

                        if !network.trips.isEmpty || !network.rentals.isEmpty {
                            VStack(spacing: 0) {
                                Hairline()
                                Button(action: switchToExpenses) {
                                    QuickActionTile(icon: "creditcard.fill", title: "Split expenses", color: Theme.orange)
                                }
                                .buttonStyle(.plain)
                                Hairline(leading: 44)
                                Button(action: switchToRentals) {
                                    QuickActionTile(icon: "car.2.fill", title: "All rentals", color: Theme.green)
                                }
                                .buttonStyle(.plain)
                                Hairline(leading: 44)
                                Button { showImport = true } label: {
                                    QuickActionTile(icon: "square.and.arrow.down.fill", title: "Import trips", color: Theme.blue)
                                }
                                .buttonStyle(.plain)
                                Hairline()
                            }
                        }
                        Color.clear.frame(height: Theme.tabBarClearance)
                    }
                    .padding(.horizontal, Theme.pagePadding + 4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .refreshable {
                    await network.fetchRentals()
                    await network.fetchTrips()
                    await network.refreshInboundBadge()
                }
            }
            .task { await network.refreshInboundBadge() }
            .trippyScreen()
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $showServer) {
                ServerSettingsView {
                    Task {
                        await network.fetchRentals()
                        await network.fetchTrips()
                    }
                }
            }
            .sheet(isPresented: $showProfile, onDismiss: { Task { await network.refreshInboundBadge() } }) {
                ProfileView(network: network).environmentObject(auth)
            }
            .sheet(isPresented: $showImport) {
                ImportView(network: network)
            }
            .sheet(item: $openFlight) { flight in
                FlightDetailView(flight: flight)
            }
            .onChange(of: network.trips.count, initial: true) { _, _ in
                let id = UserDefaults.standard.integer(forKey: "TrippyOpenFlight")
                guard id > 0, openFlight == nil,
                      let f = network.trips.flatMap(\.flights).first(where: { $0.id == id }) else { return }
                openFlight = f
            }
            .navigationDestination(for: Int.self) { id in
                if let rental = network.rentals.first(where: { $0.id == id }) {
                    RentalDetailView(rental: rental)
                }
            }
        }
    }

    // MARK: Rentals

    @ViewBuilder
    private func rentalSection(now: Date) -> some View {
        let sorted = network.rentals.sorted { ($0.pickupDate ?? .distantPast) > ($1.pickupDate ?? .distantPast) }
        let live = sorted.filter { $0.phase(at: now) != .returned }
            .sorted { ($0.pickupDate ?? .distantFuture) < ($1.pickupDate ?? .distantFuture) }
        if let rental = live.first ?? sorted.first {
            VStack(alignment: .leading, spacing: Theme.s3) {
                ListSectionTitle(title: live.isEmpty ? "Last rental" : "Your car",
                                 trailing: live.isEmpty ? nil : "\(live.count) upcoming")
                NavigationLink(value: rental.id) { RentalCard(rental: rental, now: now) }
                    .buttonStyle(.plain)
            }
        }
    }

    // MARK: Trips

    @ViewBuilder
    private func tripSection(now: Date) -> some View {
        if network.trips.isEmpty {
            if network.rentals.isEmpty && network.rentalsLoaded && network.rentalsError == nil {
                newAccountEmptyState
            } else if network.rentals.isEmpty {
                VStack(spacing: 14) {
                    ProgressView().tint(.white)
                    Text("Connecting to \(APIConfig.baseURL)…")
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                    Button("Show sample data (offline)") { loadMockTrips() }
                        .buttonStyle(TintedButtonStyle())
                        .frame(maxWidth: 260)
                    Button("Change server…") { showServer = true }
                        .type(.calloutStrong)
                        .foregroundStyle(Theme.blue)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 40)
            }
        } else if let trip = nextTrip(now: now) {
            VStack(alignment: .leading, spacing: Theme.s6) {
                tripHero(trip, now: now)
                if let flight = trip.flights.first {
                    Button {
                        Haptics.tap()
                        openFlight = flight
                    } label: {
                        FlightCard(flight: flight, now: now)
                    }
                    .buttonStyle(PressableStyle())
                }
            }
        }
    }

    /// A brand-new account: nothing to show yet, so offer the two ways in.
    private var newAccountEmptyState: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: "airplane.circle.fill")
                    .type(.largeTitle)
                    .foregroundStyle(Theme.blue)
                Text("No trips yet")
                    .type(.title)
                    .foregroundStyle(Theme.textPrimary)
                Text("Bring in what's already in your calendar, Flighty, Wallet or inbox, or start a trip from scratch.")
                    .type(.callout)
                    .foregroundStyle(Theme.textSecondary)
            }
            Button { showImport = true } label: {
                Label("Import trips", systemImage: "square.and.arrow.down.fill").frame(maxWidth: .infinity)
            }
            .buttonStyle(PrimaryButtonStyle())
            Button(action: switchToTrips) {
                Label("Plan a new trip", systemImage: "plus").frame(maxWidth: .infinity)
            }
            .buttonStyle(TintedButtonStyle())
        }
        .card()
    }

    /// One hero per screen: a huge countdown, the trip name and a muted detail line.
    private func tripHero(_ trip: ApiTrip, now: Date) -> some View {
        let start = Fmt.parse(trip.start_date)
        let end = Fmt.parse(trip.end_date ?? trip.start_date)
        let cal = Calendar.current
        let onTrip = start.map { $0 <= now } ?? false && (end.map { now <= cal.date(byAdding: .day, value: 1, to: $0)! } ?? false)
        let days = start.map { max(0, cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: $0)).day ?? 0) } ?? 0
        let codes = trip.flights.flatMap { [$0.departure_airport, $0.arrival_airport] }
            .reduce(into: [String]()) { if $0.last != $1 { $0.append($1) } }
        return VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(spacing: 6) {
                YellowPill(text: onTrip ? "Happening now" : "Up next")
                Spacer()
                if let start { MicroLabel(text: Fmt.monthDay(start)) }
            }
            HStack(alignment: .firstTextBaseline, spacing: Theme.s4) {
                if start != nil {
                    VStack(alignment: .leading, spacing: -6) {
                        Text("\(days)")
                            .type(.hero)
                            .foregroundStyle(onTrip ? Theme.green : .white)
                            .contentTransition(.numericText())
                        MicroLabel(text: onTrip ? "On trip" : (days == 1 ? "Day to go" : "Days to go"))
                    }
                    .fixedSize()
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(trip.title)
                        .type(.title).foregroundStyle(.white)
                        .lineLimit(2).minimumScaleFactor(0.8)
                    if !codes.isEmpty {
                        Text(codes.joined(separator: " → "))
                            .type(.calloutStrong).foregroundStyle(Theme.textSecondary)
                            .lineLimit(1).minimumScaleFactor(0.8)
                    }
                    HStack(spacing: 5) {
                        GrayChip(text: "\(trip.participants.count)", systemImage: "person.2.fill")
                        GrayChip(text: "\(trip.flights.count)", systemImage: "airplane")
                        GrayChip(text: "\(trip.expenses.count)", systemImage: "creditcard.fill")
                    }
                    .padding(.top, 2)
                }
            }
        }
    }

    private func nextTrip(now: Date) -> ApiTrip? {
        let dated = network.trips.compactMap { t -> (ApiTrip, Date)? in
            guard let d = Fmt.parse(t.end_date ?? t.start_date) else { return nil }
            return (t, d)
        }
        if let upcoming = dated.filter({ $0.1 >= now }).min(by: { $0.1 < $1.1 }) { return upcoming.0 }
        return network.trips.first
    }

    private func loadMockTrips() {
        let mockJson = """
        [{"id":1,"title":"London Getaway","description":"A beautiful trip","flights":[{"id":1,"airline":"Delta Air Lines","flight_number":"DL 1234","departure_airport":"JFK","arrival_airport":"LHR","status":"On Time"}],"expenses":[],"activities":[],"documents":[],"rental_cars":[],"participants":[]}]
        """
        if let data = mockJson.data(using: .utf8),
           let decoded = try? JSONDecoder().decode([ApiTrip].self, from: data) {
            network.trips = decoded
        }
    }
}

/// Hairline row with a hierarchical symbol and chevron (Flighty settings-style).
struct QuickActionTile: View {
    var icon: String
    var title: String
    var color: Color

    var body: some View {
        HStack(spacing: Theme.s3) {
            Image(systemName: icon)
                .symbolRenderingMode(.hierarchical)
                .type(.headline)
                .foregroundStyle(color)
                .frame(width: 32)
            Text(title).type(.body).foregroundStyle(.white)
            Spacer()
            Image(systemName: "chevron.right").type(.footnoteStrong)
                .foregroundStyle(Theme.textTertiary)
        }
        .padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}

#Preview {
    ContentView(network: NetworkManager(), switchToExpenses: {})
}
