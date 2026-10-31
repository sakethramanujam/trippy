import SwiftUI

// MARK: - DTOs (app/trash.py)

struct ApiTripCounts: Decodable, Equatable {
    var flights = 0, stays = 0, rentals = 0, expenses = 0, activities = 0, documents = 0, settlements = 0, travelers = 0

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        func n(_ k: K) -> Int { (try? c.decodeIfPresent(Int.self, forKey: k)) ?? 0 }
        flights = n(.flights); stays = n(.stays); rentals = n(.rentals); expenses = n(.expenses)
        activities = n(.activities); documents = n(.documents); settlements = n(.settlements); travelers = n(.travelers)
    }
    enum K: String, CodingKey { case flights, stays, rentals, expenses, activities, documents, settlements, travelers }

    static func + (a: Self, b: Self) -> Self {
        var r = Self()
        r.flights = a.flights + b.flights; r.stays = a.stays + b.stays; r.rentals = a.rentals + b.rentals
        r.expenses = a.expenses + b.expenses; r.activities = a.activities + b.activities
        r.documents = a.documents + b.documents; r.settlements = a.settlements + b.settlements
        r.travelers = a.travelers + b.travelers
        return r
    }

    /// "3 flights, 2 stays, 1 rental, 5 expenses" (zeros left out).
    var summary: String {
        func p(_ n: Int, _ one: String, _ many: String) -> String? { n == 0 ? nil : "\(n) \(n == 1 ? one : many)" }
        let parts = [p(flights, "flight", "flights"), p(stays, "stay", "stays"), p(rentals, "rental", "rentals"),
                     p(expenses, "expense", "expenses"), p(activities, "activity", "activities"),
                     p(documents, "document", "documents")].compactMap { $0 }
        return parts.isEmpty ? "No bookings or expenses" : parts.joined(separator: ", ")
    }
}

struct ApiDeletePreview: Decodable, Identifiable {
    struct Journey: Decodable { let id: Int; let title: String; let trips_left: Int; let journey_deleted: Bool }
    let trip_id: Int
    let title: String?
    let is_owner: Bool
    let action: String
    let counts: ApiTripCounts
    let unsettled: Bool
    let unsettled_people: Int
    let unsettled_cents: Int
    let journey: Journey?
    let keep_days: Int
    var id: Int { trip_id }
}

struct ApiTrashTrip: Decodable, Identifiable {
    let id: Int
    let title: String?
    let start_date: String?
    let end_date: String?
    let deleted_at: String?
    let purge_at: String?
    let counts: ApiTripCounts

    var daysLeft: Int? {
        guard let d = Fmt.parse(purge_at) else { return nil }
        return max(0, Int(ceil(d.timeIntervalSinceNow / 86_400)))
    }
}

// MARK: - API

extension NetworkManager {
    func deletePreview(_ id: Int) async -> ApiDeletePreview? {
        let r = await send("GET", "/trips/\(id)/delete-preview")
        guard let d = r.data, r.error == nil else { return nil }
        return try? JSONDecoder().decode(ApiDeletePreview.self, from: d)
    }

