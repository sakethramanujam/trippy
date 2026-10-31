import SwiftUI
import MapKit

struct TripDetailView: View {
    let tripId: Int
    private let initial: ApiTrip
    @ObservedObject var network: NetworkManager
    @Environment(\.dismiss) private var dismiss

    @State private var detent = min(max(LaunchOptions.detent, 0), 1)
    @State private var scroll: CGFloat = 0
    @State private var sheetHeight: CGFloat = 0
    @State private var ledger: ApiLedger?
    @State private var ledgerMode: LedgerMode = UserDefaults.standard.string(forKey: "TrippyGroupMode") == "pairwise" ? .pairwise : .simplified
    @State private var editingExpense: ApiExpense?
    @State private var openGroup: IntRef?
    @State private var showAddPerson = false
    @State private var showAddExpense = false
    @State private var removing: ApiParticipant?
    @State private var inviting: ApiParticipant?
    @State private var forceRemove: (person: ApiParticipant, message: String)?
    @State private var confirmDelete = false
    @State private var renaming = false
    @State private var newTitle = ""
    @State private var removedTrip = false
    @EnvironmentObject private var auth: AuthManager
    private var ownsTrip: Bool {
        guard let me = auth.profile?.id, let owner = trip.owner_id else { return true }
        return me == owner
    }
    @State private var errorText: String?
    @State private var didRunLaunchHooks = false
    @State private var showStory = false
    @State private var showShare = false
    @State private var openStay: ApiLodging?
    @State private var showAddStay = false
    @State private var showLink = false
    @State private var showMergePicker = false
    @State private var pendingMerge: ApiTrip?
    @State private var moving: [ItemRef] = []
    /// Non-nil while multi-selecting bookings (long-press → Select).
    @State private var selectedItems: Set<ItemRef>?
    @State private var openJourney: Int?

    init(trip: ApiTrip, network: NetworkManager) {
        self.tripId = trip.id
        self.initial = trip
        self.network = network
    }

