import SwiftUI
import MapKit

/// Leg colors, reused on the map, the leg headers and the card's stacked edges.
enum JourneyPalette {
    static let colors: [Color] = [Theme.blue, Theme.orange, Theme.green, Theme.purple, Theme.teal, Theme.stay]
    static func color(_ leg: Int) -> Color { colors[max(leg - 1, 0) % colors.count] }
}

// MARK: - Trips list: stacked journey card

/// A journey in the Trips list: a card with two offset "pages" behind it (it holds several trips),
/// the combined dates/stats, and a chevron that expands its trips inline.
struct JourneyCard: View {
    let journey: ApiJourney
    let legs: [TripSnapshot]
    let now: Date
    @ObservedObject var network: NetworkManager
    @State private var expanded = UserDefaults.standard.bool(forKey: "TrippyExpandJourneys")
    @State private var deleting: ApiJourney?
    @State private var shareJourney = false
    @State private var deleteLeg: IntRef?

    private var unlinkAction: SwipeAction {
        SwipeAction(title: "Unlink", icon: "link.badge.plus", tint: Theme.purple) {
            Task { _ = await network.deleteJourney(journey.id, deleteTrips: false) }
        }
    }
    private var deleteAction: SwipeAction {
        SwipeAction(title: "Delete", icon: "trash.fill", tint: Theme.red) { deleting = journey }
    }

    var body: some View {
        VStack(spacing: 0) {
            SwipeRow(key: "journey:\(journey.id)",
                     leading: [SwipeAction(title: "Share", icon: "square.and.arrow.up", tint: Theme.blue) { shareJourney = true }],
                     trailing: journey.is_owner ? [unlinkAction, deleteAction] : []) {
                NavigationLink(destination: JourneyDetailView(journeyId: journey.id, network: network)) {
                    card
                }
                .buttonStyle(.plain)
                .contextMenu {
                    Button { shareJourney = true } label: { Label("Share card", systemImage: "square.and.arrow.up") }
                    if journey.is_owner {
                        Divider()
                        Button { unlinkAction.action() } label: { Label("Unlink trips (keep them)", systemImage: "link.badge.plus") }
                        Button(role: .destructive) { deleting = journey } label: { Label("Delete journey…", systemImage: "trash") }
                    }
                }
            }
            .journeyDeleteDialog($deleting, network: network)
            .sheet(isPresented: $shareJourney) {
                ShareCardSheet(network: network, kinds: [.trip], tripId: journey.trip_ids.first, journeyId: journey.id,
                               year: journey.start.map { Calendar.current.component(.year, from: $0) }
                                   ?? Calendar.current.component(.year, from: Date()))
            }
            .sheet(item: $deleteLeg) { ref in DeleteTripSheet(network: network, tripIds: [ref.id]) }
            if expanded {
                VStack(spacing: 0) {
                    ForEach(Array(legs.enumerated()), id: \.element.id) { idx, snap in
                        if idx > 0 { Hairline(leading: 58) }
                        SwipeRow(key: "trip:\(snap.id)",
                                 trailing: journey.is_owner ? [
                                    SwipeAction(title: "Unlink", icon: "minus.circle", tint: Theme.purple) {
                                        Task { _ = await network.removeTrip(snap.id, fromJourney: journey.id) }
                                    },
                                    SwipeAction(title: "Delete", icon: "trash.fill", tint: Theme.red) { deleteLeg = IntRef(id: snap.id) },
                                 ] : []) {
                            NavigationLink(destination: TripDetailView(trip: snap.trip, network: network)) {
                                HStack(spacing: 0) {
                                    Rectangle().fill(JourneyPalette.color(idx + 1)).frame(width: 3)
                                        .padding(.vertical, 6)
                                    TripRow(snapshot: snap, now: now).padding(.leading, 10)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.top, 6)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.vertical, Theme.s3)
    }

    private var card: some View {
        ZStack(alignment: .top) {
            // Stacked pages behind the card.
            RoundedRectangle(cornerRadius: 16).fill(Theme.surfaceHigh.opacity(0.55))
                .padding(.horizontal, 16).offset(y: 12)
            RoundedRectangle(cornerRadius: 16).fill(Theme.surfaceRaised)
                .padding(.horizontal, 8).offset(y: 6)
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Label("JOURNEY", systemImage: "point.topleft.down.to.point.bottomright.curvepath.fill")
                        .type(.micro).tracking(0.6)
                        .foregroundStyle(Theme.blue)
                    Spacer()
                    Text(journey.dateText).type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                }
                Text(journey.title)
                    .type(.title3).foregroundStyle(.white)
                    .lineLimit(2)
                LegStripe(count: max(journey.trip_count, 1))
                HStack(spacing: 6) {
                    GrayChip(text: "\(journey.trip_count) trips", systemImage: "square.stack.3d.up.fill")
                    if let d = journey.stats.days { GrayChip(text: "\(d)d", systemImage: "calendar") }
                    if journey.stats.flights > 0 { GrayChip(text: "\(journey.stats.flights)", systemImage: "airplane") }
                    if journey.stats.nights > 0 { GrayChip(text: "\(journey.stats.nights)n", systemImage: "bed.double.fill") }
                    Spacer(minLength: 4)
                    Button {
                        Haptics.tap()
                        withAnimation(.snappy) { expanded.toggle() }
                    } label: {
                        Image(systemName: "chevron.down")
                            .type(.footnoteStrong)
                            .foregroundStyle(.white)
                            .rotationEffect(.degrees(expanded ? 180 : 0))
                            .frame(width: 30, height: 30)
                            .background(Theme.surfaceHigh, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(expanded ? "Collapse trips" : "Show trips")
                }
            }
            .padding(14)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(0.06)))
        }
        .padding(.bottom, 12)
        .contentShape(Rectangle())
    }
}

/// Colored segments, one per leg.
struct LegStripe: View {
    let count: Int
    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<count, id: \.self) { i in
                Capsule().fill(JourneyPalette.color(i + 1)).frame(height: 4)
            }
        }
    }
}