    /// Soft-deletes (Recently Deleted for 30 days) or, with `permanent`, deletes right away.
    /// Shows the Undo toast for soft deletes. Returns the ids that were actually deleted.
    @discardableResult
    func trashTrips(_ ids: [Int], permanent: Bool = false, undo: Bool = true) async -> (deleted: [Int], error: String?) {
        let r = await send("POST", "/trips/bulk-delete", json: ["trip_ids": ids, "permanent": permanent])
        guard r.error == nil, let d = r.data,
              let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return ([], r.error) }
        let deleted = ((obj["deleted"] as? [[String: Any]]) ?? []).compactMap { $0["id"] as? Int }
        let titles = deleted.compactMap { id in trips.first { $0.id == id }?.displayTitle }
        withAnimation(.snappy) { trips.removeAll { deleted.contains($0.id) } }
        if !deleted.isEmpty {
            Haptics.success()
            if undo && !permanent {
                TrashCenter.shared.show(ids: deleted,
                                        text: deleted.count == 1 ? "Deleted \(titles.first ?? "trip")" : "Deleted \(deleted.count) trips")
            }
        }
        let skipped = (obj["skipped"] as? [[String: Any]]) ?? []
        await afterTrashChange()
        return (deleted, skipped.isEmpty || !deleted.isEmpty ? nil : "Only the trip's owner can delete it.")
    }

    func restoreTrips(_ ids: [Int]) async -> String? {
        let r = ids.count == 1 ? await send("POST", "/trash/trips/\(ids[0])/restore")
                               : await send("POST", "/trash/trips/restore", json: ["trip_ids": ids])
        await afterTrashChange()
        return r.error
    }

    func fetchTrash() async -> [ApiTrashTrip] {
        let r = await send("GET", "/trash/trips")
        guard let d = r.data, r.error == nil else { return [] }
        struct L: Decodable { let trips: [ApiTrashTrip] }
        return (try? JSONDecoder().decode(L.self, from: d).trips) ?? []
    }

    func purgeTrash(_ id: Int?) async -> String? {
        let r = await send("DELETE", id.map { "/trash/trips/\($0)" } ?? "/trash/trips")
        await fetchRentals()
        return r.error
    }

    /// For travelers who don't own the trip. A 409 means an unsettled balance (retry with force).
    func leaveTrip(_ id: Int, force: Bool = false) async -> (error: String?, conflict: Bool) {
        let r = await send("POST", "/trips/\(id)/leave" + (force ? "?force=true" : ""))
        if r.error == nil { withAnimation(.snappy) { trips.removeAll { $0.id == id } } }
        return (r.error, r.status == 409)
    }

    /// Deleting a journey: unlink its trips (kept), or move the trips to Recently Deleted as well.
    func deleteJourney(_ id: Int, deleteTrips: Bool) async -> String? {
        let ids = journeys.first { $0.id == id }?.trip_ids ?? []
        let r = await send("DELETE", "/journeys/\(id)" + (deleteTrips ? "?delete_trips=true" : ""))
        if r.error == nil, deleteTrips {
            let deleted = ((try? JSONSerialization.jsonObject(with: r.data ?? Data()) as? [String: Any])?["deleted_trip_ids"] as? [Int]) ?? ids
            if !deleted.isEmpty { TrashCenter.shared.show(ids: deleted, text: "Deleted journey and \(deleted.count) trips") }
        }
        await afterTrashChange()
        return r.error
    }

    func setPinned(_ id: Int, _ pinned: Bool) async {
        if let i = trips.firstIndex(where: { $0.id == id }) { withAnimation(.snappy) { trips[i].pinned = pinned } }
        let r = await send(pinned ? "PUT" : "DELETE", "/trips/\(id)/pin")
        if r.error != nil, let i = trips.firstIndex(where: { $0.id == id }) { trips[i].pinned = !pinned }
    }

    func afterTrashChange() async {
        await fetchTrips()
        await fetchJourneys()
        await fetchJourneySuggestions()
        await fetchFlights()
        await fetchRentals()
    }
}

// MARK: - Undo toast

@MainActor
final class TrashCenter: ObservableObject {
    static let shared = TrashCenter()
    struct Undo: Equatable { let ids: [Int]; let text: String; let token = UUID() }
    @Published var undo: Undo?

    func show(ids: [Int], text: String) {
        let u = Undo(ids: ids, text: text)
        withAnimation(.snappy) { undo = u }
        Task {
            try? await Task.sleep(for: .seconds(UserDefaults.standard.bool(forKey: "TrippyHoldToast") ? 60 : 6))
            if undo?.token == u.token { withAnimation(.snappy) { undo = nil } }
        }
    }
}

struct UndoToastHost: View {
    @ObservedObject var network: NetworkManager
    @ObservedObject private var center = TrashCenter.shared
    @State private var busy = false

