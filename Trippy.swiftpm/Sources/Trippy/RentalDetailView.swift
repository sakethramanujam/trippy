import SwiftUI
import MapKit

struct RentalDetailView: View {
    let rental: ApiRentalCar
    @Environment(\.dismiss) private var dismiss
    @State private var detent = min(max(LaunchOptions.detent, 0), 1)
    @State private var sheetHeight: CGFloat = 0
    @State private var calendarDraft: CalendarEventDraft?
    @Environment(\.openURL) private var openURL

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            let now = context.date
            let phase = rental.phase(at: now)
            ZStack {
                Theme.canvas.ignoresSafeArea()
                // Layer 0: full-bleed dark map, route framed above the sheet
                RentalMapView(rental: rental, bottomInset: sheetHeight)
                    .ignoresSafeArea()

                // Layer 1: draggable sheet (half / full)
                DetentSheet(detents: [0.55, 0.93], selection: $detent, visibleHeight: $sheetHeight) {
                    headerView
                } content: {
                    sheet(phase: phase, now: now)
                }
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .toastHost()
        .addToCalendar($calendarDraft)
    }

    private var pickupQuery: String {
        if let c = rental.pickup_code, !c.isEmpty {
            return "\(rental.rental_company) \(Links.airportQuery(c))"
        }
        return [rental.rental_company, rental.pickup_location].joined(separator: ", ")
    }

