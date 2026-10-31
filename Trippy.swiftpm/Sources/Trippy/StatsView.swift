import SwiftUI
import Charts

/// "Driver's Log": a purple passport-style recap of rentals (+ flights/trips from /stats/).
struct StatsView: View {
    @ObservedObject var network: NetworkManager
    /// `nil` means all years
    @State private var selectedYear: Int? = nil
    @State private var yearCard: ApiYearInTravel?
    @State private var shareKind: CardKind?

    private var years: [Int] {
        let rentalYears = network.rentals.compactMap(\.pickupYear)
        return Array(Set(network.statsYears + rentalYears)).sorted(by: >)
    }

    private var rentalsInScope: [ApiRentalCar] {
        guard let selectedYear else { return network.rentals }
        return network.rentals.filter { $0.pickupYear == selectedYear }
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                LinearGradient(colors: [Theme.purpleDeep, Theme.canvas], startPoint: .top, endPoint: .center)
                    .ignoresSafeArea()
                ScrollViewReader { reader in
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Driver's Log")
                            .type(.largeTitle)
                            .foregroundStyle(.white)
                            .padding(.top, 8)

                        yearPicker

                        YourYearCard(year: yearCard, yearNumber: cardYear,
                                     onYear: { shareKind = .year }, onDrivers: { shareKind = .drivers })

                        let rentals = rentalsInScope
                        let s = RentalSummary(rentals)
                        heroCard(s, rentals)

                        if s.count > 0 {
                            companiesSection(s)
                            weekdaySection(rentals)
                            longestShortest(rentals)
                            topLocations(rentals)
                            if selectedYear == nil && s.byYear.count > 1 { byYearSection(s) }
                            if !s.topCars.isEmpty { carsSection(s) }
                        }

                        if let stats = network.stats {
                            flightsCard(stats)
                            let aircraft = stats.logbookAircraft
                            if !aircraft.isEmpty {
                                LogbookSection(title: "Top aircraft", icon: "airplane", color: Theme.blue, items: aircraft)
                            }
                            let airlines = stats.logbookAirlines
                            if !airlines.isEmpty {
                                LogbookSection(title: "Top airlines", icon: "ticket.fill", color: Theme.purple, items: airlines)
                            }
                            if let stays = stats.stays, stays.count > 0 {
                                staysCard(stays).id("stays")
                                if let brands = stays.top_brands, !brands.isEmpty {
                                    LogbookSection(title: "Top hotel chains", icon: "bed.double.fill", color: Theme.stay, items: brands)
                                }
                            }
                        }
                        Color.clear.frame(height: 90)
                    }
                    .padding(.horizontal, Theme.pagePadding)
                }
                .onChange(of: network.stats?.stays?.count) { _, n in
                    // Screenshot hook: -TrippyScrollTo stays
                    guard (n ?? 0) > 0, UserDefaults.standard.string(forKey: "TrippyScrollTo") == "stays" else { return }
                    Task {
                        try? await Task.sleep(for: .milliseconds(600))
                        withAnimation { reader.scrollTo("stays", anchor: .top) }
                    }
                }
                }
            }
            .refreshable {
                await network.fetchRentals()
                await network.fetchStats(year: selectedYear)
            }
            .toolbar(.hidden, for: .navigationBar)
            .task {
                await network.fetchStatsYears()
                await network.fetchStats(year: selectedYear)
            }
            .onChange(of: selectedYear) { _, newYear in
                Task { await network.fetchStats(year: newYear) }
            }
            .task(id: cardYear) { yearCard = await network.fetchYearInTravel(cardYear) }
            .sheet(item: $shareKind) { k in
                ShareCardSheet(network: network, kinds: [.year, .drivers], year: cardYear, initialKind: k)
            }
            .onAppear {
                if let k = UserDefaults.standard.string(forKey: "TrippyShareCard").flatMap(CardKind.init(rawValue:)), k != .trip {
                    shareKind = k
                }
            }
        }
    }

    /// The year the "Your Year" card covers: the selected chip, else the latest year with data.
    private var cardYear: Int {
        selectedYear ?? years.first(where: { $0 <= Calendar.current.component(.year, from: Date()) })
            ?? Calendar.current.component(.year, from: Date())
    }

    // MARK: Year chips (All-Time · 2026 · 2025 …)

    private var yearPicker: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) {
                yearChip(nil, "All-Time")
                ForEach(years, id: \.self) { year in
                    yearChip(year, String(year))
                }
            }
        }
    }

    private func yearChip(_ year: Int?, _ label: String) -> some View {
        let selected = selectedYear == year
        return Button { withAnimation(.snappy) { selectedYear = year } } label: {
            Text(label)
                .type(.numberSmall).monospacedDigit()
                .foregroundStyle(selected ? .white : Theme.textSecondary)
                .padding(.horizontal, 13)
                .padding(.vertical, 8)
                .background(selected ? Color.white.opacity(0.12) : .clear, in: Capsule())
                .overlay(Capsule().strokeBorder(selected ? Color.white.opacity(0.08) : .clear))
        }
        .buttonStyle(.plain)
    }

    // MARK: Purple hero

    private func heroCard(_ s: RentalSummary, _ rentals: [ApiRentalCar]) -> some View {
        let companies = Set(rentals.map { RentalBrand.forCompany($0.rental_company).name }).count
        let cars = Set(rentals.map(\.vehicleName)).count
        let longest = rentals.compactMap(\.rentalDays).max() ?? 0
        return VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("\(selectedYear.map(String.init) ?? "All-Time") Driver's Log")
                        .type(.title2).tracking(-0.5)
                        .foregroundStyle(.white)
                        .lineLimit(1).minimumScaleFactor(0.7)
                    Spacer()
                    Image(systemName: "steeringwheel")
                        .type(.headline)
                        .foregroundStyle(.white.opacity(0.8))
                }
                HStack(spacing: 5) {
                    Image(systemName: "person.text.rectangle")
                    Text("LICENSE • LICENCIA • PERMIS")
                }
                .type(.micro)
                .foregroundStyle(.white.opacity(0.6))
            }

            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 14) {
                GridRow {
                    heroStat("Rentals", "\(s.count)", sub: longest > 0 ? "Longest \(longest) days" : nil)
                    heroStat("Spent", Fmt.money(s.spend, "USD", decimals: false), sub: s.days > 0 ? "\(Fmt.money(s.spend / s.days, "USD", decimals: false))/day" : nil)
                        .gridCellColumns(2)
                }
                GridRow {
                    heroStat("Days", Fmt.number(s.days))
                    heroStat("Companies", "\(companies)")
                    heroStat("Cars", "\(cars)")
                }
                if s.miles > 0 {
                    GridRow {
                        heroStat("Distance", Fmt.number(s.miles) + " mi").gridCellColumns(3)
                    }
                }
            }

            if let top = s.byCompany.first {
                HStack {
                    Text("Most rented: \(RentalBrand.forCompany(top.company).name) · \(top.count)×")
                        .type(.callout)
                    Spacer()
                    Image(systemName: "chevron.right").type(.footnoteStrong)
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(Color.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
            }
        }
        .padding(18)
        .background(
            LinearGradient(colors: [Theme.purple.opacity(0.85), Theme.purpleDeep, Theme.purpleNight],
                           startPoint: .topTrailing, endPoint: .bottomLeading),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
    }

    private func heroStat(_ label: String, _ value: String, sub: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .type(.caption)
                .foregroundStyle(.white.opacity(0.7))
            Text(value)
                .type(.codeSmall).monospacedDigit()
                .foregroundStyle(.white)
                .lineLimit(1).minimumScaleFactor(0.6)
            if let sub {
                Text(sub)
                    .type(.caption)
                    .foregroundStyle(.white.opacity(0.6))
            }
        }
    }

    // MARK: Sections

    private func bigCount(_ n: Int, _ suffix: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("\(n)").type(.code).monospacedDigit().foregroundStyle(.white)
            Text(suffix).type(.title).foregroundStyle(Theme.textSecondary)
        }
    }

    private func sectionTitle(_ t: String) -> some View {
        Text(t).type(.title3).foregroundStyle(.white)
    }

    private func section<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10, content: content)
            .padding(.top, 16)
            .overlay(alignment: .top) { Rectangle().fill(Theme.divider).frame(height: 0.5) }
    }

    private func companiesSection(_ s: RentalSummary) -> some View {
        section {
            sectionTitle("Top Rental Companies")
            bigCount(s.byCompany.count, s.byCompany.count == 1 ? "company" : "total companies")
            Chart(s.byCompany) { row in
                BarMark(x: .value("Rentals", row.count),
                        y: .value("Company", RentalBrand.forCompany(row.company).name))
                    .foregroundStyle(Theme.purple)
                    .cornerRadius(4)
                    .annotation(position: .trailing) {
                        Text("\(row.count)")
                            .type(.timeSmall).monospacedDigit()
                            .foregroundStyle(Theme.textSecondary)
                    }
            }
            .chartXAxis(.hidden)
            .chartYAxis {
                AxisMarks { _ in
                    AxisValueLabel().font(TType.font(.calloutStrong)).foregroundStyle(.white)
                }
            }
            .frame(height: CGFloat(s.byCompany.count) * 30 + 10)

            VStack(spacing: 8) {
                ForEach(s.byCompany) { row in
                    HStack(spacing: 10) {
                        CompanyBadge(company: row.company, size: 26)
                        Text(RentalBrand.forCompany(row.company).name)
                            .type(.calloutStrong).foregroundStyle(.white)
                        Spacer()
                        Text("\(Fmt.number(row.days)) days")
                            .type(.timeSmall).monospacedDigit().foregroundStyle(Theme.textSecondary)
                        Text(Fmt.money(row.spend, "USD", decimals: false))
                            .type(.calloutStrong).monospacedDigit()
                            .foregroundStyle(Theme.green)
                            .frame(width: 76, alignment: .trailing)
                    }
                }
            }
            .padding(.top, 4)
        }
    }

    private func weekdaySection(_ rentals: [ApiRentalCar]) -> some View {
        let cal = Calendar.current
        let symbols = cal.shortWeekdaySymbols
        var counts = Array(repeating: 0, count: 7)
        for r in rentals where !r.isApproximate {
            if let d = r.pickupDate { counts[cal.component(.weekday, from: d) - 1] += 1 }
        }
        let data = (0..<7).map { (day: symbols[$0], count: counts[$0]) }
        let busiest = data.max { $0.count < $1.count }
        return section {
            sectionTitle("Pickups by Weekday")
            if let busiest, busiest.count > 0 {
                Text("You usually pick up on \(cal.weekdaySymbols[symbols.firstIndex(of: busiest.day) ?? 0])s")
                    .type(.callout).foregroundStyle(Theme.textSecondary)
            }
            Chart(data, id: \.day) { item in
                BarMark(x: .value("Day", item.day), y: .value("Pickups", item.count))
                    .foregroundStyle(item.day == busiest?.day ? Theme.purple : Theme.purple.opacity(0.45))
                    .cornerRadius(4)
            }
            .chartYAxis {
                AxisMarks(position: .leading) { _ in
                    AxisGridLine().foregroundStyle(Theme.divider)
                    AxisValueLabel().foregroundStyle(Theme.textTertiary)
                }
            }
            .chartXAxis {
                AxisMarks { _ in AxisValueLabel().foregroundStyle(Theme.textSecondary) }
            }
            .frame(height: 150)
        }
    }

    @ViewBuilder
    private func longestShortest(_ rentals: [ApiRentalCar]) -> some View {
        let timed = rentals.filter { !$0.isApproximate && $0.rentalDuration != nil }
            .sorted { ($0.rentalDuration ?? 0) > ($1.rentalDuration ?? 0) }
        if let longest = timed.first, let shortest = timed.last, timed.count > 1 {
            section {
                extremeRow("Longest rental", longest)
                Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.vertical, 4)
                extremeRow("Shortest rental", shortest)
            }
        }
    }

    private func extremeRow(_ title: String, _ r: ApiRentalCar) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).type(.body).foregroundStyle(.white)
            HStack(spacing: 12) {
                CompanyBadge(company: r.rental_company, size: 30)
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(r.pickupDisplayCity)
                        Image(systemName: "arrow.right.circle.fill").type(.footnote)
                        Text(r.dropoffDisplayCity)
                    }
                    .type(.headline).foregroundStyle(.white).lineLimit(1)
                    Text("\(r.vehicleName) · \(r.pickupDate.map(Fmt.monthDayYear) ?? "")")
                        .type(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(1)
                }
                Spacer()
                Text(r.rentalDuration.map(Fmt.duration) ?? "—")
                    .type(.time).monospacedDigit()
                    .foregroundStyle(.white)
            }
        }
    }

    @ViewBuilder
    private func topLocations(_ rentals: [ApiRentalCar]) -> some View {
        let counts = Self.stationCounts(rentals)
        if !counts.isEmpty {
            let top = Array(counts.prefix(8))
            section {
                sectionTitle("Top Pickup Locations")
                bigCount(counts.count, "total locations")
                Chart(top, id: \.code) { item in
                    BarMark(x: .value("Rentals", item.count), y: .value("Station", item.code))
                        .foregroundStyle(Theme.purple)
                        .cornerRadius(4)
                        .annotation(position: .trailing) {
                            Text("\(item.count)")
                                .type(.timeSmall).monospacedDigit()
                                .foregroundStyle(Theme.textSecondary)
                        }
                }
                .chartXAxis(.hidden)
                .chartYAxis {
                    AxisMarks { _ in
                        AxisValueLabel().font(TType.font(.calloutStrong)).foregroundStyle(.white)
                    }
                }
                .frame(height: CGFloat(top.count) * 28 + 10)
            }
        }
    }

    private struct StationCount { let code: String; let count: Int }

    private static func stationCounts(_ rentals: [ApiRentalCar]) -> [StationCount] {
        var tally: [String: Int] = [:]
        for r in rentals where r.pickupCoordinate != nil || r.pickup_code != nil {
            tally[r.pickupDisplayCode, default: 0] += 1
        }
        let rows: [StationCount] = tally.map { StationCount(code: $0.key, count: $0.value) }
        return rows.sorted { a, b in
            if a.count == b.count { return a.code < b.code }
            return a.count > b.count
        }
    }

    private func byYearSection(_ s: RentalSummary) -> some View {
        section {
            sectionTitle("Spend by Year")
            Chart(s.byYear, id: \.year) { item in
                BarMark(x: .value("Year", String(item.year)), y: .value("Spend", item.spend))
                    .foregroundStyle(Theme.purple.gradient)
                    .cornerRadius(5)
                    .annotation(position: .top) {
                        Text("\(item.count)")
                            .type(.label).monospacedDigit()
                            .foregroundStyle(Theme.textSecondary)
                    }
            }
            .chartYAxis {
                AxisMarks(position: .leading) { value in
                    AxisGridLine().foregroundStyle(Theme.divider)
                    AxisValueLabel {
                        if let v = value.as(Double.self) {
                            Text(Fmt.compactMoney(v)).foregroundStyle(Theme.textTertiary)
                        }
                    }
                }
            }
            .chartXAxis {
                AxisMarks { _ in AxisValueLabel().foregroundStyle(Theme.textSecondary) }
            }
            .frame(height: 170)
            Text("Labels show number of rentals")
                .type(.caption).foregroundStyle(Theme.textTertiary)
        }
    }

    private func carsSection(_ s: RentalSummary) -> some View {
        section {
            sectionTitle("Cars You've Driven")
            ForEach(Array(s.topCars.prefix(6).enumerated()), id: \.offset) { idx, car in
                HStack {
                    Text("\(idx + 1)")
                        .type(.calloutStrong).monospacedDigit()
                        .foregroundStyle(Theme.textTertiary)
                        .frame(width: 20, alignment: .leading)
                    Text(car.name)
                        .type(.body).foregroundStyle(.white)
                    Spacer()
                    Text("\(car.count)×")
                        .type(.calloutStrong).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                }
            }
        }
    }

    // MARK: Flights (from /stats/)

    private func flightsCard(_ stats: ApiStats) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("FLIGHTS & TRIPS")
                    .type(.monoLarge)
                Spacer()
                Image(systemName: "airplane")
            }
            .foregroundStyle(.white)
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 14) {
                GridRow {
                    heroStat("Flights", "\(stats.displayFlightCount)")
                    heroStat("Distance", formatMiles(stats.displayFlightMiles) + " mi").gridCellColumns(2)
                }
                GridRow {
                    heroStat("Flight time", formatHours(stats.flights?.duration_minutes ?? 0))
                    heroStat("Airports", "\(stats.displayAirports)")
                    heroStat("Trips", "\(stats.total_trips)")
                }
            }
            HStack {
                Text("Trip expenses")
                Spacer()
                Text(Fmt.money(stats.usdExpenses, "USD", decimals: false)).monospacedDigit().bold()
            }
            .type(.callout)
            .foregroundStyle(.white)
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(Color.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .padding(18)
        .background(
            LinearGradient(colors: [Theme.blue.opacity(0.9), Color(hex: 0x0B2A6B), Color(hex: 0x071436)],
                           startPoint: .topTrailing, endPoint: .bottomLeading),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
        .padding(.top, 8)
    }

    // MARK: Stays (from /stats/ stays block)

    private func staysCard(_ stays: ApiStayStats) -> some View {
        let spend = (stays.total_cost_by_currency ?? [:]).sorted { $0.value > $1.value }
        return VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Text("STAYS")
                    .type(.monoLarge)
                Spacer()
                GlyphImage(glyph: .bed, size: 22, color: .white)
            }
            .foregroundStyle(.white)
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 14) {
                GridRow {
                    heroStat("Nights", "\(stays.nights)")
                    heroStat("Hotels", "\(stays.count)")
                    heroStat("Cities", "\(stays.cities ?? 0)")
                }
            }
            if !spend.isEmpty {
                HStack(alignment: .firstTextBaseline) {
                    Text("Spent on stays")
                    Spacer()
                    Text(spend.prefix(2).map { Fmt.money($0.value, $0.key, decimals: false) }.joined(separator: " + "))
                        .monospacedDigit().bold()
                        .lineLimit(1).minimumScaleFactor(0.7)
                }
                .type(.callout)
                .foregroundStyle(.white)
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(Color.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if let src = stays.top_booking_sources?.first {
                Text("Booked most via \(src.name)")
                    .type(.caption)
                    .foregroundStyle(.white.opacity(0.7))
            }
        }
        .padding(18)
        .background(
            LinearGradient(colors: [Theme.stay.opacity(0.95), Color(hex: 0x8A2E1C), Color(hex: 0x2A0E08)],
                           startPoint: .topTrailing, endPoint: .bottomLeading),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Color.white.opacity(0.12)))
        .padding(.top, 8)
        .accessibilityElement(children: .combine)
    }

    private func formatMiles(_ miles: Double) -> String {
        Fmt.number(miles)
    }

    private func formatHours(_ minutes: Int) -> String {
        guard minutes > 0 else { return "0h" }
        let d = minutes / 1440, h = (minutes % 1440) / 60
        return d > 0 ? "\(d)d \(h)h" : "\(h)h \(minutes % 60)m"
    }
}

