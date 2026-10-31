import SwiftUI

// MARK: - Ledger DTOs (app/money.py)

struct ApiLedgerPerson: Decodable, Identifiable {
    var user_id: Int
    var name: String
    var paid_cents: Int
    var share_cents: Int
    var net_cents: Int
    var id: Int { user_id }
}

struct ApiBreakdown: Decodable, Hashable {
    var source: String
    var amount_cents: Int
}

/// One "from owes to" line, in either the pairwise or the simplified view.
struct ApiDebt: Decodable, Identifiable, Hashable {
    var from_user_id: Int
    var from_username: String
    var to_user_id: Int
    var to_username: String
    var amount_cents: Int
    var breakdown: [ApiBreakdown]?
    var id: String { "\(from_user_id)>\(to_user_id)" }
}

struct ApiSettlement: Decodable, Identifiable {
    var id: Int
    var from_user_id: Int
    var to_user_id: Int
    var amount_cents: Int
    var trip_id: Int?
    var group_id: Int?
    var note: String?
    var created_at: String?
}

struct ApiStandaloneSplit: Decodable, Hashable {
    var user_id: Int
    var amount_cents: Int
}

struct ApiStandalone: Decodable, Identifiable {
    var id: Int
    var description: String
    var payer_id: Int?
    var amount_cents: Int
    var split_mode: String?
    var splits: [ApiStandaloneSplit]
}

struct ApiGroupTrip: Decodable, Identifiable, Hashable {
    var id: Int
    var title: String
}

struct ApiLedger: Decodable {
    var total_cents: Int
    var people: [ApiLedgerPerson]
    var pairwise: [ApiDebt]
    var simplified: [ApiDebt]
    var settlements: [ApiSettlement]
    var trip_id: Int?
    var group_id: Int?
    var name: String?
    var trips: [ApiGroupTrip]?
    var standalone: [ApiStandalone]?

    func debts(_ mode: LedgerMode) -> [ApiDebt] { mode == .simplified ? simplified : pairwise }
    func name(_ id: Int) -> String { people.first { $0.user_id == id }?.name ?? "User \(id)" }
}

struct ApiGroup: Decodable, Identifiable {
    var id: Int
    var name: String
    var members: [ApiParticipant]
    var trips: [ApiGroupTrip]

    enum CodingKeys: String, CodingKey { case id, name, members, trips }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        members = (try? c.decode([ApiParticipant].self, forKey: .members)) ?? []
        trips = (try? c.decode([ApiGroupTrip].self, forKey: .trips)) ?? []
    }
}

enum LedgerMode: String, CaseIterable, Identifiable {
    case simplified, pairwise
    var id: String { rawValue }
    var label: String { self == .simplified ? "Simplified" : "Pairwise" }
}

enum SplitMode: String, CaseIterable, Identifiable {
    case equal, exact, percent, shares
    var id: String { rawValue }
    var label: String {
        switch self {
        case .equal: "Equally"
        case .exact: "Exact $"
        case .percent: "Percent"
        case .shares: "Shares"
        }
    }
}

/// Where an expense lives: on a trip, or directly on a group (standalone).
enum SplitScope: Hashable {
    case trip(Int)
    case group(Int)

    var path: String {
        switch self {
        case .trip(let id): "/trips/\(id)"
        case .group(let id): "/groups/\(id)"
        }
    }
}

struct IntRef: Identifiable, Hashable { let id: Int }

// MARK: - Money in integer cents

enum Cents {
    static func format(_ cents: Int, _ currency: String? = "USD") -> String {
        Fmt.money(Double(cents) / 100, currency)
    }

    /// "12.345" → 1235 (half up), matching the backend's `to_cents`.
    static func parse(_ text: String) -> Int? {
        let t = text.trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: "$", with: "")
            .replacingOccurrences(of: ",", with: ".")
        guard !t.isEmpty, var d = Decimal(string: t) else { return nil }
        d *= 100
        var r = Decimal()
        NSDecimalRound(&r, &d, 0, .plain)
        return NSDecimalNumber(decimal: r).intValue
    }

    /// Largest-remainder allocation; earlier entries win ties (the payer goes first).
    static func allocate(_ total: Int, _ weights: [(Int, Double)]) -> [Int: Int] {
        let sum = weights.reduce(0) { $0 + $1.1 }
        guard sum > 0 else { return [:] }
        var out: [Int: Int] = [:]
        var rema: [(Int, Double, Int)] = []
        for (i, (id, w)) in weights.enumerated() {
            let exact = Double(total) * w / sum
            out[id] = Int(exact.rounded(.down))
            rema.append((id, exact - exact.rounded(.down), i))
        }
        var left = total - out.values.reduce(0, +)
        for (id, _, _) in rema.sorted(by: { $0.1 != $1.1 ? $0.1 > $1.1 : $0.2 < $1.2 }) where left > 0 {
            out[id, default: 0] += 1
            left -= 1
        }
        return out
    }
}