    /// Always read the live copy so adds/removes show up immediately.
    private var trip: ApiTrip { network.trips.first { $0.id == tripId } ?? initial }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            let snap = TripSnapshot(trip: trip, allRentals: network.rentals, now: context.date)
            ZStack(alignment: .top) {
                Theme.canvas.ignoresSafeArea()
                TripRouteMap(snapshot: snap, bottomInset: sheetHeight)
                    .ignoresSafeArea()
                DetentSheet(detents: [0.56, 0.93], selection: $detent,
                            scrollOffset: $scroll, visibleHeight: $sheetHeight,
                            onRefresh: { await network.refreshTrip(tripId); await reloadBalances() }) {
                    header(snap)
                } content: {
                    sheetContent(snap, now: context.date)
                }
            }
            .overlay(alignment: .bottom) { if selectedItems != nil { itemSelectionBar } }
        }
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(item: $openJourney) { id in JourneyDetailView(journeyId: id, network: network) }
        .sheet(isPresented: $showLink) {
            LinkToJourneySheet(network: network, seed: [tripId]) { openJourney = $0 }
        }
        .sheet(isPresented: $showMergePicker) {
            TripPickerSheet(network: network, title: "Merge into…",
                            subtitle: "Everything in \(trip.displayTitle) moves into the trip you pick, then \(trip.displayTitle) is deleted. To keep both trips, use Link to journey instead.",
                            confirm: "Next", multi: false, exclude: [tripId], destructive: true) { ids, _ in
                pendingMerge = ids.first.flatMap { id in network.trips.first { $0.id == id } }
            }
        }
        .confirmationDialog(pendingMerge.map { "Merge into \($0.displayTitle)?" } ?? "",
                            isPresented: Binding(get: { pendingMerge != nil }, set: { if !$0 { pendingMerge = nil } }),
                            titleVisibility: .visible) {
            if let target = pendingMerge {
                Button("Merge and delete \(trip.displayTitle)", role: .destructive) {
                    Task {
                        if let err = await network.mergeTrip(tripId, into: target.id) { errorText = err } else { Haptics.success(); dismiss() }
                    }
                }
                Button("Link to a journey instead") { showLink = true }
            }
        } message: {
            Text("This can't be undone. Flights, stays, rentals, expenses, travelers and plans move to \(pendingMerge?.displayTitle ?? "the other trip"), and this trip is deleted.")
        }
        .sheet(isPresented: Binding(get: { !moving.isEmpty }, set: { if !$0 { moving = [] } })) {
            MoveToTripSheet(network: network, items: moving, fromTrip: tripId) { err in
                if let err { errorText = err }
                selectedItems = nil
                await reloadBalances()
            }
        }
        .task {
            if network.rentals.isEmpty { await network.fetchRentals() }
            if network.journeys.isEmpty { await network.fetchJourneys() }
            await reloadBalances()
            await runLaunchHooks()
        }
        .onChange(of: trip.expenses.count) { _, _ in Task { await reloadBalances() } }
        .sheet(isPresented: $showAddPerson) {
            AddTravelerSheet(network: network, trip: trip)
        }
        .fullScreenCover(isPresented: $showStory) {
            StoryPlayerView(network: network, tripId: trip.id)
        }
        .sheet(isPresented: $showShare) {
            ShareCardSheet(network: network, kinds: [.trip, .year], tripId: trip.id,
                           year: Fmt.parse(trip.start_date).map { Calendar.current.component(.year, from: $0) }
                               ?? Calendar.current.component(.year, from: Date()))
        }
        .sheet(item: $openStay, onDismiss: { Task { await network.refreshTrip(tripId) } }) { stay in
            StayDetailSheet(network: network, stay: stay, tripId: tripId)
        }
        .sheet(isPresented: $showAddStay, onDismiss: { Task { await network.refreshTrip(tripId) } }) {
            StayFormSheet(network: network, tripId: tripId, defaultCheckIn: Fmt.parse(trip.start_date))
        }
        .sheet(isPresented: $showAddExpense) {
            SplitExpenseSheet(network: network, scope: .trip(trip.id)) { Task { await reloadBalances() } }
        }
        .sheet(item: $editingExpense) { e in
            SplitExpenseSheet(network: network, scope: .trip(trip.id), editing: e) { Task { await reloadBalances() } }
        }
        .sheet(item: $openGroup, onDismiss: { Task { await reloadBalances() } }) { ref in
            NavigationStack { GroupDetailView(network: network, groupId: ref.id) }
                .preferredColorScheme(.dark)
        }
        .confirmationDialog(removing.map { $0.displayName } ?? "",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            if let person = removing {
                if person.is_placeholder {
                    Button("Share invite code") { inviting = person; removing = nil }
                }
                Button("Remove from trip", role: .destructive) { Task { await remove(person, force: false) } }
            }
        } message: {
            Text(removing?.is_placeholder == true
                 ? "Not on Trippy yet. An invite code lets them sign up and take over their part of this trip."
                 : "Removing keeps them in your contacts; they can be added again.")
        }
        .sheet(item: $inviting) { person in
            InviteCodeSheet(network: network, tripId: tripId, tripTitle: trip.displayTitle, person: person)
        }
        .alert("Unsettled expenses",
               isPresented: Binding(get: { forceRemove != nil }, set: { if !$0 { forceRemove = nil } })) {
            if let pending = forceRemove {
                Button("Remove anyway", role: .destructive) { Task { await remove(pending.person, force: true) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(forceRemove?.message ?? "")
        }
        .sheet(isPresented: $confirmDelete, onDismiss: { if removedTrip { dismiss() } }) {
            DeleteTripSheet(network: network, tripIds: [trip.id]) { done in removedTrip = done }
        }
        .alert("Rename trip", isPresented: $renaming) {
            TextField("Title", text: $newTitle)
            Button("Save") {
                let t = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !t.isEmpty, t != trip.displayTitle else { return }
                Task { if let err = await network.renameTrip(trip.id, title: t) { errorText = err } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(trip.title_auto ? "Trippy names this trip after its route. Once you rename it, your title stays." : "")
        }
        .alert("Something went wrong", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(errorText ?? "") }
    }

    // MARK: Header (collapses as the sheet scrolls)

    private func header(_ snap: TripSnapshot) -> some View {
        let p = min(max(scroll / 70, 0), 1)
        return VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(headerMicro(snap))
                        .type(.label).tracking(0.4).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                        .opacity(1 - p)
                        .frame(height: 15 * (1 - p), alignment: .bottom)
                        .clipped()
                    Text(trip.displayTitle)
                        .font(.system(size: 26 - 8 * p, weight: .bold))
                        .foregroundStyle(.white)
                        .lineLimit(1).minimumScaleFactor(0.7)
                }
                Spacer(minLength: 8)
                Button { showStory = true } label: { circleIcon("play.fill") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Play trip story")
                Button { showShare = true } label: { circleIcon("square.and.arrow.up") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Share trip card")
                Menu {
                    Button { showStory = true } label: { Label("Play story", systemImage: "play.rectangle.fill") }
                    Button { showShare = true } label: { Label("Share card", systemImage: "square.and.arrow.up") }
                    Divider()
                    Button { showAddPerson = true } label: { Label("Add traveler", systemImage: "person.badge.plus") }
                    Button { showAddExpense = true } label: { Label("Add expense", systemImage: "plus.circle") }
                    Button { showAddStay = true } label: { Label("Add stay", systemImage: "bed.double") }
                    Divider()
                    if let jid = trip.journey_id {
                        Button { openJourney = jid } label: { Label("Open journey", systemImage: "square.stack.3d.up") }
                        Button(role: .destructive) {
                            Task { if let err = await network.removeTrip(tripId, fromJourney: jid) { errorText = err } }
                        } label: { Label("Remove from journey", systemImage: "minus.circle") }
                    } else {
                        Button { showLink = true } label: { Label("Link to journey…", systemImage: "link") }
                    }
                    Button { withAnimation(.snappy) { selectedItems = [] } } label: { Label("Select items…", systemImage: "checkmark.circle") }
                    Button { showMergePicker = true } label: { Label("Merge into…", systemImage: "arrow.triangle.merge") }
                    Divider()
                    Button { Task { await network.setPinned(trip.id, !trip.pinned) } } label: {
                        Label(trip.pinned ? "Unpin" : "Pin to top", systemImage: trip.pinned ? "pin.slash" : "pin")
                    }
                    if ownsTrip {
                        Button { newTitle = trip.displayTitle; renaming = true } label: { Label("Rename trip…", systemImage: "pencil") }
                    }
                    Divider()
                    if ownsTrip {
                        Button(role: .destructive) { confirmDelete = true } label: { Label("Delete trip…", systemImage: "trash") }
                    } else {
                        Button(role: .destructive) { confirmDelete = true } label: { Label("Leave trip…", systemImage: "rectangle.portrait.and.arrow.right") }
                    }
                } label: {
                    circleIcon("ellipsis")
                }
                Button { dismiss() } label: { circleIcon("xmark") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Close")
            }
            .padding(.horizontal, Theme.pagePadding)
            .padding(.top, 2).padding(.bottom, 10)
            Rectangle().fill(Theme.divider).frame(height: 0.5).opacity(p)
        }
    }

    private func headerMicro(_ snap: TripSnapshot) -> String {
        var parts: [String] = []
        if trip.isAutoGenerated { parts.append("AUTO") }
        parts.append(snap.phase == .now ? "ON TRIP" : snap.phase.label.uppercased())
        if let range = trip.dateRange(events: snap.events, withYear: true) { parts.append(range.uppercased()) }
        return parts.joined(separator: " • ")
    }

    private func circleIcon(_ name: String) -> some View { CircleIcon(systemName: name) }

    // MARK: Sheet content

    private func itinerary(_ snap: TripSnapshot, now: Date) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            sectionTitle("Itinerary", trailing: snap.events.isEmpty ? nil : "\(snap.events.count) events")
            TripTimeline(events: snap.events, now: now, onOpenStay: { openStay = $0 },
                         onMove: { moving = [$0] },
                         onStartSelect: { ref in withAnimation(.snappy) { selectedItems = [ref] } },
                         selection: selectedItems == nil ? nil : Binding(get: { selectedItems ?? [] }, set: { selectedItems = $0 }))
        }
    }

    private var itemSelectionBar: some View {
        let n = selectedItems?.count ?? 0
        return HStack(spacing: 10) {
            Button("Cancel") { withAnimation(.snappy) { selectedItems = nil } }
                .buttonStyle(TintedButtonStyle(tint: Theme.textSecondary))
                .frame(width: 110)
            Button {
                moving = Array(selectedItems ?? []).sorted { $0.key < $1.key }
            } label: {
                Label(n == 0 ? "Select bookings" : "Move \(n) to trip…", systemImage: "arrow.right.doc.on.clipboard")
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(n == 0)
            .opacity(n == 0 ? 0.5 : 1)
        }
        .padding(.horizontal, Theme.pagePadding)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    @ViewBuilder
    private var journeyRow: some View {
        if let jid = trip.journey_id {
            let j = network.journeys.first { $0.id == jid }
            Button { openJourney = jid } label: {
                HStack(spacing: 12) {
                    Image(systemName: "square.stack.3d.up.fill").type(.headline).foregroundStyle(Theme.blue)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Part of a journey").type(.label).tracking(0.4).foregroundStyle(Theme.textSecondary)
                        Text(j?.title ?? "Journey").type(.calloutStrong).foregroundStyle(.white).lineLimit(1)
                    }
                    Spacer()
                    if let j, let pos = j.trip_ids.firstIndex(of: tripId) {
                        Text("Leg \(pos + 1) of \(j.trip_count)").type(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                    Image(systemName: "chevron.right").type(.footnoteStrong).foregroundStyle(Theme.textTertiary)
                }
                .padding(12)
                .background(Theme.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 14))
            }
            .buttonStyle(.plain)
        }
    }

    private func sheetContent(_ snap: TripSnapshot, now: Date) -> some View {
        VStack(alignment: .leading, spacing: Theme.sectionGap) {
            TripStatusBanner(snapshot: snap, now: now)
            journeyRow

            if UserDefaults.standard.bool(forKey: "TrippyFocusExpenses") { expensesSection(snap) }

            let focusItinerary = UserDefaults.standard.bool(forKey: "TrippyFocusItinerary")
            if focusItinerary { itinerary(snap, now: now) }

            TravelersCard(trip: trip,
                          onAdd: { showAddPerson = true },
                          onRemove: { removing = $0 })

            if !focusItinerary { itinerary(snap, now: now) }

            VStack(alignment: .leading, spacing: Theme.s3) {
                sectionTitle("Good to Know", trailing: nil)
                GoodToKnowGrid(snapshot: snap)
            }

            if !UserDefaults.standard.bool(forKey: "TrippyFocusExpenses") { expensesSection(snap) }

            if trip.isAutoGenerated {
                AutoTripFooter { confirmDelete = true }
            }
            Color.clear.frame(height: Theme.tabBarClearance + 20)
        }
        .padding(.horizontal, Theme.pagePadding)
        .padding(.top, 4)
    }

    private func expensesSection(_ snap: TripSnapshot) -> some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            sectionTitle("Expenses", trailing: nil)
            TripExpensesCard(network: network, trip: trip, snapshot: snap, ledger: ledger, mode: $ledgerMode,
                             onAdd: { showAddExpense = true },
                             onEdit: { editingExpense = $0 },
                             onSettle: { d in Task { await settle(d) } },
                             onSettleAll: { Task { await settleAll() } },
                             onGroup: { Task { await openOrCreateGroup() } },
                             hideList: UserDefaults.standard.bool(forKey: "TrippyFocusBalances"))
        }
    }

    private func sectionTitle(_ text: String, trailing: String?) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(text).type(.title3).foregroundStyle(.white)
            Spacer()
            if let trailing { MicroLabel(text: trailing) }
        }
    }

    // MARK: Actions

    private func reloadBalances() async {
        if network.users.isEmpty { await network.loadUsers() }
        if network.groups.isEmpty { await network.fetchGroups() }
        ledger = await network.fetchLedger(.trip(tripId))
    }

    private func settle(_ d: ApiDebt) async {
        if let err = await network.settle(.trip(tripId), from: d.from_user_id, to: d.to_user_id, mode: ledgerMode) { errorText = err }
        await reloadBalances()
    }

    private func settleAll() async {
        if let err = await network.settleAll(.trip(tripId)) { errorText = err }
        await reloadBalances()
    }

    private func openOrCreateGroup() async {
        if let g = trip.group_id { openGroup = IntRef(id: g); return }
        let (group, err) = await network.groupFromTrip(tripId)
        if let err { errorText = err } else if let group { openGroup = IntRef(id: group.id) }
    }

    private func remove(_ person: ApiParticipant, force: Bool) async {
        removing = nil
        let result = await network.removeTraveler(tripId: tripId, userId: person.id, force: force)
        if result.conflict {
            forceRemove = (person, result.error ?? "This person has unsettled expenses.")
        } else if let err = result.error {
            errorText = err
        }
        await reloadBalances()
    }

    /// Screenshot/UI-test hooks: `-TrippyDebugAddTraveler "Name"` adds a traveler through the
    /// same NetworkManager call the sheet uses; `-TrippyShowAddPerson 1` opens the sheet.
    private func runLaunchHooks() async {
        guard !didRunLaunchHooks else { return }
        didRunLaunchHooks = true
        let d = UserDefaults.standard
        guard d.integer(forKey: "TrippyOpenTrip") == tripId else { return }
        if let name = d.string(forKey: "TrippyDebugAddTraveler"), !name.isEmpty,
           !trip.participants.contains(where: { $0.displayName.lowercased() == name.lowercased() }) {
            if let err = await network.addTraveler(tripId: tripId, name: name, email: d.string(forKey: "TrippyDebugTravelerEmail")) {
                errorText = err
            }
        }
        if d.bool(forKey: "TrippyShowAddPerson") { showAddPerson = true }
        if d.bool(forKey: "TrippyShowRename") { newTitle = trip.displayTitle; renaming = true }
        // Stories / cards: -TrippyShowStory YES, -TrippyShowShare YES
        if d.bool(forKey: "TrippyShowStory") { showStory = true }
        if d.bool(forKey: "TrippyShowShare") { showShare = true }
        // Money hooks: -TrippyShowSplit 1, -TrippyEditExpense N, -TrippyDebugSettle "from,to", -TrippyDebugSettleAll 1
        if let pair = d.string(forKey: "TrippyDebugSettle") {
            let ids = pair.split(separator: ",").compactMap { Int($0) }
            if ids.count == 2 {
                if let err = await network.settle(.trip(tripId), from: ids[0], to: ids[1], mode: ledgerMode) { errorText = err }
                await reloadBalances()
            }
        }
        if d.bool(forKey: "TrippyDebugSettleAll") { await settleAll() }
        if d.bool(forKey: "TrippyShowSplit") { showAddExpense = true }
        // Stays: -TrippyOpenStay N (or "first"), -TrippyShowAddStay YES, -TrippyEditStay YES (with OpenStay)
        if d.bool(forKey: "TrippyShowAddStay") { showAddStay = true }
        if let v = d.string(forKey: "TrippyOpenStay") {
            openStay = Int(v).flatMap { id in trip.lodgings.first { $0.id == id } } ?? trip.lodgings.first
        }
        // Journeys: -TrippyShowLinkTrip YES, -TrippyShowMerge YES, -TrippyMergeTarget N, -TrippySelectItems "flight-3,lodging-2", -TrippyMoveItem "flight-3"
        if d.bool(forKey: "TrippyShowLinkTrip") { showLink = true }
        if d.bool(forKey: "TrippyShowMerge") { showMergePicker = true }
        if let t = d.string(forKey: "TrippyMergeTarget").flatMap(Int.init) { pendingMerge = network.trips.first { $0.id == t } }
        if let u = d.string(forKey: "TrippyInviteTraveler").flatMap(Int.init) { inviting = trip.participants.first { $0.id == u } }
        func refs(_ key: String) -> [ItemRef]? {
            d.string(forKey: key).map { $0.split(separator: ",").compactMap { part -> ItemRef? in
                let bits = part.split(separator: "-")
                guard bits.count == 2, let k = ItemRef.Kind(rawValue: String(bits[0])), let n = Int(bits[1]) else { return nil }
                return ItemRef(kind: k, id: n)
            } }
        }
        if let sel = refs("TrippySelectItems") { selectedItems = Set(sel) }
        if let mv = refs("TrippyMoveItem"), !mv.isEmpty { moving = mv }
        if let id = d.string(forKey: "TrippyEditExpense").flatMap(Int.init),
           let e = trip.expenses.first(where: { $0.id == id }) { editingExpense = e }
    }
}