    private var rentalQuickActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Button { if let u = Links.directions(to: pickupQuery) { openURL(u) } } label: {
                    Label("Directions", systemImage: "car.fill")
                }
                .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                Button {
                    guard let a = rental.pickupDate else { return }
                    var notes = [rental.rental_company + (rental.car_model.map { " · \($0)" } ?? "")]
                    if let c = rental.confirmationText { notes.append("Confirmation: \(c)") }
                    notes.append("Return: \(rental.dropoff_location)")
                    calendarDraft = CalendarEventDraft(title: "🚗 \(rental.rental_company) pickup", start: a,
                                                       end: a.addingTimeInterval(30 * 60), location: rental.pickup_location,
                                                       notes: notes.joined(separator: "\n"))
                } label: { Label("Add to Calendar", systemImage: "calendar.badge.plus") }
                    .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                    .disabled(rental.pickupDate == nil)
            }
            let phones = Links.phones(in: [rental.notes, rental.pickup_location].compactMap { $0 }.joined(separator: "\n"))
            ForEach(phones.prefix(2), id: \.self) { PhoneLink(number: $0) }
        }
    }

    private var headerView: some View {
            HStack(spacing: 12) {
                CompanyBadge(company: rental.rental_company, size: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(headerMicro)
                        .type(.footnoteStrong).monospacedDigit()
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    Text(routeTitle)
                        .type(.title3)
                        .foregroundStyle(.white)
                        .lineLimit(1).minimumScaleFactor(0.8)
                }
                Spacer(minLength: 8)
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .type(.headline)
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(Theme.surfaceRaised, in: Circle())
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, Theme.pagePadding)
            .padding(.top, 2).padding(.bottom, 12)
    }

    private func sheet(phase: RentalPhase, now: Date) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            statusBanner(phase: phase, now: now)
            rentalQuickActions

            // Timeline: pickup → return
            VStack(alignment: .leading, spacing: 0) {
                endpointBlock(icon: "arrow.up.right.circle.fill",
                              code: rental.pickupDisplayCode, place: rental.pickupDisplayCity,
                              date: rental.pickupDate,
                              color: phase == .upcoming ? .white : Theme.green,
                              highlight: pickupHighlight)
                HStack(spacing: 8) {
                    Image(systemName: "clock")
                    Text(middleCaption)
                    Rectangle().fill(Theme.divider).frame(height: 1)
                }
                .type(.footnote).monospacedDigit()
                .foregroundStyle(Theme.textTertiary)
                .padding(.vertical, 14)
                endpointBlock(icon: "arrow.down.right.circle.fill",
                              code: rental.dropoffDisplayCode, place: rental.dropoffDisplayCity,
                              date: rental.dropoffDate,
                              color: phase == .returned ? Theme.green : (phase == .overdue ? Theme.red : .white),
                              highlight: returnHighlight)
            }

            if phase == .active || phase == .overdue {
                VStack(alignment: .leading, spacing: 6) {
                    RouteProgressBar(progress: rental.progress(at: now), color: phase.color)
                    Text(rental.countdown(at: now))
                        .type(.calloutStrong).monospacedDigit()
                        .foregroundStyle(phase.color)
                }
            }

            vehicleCard

            Text("Good to Know")
                .type(.title2)
                .foregroundStyle(.white)
                .padding(.top, 4)
            goodToKnowGrid

            timetable

            if let notes = rental.notes, !notes.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("NOTES")
                        .type(.label).tracking(0.5)
                        .foregroundStyle(Theme.textSecondary)
                    Text(notes)
                        .type(.callout)
                        .foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .outlinedCard()
            }
            Color.clear.frame(height: 110)
        }
        .padding(.horizontal, Theme.pagePadding)
        .padding(.top, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var headerMicro: String {
        var parts = [RentalBrand.forCompany(rental.rental_company).name.uppercased()]
        if let conf = rental.confirmationText { parts.append(conf) }
        if let d = rental.pickupDate { parts.append(Fmt.day(d).uppercased()) }
        return parts.joined(separator: " • ")
    }

    private var routeTitle: String {
        rental.isOneWay ? "\(rental.pickupDisplayCity) to \(rental.dropoffDisplayCity)" : rental.vehicleName
    }

    private var middleCaption: String {
        var parts: [String] = []
        if let dur = rental.rentalDuration { parts.append(Fmt.duration(dur)) }
        if let mi = rental.milesDriven { parts.append(Fmt.number(mi) + " mi") }
        if rental.isApproximate { parts.append("receipt date") }
        return parts.isEmpty ? "Rental" : parts.joined(separator: " • ")
    }

    private var pickupHighlight: (icon: String, text: String, caption: String)? {
        if let plate = rental.license_plate, !plate.isEmpty { return ("car.fill", plate, "Plate") }
        if let cls = DisplayName.vehicleClass(rental.vehicle_class) {
            let short = cls.split(separator: "/").first.map { $0.trimmingCharacters(in: .whitespaces) } ?? cls
            return ("key.fill", short, "Class")
        }
        return nil
    }

    private var returnHighlight: (icon: String, text: String, caption: String)? {
        if let mi = rental.milesDriven { return ("gauge.with.needle.fill", Fmt.number(mi), "Miles driven") }
        if let cost = rental.costText { return ("creditcard.fill", cost, "Total") }
        return nil
    }

    // Green / blue / red banner, like an "Arrived 21m early" bar.
    private func statusBanner(phase: RentalPhase, now: Date) -> some View {
        let color: Color = {
            switch phase {
            case .returned: return Theme.green
            case .active: return Theme.blue
            case .upcoming: return Theme.amber
            case .overdue: return Theme.red
            }
        }()
        let title: Text = {
            switch phase {
            case .returned:
                return Text("Returned ") + Text(rental.rentalDays.map { $0 == 1 ? "· 1 day" : "· \($0) days" } ?? "").bold()
            default:
                return Text(rental.countdown(at: now)).bold()
            }
        }()
        var sub: [String] = []
        if let dur = rental.rentalDuration { sub.append("Total \(Fmt.duration(dur))") }
        if let mi = rental.milesDriven { sub.append(Fmt.number(mi) + " mi") }
        if let cost = rental.costText { sub.append(cost) }
        return VStack(alignment: .leading, spacing: 3) {
            title.type(.headline).monospacedDigit()
            if !sub.isEmpty {
                Text(sub.joined(separator: " • "))
                    .type(.timeSmall).monospacedDigit()
                    .opacity(0.85)
            }
        }
        .foregroundStyle(color)
        .padding(.horizontal, 16).padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.16), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(color.opacity(0.25), lineWidth: 1))
    }

    private func endpointBlock(icon: String, code: String, place: String, date: Date?, color: Color,
                               highlight: (icon: String, text: String, caption: String)?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: icon).type(.callout)
                Text("\(code) • \(place)")
                    .lineLimit(1)
            }
            .type(.headline)
            .foregroundStyle(.white)

            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 2) {
                    if let date {
                        Text(rental.isApproximate ? Fmt.monthDay(date) : Fmt.time(date))
                            .type(.code).monospacedDigit()
                            .foregroundStyle(color)
                            .lineLimit(1).minimumScaleFactor(0.7)
                        Text(rental.isApproximate ? "Approximate · \(Fmt.dayYear(date))" : Fmt.dayYear(date))
                            .type(.calloutStrong)
                            .foregroundStyle(color == .white ? Theme.textSecondary : color)
                    } else {
                        Text("Time not recorded")
                            .type(.title2)
                            .foregroundStyle(Theme.textSecondary)
                            .lineLimit(1).minimumScaleFactor(0.8)
                        Text("Not in the booking email")
                            .type(.calloutStrong)
                            .foregroundStyle(Theme.textTertiary)
                    }
                }
                Spacer(minLength: 8)
                if let h = highlight {
                    VStack(alignment: .trailing, spacing: 4) {
                        HighlightBlock(systemImage: h.icon, text: h.text)
                        Text(h.caption)
                            .type(.footnote)
                            .foregroundStyle(Theme.textSecondary)
                    }
                }
            }
        }
    }

    // MARK: Good to know (2-col outlined cards)

    private var goodToKnowGrid: some View {
        let items: [(icon: String, title: String, value: String?)] = [
            ("ticket", "Confirmation", rental.confirmation_number),
            ("doc.text", "Agreement", rental.agreement_number),
            ("creditcard", "Total", rental.costText),
            ("calendar", "Per Day", perDay),
            ("car", "Class", DisplayName.vehicleClass(rental.vehicle_class).map { $0.split(separator: "/").first.map { $0.trimmingCharacters(in: .whitespaces) } ?? $0 }),
            ("fuelpump", "Fuel", DisplayName.fuel(rental.fuel_type)),
            ("road.lanes", "Distance", rental.milesDriven.map { Fmt.number($0) + " mi" }),
            ("tray.and.arrow.down", "Source", DisplayName.bookingSource(rental.booking_source)),
        ]
        let shown = items.compactMap { item -> (String, String, String)? in
            guard let v = item.value, !v.isEmpty else { return nil }
            return (item.icon, item.title, v)
        }
        return LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
            ForEach(shown, id: \.1) { icon, title, value in
                VStack(alignment: .leading, spacing: 10) {
                    Image(systemName: icon)
                        .type(.body)
                        .foregroundStyle(.white)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title)
                            .type(.headline)
                            .foregroundStyle(.white)
                        Text(value)
                            .type(.timeSmall).monospacedDigit()
                            .foregroundStyle(title == "Total" ? Theme.green : Theme.textSecondary)
                            .lineLimit(1).minimumScaleFactor(0.7)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .outlinedCard()
                .contentShape(Rectangle())
                .onTapGesture { if title == "Confirmation" || title == "Agreement" { Toasts.copy(value, label: title) } }
                .accessibilityAddTraits(title == "Confirmation" || title == "Agreement" ? .isButton : [])
                .accessibilityHint(title == "Confirmation" || title == "Agreement" ? "Double-tap to copy" : "")
            }
        }
    }

    // MARK: Timetable

    private var timetable: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Detailed Timetable")
                .type(.title3)
                .foregroundStyle(.white)
            timetableRow("Pickup", rental.pickupDate)
            Rectangle().fill(Theme.divider).frame(height: 1)
            timetableRow("Return", rental.dropoffDate)
            if let p = rental.pickup_odometer {
                Rectangle().fill(Theme.divider).frame(height: 1)
                HStack {
                    Text("Odometer").foregroundStyle(Theme.textSecondary)
                    Spacer()
                    Text("\(Fmt.number(p)) → \(rental.dropoff_odometer.map(Fmt.number) ?? "—") mi")
                        .foregroundStyle(.white)
                }
                .type(.timeSmall).monospacedDigit()
            }
        }
        .outlinedCard()
    }

    private func timetableRow(_ label: String, _ date: Date?) -> some View {
        HStack {
            Text(label).foregroundStyle(Theme.textSecondary)
            Spacer()
            if let date {
                Text(rental.isApproximate ? "≈ " + Fmt.monthDayYear(date) : "\(Fmt.dayYear(date)) · \(Fmt.time(date))")
                    .foregroundStyle(.white)
            } else {
                Text("—").foregroundStyle(Theme.textTertiary)
            }
        }
        .type(.timeSmall).monospacedDigit()
    }

    // MARK: Vehicle

    private var vehicleCard: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text("VEHICLE")
                    .type(.label).tracking(0.6)
                    .foregroundStyle(Theme.textSecondary)
                Text(rental.vehicleName)
                    .type(.title2)
                    .foregroundStyle(.white)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                if !rental.vehicleSubtitle.isEmpty {
                    Text(rental.vehicleSubtitle)
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(2)
                }
                if let plate = rental.license_plate, !plate.isEmpty {
                    Text(plate)
                        .type(.mono)
                        .foregroundStyle(.black)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(Color.white, in: RoundedRectangle(cornerRadius: 5))
                        .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
            if let s = rental.photo_url, let url = URL(string: s) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFill()
                    default:
                        carPlaceholder
                    }
                }
                .frame(width: 124, height: 88)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            } else {
                carPlaceholder.frame(width: 124, height: 88)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
        .outlinedCard()
    }

    private var carPlaceholder: some View {
        ZStack {
            Theme.surfaceRaised
            Image(systemName: "car.side.fill")
                .type(.largeTitle)
                .foregroundStyle(RentalBrand.forCompany(rental.rental_company).color.opacity(0.9))
        }
    }

    private var perDay: String? {
        guard let cost = rental.cost, let days = rental.rentalDays, days > 0 else { return nil }
        return Fmt.money(cost / Double(days), rental.currency)
    }
}