    var body: some View {
        if let u = center.undo {
            HStack(spacing: 12) {
                Image(systemName: "trash.fill").foregroundStyle(Theme.red)
                VStack(alignment: .leading, spacing: 1) {
                    Text(u.text).type(.calloutStrong).foregroundStyle(.white).lineLimit(1)
                    Text("In Recently Deleted for 30 days").type(.caption).foregroundStyle(Theme.textSecondary)
                }
                Spacer(minLength: 8)
                Button {
                    busy = true
                    Task {
                        _ = await network.restoreTrips(u.ids)
                        Haptics.success()
                        busy = false
                        withAnimation(.snappy) { center.undo = nil }
                    }
                } label: {
                    Text("Undo").type(.calloutStrong).foregroundStyle(Theme.amber)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(Theme.amber.opacity(0.14), in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(busy)
            }
            .padding(.leading, 16).padding(.trailing, 10).padding(.vertical, 10)
            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.divider))
            .shadow(color: .black.opacity(0.5), radius: 18, y: 6)
            .padding(.horizontal, 14)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

// MARK: - Confirmation sheet

/// "Delete trip" for owners (with what goes with it), "Leave trip" for travelers.
struct DeleteTripSheet: View {
    @ObservedObject var network: NetworkManager
    let tripIds: [Int]
    var onDone: (Bool) -> Void = { _ in }
    @Environment(\.dismiss) private var dismiss
    @State private var previews: [ApiDeletePreview] = []
    @State private var loading = true
    @State private var working = false
    @State private var errorText: String?

    private var owned: [ApiDeletePreview] { previews.filter(\.is_owner) }
    private var notOwned: [ApiDeletePreview] { previews.filter { !$0.is_owner } }
    private var isLeave: Bool { tripIds.count == 1 && previews.first.map { !$0.is_owner } == true }
    private var counts: ApiTripCounts { owned.map(\.counts).reduce(ApiTripCounts(), +) }
    private var unsettled: [ApiDeletePreview] { (isLeave ? previews : owned).filter(\.unsettled) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    titleBlock
                    if loading {
                        ProgressView().frame(maxWidth: .infinity).padding(.vertical, 30)
                    } else if isLeave {
                        leaveBody
                    } else {
                        deleteBody
                    }
                    if let errorText { FormErrorBanner(message: errorText) }
                }
                .padding(.horizontal, Theme.pagePadding).padding(.top, 8).padding(.bottom, 20)
            }
            .safeAreaInset(edge: .bottom) { buttons }
            .trippyScreen()
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .task { await load() }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .preferredColorScheme(.dark)
    }

    private func load() async {
        var out: [ApiDeletePreview] = []
        for id in tripIds { if let p = await network.deletePreview(id) { out.append(p) } }
        previews = out
        loading = false
    }

    private var name: String {
        if let p = previews.first, tripIds.count == 1 { return "“\(p.title ?? "Trip")”" }
        return tripIds.count == 1 ? "this trip" : "\(owned.count) trips"
    }

    private var titleBlock: some View {
        HStack(spacing: 12) {
            Image(systemName: isLeave ? "rectangle.portrait.and.arrow.right" : "trash.fill")
                .type(.title3).foregroundStyle(Theme.red)
                .frame(width: 44, height: 44)
                .background(Theme.red.opacity(0.15), in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text(isLeave ? "Leave \(name)?" : "Delete \(name)?")
                    .type(.title3).foregroundStyle(.white).lineLimit(2)
                if !loading {
                    Text(isLeave ? "Only you leave. The trip stays for everyone else."
                                 : "Everything in \(owned.count > 1 ? "them" : "it") goes with \(owned.count > 1 ? "them" : "it").")
                        .type(.footnote).foregroundStyle(Theme.textSecondary)
                }
            }
        }
    }

    @ViewBuilder private var deleteBody: some View {
        countsGrid
        Text(counts.summary).type(.callout).foregroundStyle(Theme.textSecondary)
        if !unsettled.isEmpty { unsettledBanner }
        ForEach(owned.compactMap(\.journey).reduce(into: [Int: ApiDeletePreview.Journey]()) { $0[$1.id] = $1 }.values.sorted { $0.id < $1.id }, id: \.id) { j in
            FormErrorBanner(message: j.journey_deleted
                            ? "“\(j.title)” has no other trips, so the journey goes too."
                            : "Leaves the journey “\(j.title)”, which keeps its other trips.",
                            tint: Theme.purple, icon: "square.stack.3d.up.fill")
        }
        if !notOwned.isEmpty {
            FormErrorBanner(message: "\(notOwned.count) selected trip\(notOwned.count == 1 ? " belongs" : "s belong") to someone else and will be skipped.",
                            tint: Theme.textSecondary, icon: "person.2.fill")
        }
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "clock.arrow.circlepath").foregroundStyle(Theme.textSecondary)
            Text("Moves to Recently Deleted for \(previews.first?.keep_days ?? 30) days. Restore it any time from Profile → Recently Deleted.")
                .type(.footnote).foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 2)
    }

    @ViewBuilder private var leaveBody: some View {
        if !unsettled.isEmpty { unsettledBanner }
        Text("You'll stop seeing it in your trips, stats and stories. The owner can add you again.")
            .type(.callout).foregroundStyle(Theme.textSecondary)
    }

    private var unsettledBanner: some View {
        let cents = unsettled.map(\.unsettled_cents).reduce(0, +)
        let people = unsettled.map(\.unsettled_people).max() ?? 0
        return FormErrorBanner(
            message: isLeave
                ? "You still have an unsettled balance on this trip. Settle up first, or leave anyway."
                : "Balances aren't settled: \(people) people still owe or are owed \(Fmt.money(Double(cents) / 100)). Deleting removes those expenses too.",
            tint: Theme.amber)
    }

    private var countsGrid: some View {
        let items: [(String, Int, String, Color)] = [
            ("airplane", counts.flights, "Flights", Theme.blue),
            ("bed.double.fill", counts.stays, "Stays", Theme.stay),
            ("car.fill", counts.rentals, "Rentals", Theme.green),
            ("creditcard.fill", counts.expenses, "Expenses", Theme.amber),
        ]
        return HStack(spacing: 8) {
            ForEach(items, id: \.2) { icon, n, label, color in
                VStack(spacing: 4) {
                    Image(systemName: icon).foregroundStyle(color)
                    Text("\(n)").type(.number).foregroundStyle(n == 0 ? Theme.textTertiary : .white)
                    Text(label).type(.label).foregroundStyle(Theme.textSecondary)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
        }
    }

    private var buttons: some View {
        VStack(spacing: 8) {
            Button {
                Task { await act() }
            } label: {
                if working { ProgressView().tint(.white) }
                else { Text(isLeave ? "Leave trip" : owned.count > 1 ? "Delete \(owned.count) trips" : "Delete trip") }
            }
            .buttonStyle(PrimaryButtonStyle(tint: Theme.red))
            .disabled(loading || working || (!isLeave && owned.isEmpty))
            .opacity(loading || (!isLeave && owned.isEmpty) ? 0.5 : 1)
        }
        .padding(.horizontal, Theme.pagePadding).padding(.vertical, 10)
        .background(.ultraThinMaterial)
    }

    private func act() async {
        working = true
        defer { working = false }
        if isLeave {
            let r = await network.leaveTrip(tripIds[0], force: !unsettled.isEmpty)
            if let e = r.error { errorText = e; return }
            Haptics.success()
        } else {
            let r = await network.trashTrips(owned.map(\.trip_id))
            if let e = r.error { errorText = e; return }
        }
        onDone(true)
        dismiss()
    }
}

// MARK: - Recently Deleted (Profile)

struct RecentlyDeletedView: View {
    @ObservedObject var network: NetworkManager
    @State private var items: [ApiTrashTrip] = []
    @State private var loaded = false
    @State private var confirmPurge: ApiTrashTrip?
    @State private var confirmEmpty = false
    @State private var errorText: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s3) {
                Text("Deleted trips stay here for 30 days, then they're removed for good with their flights, stays, rentals and expenses.")
                    .type(.footnote).foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let errorText { FormErrorBanner(message: errorText) }
                if loaded && items.isEmpty {
                    EmptyStateCard(systemImage: "trash.slash", title: "Nothing here", message: "Trips you delete show up here so you can bring them back.")
                        .padding(.top, 8)
                }
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { idx, t in
                        if idx > 0 { Hairline() }
                        row(t)
                    }
                }
            }
            .padding(.horizontal, Theme.pagePadding + 4).padding(.vertical, 12)
        }
        .trippyScreen()
        .navigationTitle("Recently Deleted")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !items.isEmpty {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button { Task { await restore(items.map(\.id)) } } label: { Label("Restore all", systemImage: "arrow.uturn.backward") }
                        Button(role: .destructive) { confirmEmpty = true } label: { Label("Delete all now", systemImage: "trash") }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete “\(confirmPurge?.title ?? "trip")” now?",
                            isPresented: Binding(get: { confirmPurge != nil }, set: { if !$0 { confirmPurge = nil } }),
                            titleVisibility: .visible) {
            Button("Delete now", role: .destructive) {
                if let t = confirmPurge { Task { errorText = await network.purgeTrash(t.id); await load() } }
            }
        } message: {
            Text("\(confirmPurge?.counts.summary ?? "") will be removed for good. This can't be undone.")
        }
        .confirmationDialog("Delete \(items.count) trips now?", isPresented: $confirmEmpty, titleVisibility: .visible) {
            Button("Delete all now", role: .destructive) { Task { errorText = await network.purgeTrash(nil); await load() } }
        } message: { Text("This can't be undone.") }
    }

    private func load() async {
        items = await network.fetchTrash()
        loaded = true
    }

    private func restore(_ ids: [Int]) async {
        errorText = await network.restoreTrips(ids)
        if errorText == nil { Haptics.success() }
        await load()
    }

    private func row(_ t: ApiTrashTrip) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(t.title ?? "Trip").type(.headline).foregroundStyle(.white).lineLimit(1)
                Spacer()
                if let d = t.daysLeft {
                    Text(d == 0 ? "today" : "\(d) day\(d == 1 ? "" : "s") left")
                        .type(.label).foregroundStyle(d <= 3 ? Theme.red : Theme.textSecondary)
                }
            }
            Text([dateText(t), t.counts.summary].compactMap { $0 }.joined(separator: " · "))
                .type(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(2)
            HStack(spacing: 10) {
                Button { Task { await restore([t.id]) } } label: { Label("Restore", systemImage: "arrow.uturn.backward") }
                    .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                Button { confirmPurge = t } label: { Label("Delete Now", systemImage: "trash") }
                    .buttonStyle(TintedButtonStyle(tint: Theme.red))
            }
        }
        .padding(.vertical, 14)
    }

    private func dateText(_ t: ApiTrashTrip) -> String? {
        guard let s = Fmt.parse(t.start_date) else { return nil }
        let f = DateFormatter(); f.dateFormat = "MMM d, yyyy"
        return f.string(from: s)
    }
}