// MARK: - Map

struct TripRouteMap: View {
    let snapshot: TripSnapshot
    var bottomInset: CGFloat
    @State private var camera: MapCameraPosition = .automatic
    @State private var cameraTick = 0
    /// Visible map width in map points, to decide which hotel labels would collide.
    @State private var visibleWidth: Double?

    private var coords: [CLLocationCoordinate2D] { snapshot.stops.compactMap(\.coordinate) }
    private var hotels: [ApiLodging] { snapshot.trip.activeLodgings.filter { $0.coordinate != nil } }
    /// Everything the camera should frame: the route plus any hotel pins.
    private var fitCoords: [CLLocationCoordinate2D] { coords + hotels.compactMap(\.coordinate) }
    private var wide: Bool { MapFraming.isWide(fitCoords) }

    var body: some View {
        Group {
            if fitCoords.isEmpty {
                ZStack {
                    LinearGradient(colors: [Theme.purpleNight, Theme.canvas], startPoint: .top, endPoint: .bottom)
                    VStack(spacing: 8) {
                        Image(systemName: "map").font(TType.glyph(30, .semibold))
                        Text("Add a flight, stay or rental to see the route")
                            .type(.callout)
                    }
                    .foregroundStyle(Theme.textSecondary)
                    .padding(.bottom, 360)
                }
            } else {
                MapReader { proxy in
                    Map(position: $camera, interactionModes: [.pan, .zoom]) {
                        MapDimmer()
                        if coords.count > 1 {
                            GlowRoute(coords: coords)
                        }
                        ForEach(hotelGroups) { g in
                            Annotation("", coordinate: g.coordinate, anchor: .bottom) {
                                HotelPin(name: wide ? nil : g.label, count: g.stays.count)
                            }
                        }
                        if !wide {
                            ForEach(Array(snapshot.stops.enumerated()), id: \.offset) { _, stop in
                                if let c = stop.coordinate {
                                    let east = MapFraming.isEastHalf(c, of: coords)
                                    Annotation("", coordinate: c, anchor: east ? .trailing : .leading) {
                                        MapCallout(city: stop.city, code: stop.code, trailing: east)
                                    }
                                }
                            }
                        }
                    }
                    .mapStyle(MapLook.style)
                    .environment(\.colorScheme, .dark)
                    .autoFit($camera, coords: fitCoords, padding: 0.18, top: 60, bottom: bottomInset + 10, side: 24)
                    .onMapCameraChange(frequency: .continuous) { _ in cameraTick &+= 1 }
                    .onMapCameraChange(frequency: .onEnd) { ctx in
                        visibleWidth = ctx.region.span.longitudeDelta / 360 * MKMapRect.world.width
                    }
                    .overlay {
                        // Long-haul routes can exceed MapKit's zoom-out limit, so pin the
                        // endpoint labels inside the screen edges instead of letting them clip.
                        if wide {
                            GeometryReader { geo in
                                let _ = cameraTick
                                ForEach(Array(snapshot.stops.enumerated()), id: \.offset) { _, stop in
                                    if let c = stop.coordinate, let pt = proxy.convert(c, to: .local) {
                                        let east = MapFraming.isEastHalf(c, of: coords)
                                        let x = east ? min(pt.x, geo.size.width - 10) : max(pt.x, 10)
                                        let y = min(max(pt.y, 80), max(80, geo.size.height - bottomInset - 24))
                                        MapCallout(city: nil, code: stop.code, trailing: east)
                                            .fixedSize()
                                            .frame(width: 0, alignment: east ? .trailing : .leading)
                                            .position(x: x, y: y)
                                    }
                                }
                            }
                            .allowsHitTesting(false)
                        }
                    }
                }
            }
        }
    }
}