struct LogbookSection: View {
    var title: String
    var icon: String
    var color: Color
    var items: [ApiStatItem]

    func imageUrl(for name: String) -> URL? {
        switch name {
        case "Boeing 737":
            return URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f6/B737-800_Southwest_Airlines_N214WN.jpg/320px-B737-800_Southwest_Airlines_N214WN.jpg")
        case "Airbus A320":
            return URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d4/Airbus_A320-200_EasyJet_G-EZTH.jpg/320px-Airbus_A320-200_EasyJet_G-EZTH.jpg")
        case "Boeing 787", "Boeing 787 Dreamliner":
            return URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/All_Nippon_Airways_Boeing_787-8_Dreamliner_JA801A_OKJ_in_flight.jpg/320px-All_Nippon_Airways_Boeing_787-8_Dreamliner_JA801A_OKJ_in_flight.jpg")
        case "Tesla Model 3":
            return URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/9/91/2019_Tesla_Model_3_Performance_AWD_Front.jpg/320px-2019_Tesla_Model_3_Performance_AWD_Front.jpg")
        case "Toyota RAV4":
            return URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/2019_Toyota_RAV4_Cruiser_AWD_hybrid_wagon_%282020-07-25%29_01.jpg/320px-2019_Toyota_RAV4_Cruiser_AWD_hybrid_wagon_%282020-07-25%29_01.jpg")
        default:
            return nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .foregroundStyle(color)
                Text(title.uppercased())
                    .tracking(0.6)
                    .foregroundStyle(Theme.textSecondary)
            }
            .type(.label)
            .padding()

            ForEach(items) { item in
                HStack(spacing: 16) {
                    if let asset = BrandLogos.airline(name: item.name) ?? BrandLogos.rental(item.name) {
                        LogoTile(asset: asset, size: 50)
                    } else if let url = imageUrl(for: item.name) {
                        AsyncImage(url: url) { image in
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Theme.surfaceHigh
                        }
                        .frame(width: 50, height: 50)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    } else {
                        ZStack {
                            RoundedRectangle(cornerRadius: 10)
                                .fill(Theme.surfaceHigh)
                                .frame(width: 50, height: 50)
                            Image(systemName: icon)
                                .foregroundColor(.gray)
                        }
                    }

                    Text(DisplayName.humanize(item.name))
                        .type(.calloutStrong)
                        .foregroundColor(.white)

                    Spacer()

                    Text("\(item.count)x")
                        .type(.callout)
                        .fontWeight(.bold)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(color.opacity(0.2))
                        .foregroundColor(color)
                        .clipShape(Capsule())
                }
                .padding(.horizontal)
                .padding(.vertical, 10)

                if item.id != items.last?.id {
                    Divider().background(Theme.surfaceHigh)
                        .padding(.leading, 82)
                }
            }
        }
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.hairline, lineWidth: 1))
    }
}

