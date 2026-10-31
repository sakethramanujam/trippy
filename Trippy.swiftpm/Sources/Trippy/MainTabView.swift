import SwiftUI

struct MainTabView: View {
    enum Tab: String {
        case home, rentals, trips, expenses, stats
    }

    @StateObject var network = NetworkManager()
    /// Launch with `-TrippyTab rentals` (UserDefaults argument domain) to open a specific tab.
    @State private var selectedTab: Tab = Tab(rawValue: UserDefaults.standard.string(forKey: "TrippyTab") ?? "") ?? .home

    init() {
        let tabBar = UITabBarAppearance()
        tabBar.configureWithOpaqueBackground()
        tabBar.backgroundColor = UIColor(Theme.canvas)
        tabBar.shadowColor = UIColor(white: 1, alpha: 0.10)
        // Quiet tab bar: gray when idle, white when selected; color stays for status.
        let item = UITabBarItemAppearance()
        let idle = UIColor(Theme.textTertiary)
        item.normal.iconColor = idle
        item.normal.titleTextAttributes = [.foregroundColor: idle, .font: UIFont.systemFont(ofSize: 10, weight: .medium)]
        item.selected.iconColor = .white
        item.selected.titleTextAttributes = [.foregroundColor: UIColor.white, .font: UIFont.systemFont(ofSize: 10, weight: .semibold)]
        tabBar.stackedLayoutAppearance = item
        tabBar.inlineLayoutAppearance = item
        tabBar.compactInlineLayoutAppearance = item
        UITabBar.appearance().standardAppearance = tabBar
        UITabBar.appearance().scrollEdgeAppearance = tabBar

        let nav = UINavigationBarAppearance()
        nav.configureWithOpaqueBackground()
        nav.backgroundColor = UIColor(Theme.canvas)
        nav.shadowColor = .clear
        nav.titleTextAttributes = [.foregroundColor: UIColor.white,
                                   .font: UIFont.systemFont(ofSize: 17, weight: .semibold)]
        nav.largeTitleTextAttributes = [.foregroundColor: UIColor.white,
                                        .font: UIFont.systemFont(ofSize: 34, weight: .bold),
                                        .kern: -0.9]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            ContentView(network: network,
                        switchToExpenses: { selectedTab = .expenses },
                        switchToRentals: { selectedTab = .rentals },
                        switchToTrips: { selectedTab = .trips })
                .tabItem { Label("Today", systemImage: "sun.horizon.fill") }
                .tag(Tab.home)

            RentalsView(network: network)
                .tabItem { Label("Rentals", systemImage: "car.fill") }
                .tag(Tab.rentals)

            TripsView(network: network)
                .tabItem { Label("Trips", systemImage: "map.fill") }
                .tag(Tab.trips)

            ExpenseManagerView(network: network)
                .tabItem { Label("Expenses", systemImage: "creditcard.fill") }
                .tag(Tab.expenses)

            StatsView(network: network)
                .tabItem { Label("Driver's Log", systemImage: "steeringwheel") }
                .tag(Tab.stats)
        }
        .tint(Theme.blue)
        .overlay(alignment: .bottom) { UndoToastHost(network: network).padding(.bottom, 58) }
        .overlay(alignment: .top) { OfflineBanner().padding(.top, 2) }
        .preferredColorScheme(.dark)
        .sensoryFeedback(.selection, trigger: selectedTab)
        .onChange(of: network.tripsSignature) { _, _ in
            guard !network.trips.isEmpty else { return }
            WidgetSnapshot.write(trips: network.trips)
            Task { await TripReminders.reschedule(trips: network.trips) }
            BackgroundRefresh.schedule()
        }
        .task {
            network.primeFromCache()
            await network.fetchRentals()
            await network.fetchTrips()
            await network.fetchFlights()
            await network.fetchExpenses()
            #if DEBUG
            if UserDefaults.standard.bool(forKey: "TrippyExportCards") { await ShareCardFactory.exportAll(network: network) }
            #endif
        }
    }
}