// MARK: - Journey delete choice

extension View {
    /// "Unlink trips (keep them)" (default) or "Delete journey and all its trips".
    func journeyDeleteDialog(_ journey: Binding<ApiJourney?>, network: NetworkManager,
                             onDone: @escaping () -> Void = {}) -> some View {
        confirmationDialog("Delete “\(journey.wrappedValue?.title ?? "journey")”?",
                           isPresented: Binding(get: { journey.wrappedValue != nil }, set: { if !$0 { journey.wrappedValue = nil } }),
                           titleVisibility: .visible, presenting: journey.wrappedValue) { j in
            Button("Unlink trips (keep them)") {
                Task { _ = await network.deleteJourney(j.id, deleteTrips: false); onDone() }
            }
            .keyboardShortcut(.defaultAction)
            Button("Delete journey and all \(j.trip_count) trips", role: .destructive) {
                Task { _ = await network.deleteJourney(j.id, deleteTrips: true); onDone() }
            }
            Button("Cancel", role: .cancel) {}
        } message: { j in
            Text("Unlinking keeps all \(j.trip_count) trips as separate trips. Deleting moves them to Recently Deleted for 30 days.")
        }
    }
}

// MARK: - Swipe actions

struct SwipeAction: Identifiable {
    let title: String
    let icon: String
    let tint: Color
    let action: () -> Void
    var id: String { title }
}

