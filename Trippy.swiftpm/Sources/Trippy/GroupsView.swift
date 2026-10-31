import SwiftUI

// MARK: - Groups list

struct GroupsView: View {
    @ObservedObject var network: NetworkManager
    @State private var ledgers: [Int: ApiLedger] = [:]
    @State private var showNew = false

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top) {
                    ScreenHeader(title: "Groups", subtitle: "Balances combined across trips and IOUs")
                    Button { showNew = true } label: { CircleIcon(systemName: "plus") }
                        .buttonStyle(.plain)
                    .accessibilityLabel("New group")
                    .padding(.top, 6)
                }
                if network.groups.isEmpty {
                    EmptyStateCard(systemImage: "person.3", title: "No groups yet",
                                   message: "Create one here or from a trip's travelers to combine balances.")
                }
                VStack(spacing: 0) {
                    if !network.groups.isEmpty { Hairline() }
                    ForEach(network.groups) { g in
                        NavigationLink(value: ExpensesRoute.group(g.id)) { card(g) }
                            .buttonStyle(.plain)
                        Hairline()
                    }
                }
            }
            .padding(.horizontal, Theme.pagePadding + 4)
            .padding(.bottom, Theme.tabBarClearance)
        }
        .trippyScreen()
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showNew, onDismiss: { Task { await load() } }) { NewGroupSheet(network: network) }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        await network.fetchGroups()
        for g in network.groups { ledgers[g.id] = await network.fetchLedger(.group(g.id)) }
    }

    private func card(_ g: ApiGroup) -> some View {
        let led = ledgers[g.id]
        let open = led?.simplified ?? []
        let outstanding = open.reduce(0) { $0 + $1.amount_cents }
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(g.name).type(.title3).foregroundStyle(.white)
                Spacer()
                Image(systemName: "chevron.right").type(.footnoteStrong).foregroundStyle(Theme.textTertiary)
            }
            HStack(spacing: 10) {
                HStack(spacing: -8) {
                    ForEach(g.members.prefix(5)) { TravelerAvatar(person: $0, size: 30) }
                }
                Text("\(g.members.count) people · \(g.trips.count) trip\(g.trips.count == 1 ? "" : "s")")
                    .type(.footnote).foregroundStyle(Theme.textSecondary)
                Spacer()
                if led != nil {
                    if open.isEmpty {
                        StatusPill(text: "All settled", color: Theme.green)
                    } else {
                        VStack(alignment: .trailing, spacing: 0) {
                            Text(Cents.format(outstanding)).type(.number)
                                .foregroundStyle(.white)
                            Text("\(open.count) payment\(open.count == 1 ? "" : "s") to settle")
                                .type(.label).foregroundStyle(Theme.textSecondary)
                        }
                    }
                }
            }
        }
        .padding(.vertical, Theme.s4)
        .contentShape(Rectangle())
    }
}

// MARK: - Group detail

struct GroupDetailView: View {
    @ObservedObject var network: NetworkManager
    let groupId: Int
    @State private var ledger: ApiLedger?
    @State private var mode: LedgerMode = UserDefaults.standard.string(forKey: "TrippyGroupMode") == "pairwise" ? .pairwise : .simplified
    @State private var showDebt = false
    @State private var showExpense = false
    @State private var editing: ApiExpense?
    @State private var errorText: String?
    @State private var didHooks = false

