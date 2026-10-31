import SwiftUI
import MapKit

struct TripsView: View {
    @ObservedObject var network: NetworkManager
    @State private var showingAddTrip = false
    @State private var deepTripId: Int?
    @State private var detent = min(max(LaunchOptions.detent, 0), 1)
    @State private var sheetHeight: CGFloat = 0
    @EnvironmentObject private var auth: AuthManager
    /// Trips waiting on the delete confirmation sheet. `-TrippyDeleteSheet "3,5"` opens it on launch.
    @State private var deleteIds: LinkSeed? = {
        let ids = (UserDefaults.standard.string(forKey: "TrippyDeleteSheet") ?? "").split(separator: ",").compactMap { Int($0) }
        return ids.isEmpty ? nil : LinkSeed(ids: ids)
    }()
    @State private var storyTrip: IntRef?
    @State private var shareTrip: ApiTrip?
    /// Multi-select (long-press → Select): pick trips, then "Link N trips".
    @State private var selecting = UserDefaults.standard.string(forKey: "TrippySelectTrips") != nil
    @State private var selected: [Int] = (UserDefaults.standard.string(forKey: "TrippySelectTrips") ?? "")
        .split(separator: ",").compactMap { Int($0) }
    @State private var linkSeed: LinkSeed?
    @State private var openJourney: Int?
    @State private var linkingSuggestion: String?
    /// `-TrippySearch "query"` opens search on launch (screenshots).
    @State private var searching = UserDefaults.standard.string(forKey: "TrippySearch") != nil