/// Which row is swiped open (one at a time). `-TrippySwipe "trip:12:trailing"` opens one on launch.
@MainActor
final class SwipeCoordinator: ObservableObject {
    static let shared = SwipeCoordinator()
    @Published var open: String? = {
        let raw = UserDefaults.standard.string(forKey: "TrippySwipe") ?? ""
        return raw.isEmpty ? nil : raw
    }()
}

/// Mail-style swipe actions for rows that live in a plain stack (not a List).
/// Leading actions read left→right with the first as the full swipe; trailing read left→right with the last as the full swipe.
struct SwipeRow<Content: View>: View {
    let key: String
    var leading: [SwipeAction] = []
    var trailing: [SwipeAction] = []
    @ViewBuilder var content: () -> Content

    @ObservedObject private var coordinator = SwipeCoordinator.shared
    @State private var offset: CGFloat = 0
    @State private var start: CGFloat = 0
    @State private var axis: Axis?
    @State private var armed = false
    @State private var width: CGFloat = 360

    private let button: CGFloat = 76
    private var fullSwipe: CGFloat { max(width * 0.62, 200) }

    var body: some View {
        ZStack {
            if offset > 0 { buttons(leading, edge: .leading) }
            if offset < 0 { buttons(trailing, edge: .trailing) }
            content()
                .offset(x: offset)
                .overlay {
                    if offset != 0 { Color.black.opacity(0.001).onTapGesture { close() } }
                }
        }
        .clipped()
        .background(GeometryReader { g in Color.clear.onAppear { width = g.size.width } })
        .simultaneousGesture(drag)
        .onAppear(perform: syncFromCoordinator)
        .onChange(of: coordinator.open) { _, _ in syncFromCoordinator() }
    }