// MARK: - Network

extension NetworkManager {
    func loadUsers() async {
        let list = await fetchUsers()
        if !list.isEmpty { users = list }
    }

    func person(_ id: Int?, fallback: String? = nil) -> ApiParticipant? {
        guard let id else { return nil }
        if let u = users.first(where: { $0.id == id }) { return u }
        for t in trips { if let p = t.participants.first(where: { $0.id == id }) { return p } }
        for g in groups { if let p = g.members.first(where: { $0.id == id }) { return p } }
        return ApiParticipant(id: id, username: fallback ?? "User \(id)")
    }

    /// The trip's owner first, then its travelers: everyone who can pay or share.
    func people(forTrip trip: ApiTrip) -> [ApiParticipant] {
        var out: [ApiParticipant] = []
        if let owner = person(trip.owner_id) { out.append(owner) }
        for p in trip.participants where !out.contains(where: { $0.id == p.id }) { out.append(p) }
        return out
    }

    func people(for scope: SplitScope) -> [ApiParticipant] {
        switch scope {
        case .trip(let id): trips.first { $0.id == id }.map { people(forTrip: $0) } ?? []
        case .group(let id): groups.first { $0.id == id }?.members ?? []
        }
    }

    func scopeName(_ scope: SplitScope) -> String {
        switch scope {
        case .trip(let id): trips.first { $0.id == id }?.displayTitle ?? "Trip \(id)"
        case .group(let id): groups.first { $0.id == id }?.name ?? "Group \(id)"
        }
    }

    func fetchLedger(_ scope: SplitScope) async -> ApiLedger? {
        let path: String
        switch scope {
        case .trip(let id): path = "/trips/\(id)/ledger"
        case .group(let id): path = "/groups/\(id)/balances"
        }
        let r = await send("GET", path)
        guard r.error == nil, let data = r.data else { return nil }
        do { return try JSONDecoder().decode(ApiLedger.self, from: data) } catch {
            print("Ledger decode failed: \(error)")
            return nil
        }
    }

    /// Re-pulls everything that money changes touch.
    func refreshMoney() async {
        await fetchTrips()
        await fetchExpenses()
        await fetchGroups()
    }

    func saveExpense(scope: SplitScope?, editing: Int?, body: [String: Any]) async -> String? {
        let r: (data: Data?, status: Int, error: String?)
        if let editing {
            r = await send("PUT", "/expenses/\(editing)", json: body)
        } else if let scope {
            switch scope {
            case .trip(let id): r = await send("POST", "/trips/\(id)/expenses/split", json: body)
            case .group(let id): r = await send("POST", "/groups/\(id)/expenses", json: body)
            }
        } else {
            return "Pick a trip or group first."
        }
        if r.error == nil { await refreshMoney() }
        return r.error
    }

    func deleteExpense(id: Int) async -> String? {
        let r = await send("DELETE", "/expenses/\(id)")
        if r.error == nil { await refreshMoney() }
        return r.error
    }

    func settle(_ scope: SplitScope, from: Int, to: Int, amountCents: Int? = nil, mode: LedgerMode) async -> String? {
        var body: [String: Any] = ["from_user_id": from, "to_user_id": to, "mode": mode.rawValue]
        if let amountCents { body["amount"] = Double(amountCents) / 100 }
        return await send("POST", scope.path + "/settle", json: body).error
    }

    func settleAll(_ scope: SplitScope) async -> String? {
        await send("POST", scope.path + "/settle-all").error
    }

    func undoSettlement(id: Int) async -> String? {
        await send("DELETE", "/settlements/\(id)").error
    }

    func fetchGroups() async {
        let r = await send("GET", "/groups")
        guard r.error == nil, let data = r.data,
              let list = try? JSONDecoder().decode([ApiGroup].self, from: data) else { return }
        groups = list
    }