    struct LinkSeed: Identifiable { let ids: [Int]; var id: String { ids.map(String.init).joined(separator: ",") } }

    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: .now, by: 300)) { context in
                let snaps = network.trips.map { TripSnapshot(trip: $0, allRentals: network.rentals, now: context.date) }
                ScrollViewReader { reader in
                ZStack {
                    Theme.canvas.ignoresSafeArea()
                    TripsOverviewMap(snapshots: snaps, bottomInset: sheetHeight)
                        .ignoresSafeArea()
                    DetentSheet(detents: [0.52, 0.92], selection: $detent, visibleHeight: $sheetHeight,
                                onRefresh: { await network.refreshAll() }) {
                        header(snaps)
                    } content: {
                        list(snaps, now: context.date)
                    }
                }
                .onChange(of: network.journeys.count + network.journeySuggestions.count) { _, n in
                    // Screenshot hook: -TrippyScrollTo journeys
                    guard n > 0, UserDefaults.standard.string(forKey: "TrippyScrollTo") == "journeys" else { return }
                    Task {
                        try? await Task.sleep(for: .milliseconds(700))
                        withAnimation { reader.scrollTo("journeys", anchor: .top) }
                    }
                }
                }
                .overlay(alignment: .bottom) { if selecting { selectionBar } }
            }
            .navigationDestination(item: $openJourney) { id in JourneyDetailView(journeyId: id, network: network) }
            .sheet(item: $linkSeed) { seed in
                LinkToJourneySheet(network: network, seed: seed.ids) { jid in
                    selecting = false
                    selected = []
                    openJourney = jid
                }
            }
            .navigationDestination(item: $deepTripId) { id in
                if let t = network.trips.first(where: { $0.id == id }) { TripDetailView(trip: t, network: network) }
            }
            .onAppear(perform: openDeepLink)
            .onChange(of: network.trips.count) { _, _ in openDeepLink() }
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $showingAddTrip) { AddTripView(network: network) }
            .fullScreenCover(isPresented: $searching) { TripSearchView(network: network) }
            .fullScreenCover(item: $storyTrip) { ref in StoryPlayerView(network: network, tripId: ref.id) }
            .sheet(item: $shareTrip) { t in
                ShareCardSheet(network: network, kinds: [.trip, .year], tripId: t.id,
                               year: Fmt.parse(t.start_date).map { Calendar.current.component(.year, from: $0) }
                                   ?? Calendar.current.component(.year, from: Date()))
            }
            .sheet(item: $deleteIds) { seed in
                DeleteTripSheet(network: network, tripIds: seed.ids) { _ in
                    withAnimation(.snappy) { selecting = false; selected = [] }
                }
            }
            .task {
                if network.rentals.isEmpty { await network.fetchRentals() }
                await network.fetchJourneys()
                await network.fetchJourneySuggestions()
                openJourneyDeepLink()
                // Screenshot hook: -TrippyDeleteOnLaunch N deletes trip N for real (shows the Undo toast).
                let del = UserDefaults.standard.integer(forKey: "TrippyDeleteOnLaunch")
                if del > 0, network.trips.contains(where: { $0.id == del }) { await network.trashTrips([del]) }
                if UserDefaults.standard.bool(forKey: "TrippyShowLink") {
                    let ids = (UserDefaults.standard.string(forKey: "TrippyLinkSeed") ?? "").split(separator: ",").compactMap { Int($0) }
                    if !ids.isEmpty { linkSeed = LinkSeed(ids: ids) }
                }
            }
        }
    }

    /// `-TrippyOpenJourney N` opens a journey on launch (screenshots).
    private func openJourneyDeepLink() {
        let id = UserDefaults.standard.integer(forKey: "TrippyOpenJourney")
        if id > 0, openJourney == nil, network.journeys.contains(where: { $0.id == id }) { openJourney = id }
    }

    private var selectionBar: some View {
        HStack(spacing: 10) {
            Button("Cancel") { withAnimation(.snappy) { selecting = false; selected = [] } }
                .buttonStyle(TintedButtonStyle(tint: Theme.textSecondary))
                .frame(width: 110)
            Button {
                linkSeed = LinkSeed(ids: selected)
            } label: {
                Label(selected.count < 2 ? "Select trips" : "Link \(selected.count) trips", systemImage: "link")
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(selected.isEmpty)
            .opacity(selected.isEmpty ? 0.5 : 1)
            Button { deleteIds = LinkSeed(ids: selected) } label: {
                Image(systemName: "trash").font(.system(size: 18, weight: .semibold))
            }
            .buttonStyle(TintedButtonStyle(tint: Theme.red))
            .frame(width: 60)
            .disabled(selected.isEmpty)
            .opacity(selected.isEmpty ? 0.5 : 1)
            .accessibilityLabel(selected.count == 1 ? "Delete trip" : "Delete \(selected.count) trips")
        }
        .padding(.horizontal, Theme.pagePadding)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    // MARK: Row actions (swipe + long-press menu share these)

    /// Owner, or unknown (dev auth bypass): the delete sheet re-checks with the server either way.
    private func owns(_ t: ApiTrip) -> Bool {
        guard let me = auth.profile?.id, let owner = t.owner_id else { return true }
        return me == owner
    }

    private func leadingActions(_ t: ApiTrip) -> [SwipeAction] {
        [SwipeAction(title: t.pinned ? "Unpin" : "Pin", icon: t.pinned ? "pin.slash.fill" : "pin.fill", tint: Theme.stay) {
            Haptics.tap()
            Task { await network.setPinned(t.id, !t.pinned) }
         },
         SwipeAction(title: "Share", icon: "square.and.arrow.up", tint: Theme.blue) { shareTrip = t }]
    }

    private func trailingActions(_ t: ApiTrip) -> [SwipeAction] {
        [SwipeAction(title: t.journey_id == nil ? "Link" : "Move", icon: "link", tint: Theme.purple) { linkSeed = LinkSeed(ids: [t.id]) },
         SwipeAction(title: owns(t) ? "Delete" : "Leave", icon: owns(t) ? "trash.fill" : "rectangle.portrait.and.arrow.right",
                     tint: Theme.red) { deleteIds = LinkSeed(ids: [t.id]) }]
    }

    @ViewBuilder
    private func rowMenu(_ t: ApiTrip) -> some View {
        Button { Task { await network.setPinned(t.id, !t.pinned) } } label: {
            Label(t.pinned ? "Unpin" : "Pin to top", systemImage: t.pinned ? "pin.slash" : "pin")
        }
        Button { shareTrip = t } label: { Label("Share card", systemImage: "square.and.arrow.up") }
        Button { storyTrip = IntRef(id: t.id) } label: { Label("Play story", systemImage: "play.rectangle.fill") }
        Divider()
        Button { linkSeed = LinkSeed(ids: [t.id]) } label: {
            Label(t.journey_id == nil ? "Link to journey…" : "Move to journey…", systemImage: "link")
        }
        Button {
            withAnimation(.snappy) { selecting = true; selected = [t.id] }
        } label: { Label("Select", systemImage: "checkmark.circle") }
        Divider()
        if owns(t) {
            Button(role: .destructive) { deleteIds = LinkSeed(ids: [t.id]) } label: { Label("Delete trip…", systemImage: "trash") }
        } else {
            Button(role: .destructive) { deleteIds = LinkSeed(ids: [t.id]) } label: {
                Label("Leave trip…", systemImage: "rectangle.portrait.and.arrow.right")
            }
        }
    }

    private func toggleSelect(_ id: Int) {
        Haptics.tap()
        if let i = selected.firstIndex(of: id) { selected.remove(at: i) } else { selected.append(id) }
    }

    private func openDeepLink() {
        let id = UserDefaults.standard.integer(forKey: "TrippyOpenTrip")
        if id > 0, deepTripId == nil, network.trips.contains(where: { $0.id == id }) { deepTripId = id }
    }

    // MARK: Header

    private func header(_ snaps: [TripSnapshot]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .center) {
                Text("My Trips")
                    .type(.largeTitle)
                    .foregroundStyle(.white)
                Spacer()
                Button { searching = true } label: { CircleIcon(systemName: "magnifyingglass") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Search")
                    .keyboardShortcut("f", modifiers: .command)
                Button { showingAddTrip = true } label: { CircleIcon(systemName: "plus") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("New trip")
                    .sensoryFeedback(.impact(weight: .light), trigger: showingAddTrip)
            }
            TripStatsStrip(snapshots: snaps)
            SyncedCaption().padding(.top, 2)
        }
        .padding(.horizontal, Theme.pagePadding + 4)
        .padding(.top, 4).padding(.bottom, Theme.s3)
    }

    // MARK: List

    @ViewBuilder
    private func list(_ all: [TripSnapshot], now: Date) -> some View {
        let journeys = network.journeys.filter { j in j.trip_ids.contains { id in all.contains { $0.id == id } } }
        let linked = Set(journeys.flatMap(\.trip_ids))
        let pinned = all.filter { !linked.contains($0.id) && $0.trip.pinned }
            .sorted { ($0.start ?? .distantFuture) < ($1.start ?? .distantFuture) }
        let snaps = all.filter { !linked.contains($0.id) && !$0.trip.pinned }
        let current = snaps.filter { $0.phase == .now }.sorted { ($0.start ?? .distantPast) < ($1.start ?? .distantPast) }
        let upcoming = snaps.filter { $0.phase == .upcoming }.sorted { ($0.start ?? .distantFuture) < ($1.start ?? .distantFuture) }
        let past = snaps.filter { $0.phase == .past }.sorted { ($0.start ?? .distantPast) > ($1.start ?? .distantPast) }
        let hero = current.first ?? upcoming.first
        let years = Dictionary(grouping: past, by: \.year).keys.sorted(by: >)

        VStack(alignment: .leading, spacing: 0) {
            if network.trips.isEmpty {
                EmptyStateCard(systemImage: "suitcase.rolling",
                               title: "No trips yet",
                               message: "Create a trip, or pull to load trips generated from your rentals.")
                    .padding(.top, 8)
            }
            let storyTrips = (current + past).filter { !$0.stops.isEmpty }.prefix(12)
            if !storyTrips.isEmpty {
                StoriesRail(snapshots: Array(storyTrips)) { storyTrip = IntRef(id: $0.trip.id) }
                    .padding(.bottom, Theme.s3)
            }
            if let hero {
                NavigationLink(destination: TripDetailView(trip: hero.trip, network: network)) {
                    UpNextCard(snapshot: hero, now: now)
                }
                .buttonStyle(.plain)
                Hairline()
            }
            section("Pinned", pinned, now: now)
            Color.clear.frame(height: 1).id("journeys")
            if !selecting, let sug = network.journeySuggestions.first(where: { !$0.dismissed }) {
                JourneySuggestionBanner(suggestion: sug, onLink: {
                    Task {
                        let (jid, err) = await network.acceptJourneySuggestion(sug)
                        if err == nil, let jid { Haptics.success(); openJourney = jid }
                    }
                }, onDismiss: {
                    withAnimation(.snappy) { Task { await network.dismissJourneySuggestion(sug) } }
                })
                .padding(.top, Theme.s4)
            }
            if !journeys.isEmpty {
                ListSectionTitle(title: "Journeys", trailing: "\(journeys.count)")
                    .padding(.top, Theme.sectionGap).padding(.bottom, Theme.s2)
                ForEach(journeys.sorted { ($0.start ?? .distantPast) > ($1.start ?? .distantPast) }) { j in
                    let legs = j.trip_ids.compactMap { id in all.first { $0.id == id } }
                    JourneyCard(journey: j, legs: legs, now: now, network: network)
                }
            }
            section("Now", current.filter { $0.id != hero?.id }, now: now)
            section("Upcoming", upcoming.filter { $0.id != hero?.id }, now: now)
            ForEach(years, id: \.self) { year in
                section(year == 0 ? "Undated" : String(year), past.filter { $0.year == year }, now: now)
            }
            Color.clear.frame(height: Theme.tabBarClearance + 24)
        }
        .padding(.horizontal, Theme.pagePadding + 4)
    }

    @ViewBuilder
    private func section(_ title: String, _ items: [TripSnapshot], now: Date) -> some View {
        if !items.isEmpty {
            ListSectionTitle(title: title, trailing: "\(items.count) trip\(items.count == 1 ? "" : "s")")
                .padding(.top, Theme.sectionGap).padding(.bottom, Theme.s2)
            Hairline()
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { idx, snap in
                    if idx > 0 { Hairline(leading: 58) }
                    if selecting {
                        Button { toggleSelect(snap.id) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: selected.contains(snap.id) ? "checkmark.circle.fill" : "circle")
                                    .type(.title3)
                                    .foregroundStyle(selected.contains(snap.id) ? Theme.blue : Theme.textTertiary)
                                TripRow(snapshot: snap, now: now)
                            }
                        }
                        .buttonStyle(.plain)
                    } else {
                    SwipeRow(key: "trip:\(snap.id)", leading: leadingActions(snap.trip), trailing: trailingActions(snap.trip)) {
                        NavigationLink(destination: TripDetailView(trip: snap.trip, network: network)) {
                            TripRow(snapshot: snap, now: now)
                                .overlay(alignment: .topTrailing) {
                                    if snap.trip.pinned {
                                        Image(systemName: "pin.fill").font(.system(size: 10, weight: .bold))
                                            .foregroundStyle(Theme.stay).rotationEffect(.degrees(40)).padding(.top, 6)
                                    }
                                }
                        }
                        .buttonStyle(.plain)
                        .contextMenu { rowMenu(snap.trip) }
                    }
                    }
                }
            }
        }
    }
}