    private var group: ApiGroup? { network.groups.first { $0.id == groupId } }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: Theme.sectionGap) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(group?.name ?? ledger?.name ?? "Group")
                        .type(.largeTitle).foregroundStyle(.white)
                    if let g = group {
                        HStack(spacing: 10) {
                            HStack(spacing: -8) { ForEach(g.members) { TravelerAvatar(person: $0, size: 28) } }
                            Text("\(g.members.count) people · \(g.trips.count) trip\(g.trips.count == 1 ? "" : "s") · \(ledger?.standalone?.count ?? 0) IOU\((ledger?.standalone?.count ?? 0) == 1 ? "" : "s")")
                                .type(.footnote).foregroundStyle(Theme.textSecondary)
                        }
                    }
                }

                if let ledger {
                    VStack(alignment: .leading, spacing: Theme.s3) {
                        ListSectionTitle(title: "Balances", trailing: Cents.format(ledger.total_cents) + " total")
                        BalancesPanel(network: network, ledger: ledger, mode: $mode, showBreakdown: true,
                                      onSettle: { d in Task { await settle(d) } },
                                      onSettleAll: { Task { await settleAll() } })
                    }

                    VStack(alignment: .leading, spacing: Theme.s2) {
                        let items = ledger.standalone ?? []
                        ListSectionTitle(title: "IOUs & expenses", trailing: items.isEmpty ? nil : "\(items.count)")
                        Hairline()
                        if items.isEmpty {
                            Text("Debts that happened outside a trip, e.g. \u{201C}Sam already owes Maya $30\u{201D}.")
                                .type(.footnote).foregroundStyle(Theme.textSecondary)
                        }
                        ForEach(items) { s in
                            Button {
                                editing = network.expenses.first { $0.id == s.id }
                            } label: { standaloneRow(s, ledger) }
                            .buttonStyle(.plain)
                            Hairline(leading: 44)
                        }
                        HStack(spacing: 10) {
                            pillButton("Add IOU", "arrow.left.arrow.right", Theme.purple) { showDebt = true }
                            pillButton("Add expense", "plus", Theme.blue) { showExpense = true }
                        }
                        .padding(.top, Theme.s2)
                    }

                    if let trips = ledger.trips, !trips.isEmpty {
                        VStack(alignment: .leading, spacing: 0) {
                            ListSectionTitle(title: "Trips", trailing: "\(trips.count)").padding(.bottom, Theme.s2)
                            Hairline()
                            ForEach(trips) { t in
                                let total = network.trips.first { $0.id == t.id }?.expenses.reduce(0) { $0 + $1.cents } ?? 0
                                HStack(spacing: Theme.s3) {
                                    Image(systemName: "airplane").symbolRenderingMode(.hierarchical)
                                        .foregroundStyle(.white).frame(width: 32)
                                    Text(t.title).type(.headline).foregroundStyle(.white)
                                    Spacer()
                                    Text(Cents.format(total)).type(.numberSmall)
                                        .foregroundStyle(Theme.textSecondary)
                                }
                                .padding(.vertical, 13)
                                Hairline(leading: 44)
                            }
                        }
                    }
                } else {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(40)
                }
            }
            .padding(.horizontal, Theme.pagePadding + 4)
            .padding(.bottom, Theme.tabBarClearance)
        }
        .trippyScreen()
        .navigationBarTitleDisplayMode(.inline)
        .task { await reload(); await runLaunchHooks() }
        .refreshable { await reload() }
        .sheet(isPresented: $showDebt, onDismiss: { Task { await reload() } }) {
            if let group { AddDebtSheet(network: network, group: group) }
        }
        .sheet(isPresented: $showExpense, onDismiss: { Task { await reload() } }) {
            SplitExpenseSheet(network: network, scope: .group(groupId))
        }
        .sheet(item: $editing, onDismiss: { Task { await reload() } }) { e in
            SplitExpenseSheet(network: network, scope: .group(groupId), editing: e)
        }
        .alert("Something went wrong", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(errorText ?? "") }
    }

    private func pillButton(_ title: String, _ icon: String, _ tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .type(.calloutStrong).foregroundStyle(.white)
                .frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(Theme.surfaceRaised, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func standaloneRow(_ s: ApiStandalone, _ ledger: ApiLedger) -> some View {
        let payer = s.payer_id.map { ledger.name($0) } ?? "Someone"
        let debtors = s.splits.filter { $0.user_id != s.payer_id }.map { ledger.name($0.user_id) }
        let isIOU = s.split_mode == "exact" && s.splits.count == 1 && s.splits.first?.user_id != s.payer_id
        return HStack(spacing: 10) {
            Image(systemName: isIOU ? "arrow.left.arrow.right" : "creditcard.fill")
                .symbolRenderingMode(.hierarchical)
                .type(.calloutStrong).foregroundStyle(.white)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(s.description).type(.callout).foregroundStyle(.white).lineLimit(1)
                Text(isIOU ? "\(debtors.joined(separator: ", ")) owes \(payer)" : "\(payer) paid · split \(s.splits.count) ways")
                    .type(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
            }
            Spacer()
            Text(Cents.format(s.amount_cents)).type(.numberSmall)
                .foregroundStyle(.white)
        }
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    private func reload() async {
        if network.users.isEmpty { await network.loadUsers() }
        if group == nil { await network.fetchGroups() }
        if network.expenses.isEmpty { await network.fetchExpenses() }
        ledger = await network.fetchLedger(.group(groupId))
    }

    private func settle(_ d: ApiDebt) async {
        if let err = await network.settle(.group(groupId), from: d.from_user_id, to: d.to_user_id, mode: mode) { errorText = err }
        await reload()
    }

    private func settleAll() async {
        if let err = await network.settleAll(.group(groupId)) { errorText = err }
        await reload()
    }

    /// `-TrippyShowAddDebt 1`, `-TrippyDebugSettle "from,to"`, `-TrippyDebugSettleAll 1` (group scope).
    private func runLaunchHooks() async {
        guard !didHooks else { return }
        didHooks = true
        let d = UserDefaults.standard
        guard d.integer(forKey: "TrippyOpenGroup") == groupId else { return }
        if let pair = d.string(forKey: "TrippyDebugSettle") {
            let ids = pair.split(separator: ",").compactMap { Int($0) }
            if ids.count == 2 {
                if let err = await network.settle(.group(groupId), from: ids[0], to: ids[1], mode: mode) { errorText = err }
                await reload()
            }
        }
        if d.bool(forKey: "TrippyDebugSettleAll") { await settleAll() }
        if d.bool(forKey: "TrippyShowAddDebt") { showDebt = true }
    }
}

// MARK: - Add IOU

struct AddDebtSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var network: NetworkManager
    let group: ApiGroup

    @State private var fromId: Int?
    @State private var toId: Int?
    @State private var amountText = ""
    @State private var description = ""
    @State private var error: String?
    @State private var isSaving = false

    private var cents: Int? { Cents.parse(amountText).flatMap { $0 > 0 ? $0 : nil } }
    private var valid: Bool { fromId != nil && toId != nil && fromId != toId && cents != nil && !isSaving }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Who owes")
                        PersonChips(people: group.members, selected: { fromId == $0 }, tint: Theme.red) { fromId = $0 }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Who they owe")
                        PersonChips(people: group.members, selected: { toId == $0 }, tint: Theme.green) { toId = $0 }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Amount")
                        HStack(spacing: 4) {
                            Text("$").type(.largeTitle).foregroundStyle(Theme.green.opacity(0.7))
                            TextField("", text: $amountText, prompt: Text("0.00").foregroundStyle(Theme.textTertiary))
                                .keyboardType(.decimalPad)
                                .type(.code).monospacedDigit().foregroundStyle(Theme.green)
                        }
                        .padding(14)
                        .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "What for")
                        TextField("", text: $description, prompt: Text("e.g. Concert tickets").foregroundStyle(Theme.textTertiary))
                            .foregroundStyle(.white).padding(14)
                            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    if let f = fromId, let t = toId, f != t, let c = cents {
                        let fn = group.members.first { $0.id == f }?.firstName ?? ""
                        let tn = group.members.first { $0.id == t }?.firstName ?? ""
                        Label("\(fn) owes \(tn) \(Cents.format(c)). It's combined with trip balances in \(group.name).",
                              systemImage: "info.circle")
                            .type(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .type(.footnote).foregroundStyle(Theme.red)
                    }
                }
                .padding(Theme.pagePadding)
            }
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle("Add IOU")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") { Task { await save() } }.fontWeight(.bold).disabled(!valid)
                }
            }
            .task {
                let d = UserDefaults.standard
                if let f = d.string(forKey: "TrippyDebtFrom").flatMap(Int.init) { fromId = f }
                if let t = d.string(forKey: "TrippyDebtTo").flatMap(Int.init) { toId = t }
                if let a = d.string(forKey: "TrippyDebtAmount") { amountText = a }
                if let s = d.string(forKey: "TrippyDebtDesc") { description = s }
            }
        }
        .presentationDetents([.large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private func save() async {
        guard let f = fromId, let t = toId, let c = cents else { return }
        isSaving = true
        let desc = description.trimmingCharacters(in: .whitespaces)
        let err = await network.addDebt(groupId: group.id, from: f, to: t, amountCents: c, description: desc.isEmpty ? "IOU" : desc)
        isSaving = false
        if let err { error = err } else { dismiss() }
    }
}

// MARK: - New group

struct NewGroupSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var network: NetworkManager
    @State private var name = ""
    @State private var members: Set<Int> = []
    @State private var tripIds: Set<Int> = []
    @State private var error: String?
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Name")
                        TextField("", text: $name, prompt: Text("e.g. Roommates").foregroundStyle(Theme.textTertiary))
                            .foregroundStyle(.white).padding(14)
                            .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "Trips to combine")
                        ForEach(network.trips) { t in
                            let on = tripIds.contains(t.id)
                            Button {
                                if on { tripIds.remove(t.id) } else {
                                    tripIds.insert(t.id)
                                    for p in network.people(forTrip: t) { members.insert(p.id) }
                                }
                            } label: {
                                HStack {
                                    Image(systemName: on ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(on ? Theme.blue : Theme.textTertiary)
                                    Text(t.displayTitle).foregroundStyle(.white)
                                    Spacer()
                                    if let g = t.group_id, g > 0 {
                                        Text("in a group").type(.caption).foregroundStyle(Theme.textTertiary)
                                    }
                                }
                                .type(.callout)
                                .padding(.vertical, 6)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        MoneyLabel(text: "People")
                        PersonChips(people: network.users, selected: { members.contains($0) }) { id in
                            if members.contains(id) { members.remove(id) } else { members.insert(id) }
                        }
                    }
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .type(.footnote).foregroundStyle(Theme.red)
                    }
                }
                .padding(Theme.pagePadding)
            }
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle("New Group")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Creating…" : "Create") { Task { await save() } }
                        .fontWeight(.bold)
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || members.count < 2 || isSaving)
                }
            }
            .task { if network.users.isEmpty { await network.loadUsers() } }
        }
        .presentationDetents([.large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private func save() async {
        isSaving = true
        let (_, err) = await network.createGroup(name: name.trimmingCharacters(in: .whitespaces),
                                                 memberIds: Array(members), tripIds: Array(tripIds))
        isSaving = false
        if let err { error = err } else { dismiss() }
    }
}
