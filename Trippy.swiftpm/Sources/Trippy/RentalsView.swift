import SwiftUI
import MapKit

struct RentalsView: View {
    @ObservedObject var network: NetworkManager
    @State private var path: [Int] = []
    @State private var didDeepLink = false
    @State private var detent = min(max(LaunchOptions.detent, 0), 1)
    @State private var sheetHeight: CGFloat = 0

    private var sorted: [ApiRentalCar] {
        network.rentals.sorted { ($0.pickupDate ?? .distantPast) > ($1.pickupDate ?? .distantPast) }
    }

    var body: some View {
        NavigationStack(path: $path) {
            TimelineView(.periodic(from: .now, by: 60)) { context in
                content(now: context.date)
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: Int.self) { id in
                if let rental = network.rentals.first(where: { $0.id == id }) {
                    RentalDetailView(rental: rental)
                }
            }
            .task {
                if !network.rentalsLoaded { await network.fetchRentals() }
                openDeepLinkIfNeeded()
            }
            .onChange(of: network.rentals.count) { _, _ in openDeepLinkIfNeeded() }
        }
    }

    @ViewBuilder
    private func content(now: Date) -> some View {
        let rentals = sorted
        let live = rentals.filter { [.active, .upcoming, .overdue].contains($0.phase(at: now)) }
            .sorted { ($0.pickupDate ?? .distantFuture) < ($1.pickupDate ?? .distantFuture) }
        let past = rentals.filter { $0.phase(at: now) == .returned }
        let summary = RentalSummary(rentals)

        ZStack {
            Theme.canvas.ignoresSafeArea()
            // Layer 0: full-screen dark map with every pickup station, framed above the sheet
            RentalsOverviewMap(rentals: rentals, bottomInset: sheetHeight)
                .ignoresSafeArea()

            // Layer 1: draggable sheet (half / full)
            DetentSheet(detents: [0.5, 0.92], selection: $detent, visibleHeight: $sheetHeight,
                        onRefresh: { await network.fetchRentals() }) {
                        HStack(alignment: .center) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("My Rentals")
                                    .type(.title)
                                    .foregroundStyle(.white)
                                if !rentals.isEmpty {
                                    Text("\(summary.count) rentals · \(Fmt.number(summary.days)) days · \(Fmt.compactMoney(summary.spend))")
                                        .type(.timeSmall).monospacedDigit()
                                        .foregroundStyle(Theme.textSecondary)
                                }
                                SyncedCaption()
                            }
                            Spacer()
                            Image(systemName: "car.fill")
                                .type(.headline)
                                .foregroundStyle(.white)
                                .frame(width: 40, height: 40)
                                .background(Theme.surfaceRaised, in: Circle())
                        }
                        .padding(.horizontal, Theme.pagePadding)
                        .padding(.top, 2).padding(.bottom, 12)
            } content: {
                VStack(alignment: .leading, spacing: 0) {

                        if !network.rentalsLoaded && rentals.isEmpty {
                            ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.vertical, 60)
                        } else if let error = network.rentalsError, rentals.isEmpty {
                            EmptyStateCard(systemImage: "wifi.exclamationmark",
                                           title: "Can't reach Trippy API",
                                           message: "\(error)\n\(APIConfig.baseURL)")
                        } else if rentals.isEmpty {
                            EmptyStateCard(systemImage: "car.side",
                                           title: "No rentals yet",
                                           message: "Import your rental history with scripts/import_rentals.py")
                        } else {
                            if live.isEmpty {
                                HStack(spacing: 12) {
                                    Image(systemName: "calendar.badge.plus")
                                        .symbolRenderingMode(.hierarchical)
                                        .type(.title3)
                                        .foregroundStyle(.white)
                                        .frame(width: 44)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("No upcoming rentals")
                                            .type(.calloutStrong).foregroundStyle(.white)
                                        Text("Last returned \(past.first.map { $0.countdown(at: now).replacingOccurrences(of: "Returned ", with: "") } ?? "—")")
                                            .type(.footnote).foregroundStyle(Theme.textSecondary)
                                    }
                                    Spacer()
                                }
                                .padding(.vertical, Theme.s3)
                                .overlay(alignment: .bottom) { Hairline() }
                                .padding(.bottom, 6)
                            } else {
                                ForEach(live) { rental in
                                    NavigationLink(value: rental.id) { RentalCard(rental: rental, now: now) }
                                        .buttonStyle(.plain)
                                        .padding(.bottom, 10)
                                }
                            }

                            ForEach(groupByYear(past), id: \.year) { group in
                                HStack(alignment: .firstTextBaseline) {
                                    Text(group.year == 0 ? "Undated" : String(group.year))
                                        .type(.title3)
                                        .foregroundStyle(.white)
                                    Spacer()
                                    Text("\(group.items.count) · \(Fmt.compactMoney(group.items.reduce(0) { $0 + ($1.cost ?? 0) }))")
                                        .type(.footnote).monospacedDigit()
                                        .foregroundStyle(Theme.textSecondary)
                                }
                                .padding(.top, 18).padding(.bottom, 2)
                                ForEach(Array(group.items.enumerated()), id: \.element.id) { idx, rental in
                                    NavigationLink(value: rental.id) { RentalRow(rental: rental, now: now) }
                                        .buttonStyle(.plain)
                                    if idx < group.items.count - 1 {
                                        Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.leading, 72)
                                    }
                                }
                            }
                        }
                    Color.clear.frame(height: Theme.tabBarClearance + 24)
                }
                .padding(.horizontal, Theme.pagePadding)
            }
        }
    }

    private func groupByYear(_ rentals: [ApiRentalCar]) -> [(year: Int, items: [ApiRentalCar])] {
        let groups = Dictionary(grouping: rentals) { $0.pickupYear ?? 0 }
        return groups.map { ($0.key, $0.value) }.sorted { $0.year > $1.year }
    }

    private func openDeepLinkIfNeeded() {
        guard !didDeepLink else { return }
        let target = UserDefaults.standard.integer(forKey: "TrippyOpenRental")
        guard target != 0 else { return }
        let id = target > 0 ? target : sorted.first?.id
        if let id, network.rentals.contains(where: { $0.id == id }) {
            didDeepLink = true
            path = [id]
        }
    }
}