    private func syncFromCoordinator() {
        guard let open = coordinator.open else { if offset != 0 { withAnimation(.snappy) { offset = 0 } }; return }
        if open == key + ":leading" { withAnimation(.snappy) { offset = button * CGFloat(leading.count) } }
        else if open == key + ":trailing" { withAnimation(.snappy) { offset = -button * CGFloat(trailing.count) } }
        else if !open.hasPrefix(key + ":"), offset != 0 { withAnimation(.snappy) { offset = 0 } }
    }

    private func close() {
        withAnimation(.snappy) { offset = 0 }
        if coordinator.open?.hasPrefix(key + ":") == true { coordinator.open = nil }
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 16)
            .onChanged { v in
                if axis == nil {
                    axis = abs(v.translation.width) > abs(v.translation.height) * 1.4 ? .horizontal : .vertical
                    start = offset
                }
                guard axis == .horizontal else { return }
                var x = start + v.translation.width
                if leading.isEmpty { x = min(0, x) }
                if trailing.isEmpty { x = max(0, x) }
                offset = x
                let past = abs(x) > fullSwipe
                if past != armed {
                    armed = past
                    if past { Haptics.impact(.medium) } else { Haptics.tap() }
                }
            }
            .onEnded { v in
                defer { axis = nil; armed = false }
                guard axis == .horizontal else { return }
                let x = offset + (v.predictedEndTranslation.width - v.translation.width) * 0.15
                if armed, x < 0, let a = trailing.last { fire(a) }
                else if armed, x > 0, let a = leading.first { fire(a) }
                else if x < -button * 0.6 {
                    withAnimation(.snappy) { offset = -button * CGFloat(trailing.count) }
                    coordinator.open = key + ":trailing"
                } else if x > button * 0.6 {
                    withAnimation(.snappy) { offset = button * CGFloat(leading.count) }
                    coordinator.open = key + ":leading"
                } else { close() }
            }
    }

    private func fire(_ a: SwipeAction) {
        close()
        a.action()
    }

    private func buttons(_ actions: [SwipeAction], edge: HorizontalEdge) -> some View {
        let revealed = abs(offset)
        let full = armed
        return HStack(spacing: 0) {
            if edge == .trailing { Spacer(minLength: 0) }
            HStack(spacing: 0) {
                ForEach(actions) { a in
                    let isFull = full && (edge == .trailing ? a.id == actions.last?.id : a.id == actions.first?.id)
                    Button { fire(a) } label: {
                        VStack(spacing: 4) {
                            Image(systemName: a.icon).font(.system(size: 18, weight: .semibold))
                            Text(a.title).type(.label).lineLimit(1).minimumScaleFactor(0.7)
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(a.tint)
                    }
                    .buttonStyle(.plain)
                    .frame(width: full ? (isFull ? revealed : 0) : revealed / CGFloat(max(actions.count, 1)))
                    .clipped()
                }
            }
            .frame(width: revealed)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .animation(.snappy(duration: 0.2), value: full)
            if edge == .leading { Spacer(minLength: 0) }
        }
        .padding(.vertical, 4)
    }
}