// MARK: - Suggestion banner

struct JourneySuggestionBanner: View {
    let suggestion: ApiJourneySuggestion
    var onLink: () -> Void
    var onDismiss: () -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "link.circle.fill")
                    .type(.title2).foregroundStyle(Theme.blue)
                VStack(alignment: .leading, spacing: 3) {
                    Text(suggestion.journey_id == nil ? "Link these into one journey?" : "Add to your journey?")
                        .type(.calloutStrong).foregroundStyle(.white)
                    Text(suggestion.trips.map(\.title).joined(separator: " + "))
                        .type(.footnote).foregroundStyle(Theme.textSecondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
            }
            VStack(alignment: .leading, spacing: 4) {
                ForEach(suggestion.reasons.prefix(3), id: \.self) { r in
                    Label(r, systemImage: "checkmark")
                        .type(.caption).foregroundStyle(Theme.textSecondary)
                        .labelStyle(TightLabel())
                }
            }
            HStack(spacing: 10) {
                Button {
                    busy = true
                    onLink()
                } label: {
                    BusyButtonLabel(title: "Link as “\(suggestion.title)”", busy: busy)
                        .lineLimit(1)
                }
                .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                Button("Dismiss") { onDismiss() }
                    .buttonStyle(TintedButtonStyle(tint: Theme.textSecondary))
                    .fixedSize()
            }
        }
        .padding(14)
        .background(Theme.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Theme.blue.opacity(0.30)))
    }
}

struct TightLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            configuration.icon.font(TType.glyph(9, .bold)).foregroundStyle(Theme.green)
            configuration.title
        }
    }
}

// MARK: - Journey detail

struct JourneyDetailView: View {
    let journeyId: Int
    @ObservedObject var network: NetworkManager
    @Environment(\.dismiss) private var dismiss