// MARK: - Timeline row

private struct TimelineRow: View {
    let title: String
    let date: Date?
    let approximate: Bool
    let place: String?
    let detail: String?
    let done: Bool
    let color: Color
    let isLast: Bool
    var isNow: Bool = false

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                ZStack {
                    Circle().fill(done ? color : Theme.surfaceHigh).frame(width: 14, height: 14)
                    if !done { Circle().strokeBorder(color, lineWidth: 2).frame(width: 14, height: 14) }
                    if isNow { Circle().fill(color.opacity(0.25)).frame(width: 26, height: 26) }
                }
                .frame(width: 26, height: 20)
                if !isLast {
                    Rectangle()
                        .fill(done ? color.opacity(0.6) : Theme.divider)
                        .frame(width: 2)
                        .frame(maxHeight: .infinity)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(title)
                        .type(.calloutStrong)
                        .foregroundStyle(isNow ? color : .white)
                    Spacer()
                    if let date, !isNow {
                        Text(approximate ? "≈ " + Fmt.monthDayYear(date) : Fmt.time(date))
                            .type(.calloutStrong).monospacedDigit()
                            .foregroundStyle(.white)
                    }
                }
                if let date, !isNow, !approximate {
                    Text(Fmt.dayYear(date))
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                }
                if let place {
                    Text(place)
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let detail {
                    Text(detail)
                        .type(.caption).monospacedDigit()
                        .foregroundStyle(Theme.textTertiary)
                }
            }
            .padding(.bottom, isLast ? 0 : 18)
        }
    }
}