/// Hotel marker: a coral disc with the stamp's bed glyph and, when zoomed in, the property name.
extension TripRouteMap {
    private var hotelGroups: [HotelCluster] {
        let width = visibleWidth ?? MapFraming.target(fitCoords, padding: 0.18)?.width ?? 1
        return HotelCluster.group(hotels, avoiding: snapshot.stops.compactMap(\.coordinate),
                                  pointsPerScreenPoint: width / Double(MapFraming.windowSize.width))
    }
}

/// Hotel pins whose labels would overlap at the current zoom share one pin ("3 stays").
struct HotelCluster: Identifiable {
    var stays: [ApiLodging]
    var coordinate: CLLocationCoordinate2D
    var labelHidden = false
    var id: Int { stays[0].id }

    var label: String? {
        if labelHidden { return nil }
        let names = Set(stays.map(\.name))
        return names.count == 1 ? stays[0].name : "\(stays.count) stays"
    }

    /// Greedy in check-in order. A label is ~140×30 pt; route-stop callouts claim their space first.
    static func group(_ hotels: [ApiLodging], avoiding stops: [CLLocationCoordinate2D], pointsPerScreenPoint k: Double) -> [HotelCluster] {
        func close(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D, w: Double, h: Double) -> Bool {
            let p = MKMapPoint(a), q = MKMapPoint(b)
            return abs(p.x - q.x) < w * k && abs(p.y - q.y) < h * k
        }
        var out: [HotelCluster] = []
        let ordered = hotels.sorted { ($0.checkInDate ?? .distantFuture) < ($1.checkInDate ?? .distantFuture) }
        for h in ordered {
            guard let c = h.coordinate else { continue }
            if let i = out.firstIndex(where: { close($0.coordinate, c, w: 140, h: 34) }) {
                out[i].stays.append(h)
            } else {
                out.append(HotelCluster(stays: [h], coordinate: c))
            }
        }
        for i in out.indices where stops.contains(where: { close($0, out[i].coordinate, w: 120, h: 30) }) {
            out[i].labelHidden = true
        }
        return out
    }
}