    @State private var journey: ApiJourney?
    @State private var errorText: String?
    @State private var detent = min(max(LaunchOptions.detent, 0), 1)
    @State private var scroll: CGFloat = 0
    @State private var sheetHeight: CGFloat = 0
    @State private var showStory = false
    @State private var showShare = false
    @State private var showAddTrips = false
    @State private var showReorder = false
    @State private var renaming = false
    @State private var newTitle = ""
    @State private var deleting: ApiJourney?
    @State private var removing: ApiJourneyLeg?
    @State private var moving: [ItemRef] = []
    @State private var openStay: (stay: ApiLodging, tripId: Int)?
    @State private var didRunHooks = false

    var body: some View {
        TimelineView(.periodic(from: .now, by: 300)) { context in
            ZStack(alignment: .top) {
                Theme.canvas.ignoresSafeArea()
                JourneyRouteMap(legs: journey?.legs ?? [], bottomInset: sheetHeight)
                    .ignoresSafeArea()
                DetentSheet(detents: [0.56, 0.93], selection: $detent,
                            scrollOffset: $scroll, visibleHeight: $sheetHeight,
                            onRefresh: { await network.fetchTrips(); await load() }) {
                    header
                } content: {
                    content(now: context.date)
                }
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task { await load(); await runHooks() }
        .onChange(of: network.trips.map(\.journey_id)) { _, _ in Task { await load() } }
        .fullScreenCover(isPresented: $showStory) {
            StoryPlayerView(network: network, tripId: journey?.trip_ids.first ?? 0, journeyId: journeyId)
        }
        .sheet(isPresented: $showShare) {
            ShareCardSheet(network: network, kinds: [.trip], tripId: journey?.trip_ids.first, journeyId: journeyId,
                           year: journey?.start.map { Calendar.current.component(.year, from: $0) }
                               ?? Calendar.current.component(.year, from: Date()))
        }
        .sheet(isPresented: $showAddTrips) {
            TripPickerSheet(network: network, title: "Add trips", subtitle: "Pick trips to add to \(journey?.title ?? "this journey").",
                            confirm: "Add", multi: true,
                            exclude: Set(journey?.trip_ids ?? [])) { ids, _ in
                Task {
                    if let err = await network.addTrips(ids, toJourney: journeyId) { errorText = err }
                    await load()
                }
            }
        }
        .sheet(isPresented: $showReorder) {
            if let journey {
                ReorderJourneySheet(network: network, journey: journey) { await load() }
            }
        }
        .sheet(isPresented: Binding(get: { !moving.isEmpty }, set: { if !$0 { moving = [] } })) {
            MoveToTripSheet(network: network, items: moving, fromTrip: nil) { err in
                if let err { errorText = err }
                await load()
            }
        }
        .sheet(isPresented: Binding(get: { openStay != nil }, set: { if !$0 { openStay = nil } }),
               onDismiss: { Task { await load() } }) {
            if let o = openStay { StayDetailSheet(network: network, stay: o.stay, tripId: o.tripId) }
        }
        .alert("Rename journey", isPresented: $renaming) {
            TextField("Title", text: $newTitle)
            Button("Save") {
                Task {
                    if let err = await network.renameJourney(journeyId, title: newTitle) { errorText = err }
                    await load()
                }
            }
            Button("Cancel", role: .cancel) {}
        }
        .journeyDeleteDialog($deleting, network: network) { dismiss() }
        .confirmationDialog(removing.map { "Remove \($0.title) from this journey?" } ?? "",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            if let leg = removing {
                Button("Remove from journey", role: .destructive) {
                    Task {
                        if let err = await network.removeTrip(leg.trip_id, fromJourney: journeyId) { errorText = err }
                        if network.journeys.contains(where: { $0.id == journeyId }) { await load() } else { dismiss() }
                    }
                }
            }
        } message: {
            Text("The trip is kept as it is; it just stops being part of this journey.")
        }
        .alert("Something went wrong", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(errorText ?? "") }
    }

    // MARK: Header

    private var header: some View {
        let p = min(max(scroll / 70, 0), 1)
        return VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(("Journey • " + (journey?.dateText ?? "")).uppercased())
                        .type(.label).tracking(0.4).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                        .opacity(1 - p)
                        .frame(height: 15 * (1 - p), alignment: .bottom)
                        .clipped()
                    Text(journey?.title ?? "Journey")
                        .font(.system(size: 26 - 8 * p, weight: .bold))
                        .foregroundStyle(.white)
                        .lineLimit(1).minimumScaleFactor(0.7)
                }
                Spacer(minLength: 8)
                Button { showStory = true } label: { CircleIcon(systemName: "play.fill") }
                    .buttonStyle(.plain).accessibilityLabel("Play journey story")
                Menu {
                    Button { showStory = true } label: { Label("Play story", systemImage: "play.rectangle.fill") }
                    Button { showShare = true } label: { Label("Share card", systemImage: "square.and.arrow.up") }
                    if journey?.is_owner ?? true {
                        Divider()
                        Button { newTitle = journey?.title ?? ""; renaming = true } label: { Label("Rename", systemImage: "pencil") }
                        Button { showAddTrips = true } label: { Label("Add trip…", systemImage: "plus.square.on.square") }
                        Button { showReorder = true } label: { Label("Reorder trips", systemImage: "arrow.up.arrow.down") }
                        Divider()
                        Button(role: .destructive) { deleting = journey } label: { Label("Delete journey…", systemImage: "trash") }
                    }
                } label: { CircleIcon(systemName: "ellipsis") }
                Button { dismiss() } label: { CircleIcon(systemName: "xmark") }
                    .buttonStyle(.plain).accessibilityLabel("Close")
            }
            .padding(.horizontal, Theme.pagePadding)
            .padding(.top, 2).padding(.bottom, 10)
            Rectangle().fill(Theme.divider).frame(height: 0.5).opacity(p)
        }
    }

    // MARK: Content

    @ViewBuilder
    private func content(now: Date) -> some View {
        VStack(alignment: .leading, spacing: Theme.sectionGap) {
            if let journey {
                JourneyHeroStats(journey: journey)
                legsSection(journey, now: now)
                if let money = moneySection(journey) { money }
            } else if let errorText {
                FormErrorBanner(message: errorText)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 40)
            }
            Color.clear.frame(height: Theme.tabBarClearance + 20)
        }
        .padding(.horizontal, Theme.pagePadding)
        .padding(.top, 4)
    }

    private func legsSection(_ journey: ApiJourney, now: Date) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(alignment: .firstTextBaseline) {
                Text("Itinerary").type(.title3).foregroundStyle(.white)
                Spacer()
                if journey.is_owner {
                    Button { showAddTrips = true } label: {
                        Label("Add trip", systemImage: "plus").type(.footnoteStrong)
                    }
                    .tint(Theme.blue)
                }
            }
            ForEach(journey.legs ?? []) { leg in
                legBlock(leg, journey: journey, now: now)
            }
        }
    }

    @ViewBuilder
    private func legBlock(_ leg: ApiJourneyLeg, journey: ApiJourney, now: Date) -> some View {
        let trip = network.trips.first { $0.id == leg.trip_id }
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .center, spacing: 10) {
                Text("\(leg.leg)")
                    .type(.numberSmall).foregroundStyle(.black)
                    .frame(width: 26, height: 26)
                    .background(JourneyPalette.color(leg.leg), in: Circle())
                VStack(alignment: .leading, spacing: 1) {
                    Text(leg.title).type(.headline).foregroundStyle(.white).lineLimit(1)
                    Text(legSubtitle(leg)).type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                Menu {
                    if let trip {
                        NavigationLink(destination: TripDetailView(trip: trip, network: network)) {
                            Label("Open trip", systemImage: "arrow.up.right.square")
                        }
                    }
                    if journey.is_owner {
                        Button { showReorder = true } label: { Label("Reorder…", systemImage: "arrow.up.arrow.down") }
                        Button(role: .destructive) { removing = leg } label: {
                            Label("Remove from journey", systemImage: "minus.circle")
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis").type(.footnoteStrong)
                        .foregroundStyle(Theme.textSecondary)
                        .frame(width: 32, height: 32)
                        .background(Theme.surfaceHigh, in: Circle())
                }
            }
            .padding(.top, 8)
            if let trip {
                let snap = TripSnapshot(trip: trip, allRentals: network.rentals, now: now)
                TripTimeline(events: snap.events, now: now,
                             onOpenStay: { openStay = ($0, leg.trip_id) },
                             onMove: journey.is_owner ? { moving = [$0] } : nil)
                    .padding(.leading, 4)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(JourneyPalette.color(leg.leg).opacity(0.35)).frame(width: 2)
                            .offset(x: -8)
                    }
            } else {
                Text("\(leg.item_count) items").type(.footnote).foregroundStyle(Theme.textTertiary)
            }
        }
    }

    private func legSubtitle(_ leg: ApiJourneyLeg) -> String {
        var parts: [String] = []
        if let s = Fmt.parse(leg.start_date) {
            if let e = Fmt.parse(leg.end_date), !Calendar.current.isDate(s, inSameDayAs: e) {
                parts.append("\(Fmt.monthDay(s)) – \(Fmt.monthDay(e))")
            } else { parts.append(Fmt.monthDay(s)) }
        }
        let codes = leg.route.compactMap { $0.code ?? $0.city }
        if !codes.isEmpty { parts.append(codes.joined(separator: " → ")) }
        return parts.joined(separator: "  •  ")
    }

    private func moneySection(_ journey: ApiJourney) -> AnyView? {
        let debts = journey.balances?.simplified ?? []
        guard journey.costText != nil || !debts.isEmpty else { return nil }
        return AnyView(VStack(alignment: .leading, spacing: Theme.s2) {
            Text("Money").type(.title3).foregroundStyle(.white)
            if let cost = journey.costText {
                HStack {
                    Text("Total across trips").type(.callout).foregroundStyle(Theme.textSecondary)
                    Spacer()
                    Text(cost).type(.calloutStrong).monospacedDigit().foregroundStyle(.white)
                }
                .padding(.vertical, 6)
            }
            if !debts.isEmpty {
                Hairline()
                MicroLabel(text: "BALANCES").padding(.top, 6)
                ForEach(debts) { d in
                    HStack {
                        Text("\(d.from_username) owes \(d.to_username)").type(.callout).foregroundStyle(.white)
                        Spacer()
                        Text(Fmt.money(Double(d.amount_cents) / 100)).type(.calloutStrong).monospacedDigit()
                            .foregroundStyle(Theme.orange)
                    }
                    .padding(.vertical, 4)
                }
            }
        })
    }

    // MARK: Data

    private func load() async {
        switch await network.fetchJourney(journeyId) {
        case .success(let j): journey = j
        case .failure(let e): if journey == nil { errorText = e.message }
        }
    }

    /// Screenshots: -TrippyJourneyShow story|share|add|reorder|remove
    private func runHooks() async {
        guard !didRunHooks else { return }
        didRunHooks = true
        switch UserDefaults.standard.string(forKey: "TrippyJourneyShow") {
        case "story": showStory = true
        case "share": showShare = true
        case "add": showAddTrips = true
        case "reorder": showReorder = true
        case "remove": removing = journey?.legs?.last
        case "delete": deleting = journey
        case "move":
            if let leg = journey?.legs?.first, let t = network.trips.first(where: { $0.id == leg.trip_id }),
               let f = t.flights.first { moving = [ItemRef(kind: .flight, id: f.id)] }
        default: break
        }
    }
}