// MARK: - Map

struct RentalMapView: View {
    let rental: ApiRentalCar
    var bottomInset: CGFloat = 0
    @State private var camera: MapCameraPosition = .automatic

    private var coords: [CLLocationCoordinate2D] {
        [rental.pickupCoordinate, rental.isOneWay ? rental.dropoffCoordinate : nil].compactMap { $0 }
    }

    var body: some View {
        if let start = rental.pickupCoordinate {
            let end = rental.dropoffCoordinate ?? start
            Map(position: $camera, interactionModes: [.zoom, .pan]) {
                MapDimmer()
                if rental.isOneWay {
                    GlowRoute(coords: [start, end], geodesic: false)
                }
                Annotation("", coordinate: start, anchor: .leading) {
                    callout(city: rental.pickupDisplayCity, code: rental.pickupDisplayCode)
                }
                if rental.isOneWay {
                    Annotation("", coordinate: end, anchor: .leading) {
                        callout(city: rental.dropoffDisplayCity, code: rental.dropoffDisplayCode)
                    }
                }
            }
            .mapStyle(MapLook.style)
            .environment(\.colorScheme, .dark)
            .autoFit($camera, coords: coords, minMeters: 12_000, padding: 0.3, top: 70, bottom: bottomInset + 10, side: 40)
        } else {
            ZStack {
                LinearGradient(colors: [Theme.surfaceRaised, Theme.surface], startPoint: .top, endPoint: .bottom)
                VStack(spacing: 8) {
                    Image(systemName: "map")
                        .type(.title)
                        .foregroundStyle(Theme.textTertiary)
                    Text(rental.isApproximate ? "Receipt only — no station recorded" : "No location on file")
                        .type(.footnote)
                        .foregroundStyle(Theme.textSecondary)
                }
            }
        }
    }

    /// Blue dot + "City CODE" label, like a route endpoint on a flight map.
    private func callout(city: String, code: String) -> some View {
        HStack(spacing: 6) {
            Circle().fill(Theme.blue).frame(width: 12, height: 12)
                .overlay(Circle().strokeBorder(.white, lineWidth: 2))
            HStack(spacing: 0) {
                Text(city).padding(.horizontal, 6)
                Text(code).padding(.horizontal, 6)
                    .background(Color.white.opacity(0.18))
            }
            .type(.footnoteStrong)
            .foregroundStyle(.white)
            .padding(.vertical, 3)
            .background(Theme.blue, in: RoundedRectangle(cornerRadius: 5))
            .clipShape(RoundedRectangle(cornerRadius: 5))
        }
    }

    private func pin(icon: String, color: Color) -> some View {
        ZStack {
            Circle().fill(color.opacity(0.25)).frame(width: 34, height: 34)
            Circle().fill(color).frame(width: 22, height: 22)
            Image(systemName: icon).type(.micro).foregroundStyle(.white)
        }
    }
}