struct HotelPin: View {
    var name: String?
    var count = 1
    var body: some View {
        VStack(spacing: 3) {
            if let name {
                Text(name)
                    .type(.caption).fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(.black.opacity(0.65), in: Capsule())
                    .fixedSize()
            }
            ZStack {
                Circle().fill(Theme.stay)
                GlyphImage(glyph: .bed, size: 15, color: .white)
            }
            .frame(width: 26, height: 26)
            .overlay(Circle().strokeBorder(.white.opacity(0.9), lineWidth: 2))
            .overlay(alignment: .topTrailing) {
                if count > 1 {
                    Text("\(count)").type(.micro).foregroundStyle(.black)
                        .padding(.horizontal, 4).frame(minWidth: 15, minHeight: 15)
                        .background(.white, in: Capsule())
                        .offset(x: 7, y: -6)
                }
            }
            .shadow(color: .black.opacity(0.4), radius: 4, y: 2)
        }
        .accessibilityLabel(count > 1 ? "\(count) hotel stays" : name.map { "Hotel: \($0)" } ?? "Hotel")
    }
}

// MARK: - Status banner

struct TripStatusBanner: View {
    let snapshot: TripSnapshot
    let now: Date

    var body: some View {
        // Accent only for meaning: on-trip is green; upcoming/past are neutral.
        let color: Color = snapshot.phase == .now ? Theme.green : Color(hex: 0xD1D1D6)
        StatusBanner(title: title, subtitle: subtitle, color: color)
    }

    private var title: String {
        switch snapshot.phase {
        case .upcoming:
            guard snapshot.start != nil else { return "Not scheduled yet" }
            let d = snapshot.countdownDays(now: now)
            return d == 0 ? "Starts today" : (d == 1 ? "Starts tomorrow" : "Starts in \(d) days")
        case .now:
            return "Day \(snapshot.dayOfTrip(now: now)) of \(snapshot.days ?? 1)"
        case .past:
            guard let end = snapshot.end else { return "Completed" }
            let days = Calendar.current.dateComponents([.day], from: end, to: now).day ?? 0
            return days < 60 ? "Completed \(days) days ago" : "Completed \(Fmt.monthDayYear(end))"
        }
    }