// MARK: - Hero stats

struct JourneyHeroStats: View {
    let journey: ApiJourney

    var body: some View {
        let s = journey.stats
        VStack(alignment: .leading, spacing: 12) {
            LegStripe(count: max(journey.trip_count, 1))
            HStack(alignment: .top, spacing: 0) {
                stat("\(s.days ?? 0)", "days")
                stat("\(s.flights)", "flights")
                stat("\(s.nights)", "nights")
                stat(Fmt.number(s.miles.rounded()), "miles")
            }
            HStack(spacing: 8) {
                GrayChip(text: "\(journey.trip_count) trips linked", systemImage: "link")
                if s.places > 0 { GrayChip(text: "\(s.places) places", systemImage: "mappin") }
                if s.countries > 1 { GrayChip(text: "\(s.countries) countries", systemImage: "globe") }
                if let cost = journey.costText { GrayChip(text: cost, systemImage: "creditcard.fill") }
            }
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16))
    }

    private func stat(_ value: String, _ unit: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value).type(.heroSmall).foregroundStyle(.white).minimumScaleFactor(0.5).lineLimit(1)
            Text(unit.uppercased()).type(.micro).tracking(0.6).foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Map

struct JourneyRouteMap: View {
    let legs: [ApiJourneyLeg]
    var bottomInset: CGFloat
    @State private var camera: MapCameraPosition = .automatic
    /// nil = automatic: flat overview when MapKit can't fit the whole route on screen.
    @State private var flatChoice: Bool? = {
        switch UserDefaults.standard.string(forKey: "TrippyJourneyMap") {
        case "flat": return true
        case "map": return false
        default: return nil
        }
    }()