// MARK: - Stories rail

/// Instagram-style circles for recent trips; tap to play the trip's story.
struct StoriesRail: View {
    let snapshots: [TripSnapshot]
    let onOpen: (TripSnapshot) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 14) {
                ForEach(snapshots, id: \.id) { snap in
                    Button { onOpen(snap) } label: { bubble(snap) }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Play \(snap.trip.displayTitle) story")
                }
            }
            .padding(.vertical, 2)
        }
    }

    private func bubble(_ snap: TripSnapshot) -> some View {
        let theme = StoryTheme.allCases[abs(snap.trip.id) % StoryTheme.allCases.count]
        let dest = snap.stops.dropFirst().first ?? snap.stops.first
        let code = dest.map { $0.code.isEmpty ? String(($0.city ?? "?").prefix(3)).uppercased() : $0.code } ?? "?"
        return VStack(spacing: 6) {
            ZStack {
                Circle()
                    .strokeBorder(AngularGradient(colors: [theme.accent, theme.colors[0], Color(hex: 0xFF8A3D), theme.accent], center: .center), lineWidth: 2.5)
                Circle()
                    .fill(theme.gradient)
                    .padding(5)
                Text(code)
                    .type(.numberSmall)
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.6)
                    .padding(.horizontal, 10)
            }
            .frame(width: 66, height: 66)
            Text(snap.trip.displayTitle)
                .type(.label)
                .foregroundStyle(.white.opacity(0.85))
                .lineLimit(1)
                .frame(width: 70)
        }
    }
}