    func createGroup(name: String, memberIds: [Int], tripIds: [Int]) async -> (ApiGroup?, String?) {
        let r = await send("POST", "/groups", json: ["name": name, "member_ids": memberIds, "trip_ids": tripIds])
        let g = r.data.flatMap { try? JSONDecoder().decode(ApiGroup.self, from: $0) }
        if r.error == nil { await fetchGroups(); await fetchTrips() }
        return (g, r.error)
    }

    func groupFromTrip(_ tripId: Int) async -> (ApiGroup?, String?) {
        let r = await send("POST", "/trips/\(tripId)/group", json: [:])
        let g = r.data.flatMap { try? JSONDecoder().decode(ApiGroup.self, from: $0) }
        if r.error == nil { await fetchGroups(); await fetchTrips() }
        return (g, r.error)
    }

    func addDebt(groupId: Int, from: Int, to: Int, amountCents: Int, description: String) async -> String? {
        let r = await send("POST", "/groups/\(groupId)/debts",
                           json: ["from_user_id": from, "to_user_id": to,
                                  "amount": Double(amountCents) / 100, "description": description])
        if r.error == nil { await refreshMoney() }
        return r.error
    }
}

// MARK: - Shared bits

struct MoneyLabel: View {
    let text: String
    var body: some View {
        Text(text.uppercased()).type(.label).tracking(0.5)
            .foregroundStyle(Theme.textSecondary)
    }
}