struct StatBox: View {
    var title: String
    var value: String

    var body: some View {
        VStack(spacing: 8) {
            Text(value)
                .type(.number)
                .foregroundColor(.white)
                .minimumScaleFactor(0.7)
                .lineLimit(1)
            Text(title)
                .type(.caption)
                .foregroundColor(.gray)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

#Preview {
    StatsView(network: NetworkManager())
}


// MARK: - Your Year (share cards entry)

struct YourYearCard: View {
    let year: ApiYearInTravel?
    let yearNumber: Int
    let onYear: () -> Void
    let onDrivers: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("YOUR \(String(yearNumber))")
                        .type(.label).tracking(1.4)
                        .foregroundStyle(.white.opacity(0.7))
                    Text("Year in Travel")
                        .type(.number)
                        .foregroundStyle(.white)
                }
                Spacer()
                Image(systemName: "sparkles")
                    .type(.title3)
                    .foregroundStyle(.white.opacity(0.85))
            }
            HStack(spacing: 10) {
                mini("\(year?.days_away ?? 0)", "DAYS AWAY")
                mini(year.map { Fmt.number(Double($0.miles)) } ?? "–", "MILES")
                mini("\(year?.cities ?? 0)", "CITIES")
                mini("\(year?.countries ?? 0)", "COUNTRIES")
            }
            HStack(spacing: 10) {
                Button(action: onYear) {
                    Label("Passport card", systemImage: "globe.americas.fill")
                        .frame(maxWidth: .infinity).frame(height: 44)
                        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(.white))
                        .foregroundStyle(Color(hex: 0x2D138F))
                }
                Button(action: onDrivers) {
                    Label("Driver's card", systemImage: "steeringwheel")
                        .frame(maxWidth: .infinity).frame(height: 44)
                        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(.white.opacity(0.16)))
                        .foregroundStyle(.white)
                }
            }
            .type(.calloutStrong)
            .buttonStyle(.plain)
        }
        .padding(18)
        .background(
            ZStack {
                LinearGradient(colors: CardKind.year.gradient, startPoint: .topLeading, endPoint: .bottomTrailing)
                RadialGradient(colors: [Color(hex: 0xE05BFF).opacity(0.35), .clear], center: .topTrailing, startRadius: 0, endRadius: 260)
            }
        )
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(.white.opacity(0.1)))
    }

    private func mini(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).type(.number).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.5)
            Text(label).type(.micro).tracking(0.8).foregroundStyle(.white.opacity(0.6)).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