    private var subtitle: String? {
        var parts: [String] = []
        if let d = snapshot.days { parts.append(d == 1 ? "1 day" : "\(d) days") }
        parts.append(snapshot.routeCodes)
        if let first = snapshot.events.first(where: { $0.date != nil }), snapshot.phase == .upcoming, let date = first.date {
            parts.append("\(first.kind == .departure ? "Departs" : "Starts") \(Fmt.time(date))")
        }
        return parts.joined(separator: " • ")
    }
}

// MARK: - Travelers

struct TravelersCard: View {
    let trip: ApiTrip
    var onAdd: () -> Void
    var onRemove: (ApiParticipant) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Travelers").type(.title3).foregroundStyle(.white)
                Text("\(trip.participants.count)")
                    .type(.number)
                    .foregroundStyle(Theme.textTertiary)
                Spacer()
                if !trip.participants.isEmpty {
                    Text("Tap a person for options")
                        .type(.label)
                        .foregroundStyle(Theme.textTertiary)
                }
            }
            if trip.participants.isEmpty {
                HStack(spacing: 12) {
                    addButton
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Who's coming?")
                            .type(.headline).foregroundStyle(.white)
                        Text("Add people by name to split costs")
                            .type(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                    Spacer()
                }
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 14) {
                        ForEach(trip.participants) { person in
                            Button { onRemove(person) } label: {
                                VStack(spacing: 5) {
                                    TravelerAvatar(person: person, size: 48)
                                    Text(person.firstName)
                                        .type(.caption)
                                        .foregroundStyle(.white)
                                        .lineLimit(1)
                                    if person.id == trip.owner_id {
                                        Text("Organizer").type(.micro)
                                            .foregroundStyle(Theme.textSecondary)
                                    }
                                }
                                .frame(width: 60)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(person.displayName). Double-tap for options.")
                        }
                        VStack(spacing: 5) {
                            addButton
                            Text("Add").type(.caption).foregroundStyle(Theme.textSecondary)
                        }
                        .frame(width: 60)
                    }
                }
            }
        }
    }

    private var addButton: some View {
        Button(action: onAdd) {
            Image(systemName: "plus")
                .type(.headline)
                .foregroundStyle(.white)
                .frame(width: 48, height: 48)
                .background(Theme.surfaceRaised, in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Add traveler")
    }
}

struct TravelerAvatar: View {
    let person: ApiParticipant
    var size: CGFloat = 40

    var body: some View {
        Text(person.initials)
            .font(.system(size: size * 0.36, weight: .bold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(person.avatarColor, in: Circle())
    }
}

// MARK: - Timeline

struct TripTimeline: View {
    let events: [TripEvent]
    let now: Date
    var onOpenStay: (ApiLodging) -> Void = { _ in }
    /// "Move to trip…" on a booking's long-press menu (flights, stays, rentals).
    var onMove: ((ItemRef) -> Void)? = nil
    /// Long-press → "Select" starts multi-select with that booking.
    var onStartSelect: ((ItemRef) -> Void)? = nil
    /// Non-nil while multi-selecting: rows toggle instead of opening.
    var selection: Binding<Set<ItemRef>>? = nil

    var body: some View {
        if events.isEmpty {
            HStack(spacing: 12) {
                Image(systemName: "calendar.badge.plus")
                    .type(.headline).foregroundStyle(Theme.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Nothing booked yet").type(.calloutStrong).foregroundStyle(.white)
                    Text("Flights, stays, rentals and plans for these dates show up here.")
                        .type(.footnote).foregroundStyle(Theme.textSecondary)
                }
                Spacer()
            }
            .padding(.vertical, Theme.s2)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(events.enumerated()), id: \.element.id) { idx, event in
                    if showsDayHeader(idx) {
                        dayHeader(event.date)
                    }
                    if let selection, let ref = ItemRef(eventId: event.id) {
                        let on = selection.wrappedValue.contains(ref)
                        Button {
                            Haptics.tap()
                            if on { selection.wrappedValue.remove(ref) } else { selection.wrappedValue.insert(ref) }
                        } label: {
                            HStack(spacing: 10) {
                                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                                    .type(.title3)
                                    .foregroundStyle(on ? Theme.blue : Theme.textTertiary)
                                plainRow(idx, event).allowsHitTesting(false)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    } else if selection != nil {
                        plainRow(idx, event).opacity(0.45)
                    } else {
                        row(idx, event)
                            .contextMenu {
                                if let ref = ItemRef(eventId: event.id) {
                                    if let onMove {
                                        Button { onMove(ref) } label: { Label("Move to trip…", systemImage: "arrow.right.doc.on.clipboard") }
                                    }
                                    if let onStartSelect {
                                        Button { onStartSelect(ref) } label: { Label("Select", systemImage: "checkmark.circle") }
                                    }
                                }
                            }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func plainRow(_ idx: Int, _ event: TripEvent) -> some View {
        if let stay = event.lodging {
            StayRow(stay: stay, now: now, isLast: idx == events.count - 1)
        } else {
            TripEventRow(event: event, now: now, isLast: idx == events.count - 1)
        }
    }

    @ViewBuilder
    private func row(_ idx: Int, _ event: TripEvent) -> some View {
        if let stay = event.lodging {
            Button { Haptics.tap(); onOpenStay(stay) } label: {
                StayRow(stay: stay, now: now, isLast: idx == events.count - 1)
            }
            .buttonStyle(.plain)
        } else if let rental = event.rental {
            NavigationLink(destination: RentalDetailView(rental: rental)) {
                TripEventRow(event: event, now: now, isLast: idx == events.count - 1)
            }
            .buttonStyle(.plain)
        } else {
            TripEventRow(event: event, now: now, isLast: idx == events.count - 1)
        }
    }

    private func showsDayHeader(_ idx: Int) -> Bool {
        guard idx > 0 else { return true }
        guard let a = events[idx - 1].date, let b = events[idx].date else { return events[idx].date == nil && events[idx - 1].date != nil }
        return !Calendar.current.isDate(a, inSameDayAs: b)
    }

    private func dayHeader(_ date: Date?) -> some View {
        HStack(spacing: 8) {
            Text(date.map { Fmt.dayYear($0).uppercased() } ?? "UNSCHEDULED")
                .type(.label).tracking(0.6)
                .foregroundStyle(Theme.textSecondary)
            Rectangle().fill(Theme.divider).frame(height: 0.5)
        }
        .padding(.top, 10).padding(.bottom, 6)
    }
}

struct TripEventRow: View {
    let event: TripEvent
    let now: Date
    let isLast: Bool

    private var done: Bool { (event.date ?? .distantFuture) <= now }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // Rail: colored dot on a thin gray line
            VStack(spacing: 0) {
                Circle().fill(done ? Theme.green : event.kind.color)
                    .frame(width: 12, height: 12)
                    .overlay(Circle().strokeBorder(Theme.sheet, lineWidth: 2))
                    .padding(.top, 4)
                Rectangle().fill(isLast ? Color.clear : Theme.divider)
                    .frame(width: 2)
                    .frame(maxHeight: .infinity)
            }
            .frame(width: 14)

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    if let asset = event.brandAsset {
                        LogoTile(asset: asset, size: 18)
                    } else {
                        Image(systemName: event.kind.icon).type(.footnoteStrong)
                            .foregroundStyle(event.kind.color)
                    }
                    Text(event.micro)
                        .type(.label).tracking(0.4)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if !event.code.isEmpty {
                        Text(event.code)
                            .type(.footnoteStrong)
                            .foregroundStyle(.white.opacity(0.9))
                    }
                }
                Text(event.title)
                    .type(.headline)
                    .foregroundStyle(.white)
                    .lineLimit(1).minimumScaleFactor(0.8)
                HStack(alignment: .center, spacing: 8) {
                    timeText
                    Spacer(minLength: 6)
                    if let h = event.highlight, !h.isEmpty {
                        HighlightBlock(systemImage: event.highlightIcon, text: h)
                    }
                }
                if let sub = event.subtitle, !sub.isEmpty {
                    Text(sub)
                        .type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(2)
                }
            }
            .padding(.bottom, isLast ? 4 : 18)
            if event.rental != nil {
                Image(systemName: "chevron.right")
                    .type(.footnoteStrong)
                    .foregroundStyle(Theme.textTertiary)
                    .padding(.top, 30)
            }
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder private var timeText: some View {
        if let d = event.date {
            let parts = Fmt.time(d).split(separator: " ", maxSplits: 1).map(String.init)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(parts.first ?? "")
                    .type(.heroSmall)
                if parts.count > 1 {
                    Text(parts[1]).type(.numberSmall)
                }
            }
            .foregroundStyle(done ? Theme.green : .white)
            .lineLimit(1).minimumScaleFactor(0.7)
        } else {
            Text("—").type(.largeTitle).foregroundStyle(Theme.textTertiary)
        }
    }
}

// MARK: - Good to know

struct GoodToKnowGrid: View {
    let snapshot: TripSnapshot

    private struct Tile: Identifiable {
        var id: String { label }
        let icon: String
        let label: String
        let value: String
        let caption: String?
        var tint: Color = .white
    }

    private var tiles: [Tile] {
        let trip = snapshot.trip
        let stays = trip.activeLodgings
        var t: [Tile] = []
        if let days = snapshot.days {
            t.append(Tile(icon: "calendar", label: "Duration", value: days == 1 ? "1 day" : "\(days) days",
                          caption: snapshot.dateRange))
        }
        let places = snapshot.stops
        t.append(Tile(icon: "mappin.and.ellipse", label: "Places", value: "\(Set(places.map(\.code)).count)",
                      caption: places.isEmpty ? "None yet" : places.map { $0.city ?? $0.code }.uniqued().prefix(3).joined(separator: ", ")))
        let spend = snapshot.spend
        t.append(Tile(icon: "creditcard", label: spend.isBookings ? "Bookings" : "Spent",
                      value: Fmt.compactMoney(spend.amount),
                      caption: spend.isBookings ? (stays.isEmpty ? "Rental & flight totals" : "Flights, stays & cars") : "\(trip.expenses.count) expense\(trip.expenses.count == 1 ? "" : "s")",
                      tint: Theme.green))
        t.append(Tile(icon: "person.2", label: "Travelers", value: "\(trip.participants.count)",
                      caption: trip.participants.isEmpty ? "Add people to split" : trip.participants.map(\.firstName).prefix(3).joined(separator: ", ")))
        var booked: [String] = []
        if !trip.flights.isEmpty { booked.append("\(trip.flights.count) flight\(trip.flights.count == 1 ? "" : "s")") }
        if !snapshot.rentals.isEmpty { booked.append("\(snapshot.rentals.count) car\(snapshot.rentals.count == 1 ? "" : "s")") }
        if !stays.isEmpty { booked.append("\(stays.count) stay\(stays.count == 1 ? "" : "s")") }
        if !trip.activities.isEmpty { booked.append("\(trip.activities.count) plan\(trip.activities.count == 1 ? "" : "s")") }
        if !booked.isEmpty {
            t.append(Tile(icon: "checklist", label: "Booked", value: "\(trip.flights.count + stays.count + snapshot.rentals.count + trip.activities.count)",
                          caption: booked.joined(separator: " · ")))
        }
        if !stays.isEmpty {
            let nights = stays.reduce(0) { $0 + $1.nightCount }
            t.append(Tile(icon: "bed.double", label: "Nights", value: "\(nights)",
                          caption: stays.map(\.name).uniqued().prefix(2).joined(separator: ", "), tint: Theme.stay))
        }
        let flightMiles = trip.flights.reduce(0) { $0 + ($1.distance_miles ?? 0) }
        let driven = snapshot.rentals.reduce(0) { $0 + ($1.milesDriven ?? 0) }
        if flightMiles + driven > 0 {
            var cap: [String] = []
            if flightMiles > 0 { cap.append("\(Fmt.number(flightMiles)) flown") }
            if driven > 0 { cap.append("\(Fmt.number(driven)) driven") }
            t.append(Tile(icon: "point.topleft.down.to.point.bottomright.curvepath", label: "Distance",
                          value: "\(Fmt.number(flightMiles + driven)) mi", caption: cap.joined(separator: " · ")))
        }
        return t
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
            ForEach(tiles) { tile in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 5) {
                        Image(systemName: tile.icon).type(.label)
                        Text(tile.label.uppercased()).type(.label).tracking(0.5)
                    }
                    .foregroundStyle(Theme.textSecondary)
                    Text(tile.value)
                        .type(.number)
                        .foregroundStyle(.white)
                        .lineLimit(1).minimumScaleFactor(0.6)
                    Text(tile.caption ?? " ")
                        .type(.caption)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1).minimumScaleFactor(0.85)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(Theme.s4)
                .background(Color.white.opacity(0.03), in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.10), lineWidth: 1))
            }
        }
    }
}