// MARK: - Stats

struct TripStatsStrip: View {
    let snapshots: [TripSnapshot]

    var body: some View {
        let days = snapshots.filter { $0.phase != .upcoming }.compactMap(\.days).reduce(0, +)
        let places = Set(snapshots.flatMap { $0.stops.map { $0.city ?? $0.code } }).count
        let spent = snapshots.reduce(0) { $0 + $1.spend.amount }
        Text("\(snapshots.count) trips · \(days) days away · \(places) places · \(Fmt.compactMoney(spent))")
            .type(.timeSmall).monospacedDigit()
            .foregroundStyle(Theme.textSecondary)
            .lineLimit(1).minimumScaleFactor(0.8)
            .contentTransition(.numericText())
    }
}

// MARK: - Up next hero

struct UpNextCard: View {
    let snapshot: TripSnapshot
    let now: Date

    var body: some View {
        let isNow = snapshot.phase == .now
        let n = isNow ? snapshot.dayOfTrip(now: now) : snapshot.countdownDays(now: now)
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(spacing: 6) {
                YellowPill(text: isNow ? "Happening now" : "Up next")
                if snapshot.trip.isAutoGenerated { AutoTag() }
                Spacer()
                if let range = snapshot.trip.dateRange(events: snapshot.events, withYear: false) {
                    Text(range).type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: Theme.s4) {
                VStack(alignment: .leading, spacing: -4) {
                    Text(n == 0 && !isNow ? "0" : "\(n)")
                        .type(.hero)
                        .foregroundStyle(isNow ? Theme.green : .white)
                        .contentTransition(.numericText())
                    MicroLabel(text: isNow ? "Day of \(snapshot.days ?? 1)" : (n == 1 ? "Day to go" : "Days to go"))
                }
                .fixedSize()
                VStack(alignment: .leading, spacing: 4) {
                    Text(snapshot.trip.displayTitle)
                        .type(.title2).foregroundStyle(.white)
                        .lineLimit(2).minimumScaleFactor(0.8)
                    Text(snapshot.routeCodes)
                        .type(.calloutStrong).foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    HStack(spacing: 6) { TripChips(snapshot: snapshot, onDark: false) }
                        .padding(.top, 2)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").type(.footnoteStrong)
                    .foregroundStyle(Theme.textTertiary)
            }
        }
        .padding(.vertical, Theme.s4)
        .contentShape(Rectangle())
    }
}

// MARK: - Row

struct TripRow: View {
    let snapshot: TripSnapshot
    let now: Date

