import SwiftUI

enum ExpensesRoute: Hashable {
    case groups
    case group(Int)
}

struct ExpenseManagerView: View {
    @ObservedObject var network: NetworkManager
    @State private var path: [ExpensesRoute] = []
    @State private var showingAdd = false
    @State private var editing: ApiExpense?
    @State private var didHooks = false

    private var totalCents: Int { network.expenses.reduce(0) { $0 + $1.cents } }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: Theme.sectionGap) {
                    HStack(alignment: .top) {
                        ScreenHeader(title: "Expenses",
                                     subtitle: "\(network.expenses.count) expenses · \(network.trips.count) trips · \(network.groups.count) group\(network.groups.count == 1 ? "" : "s")")
                        Button { showingAdd = true } label: { CircleIcon(systemName: "plus") }
                            .buttonStyle(.plain)
                            .accessibilityLabel("New expense")
                            .padding(.top, 6)
                            .sensoryFeedback(.impact(weight: .light), trigger: showingAdd)
                    }
                    .padding(.top, 8)

                    // Hero: one huge number, no box.
                    VStack(alignment: .leading, spacing: 0) {
                        MicroLabel(text: "Total spent")
                        Text(Cents.format(totalCents))
                            .type(.hero)
                            .foregroundStyle(.white).minimumScaleFactor(0.6).lineLimit(1)
                            .contentTransition(.numericText())
                        Text("Split across trips and groups, in exact cents")
                            .type(.callout).foregroundStyle(Theme.textSecondary)
                    }

                    NavigationLink(value: ExpensesRoute.groups) {
                        HStack(spacing: Theme.s3) {
                            Image(systemName: "person.3.fill")
                                .symbolRenderingMode(.hierarchical)
                                .type(.headline).foregroundStyle(.white)
                                .frame(width: 32)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Balances & Groups").type(.headline).foregroundStyle(.white)
                                Text("Combine what people owe across trips and IOUs")
                                    .type(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(1)
                            }
                            Spacer()
                            Text("\(network.groups.count)").type(.numberSmall)
                                .foregroundStyle(Theme.textSecondary)
                            Image(systemName: "chevron.right").type(.footnoteStrong)
                                .foregroundStyle(Theme.textTertiary)
                        }
                        .padding(.vertical, 14)
                        .overlay(alignment: .top) { Hairline() }
                        .overlay(alignment: .bottom) { Hairline() }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)

                    VStack(alignment: .leading, spacing: Theme.s2) {
                        ListSectionTitle(title: "Recent", trailing: network.expenses.isEmpty ? nil : "\(network.expenses.count) · tap to edit")
                        if network.expenses.isEmpty {
                            EmptyStateCard(systemImage: "creditcard", title: "No expenses yet",
                                           message: "Tap + to split one on a trip or in a group.")
                        } else {
                            VStack(spacing: 0) {
                                Hairline()
                                ForEach(Array(network.expenses.sorted { $0.id > $1.id }.enumerated()), id: \.element.id) { idx, e in
                                    if idx > 0 { Hairline() }
                                    Button { editing = e } label: { ExpenseLine(network: network, expense: e) }
                                        .buttonStyle(.plain)
                                }
                                Hairline()
                            }
                        }
                    }
                    Color.clear.frame(height: Theme.tabBarClearance)
                }
                .padding(.horizontal, Theme.pagePadding + 4)
            }
            .refreshable { await network.refreshMoney() }
            .trippyScreen()
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: ExpensesRoute.self) { route in
                switch route {
                case .groups: GroupsView(network: network)
                case .group(let id): GroupDetailView(network: network, groupId: id)
                }
            }
            .sheet(isPresented: $showingAdd) { SplitExpenseSheet(network: network, scope: nil) }
            .sheet(item: $editing) { e in SplitExpenseSheet(network: network, scope: nil, editing: e) }
            .task {
                if network.users.isEmpty { await network.loadUsers() }
                await network.fetchGroups()
                await runLaunchHooks()
            }
        }
    }

    /// `-TrippyOpenGroups 1`, `-TrippyOpenGroup N`, `-TrippyShowSplit 1`, `-TrippyEditExpense N`.
    private func runLaunchHooks() async {
        guard !didHooks else { return }
        didHooks = true
        let d = UserDefaults.standard
        guard d.string(forKey: "TrippyTab") == "expenses" else { return }
        if d.bool(forKey: "TrippyOpenGroups") { path = [.groups] }
        if d.integer(forKey: "TrippyOpenGroup") > 0 { path = [.groups, .group(d.integer(forKey: "TrippyOpenGroup"))] }
        if d.bool(forKey: "TrippyShowSplit") { showingAdd = true }
        if let id = d.string(forKey: "TrippyEditExpense").flatMap(Int.init) {
            if network.expenses.isEmpty { await network.fetchExpenses() }
            editing = network.expenses.first { $0.id == id }
        }
    }
}