// MARK: - Card

struct RentalCard: View {
    let rental: ApiRentalCar
    var now: Date = Date()

    var body: some View {
        let phase = rental.phase(at: now)
        VStack(alignment: .leading, spacing: 14) {
            // Header: brand + car + status
            HStack(spacing: 10) {
                CompanyBadge(company: rental.rental_company)
                VStack(alignment: .leading, spacing: 1) {
                    Text(rental.vehicleName)
                        .type(.headline)
                        .foregroundStyle(.white)
                        .lineLimit(1)
                    Text(headerSubtitle)
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 6)
                StatusPill(text: phase.label, color: phase.color)
            }

            // Big codes
            HStack(alignment: .top, spacing: 10) {
                endpoint(code: rental.pickupDisplayCode, city: rental.pickupDisplayCity,
                         date: rental.pickupDate, align: .leading)
                DashedConnector(glyph: rental.isOneWay ? "arrow.right" : "arrow.triangle.2.circlepath",
                                caption: durationCaption,
                                color: phase == .active ? Theme.green : Theme.textSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 14)
                endpoint(code: rental.dropoffDisplayCode, city: rental.dropoffDisplayCity,
                         date: rental.dropoffDate, align: .trailing)
            }

            if phase == .active || phase == .upcoming {
                VStack(alignment: .leading, spacing: 6) {
                    if phase == .active {
                        RouteProgressBar(progress: rental.progress(at: now), color: Theme.green)
                    }
                    Text(rental.countdown(at: now))
                        .type(.calloutStrong)
                        .monospacedDigit()
                        .foregroundStyle(phase.color)
                }
            }

            // Chips
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    if let cls = DisplayName.vehicleClass(rental.vehicle_class) {
                        InfoChip(label: "Class", value: cls)
                    }
                    if let conf = rental.confirmationText {
                        InfoChip(label: "Conf", value: conf)
                    }
                    if let miles = rental.milesDriven {
                        InfoChip(label: "Mi", value: Fmt.number(miles))
                    }
                    if let cost = rental.costText {
                        InfoChip(label: "Total", value: cost, tint: Theme.green)
                    }
                }
            }
        }
        .card()
    }

    private var headerSubtitle: String {
        var parts = [RentalBrand.forCompany(rental.rental_company).name]
        if let y = rental.vehicle_year { parts.append(String(y)) }
        if rental.isSimilarModel { parts.append("or similar") }
        return parts.joined(separator: " · ")
    }

    private var durationCaption: String? {
        if rental.isApproximate { return "date approx." }
        if let days = rental.rentalDays { return days == 1 ? "1 day" : "\(days) days" }
        return nil
    }

    private func endpoint(code: String, city: String, date: Date?, align: HorizontalAlignment) -> some View {
        VStack(alignment: align, spacing: 2) {
            Text(code)
                .type(.largeTitle)
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(city)
                .type(.footnote)
                .foregroundStyle(Theme.textSecondary)
                .lineLimit(1)
            if let date {
                Text(rental.isApproximate ? Fmt.monthDayYear(date) : Fmt.time(date))
                    .type(.calloutStrong)
                    .monospacedDigit()
                    .foregroundStyle(.white)
                    .padding(.top, 2)
                Text(rental.isApproximate ? "approx." : Fmt.day(date))
                    .type(.caption)
                    .foregroundStyle(Theme.textTertiary)
            } else {
                Text("—")
                    .type(.calloutStrong)
                    .foregroundStyle(Theme.textTertiary)
                    .padding(.top, 2)
            }
        }
        .frame(width: 104, alignment: align == .leading ? .leading : .trailing)
    }
}