struct PersonChips: View {
    let people: [ApiParticipant]
    var selected: (Int) -> Bool
    var tint: Color = Theme.blue
    var tap: (Int) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(people) { p in
                    Button { tap(p.id) } label: {
                        HStack(spacing: 8) {
                            TravelerAvatar(person: p, size: 26)
                            Text(p.firstName).type(.calloutStrong)
                        }
                        .foregroundStyle(.white)
                        .padding(.leading, 5).padding(.trailing, 12).padding(.vertical, 5)
                        .background(selected(p.id) ? tint : Theme.surfaceRaised, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

struct Segmented<T: Hashable & Identifiable>: View {
    let options: [T]
    @Binding var selection: T
    let label: (T) -> String

    var body: some View {
        HStack(spacing: 2) {
            ForEach(options) { o in
                Button { withAnimation(.snappy(duration: 0.2)) { selection = o } } label: {
                    Text(label(o))
                        .type(.footnoteStrong)
                        .foregroundStyle(selection == o ? .white : Theme.textSecondary)
                        .frame(maxWidth: .infinity).padding(.vertical, 7)
                        .background(selection == o ? Theme.surfaceHigh : .clear,
                                    in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

// MARK: - Split expense sheet (add + edit + delete)

struct SplitExpenseSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var network: NetworkManager
    let editing: ApiExpense?
    var onDone: () -> Void

    @State private var scope: SplitScope?
    @State private var amountText = ""
    @State private var description = ""
    @State private var payerId: Int?
    @State private var mode: SplitMode = .equal
    @State private var included: Set<Int> = []
    @State private var values: [Int: String] = [:]
    @State private var isSaving = false
    @State private var error: String?
    @State private var confirmDelete = false
    @State private var didSetup = false
    @State private var moving = false

    /// Launch-argument prefill (screenshots / UI tests) is applied to the first sheet only.
    private static var hookConsumed = false

    init(network: NetworkManager, scope: SplitScope?, editing: ApiExpense? = nil, onDone: @escaping () -> Void = {}) {
        self.network = network
        self.editing = editing
        self.onDone = onDone
        var s = scope
        if let e = editing {
            if let t = e.trip_id { s = .trip(t) } else if let g = e.group_id { s = .group(g) }
        }
        _scope = State(initialValue: s)
    }

    private var people: [ApiParticipant] { scope.map { network.people(for: $0) } ?? [] }
    private var totalCents: Int? { Cents.parse(amountText).flatMap { $0 > 0 ? $0 : nil } }
    /// Included people in display order with the payer first (who absorbs the odd cent).
    private var ordered: [Int] {
        let ids = people.map(\.id).filter { included.contains($0) }
        guard let payerId, ids.contains(payerId) else { return ids }
        return [payerId] + ids.filter { $0 != payerId }
    }
    private func number(_ id: Int) -> Double? {
        Double((values[id] ?? "").replacingOccurrences(of: ",", with: ".").trimmingCharacters(in: .whitespaces))
    }

    private var preview: [Int: Int] {
        guard let total = totalCents, !ordered.isEmpty else { return [:] }
        switch mode {
        case .equal: return Cents.allocate(total, ordered.map { ($0, 1) })
        case .exact:
            var out: [Int: Int] = [:]
            for id in ordered { out[id] = Cents.parse(values[id] ?? "") ?? 0 }
            return out
        case .percent:
            let ws = ordered.map { ($0, max(number($0) ?? 0, 0)) }
            let sum = ws.reduce(0) { $0 + $1.1 }
            if abs(sum - 100) < 0.0001 { return Cents.allocate(total, ws) }
            var out: [Int: Int] = [:]
            for (id, w) in ws { out[id] = Int((Double(total) * w / 100).rounded()) }
            return out
        case .shares:
            return Cents.allocate(total, ordered.map { ($0, max(number($0) ?? 0, 0)) })
        }
    }

    /// (text, isOK) for the live "left to assign" line.
    private var status: (String, Bool)? {
        guard let total = totalCents, !ordered.isEmpty else { return nil }
        switch mode {
        case .equal, .shares:
            let sum = preview.values.reduce(0, +)
            if mode == .shares && sum == 0 { return ("Give at least one person a share", false) }
            return ("Adds up to \(Cents.format(sum)) of \(Cents.format(total))", sum == total)
        case .exact:
            let left = total - preview.values.reduce(0, +)
            if left == 0 { return ("All \(Cents.format(total)) assigned", true) }
            return left > 0 ? ("\(Cents.format(left)) left to assign", false) : ("Over by \(Cents.format(-left))", false)
        case .percent:
            let sum = ordered.reduce(0) { $0 + (number($1) ?? 0) }
            let left = 100 - sum
            if abs(left) < 0.0001 { return ("100% assigned", true) }
            return left > 0 ? ("\(Fmt.number2(left))% left to assign", false) : ("Over by \(Fmt.number2(-left))%", false)
        }
    }

    private var canSave: Bool {
        scope != nil && totalCents != nil && payerId != nil && !ordered.isEmpty
            && !description.trimmingCharacters(in: .whitespaces).isEmpty && (status?.1 ?? false) && !isSaving
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if editing == nil { scopePicker }
                    amountField
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Description")
                        TextField("", text: $description, prompt: Text("What's this for?").foregroundStyle(Theme.textTertiary))
                            .foregroundStyle(.white)
                            .padding(14)
                            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    if !people.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            MoneyLabel(text: "Paid by")
                            PersonChips(people: people, selected: { payerId == $0 }) { payerId = $0 }
                        }
                        splitSection
                    }
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .type(.footnote).foregroundStyle(Theme.red)
                    }
                    if let e = editing, e.trip_id != nil {
                        Button { moving = true } label: {
                            Label("Move to trip…", systemImage: "arrow.right.doc.on.clipboard")
                                .type(.calloutStrong)
                                .frame(maxWidth: .infinity).padding(.vertical, 13)
                                .foregroundStyle(Theme.blue)
                                .background(Theme.blue.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                    if editing != nil {
                        Button(role: .destructive) { confirmDelete = true } label: {
                            Label("Delete expense", systemImage: "trash")
                                .type(.calloutStrong)
                                .frame(maxWidth: .infinity).padding(.vertical, 13)
                                .foregroundStyle(Theme.red)
                                .background(Theme.red.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(Theme.pagePadding)
            }
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle(editing == nil ? "Split Expense" : "Edit Expense")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") { Task { await save() } }
                        .fontWeight(.bold).disabled(!canSave)
                }
            }
            .confirmationDialog("Delete this expense?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await performDelete() } }
            } message: {
                Text("Balances are recalculated. Recorded payments are kept.")
            }
            .task { await setup() }
            .onChange(of: scope) { _, _ in resetPeople() }
            .sheet(isPresented: $moving) {
                if let e = editing {
                    MoveToTripSheet(network: network, items: [ItemRef(kind: .expense, id: e.id)], fromTrip: e.trip_id) { err in
                        if let err { error = err } else { onDone(); dismiss() }
                    }
                }
            }
        }
        .presentationDetents([.large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private var scopePicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            MoneyLabel(text: "Trip or group")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(network.trips) { t in scopeChip(.trip(t.id), t.displayTitle, "airplane") }
                    ForEach(network.groups) { g in scopeChip(.group(g.id), g.name, "person.3.fill") }
                }
            }
        }
    }

    private func scopeChip(_ s: SplitScope, _ title: String, _ icon: String) -> some View {
        Button { scope = s } label: {
            Label(title, systemImage: icon)
                .type(.calloutStrong).lineLimit(1)
                .foregroundStyle(.white)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(scope == s ? Theme.blue : Theme.surfaceRaised, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private var amountField: some View {
        VStack(alignment: .leading, spacing: 8) {
            MoneyLabel(text: "Amount")
            HStack(spacing: 4) {
                Text("$").type(.largeTitle).foregroundStyle(Theme.green.opacity(0.7))
                TextField("", text: $amountText, prompt: Text("0.00").foregroundStyle(Theme.textTertiary))
                    .keyboardType(.decimalPad)
                    .type(.code).monospacedDigit()
                    .foregroundStyle(Theme.green)
            }
            .padding(14)
            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }

    private var splitSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            MoneyLabel(text: "Split")
            Segmented(options: SplitMode.allCases, selection: $mode) { $0.label }
            VStack(spacing: 0) {
                ForEach(Array(people.enumerated()), id: \.element.id) { idx, p in
                    if idx > 0 { Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.leading, 56) }
                    personRow(p)
                }
            }
            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            if let status {
                Label(status.0, systemImage: status.1 ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                    .type(.footnoteStrong).monospacedDigit()
                    .foregroundStyle(status.1 ? Theme.green : Theme.amber)
            }
        }
    }

    private func personRow(_ p: ApiParticipant) -> some View {
        let on = included.contains(p.id)
        return HStack(spacing: 12) {
            Button {
                if on { included.remove(p.id) } else { included.insert(p.id) }
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: on ? "checkmark.circle.fill" : "circle")
                        .type(.title3).foregroundStyle(on ? Theme.blue : Theme.textTertiary)
                    TravelerAvatar(person: p, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(p.firstName).type(.calloutStrong).foregroundStyle(on ? .white : Theme.textSecondary)
                            .lineLimit(1).minimumScaleFactor(0.8).fixedSize(horizontal: true, vertical: false)
                        if p.id == payerId {
                            Text("paid").type(.label).foregroundStyle(Theme.green)
                        }
                    }
                }
            }
            .buttonStyle(.plain)
            Spacer(minLength: 6)
            if on {
                if mode == .equal {
                    Text(Cents.format(preview[p.id] ?? 0)).type(.calloutStrong).monospacedDigit()
                        .foregroundStyle(.white)
                } else {
                    if mode != .exact, let c = preview[p.id], totalCents != nil {
                        Text(Cents.format(c)).type(.caption).monospacedDigit()
                            .foregroundStyle(Theme.textSecondary)
                    }
                    valueField(p.id)
                }
            }
        }
        .padding(.horizontal, 12).frame(minHeight: 52)
    }

    private func valueField(_ id: Int) -> some View {
        HStack(spacing: 2) {
            if mode == .exact { Text("$").foregroundStyle(Theme.textSecondary) }
            TextField("", text: Binding(get: { values[id] ?? "" }, set: { values[id] = $0 }),
                      prompt: Text(mode == .shares ? "1" : "0").foregroundStyle(Theme.textTertiary))
                .keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                .foregroundStyle(.white).monospacedDigit()
                .frame(width: mode == .exact ? 74 : 44)
            if mode == .percent { Text("%").foregroundStyle(Theme.textSecondary) }
            if mode == .shares { Text("×").foregroundStyle(Theme.textSecondary) }
        }
        .type(.calloutStrong)
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(Theme.surfaceHigh, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    // MARK: Lifecycle

    private func setup() async {
        guard !didSetup else { return }
        didSetup = true
        if network.users.isEmpty { await network.loadUsers() }
        if network.groups.isEmpty { await network.fetchGroups() }
        if let e = editing {
            amountText = String(format: "%.2f", Double(e.cents) / 100)
            description = e.description
            payerId = e.payer_id
            mode = SplitMode(rawValue: e.split_mode ?? "equal") ?? .equal
            included = Set(e.splits.map(\.user_id))
            for s in e.splits {
                switch mode {
                case .exact: values[s.user_id] = String(format: "%.2f", Double(s.cents) / 100)
                case .percent, .shares: values[s.user_id] = s.share.map(Fmt.number2) ?? ""
                case .equal: break
                }
            }
        } else {
            resetPeople()
        }
        await applyLaunchHooks()
    }

    private func resetPeople() {
        guard editing == nil else { return }
        included = Set(people.map(\.id))
        if payerId == nil || !people.contains(where: { $0.id == payerId }) { payerId = people.first?.id }
    }

    /// `-TrippySplitAmount 100 -TrippySplitMode exact -TrippySplitValues "3:10,4:15"
    ///  -TrippySplitPayer 3 -TrippySplitDesc Taxi -TrippySplitAutoSave 1 -TrippySplitAutoDelete 1`
    private func applyLaunchHooks() async {
        let d = UserDefaults.standard
        guard !Self.hookConsumed, d.object(forKey: "TrippyShowSplit") != nil || d.object(forKey: "TrippyEditExpense") != nil else { return }
        Self.hookConsumed = true
        if let t = d.string(forKey: "TrippySplitTrip").flatMap(Int.init), editing == nil { scope = .trip(t); resetPeople() }
        if let a = d.string(forKey: "TrippySplitAmount") { amountText = a }
        if let s = d.string(forKey: "TrippySplitDesc") { description = s }
        if let m = d.string(forKey: "TrippySplitMode").flatMap(SplitMode.init) { mode = m }
        if let p = d.string(forKey: "TrippySplitPayer").flatMap(Int.init) { payerId = p }
        if let v = d.string(forKey: "TrippySplitValues") {
            var ids: Set<Int> = []
            for pair in v.split(separator: ",") {
                let kv = pair.split(separator: ":")
                if kv.count == 2, let id = Int(kv[0]) { values[id] = String(kv[1]); ids.insert(id) }
            }
            if !ids.isEmpty { included = ids }
        }
        if d.bool(forKey: "TrippySplitAutoSave") {
            try? await Task.sleep(for: .seconds(1.5))
            await save(dismissAfter: false)
        }
        if d.bool(forKey: "TrippySplitAutoDelete") {
            try? await Task.sleep(for: .seconds(1.5))
            confirmDelete = true
        }
    }

    private func save(dismissAfter: Bool = true) async {
        guard let total = totalCents, let payerId else { return }
        if !(status?.1 ?? false) { error = status?.0; return }
        isSaving = true
        error = nil
        var body: [String: Any] = [
            "amount": Double(total) / 100,
            "description": description.trimmingCharacters(in: .whitespaces),
            "payer_id": payerId,
            "split_mode": mode.rawValue,
            "split_among": ordered,
        ]
        if mode != .equal {
            body["splits"] = ordered.map { id -> [String: Any] in
                let v: Double = mode == .exact ? Double(Cents.parse(values[id] ?? "") ?? 0) / 100 : (number(id) ?? 0)
                return ["user_id": id, "value": v]
            }
        }
        let err = await network.saveExpense(scope: scope, editing: editing?.id, body: body)
        isSaving = false
        if let err { error = err; return }
        onDone()
        if dismissAfter { dismiss() }
    }

    private func performDelete() async {
        guard let e = editing else { return }
        if let err = await network.deleteExpense(id: e.id) { error = err; return }
        onDone()
        dismiss()
    }
}

extension Fmt {
    /// 33.5 → "33.5", 25 → "25".
    static func number2(_ v: Double) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.usesGroupingSeparator = false
        f.maximumFractionDigits = 2
        return f.string(from: NSNumber(value: v)) ?? "\(v)"
    }
}

// MARK: - Balances panel (trip + group)

struct BalancesPanel: View {
    @ObservedObject var network: NetworkManager
    let ledger: ApiLedger
    @Binding var mode: LedgerMode
    var showBreakdown = false
    var onSettle: (ApiDebt) -> Void
    var onSettleAll: () -> Void

    private func avatar(_ id: Int, _ name: String) -> ApiParticipant {
        network.person(id, fallback: name) ?? ApiParticipant(id: id, username: name)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(spacing: 0) {
                ForEach(Array(ledger.people.enumerated()), id: \.element.id) { idx, p in
                    if idx > 0 { Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.leading, 50) }
                    netRow(p)
                }
            }

            let debts = ledger.debts(mode)
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    MoneyLabel(text: mode == .simplified ? "Suggested payments" : "Who owes whom")
                    Spacer()
                    Text("\(ledger.simplified.count) vs \(ledger.pairwise.count)")
                        .type(.label).monospacedDigit()
                        .foregroundStyle(Theme.textTertiary)
                }
                Segmented(options: LedgerMode.allCases, selection: $mode) { m in
                    "\(m.label) · \(ledger.debts(m).count)"
                }
                if debts.isEmpty {
                    Label(ledger.total_cents > 0 ? "All settled up" : "Nothing to split yet",
                          systemImage: ledger.total_cents > 0 ? "checkmark.circle.fill" : "circle.dashed")
                        .type(.calloutStrong)
                        .foregroundStyle(ledger.total_cents > 0 ? Theme.green : Theme.textSecondary)
                        .padding(.vertical, 4)
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(debts.enumerated()), id: \.element.id) { idx, d in
                            if idx > 0 { Hairline(leading: 66) }
                            debtRow(d)
                        }
                    }
                    if debts.count > 1 || mode == .pairwise {
                        Button(action: onSettleAll) {
                            Label(mode == .pairwise
                                ? "Settle all in \(ledger.simplified.count) payment\(ledger.simplified.count == 1 ? "" : "s") (simplified)"
                                : "Settle all · \(ledger.simplified.count) payment\(ledger.simplified.count == 1 ? "" : "s")",
                                  systemImage: "checkmark.seal.fill")
                                .type(.calloutStrong)
                                .frame(maxWidth: .infinity).padding(.vertical, 12)
                                .foregroundStyle(Theme.green)
                                .background(Theme.green.opacity(0.14), in: Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            if !ledger.settlements.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    MoneyLabel(text: "Payments recorded")
                    ForEach(ledger.settlements.prefix(4)) { s in
                        HStack(spacing: 8) {
                            Image(systemName: "arrow.right.circle.fill").foregroundStyle(Theme.green)
                            Text("\(firstName(ledger.name(s.from_user_id))) paid \(firstName(ledger.name(s.to_user_id)))")
                                .type(.callout).foregroundStyle(.white)
                            Spacer()
                            Text(Cents.format(s.amount_cents)).type(.calloutStrong).monospacedDigit()
                                .foregroundStyle(Theme.textSecondary)
                        }
                    }
                }
            }
        }
        .sensoryFeedback(.success, trigger: ledger.settlements.count)
    }

    private func firstName(_ s: String) -> String { s.split(separator: " ").first.map(String.init) ?? s }

    private func netRow(_ p: ApiLedgerPerson) -> some View {
        HStack(spacing: 12) {
            TravelerAvatar(person: avatar(p.user_id, p.name), size: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text(p.name).type(.calloutStrong).foregroundStyle(.white).lineLimit(1)
                Text("paid \(Cents.format(p.paid_cents)) · share \(Cents.format(p.share_cents))")
                    .type(.caption).monospacedDigit().foregroundStyle(Theme.textSecondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 1) {
                if p.net_cents == 0 {
                    Label("settled", systemImage: "checkmark").type(.footnoteStrong)
                        .foregroundStyle(Theme.textSecondary)
                } else {
                    Text(p.net_cents > 0 ? "gets back" : "owes")
                        .type(.label).foregroundStyle(Theme.textSecondary)
                    Text(Cents.format(abs(p.net_cents)))
                        .type(.number)
                        .contentTransition(.numericText())
                        .foregroundStyle(p.net_cents > 0 ? Theme.green : Theme.red)
                }
            }
        }
        .padding(.vertical, 8)
    }

    private func debtRow(_ d: ApiDebt) -> some View {
        HStack(spacing: 10) {
            HStack(spacing: -8) {
                TravelerAvatar(person: avatar(d.from_user_id, d.from_username), size: 32)
                TravelerAvatar(person: avatar(d.to_user_id, d.to_username), size: 32)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("\(firstName(d.from_username)) → \(firstName(d.to_username))")
                    .type(.calloutStrong).foregroundStyle(.white).lineLimit(1)
                if showBreakdown, let parts = d.breakdown, !parts.isEmpty {
                    ForEach(Array(parts.enumerated()), id: \.offset) { _, b in
                        Text("\(b.source) · \(Cents.format(b.amount_cents))")
                            .type(.caption).monospacedDigit().foregroundStyle(Theme.textSecondary).lineLimit(1)
                    }
                }
            }
            .layoutPriority(1)
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 6) {
                Text(Cents.format(d.amount_cents))
                    .type(.numberSmall).foregroundStyle(.white)
                Button("Settle") { onSettle(d) }
                    .type(.footnoteStrong)
                    .foregroundStyle(Theme.green)
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(Theme.green.opacity(0.16), in: Capsule())
                    .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 10)
    }
}

// MARK: - Trip expenses card (trip detail)

struct TripExpensesCard: View {
    @ObservedObject var network: NetworkManager
    let trip: ApiTrip
    let snapshot: TripSnapshot
    let ledger: ApiLedger?
    @Binding var mode: LedgerMode
    var onAdd: () -> Void
    var onEdit: (ApiExpense) -> Void
    var onSettle: (ApiDebt) -> Void
    var onSettleAll: () -> Void
    var onGroup: () -> Void
    /// Screenshot aid (-TrippyFocusBalances): skip the expense rows so balances fit on screen.
    var hideList = false

    private var groupName: String? {
        trip.group_id.map { id in network.groups.first { $0.id == id }?.name ?? "Group \(id)" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    MoneyLabel(text: trip.expenses.isEmpty ? "No expenses logged" : "Total spent")
                    Text(trip.expenses.isEmpty ? Fmt.money(snapshot.spend.amount, decimals: false)
                                               : Cents.format(trip.expenses.reduce(0) { $0 + $1.cents }))
                        .type(.heroSmall)
                        .foregroundStyle(.white)
                        .contentTransition(.numericText())
                    if trip.expenses.isEmpty && snapshot.spend.amount > 0 {
                        Text("Booked rental & flight cost").type(.caption).foregroundStyle(Theme.textSecondary)
                    }
                }
                Spacer()
                Button(action: onAdd) {
                    Label("Split", systemImage: "plus")
                        .type(.calloutStrong)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(Theme.surfaceRaised, in: Capsule())
                }
                .buttonStyle(.plain)
            }

            if !trip.expenses.isEmpty && !hideList {
                VStack(spacing: 0) {
                    Hairline()
                    ForEach(Array(trip.expenses.sorted { $0.id > $1.id }.enumerated()), id: \.element.id) { idx, e in
                        if idx > 0 { Hairline() }
                        Button { onEdit(e) } label: { ExpenseLine(network: network, expense: e, showScope: false) }
                            .buttonStyle(.plain)
                    }
                    Hairline()
                }
            }

            if let ledger, !ledger.people.isEmpty, ledger.total_cents > 0 {
                MoneyLabel(text: "Balances").padding(.top, Theme.s2)
                BalancesPanel(network: network, ledger: ledger, mode: $mode, onSettle: onSettle, onSettleAll: onSettleAll)
            }

            Button(action: onGroup) {
                HStack(spacing: 10) {
                    Image(systemName: "person.3.fill").symbolRenderingMode(.hierarchical).foregroundStyle(.white)
                        .frame(width: 32, height: 32)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(groupName.map { "Group: \($0)" } ?? "Create group from travelers")
                            .type(.calloutStrong).foregroundStyle(.white)
                        Text(groupName == nil ? "Combine balances with other trips and IOUs"
                                              : "Combined balances across trips and IOUs")
                            .type(.caption).foregroundStyle(Theme.textSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").type(.footnoteStrong).foregroundStyle(Theme.textTertiary)
                }
                .padding(.vertical, Theme.s3)
                .overlay(alignment: .top) { Hairline() }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }
}

/// One expense: description, who paid, how it was split, amount.
struct ExpenseLine: View {
    @ObservedObject var network: NetworkManager
    let expense: ApiExpense
    var showScope = true

    private var subtitle: String {
        var parts: [String] = []
        let payer = network.person(expense.payer_id)?.firstName ?? "Someone"
        parts.append("\(payer) paid")
        if showScope {
            if let t = expense.trip_id { parts.append(network.scopeName(.trip(t))) }
            else if let g = expense.group_id { parts.append(network.scopeName(.group(g))) }
        }
        if !expense.splits.isEmpty {
            let mode = expense.split_mode ?? "equal"
            if expense.splits.count == 1, let only = expense.splits.first {
                parts.append("for \(network.person(only.user_id)?.firstName ?? "1 person")")
            } else {
                parts.append(mode == "equal" ? "split \(expense.splits.count) ways" : DisplayName.splitMode(mode))
            }
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(expense.description).type(.headline).foregroundStyle(.white).lineLimit(1)
                Text(subtitle).type(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
            }
            Spacer()
            if !expense.splits.isEmpty {
                HStack(spacing: -6) {
                    ForEach(expense.splits.prefix(4)) { s in
                        if let p = network.person(s.user_id) { TravelerAvatar(person: p, size: 20) }
                    }
                }
            }
            Text(Cents.format(expense.cents, expense.currency))
                .type(.numberSmall).foregroundStyle(.white)
        }
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }
}