    var body: some View {
        HStack(alignment: .center, spacing: Theme.s3) {
            leftCount.frame(width: 46)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(snapshot.routeCodes)
                        .type(.footnote).foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 6)
                    Text(snapshot.dateRange ?? "No dates")
                        .type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                        .fixedSize()
                }
                HStack(spacing: 6) {
                    Text(snapshot.trip.displayTitle)
                        .type(.headline).foregroundStyle(.white)
                        .lineLimit(1)
                    if snapshot.trip.isAutoGenerated { AutoTag() }
                }
                HStack(spacing: 5) { TripChips(snapshot: snapshot, onDark: false) }
                    .padding(.top, 1)
            }
        }
        .padding(.vertical, Theme.s3)
        .contentShape(Rectangle())
    }

    private var leftCount: some View {
        switch snapshot.phase {
        case .upcoming:
            let d = snapshot.countdownDays(now: now)
            return DayCount(value: "\(d)", unit: d == 1 ? "Day" : "Days")
        case .now:
            return DayCount(value: "\(snapshot.dayOfTrip(now: now))", unit: "Day", color: Theme.green)
        case .past:
            let d = snapshot.days ?? 0
            return DayCount(value: d == 0 ? "–" : "\(d)", unit: d == 1 ? "Day" : "Days")
        }
    }
}

struct TripChips: View {
    let snapshot: TripSnapshot
    var onDark: Bool

    var body: some View {
        let t = snapshot.trip
        if !t.flights.isEmpty { GrayChip(text: "\(t.flights.count)", systemImage: "airplane") }
        if !snapshot.rentals.isEmpty { GrayChip(text: "\(snapshot.rentals.count)", systemImage: "car.fill") }
        if !t.expenses.isEmpty { GrayChip(text: "\(t.expenses.count)", systemImage: "creditcard.fill") }
        if !t.participants.isEmpty { GrayChip(text: "\(t.participants.count)", systemImage: "person.2.fill") }
        if t.flights.isEmpty && snapshot.rentals.isEmpty && t.expenses.isEmpty && t.participants.isEmpty {
            Text("Nothing booked").type(.label).foregroundStyle(Theme.textTertiary)
        }
    }
}