extension Sequence where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}

struct AutoTripFooter: View {
    var onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Auto-generated from your rental history", systemImage: "wand.and.stars")
                .type(.footnote).foregroundStyle(Theme.textSecondary)
            Button(role: .destructive, action: onDelete) {
                Label("Delete this trip", systemImage: "trash")
                    .type(.calloutStrong)
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
                    .foregroundStyle(Theme.red)
                    .background(Theme.red.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
        }
    }
}

// MARK: - Add traveler sheet

struct AddTravelerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var network: NetworkManager
    let trip: ApiTrip

    @State private var name = ""
    @State private var email = ""
    @State private var known: [ApiParticipant] = []
    @State private var isSaving = false
    @State private var error: String?
    @FocusState private var nameFocused: Bool

    private var suggestions: [ApiParticipant] {
        let onTrip = Set(trip.participants.map(\.id))
        return known.filter { !onTrip.contains($0.id) }
    }

    private var valid: Bool {
        let n = name.trimmingCharacters(in: .whitespaces)
        let e = email.trimmingCharacters(in: .whitespaces)
        return !n.isEmpty && (e.isEmpty || (e.contains("@") && e.contains(".")))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(spacing: 0) {
                        field("Name", text: $name, prompt: "e.g. Maya Chen")
                            .focused($nameFocused)
                            .textContentType(.name)
                        Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.leading, 16)
                        field("Email", text: $email, prompt: "Optional")
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))

                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .type(.footnote).foregroundStyle(Theme.red)
                    }

                    Text("They'll appear in Travelers and can be picked when you split an expense. If someone with that name or email already exists, they're reused.")
                        .type(.footnote).foregroundStyle(Theme.textSecondary)

                    if !suggestions.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("PEOPLE YOU'VE ADDED BEFORE")
                                .type(.label).tracking(0.5)
                                .foregroundStyle(Theme.textSecondary)
                            ForEach(suggestions) { p in
                                Button {
                                    name = p.displayName
                                    email = p.realEmail ?? ""
                                } label: {
                                    HStack(spacing: 12) {
                                        TravelerAvatar(person: p, size: 34)
                                        VStack(alignment: .leading, spacing: 1) {
                                            Text(p.displayName).type(.callout).foregroundStyle(.white)
                                            if let e = p.realEmail {
                                                Text(e).type(.caption).foregroundStyle(Theme.textSecondary)
                                            }
                                        }
                                        Spacer()
                                        Image(systemName: "plus.circle.fill").foregroundStyle(Theme.blue)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(Theme.pagePadding)
            }
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle("Add Traveler")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Adding…" : "Add") { save() }
                        .fontWeight(.bold)
                        .disabled(!valid || isSaving)
                }
            }
            .task {
                known = await network.fetchUsers()
                if UserDefaults.standard.bool(forKey: "TrippyShowAddPerson") == false { nameFocused = true }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private func field(_ label: String, text: Binding<String>, prompt: String) -> some View {
        HStack(spacing: 12) {
            Text(label).type(.callout).foregroundStyle(Theme.textSecondary)
                .frame(width: 52, alignment: .leading)
            TextField("", text: text, prompt: Text(prompt).foregroundStyle(Theme.textTertiary))
                .type(.body).foregroundStyle(.white)
                .submitLabel(.done)
                .onSubmit { if valid { save() } }
        }
        .padding(.horizontal, 16).frame(height: 50)
    }

    private func save() {
        isSaving = true
        error = nil
        Task {
            let err = await network.addTraveler(tripId: trip.id,
                                                name: name.trimmingCharacters(in: .whitespaces),
                                                email: email.trimmingCharacters(in: .whitespaces))
            isSaving = false
            if let err { error = err } else { dismiss() }
        }
    }
}

// Preview helper
extension ApiTrip {
    static var previewTrip: ApiTrip {
        let json = """
        {"id":1,"title":"Preview Trip","description":"A test trip","flights":[],"expenses":[],"activities":[],"documents":[],"rental_cars":[],"participants":[]}
        """
        return try! JSONDecoder().decode(ApiTrip.self, from: json.data(using: .utf8)!)
    }
}