// MARK: - List row (countdown left · logo + code · route + times)

struct RentalRow: View {
    let rental: ApiRentalCar
    var now: Date = Date()

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            countdown
                .frame(width: 56)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    CompanyBadge(company: rental.rental_company, size: 18)
                    Text(microLine)
                        .type(.footnote).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if let d = rental.pickupDate {
                        Text(Fmt.day(d))
                            .type(.footnote)
                            .foregroundStyle(Theme.textSecondary)
                    }
                }
                Text(rental.vehicleName)
                    .type(.headline)
                    .foregroundStyle(.white)
                    .lineLimit(1)
                HStack(spacing: 14) {
                    endpoint("arrow.up.right.circle.fill", rental.pickupDisplayCode, rental.pickupDate)
                    endpoint("arrow.down.right.circle.fill", rental.dropoffDisplayCode, rental.dropoffDate)
                }
            }
        }
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    private var microLine: String {
        var parts = [RentalBrand.forCompany(rental.rental_company).name]
        if let conf = rental.confirmationText { parts.append(conf) }
        return parts.joined(separator: " ")
    }

    @ViewBuilder
    private var countdown: some View {
        let phase = rental.phase(at: now)
        switch phase {
        case .upcoming, .active, .overdue:
            let target = phase == .upcoming ? rental.pickupDate : rental.dropoffDate
            let days = target.map { max(0, Int(ceil($0.timeIntervalSince(now) / 86_400))) } ?? 0
            VStack(spacing: 0) {
                Text("\(days)")
                    .type(.codeSmall).monospacedDigit()
                    .foregroundStyle(phase == .upcoming ? .white : phase.color)
                Text(phase == .upcoming ? "DAYS" : "LEFT")
                    .type(.micro).tracking(0.4)
                    .foregroundStyle(Theme.textSecondary)
            }
        case .returned:
            // Past rentals: rental length in days, like Flighty's day counter
            // Unknown length (no return time): show the pickup date like a calendar tile instead of "–".
            let days = rental.rentalDays
            let pickup = rental.pickupDate
            VStack(spacing: 0) {
                Text(days.map(String.init) ?? pickup.map { String(Calendar.current.component(.day, from: $0)) } ?? "?")
                    .type(.codeSmall).monospacedDigit()
                    .foregroundStyle(.white)
                Text(days != nil ? (days == 1 ? "DAY" : "DAYS") : (pickup.map { $0.formatted(.dateTime.month(.abbreviated)).uppercased() } ?? "DAYS"))
                    .type(.micro).tracking(0.4)
                    .foregroundStyle(Theme.textSecondary)
            }
        }
    }

    private func endpoint(_ icon: String, _ code: String, _ date: Date?) -> some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .type(.caption)
                .foregroundStyle(Theme.textSecondary)
            Text(code)
                .type(.callout)
                .foregroundStyle(Theme.textSecondary)
            if let date {
                Text(rental.isApproximate ? Fmt.monthDay(date) : Fmt.time(date))
                    .type(.timeSmall).monospacedDigit()
                    .foregroundStyle(.white)
            }
        }
        .lineLimit(1)
    }
}

// MARK: - Overview map (every station you've picked up from)


struct RentalsOverviewMap: View {
    let rentals: [ApiRentalCar]
    var bottomInset: CGFloat = 0
    @State private var camera: MapCameraPosition = .automatic

    private struct Station: Identifiable {
        let id: String
        let code: String
        let coordinate: CLLocationCoordinate2D
        let count: Int
    }

    private var stations: [Station] {
        var byCode: [String: (CLLocationCoordinate2D, Int)] = [:]
        for r in rentals {
            guard let c = r.pickupCoordinate else { continue }
            let code = r.pickupDisplayCode
            byCode[code] = (byCode[code]?.0 ?? c, (byCode[code]?.1 ?? 0) + 1)
        }
        return byCode.map { Station(id: $0.key, code: $0.key, coordinate: $0.value.0, count: $0.value.1) }
    }

    var body: some View {
        Map(position: $camera, interactionModes: [.pan, .zoom]) {
            MapDimmer()
            ForEach(stations) { s in
                Annotation("", coordinate: s.coordinate, anchor: .center) {
                    ZStack {
                        Circle().fill(Theme.route.opacity(0.22)).frame(width: 14 + CGFloat(min(s.count, 12)) * 2)
                        Circle().fill(Theme.route).frame(width: 8, height: 8)
                            .overlay(Circle().strokeBorder(.white, lineWidth: 1.5))
                    }
                }
            }
        }
        .mapStyle(MapLook.style)
        .environment(\.colorScheme, .dark)
        .autoFit($camera, coords: stations.map(\.coordinate), padding: 0.12, top: 60, bottom: bottomInset, side: 20)
    }
}