struct AutoTag: View {
    var body: some View {
        Text("AUTO")
            .type(.micro).tracking(0.5)
            .foregroundStyle(Theme.purple)
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(Theme.purple.opacity(0.18), in: RoundedRectangle(cornerRadius: 4))
    }
}

// MARK: - Overview map

struct TripsOverviewMap: View {
    let snapshots: [TripSnapshot]
    var bottomInset: CGFloat
    @State private var camera: MapCameraPosition = .automatic

    /// Frame what's ahead (current + upcoming trips); fall back to everything when nothing is planned.
    private var allCoords: [CLLocationCoordinate2D] {
        let ahead = snapshots.filter { $0.phase != .past }.flatMap { $0.stops.compactMap(\.coordinate) }
        return ahead.isEmpty ? snapshots.flatMap { $0.stops.compactMap(\.coordinate) } : ahead
    }

    /// Unique stops across trips, coloured by the "most current" phase that visits them.
    private var places: [(stop: TripStop, phase: TripPhase)] {
        var best: [String: (TripStop, TripPhase)] = [:]
        for s in snapshots {
            for stop in s.stops where stop.coordinate != nil {
                if let cur = best[stop.code], cur.1.rawValue <= s.phase.rawValue { continue }
                best[stop.code] = (stop, s.phase)
            }
        }
        return best.values.map { (stop: $0.0, phase: $0.1) }.sorted { $0.phase.rawValue > $1.phase.rawValue }
    }

    var body: some View {
        Map(position: $camera, interactionModes: [.pan, .zoom]) {
            MapDimmer()
            ForEach(snapshots) { s in
                let coords = s.stops.compactMap(\.coordinate)
                if coords.count > 1 {
                    if s.phase == .past {
                        MapPolyline(coordinates: coords, contourStyle: .geodesic)
                            .stroke(Color.white.opacity(0.28), style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                            .mapOverlayLevel(level: .aboveLabels)
                    } else {
                        GlowRoute(coords: coords, color: s.phase == .now ? Theme.green : Theme.route)
                    }
                }
            }
            ForEach(places, id: \.stop.code) { p in
                if let c = p.stop.coordinate {
                    if p.phase == .past {
                        Annotation("", coordinate: c) {
                            Circle().fill(Color.white.opacity(0.85)).frame(width: 7, height: 7)
                                .overlay(Circle().strokeBorder(.black.opacity(0.4), lineWidth: 1))
                        }
                    } else {
                        let east = MapFraming.isEastHalf(c, of: allCoords)
                        Annotation("", coordinate: c, anchor: east ? .trailing : .leading) {
                            MapCallout(city: MapFraming.isWide(allCoords) ? nil : p.stop.city, code: p.stop.code, color: p.phase.color, trailing: east)
                        }
                    }
                }
            }
        }
        .mapStyle(MapLook.style)
        .environment(\.colorScheme, .dark)
        .autoFit($camera, coords: allCoords, padding: 0.18, top: 60, bottom: bottomInset, side: 24)
    }
}

struct AddTripView: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var network: NetworkManager

    @State private var title = ""
    @State private var description = ""
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // Custom Input Card
                        VStack(spacing: 0) {
                            TextField("Where to next?", text: $title)
                                .type(.title)
                                .fontWeight(.bold)
                                .padding()
                                .background(Theme.surface)

                            Divider()

                            TextField("Trip description or notes", text: $description)
                                .padding()
                                .background(Theme.surface)
                        }
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .shadow(color: .black.opacity(0.05), radius: 10, y: 4)

                        // Save Button
                        Button(action: saveTrip) {
                            HStack {
                                if isSaving {
                                    ProgressView().tint(.white)
                                } else {
                                    Text("Create Trip")
                                        .type(.headline)
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(title.isEmpty ? Theme.surfaceHigh : Theme.blue)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        }
                        .disabled(title.isEmpty || isSaving)
                    }
                    .padding()
                }
            }
            .navigationTitle("New Trip")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundColor(.secondary)
                }
            }
        }
    }

    func saveTrip() {
        isSaving = true
        Task {
            await network.createTrip(title: title, description: description)
            isSaving = false
            dismiss()
        }
    }
}