    private var all: [CLLocationCoordinate2D] { legs.flatMap { $0.route.compactMap(\.coordinate) } }

    /// Wider than ~110° of longitude: MapKit's zoom-out floor would crop part of the route.
    private var tooWide: Bool { (MapFraming.rect(all, minMeters: 0, padding: 0)?.width ?? 0) > MKMapRect.world.width * 0.3 }
    private var flat: Bool { flatChoice ?? tooWide }

    var body: some View {
        if all.isEmpty {
            LinearGradient(colors: [Theme.purpleNight, Theme.canvas], startPoint: .top, endPoint: .bottom)
        } else {
            ZStack(alignment: .topTrailing) {
                if flat {
                    FlatRouteMap(lines: legs.map { .init(coords: $0.route.compactMap(\.coordinate), color: JourneyPalette.color($0.leg)) },
                                 pins: stops.compactMap { s in s.place.coordinate.map { .init(coord: $0, code: s.place.code ?? s.place.city ?? "") } },
                                 top: 64, bottom: bottomInset + 10)
                } else {
                    mapKit
                }
                if tooWide || flatChoice != nil {
                    Button { withAnimation(.snappy) { flatChoice = !flat } } label: {
                        Label(flat ? "Map" : "Whole route", systemImage: flat ? "map" : "globe")
                            .type(.footnoteStrong).foregroundStyle(.white)
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(.ultraThinMaterial, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 58).padding(.trailing, 16)
                    .accessibilityLabel(flat ? "Show interactive map" : "Show whole route")
                }
            }
        }
    }

    @ViewBuilder private var mapKit: some View {
            Map(position: $camera, interactionModes: [.pan, .zoom]) {
                MapDimmer()
                ForEach(legs) { leg in
                    let coords = leg.route.compactMap(\.coordinate)
                    if coords.count > 1 { GlowRoute(coords: coords, color: JourneyPalette.color(leg.leg)) }
                }
                ForEach(Array(stops.enumerated()), id: \.offset) { _, stop in
                    if let c = stop.place.coordinate {
                        let east = MapFraming.isEastHalf(c, of: all)
                        Annotation("", coordinate: c, anchor: east ? .trailing : .leading) {
                            MapCallout(city: wide ? nil : stop.place.city, code: stop.place.code ?? "", trailing: east)
                        }
                    }
                }
            }
            .mapStyle(MapLook.style)
            .environment(\.colorScheme, .dark)
            .autoFit($camera, coords: all, padding: 0.18, top: 60, bottom: bottomInset + 10, side: 24)
    }

    private var wide: Bool { MapFraming.isWide(all) }

    /// Unique stops in order (a leg's start usually repeats the previous leg's end).
    private var stops: [(place: ApiStoryPlace, leg: Int)] {
        var seen = Set<String>()
        var out: [(ApiStoryPlace, Int)] = []
        for leg in legs {
            for p in leg.route {
                let k = p.code ?? p.city ?? ""
                if k.isEmpty || seen.contains(k) { continue }
                seen.insert(k)
                out.append((p, leg.leg))
            }
        }
        return out.map { (place: $0.0, leg: $0.1) }
    }
}
