import SwiftUI

// MARK: - Shared flight helpers

extension ApiFlight {
    var departureDate: Date? { Fmt.parse(departure_time) }
    var arrivalDate: Date? { Fmt.parse(arrival_time) }

    func progress(at now: Date) -> Double {
        guard let d = departureDate, let a = arrivalDate, a > d else { return 0 }
        return min(max(now.timeIntervalSince(d) / a.timeIntervalSince(d), 0), 1)
    }

    /// "Departs in 3d 4h" / "Arrives in 2h 10m" / "Landed".
    func countdown(at now: Date) -> String? {
        guard let d = departureDate else { return nil }
        if now < d { return "Departs in " + Fmt.duration(d.timeIntervalSince(now)) }
        if let a = arrivalDate, now < a { return "Arrives in " + Fmt.duration(a.timeIntervalSince(now)) }
        return "Landed"
    }

    var statusColor: Color {
        let s = status.lowercased()
        if s.contains("cancel") { return Theme.red }
        if s.contains("delay") || (delay_minutes ?? 0) > 0 { return Theme.amber }
        if s.contains("land") || s.contains("arriv") { return Theme.textSecondary }
        return Theme.green
    }

    var durationText: String? { duration_minutes.map { Fmt.duration(Double($0) * 60) } }
}

/// Big code over its time and date, aligned to one side of a route.
struct FlightEndpoint: View {
    let code: String
    let date: Date?
    var alignment: HorizontalAlignment = .leading
    var codeStyle: TType = .code

    var body: some View {
        VStack(alignment: alignment, spacing: 2) {
            Text(code)
                .type(codeStyle)
                .foregroundStyle(.white)
                .lineLimit(1).minimumScaleFactor(0.7)
            if let date {
                Text(Fmt.time(date))
                    .type(.timeSmall)
                    .foregroundStyle(.white)
                Text(Fmt.day(date))
                    .type(.caption)
                    .foregroundStyle(Theme.textSecondary)
            }
        }
        .fixedSize()
    }
}

/// Thin route line with a plane glyph that sits at the flight's progress (center before departure).
struct FlightRouteLine: View {
    var progress: Double = 0
    var caption: String?
    var color: Color = Theme.route
    var backdrop: Color = Theme.surface

    var body: some View {
        VStack(spacing: Theme.s1 + 2) {
            GeometryReader { geo in
                let w = geo.size.width
                let p = progress > 0 ? min(max(progress, 0), 1) : 0.5
                ZStack(alignment: .leading) {
                    Rectangle().fill(Theme.textTertiary.opacity(0.7)).frame(height: 0.75)
                    if progress > 0 {
                        Rectangle().fill(color).frame(width: w * p, height: 1.25)
                    }
                    Circle().strokeBorder(Theme.textSecondary, lineWidth: 1).frame(width: 6, height: 6)
                    Circle().fill(Theme.textSecondary).frame(width: 6, height: 6).offset(x: w - 6)
                    Image(systemName: "airplane")
                        .font(TType.glyph(13, .semibold))
                        .foregroundStyle(progress > 0 ? color : Theme.textSecondary)
                        .padding(.horizontal, 5)
                        .background(backdrop)
                        .offset(x: min(max(w * p - 12, 4), max(w - 28, 4)))
                }
                .frame(height: geo.size.height)
                .animation(Theme.gentle, value: p)
            }
            .frame(height: 16)
            if let caption {
                Text(caption)
                    .type(.caption).monospacedDigit()
                    .foregroundStyle(Theme.textTertiary)
                    .lineLimit(1)
            }
        }
    }
}

// MARK: - Flight card (Today)

/// Flighty-style flight card: airline + flight number, two huge codes joined by a thin
/// route line with a plane, times underneath, then the countdown and a few chips.
struct FlightCard: View {
    var flight: ApiFlight
    var now: Date = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s5) {
            HStack(spacing: Theme.s3) {
                AirlineBadge(airline: flight.airline, flightNumber: flight.flight_number, size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text(flight.airline)
                        .type(.headline).foregroundStyle(.white)
                        .lineLimit(1)
                    Text(flight.flight_number)
                        .type(.mono).foregroundStyle(Theme.textSecondary)
                }
                Spacer(minLength: Theme.s2)
                StatusPill(text: DisplayName.flightStatus(flight.status) ?? "Scheduled", color: flight.statusColor)
            }

            HStack(alignment: .top, spacing: Theme.s3) {
                FlightEndpoint(code: flight.departure_airport, date: flight.departureDate, alignment: .leading)
                FlightRouteLine(progress: flight.progress(at: now), caption: flight.durationText)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 14)
                FlightEndpoint(code: flight.arrival_airport, date: flight.arrivalDate, alignment: .trailing)
            }

            if let countdown = flight.countdown(at: now) {
                Hairline()
                HStack(alignment: .firstTextBaseline) {
                    Text(countdown)
                        .type(.calloutStrong).monospacedDigit()
                        .foregroundStyle(.white)
                        .contentTransition(.numericText())
                        .animation(Theme.snappy, value: countdown)
                    Spacer(minLength: Theme.s2)
                    HStack(spacing: Theme.s3) {
                        if let seat = flight.seat { detail("Seat", seat) }
                        if let cabin = DisplayName.cabin(flight.cabin_class) { detail("Cabin", cabin) }
                    }
                    Image(systemName: "chevron.right")
                        .font(TType.glyph(12, .semibold))
                        .foregroundStyle(Theme.textTertiary)
                }
            }
        }
        .card()
    }

    private func detail(_ label: String, _ value: String) -> some View {
        HStack(spacing: 4) {
            Text(label.uppercased()).type(.micro).foregroundStyle(Theme.textTertiary)
            Text(value).type(.footnoteStrong).foregroundStyle(Theme.textSecondary).lineLimit(1)
        }
    }
}

// MARK: - Flight detail

/// Full flight page: status, the route with big codes, departure/arrival blocks,
/// then the facts in hairline rows.
struct FlightDetailView: View {
    let flight: ApiFlight
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var calendarDraft: CalendarEventDraft?
    @State private var tracking = false

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { ctx in
            let now = ctx.date
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: Theme.sectionGap) {
                    header
                    route(now: now)
                    if let countdown = flight.countdown(at: now) {
                        StatusBanner(title: countdown,
                                     subtitle: statusLine,
                                     color: flight.statusColor == Theme.textSecondary ? Theme.textSecondary : flight.statusColor)
                    }
                    times
                    checkIn(now: now)
                    quickActions
                    LiveStatusCard(flight: flight)
                    facts
                    Color.clear.frame(height: Theme.s8)
                }
                .padding(.horizontal, Theme.pagePadding)
                .padding(.top, Theme.s6)
            }
        }
        .background(Theme.canvas.ignoresSafeArea())
        .presentationDragIndicator(.visible)
        .presentationBackground(Theme.canvas)
        .toastHost()
        .addToCalendar($calendarDraft)
        .onAppear {
            if UserDefaults.standard.bool(forKey: "TrippyShowCalendar") { calendarDraft = calendarEvent }
            if UserDefaults.standard.bool(forKey: "TrippyShowToast") { Toasts.copy(flight.confirmation_number ?? "ABC123", label: "Confirmation") }
        }
    }

    // MARK: Check-in + quick actions

    @ViewBuilder private func checkIn(now: Date) -> some View {
        if let c = AirlineCheckIn.countdown(for: flight, at: now), let info = AirlineCheckIn.info(for: flight) {
            Button { openURL(info.url) } label: {
                HStack(spacing: 12) {
                    Image(systemName: c.open ? "checkmark.seal.fill" : "clock.badge")
                        .font(TType.glyph(20, .semibold)).foregroundStyle(c.open ? Theme.green : Theme.amber)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.text).type(.headline).foregroundStyle(.white)
                        Text(info.known ? "\(flight.airline) usually opens check-in \(info.opensHours)h before departure"
                                        : "Search for \(flight.airline) online check-in")
                            .type(.footnote).foregroundStyle(Theme.textSecondary)
                    }
                    Spacer()
                    Text(c.open ? "Check in" : "Open").type(.headline).foregroundStyle(Theme.blue)
                    Image(systemName: "arrow.up.right").font(TType.glyph(12, .semibold)).foregroundStyle(Theme.blue)
                }
            }
            .buttonStyle(.plain)
            .card(padding: Theme.s4)
            .accessibilityHint("Opens the airline's check-in page")
        }
    }

    private var quickActions: some View {
        VStack(spacing: 10) {
        HStack(spacing: 10) {
            Button {
                if let u = Links.directions(to: Links.airportQuery(flight.departure_airport)) { openURL(u) }
            } label: { Label("Directions to \(flight.departure_airport)", systemImage: "car.fill").lineLimit(1).minimumScaleFactor(0.8) }
                .buttonStyle(TintedButtonStyle(tint: Theme.blue))
            Button { calendarDraft = calendarEvent } label: { Label("Add to Calendar", systemImage: "calendar.badge.plus").lineLimit(1).minimumScaleFactor(0.8) }
                .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                .disabled(flight.departureDate == nil)
        }
        if FlightActivity.eligible(flight) && FlightActivity.supported {
            Button {
                if tracking { FlightActivity.stop(flight); tracking = false }
                else if let err = FlightActivity.start(flight) { Toasts.shared.show(err) }
                else { tracking = true; Toasts.shared.show("On your Lock Screen") }
            } label: {
                Label(tracking ? "Stop Lock Screen tracking" : "Track on Lock Screen", systemImage: "platter.filled.bottom.iphone")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(TintedButtonStyle(tint: Theme.green))
            .onAppear { tracking = FlightActivity.isRunning(flight) }
        }
        }
    }

    private var calendarEvent: CalendarEventDraft? {
        guard let dep = flight.departureDate else { return nil }
        var notes = ["\(flight.airline) \(flight.flight_number)"]
        if let c = flight.confirmation_number { notes.append("Confirmation: \(c)") }
        if let s = flight.seat { notes.append("Seat: \(s)") }
        return CalendarEventDraft(title: "✈︎ \(flight.flight_number) \(flight.departure_airport) → \(flight.arrival_airport)",
                                  start: dep, end: flight.arrivalDate ?? dep.addingTimeInterval(2 * 3600),
                                  location: Links.airportQuery(flight.departure_airport), notes: notes.joined(separator: "\n"),
                                  timeZone: Airports.timeZone(flight.departure_airport))
    }

    private var statusLine: String {
        var parts: [String] = [DisplayName.flightStatus(flight.status) ?? "Scheduled"]
        if let d = flight.delay_minutes, d > 0 { parts.append("\(d)m late") }
        return parts.joined(separator: " · ")
    }

    private var header: some View {
        HStack(alignment: .center, spacing: Theme.s3) {
            AirlineBadge(airline: flight.airline, flightNumber: flight.flight_number, size: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(flight.flight_number)
                    .type(.title2)
                    .foregroundStyle(.white)
                Text(flight.airline)
                    .type(.callout)
                    .foregroundStyle(Theme.textSecondary)
            }
            Spacer()
            Button { dismiss() } label: { CircleIcon(systemName: "xmark", size: 32) }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
        }
    }

    private func route(now: Date) -> some View {
        HStack(alignment: .top, spacing: Theme.s3) {
            codeColumn(flight.departure_airport, "Depart", .leading)
            FlightRouteLine(progress: flight.progress(at: now), caption: flight.durationText, backdrop: Theme.canvas)
                .frame(maxWidth: .infinity)
                .padding(.top, 26)
            codeColumn(flight.arrival_airport, "Arrive", .trailing)
        }
    }

    private func codeColumn(_ code: String, _ label: String, _ align: HorizontalAlignment) -> some View {
        VStack(alignment: align, spacing: 2) {
            Text(code)
                .type(.hero)
                .foregroundStyle(.white)
                .lineLimit(1).minimumScaleFactor(0.6)
            MicroLabel(text: label, color: Theme.textTertiary)
        }
        .fixedSize()
    }

    private var times: some View {
        HStack(alignment: .top, spacing: 0) {
            timeBlock("Departs", flight.departureDate, .leading)
            Rectangle().fill(Theme.divider).frame(width: 0.5).padding(.vertical, 4)
            timeBlock("Arrives", flight.arrivalDate, .trailing)
        }
        .card(padding: Theme.s5)
    }

    private func timeBlock(_ label: String, _ date: Date?, _ align: HorizontalAlignment) -> some View {
        VStack(alignment: align, spacing: Theme.s1) {
            MicroLabel(text: label)
            Text(date.map(Fmt.time) ?? "—")
                .type(.time)
                .foregroundStyle(.white)
            Text(date.map(Fmt.dayYear) ?? "Time not set")
                .type(.footnote)
                .foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: Alignment(horizontal: align, vertical: .top))
    }

    private var facts: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            SectionHeader(title: "Flight details")
            VStack(spacing: 0) {
                let rows = factRows
                ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                    if i > 0 { Hairline() }
                    factRow(row)
                }
            }
        }
    }

    private struct Fact { let label: String; let value: String; var mono = false; var copyable = false }

    private var factRows: [Fact] {
        var r: [Fact] = []
        if let c = flight.confirmation_number { r.append(Fact(label: "Confirmation", value: c, mono: true, copyable: true)) }
        if let s = flight.seat { r.append(Fact(label: "Seat", value: s, mono: true)) }
        if let c = DisplayName.cabin(flight.cabin_class) { r.append(Fact(label: "Cabin", value: c)) }
        if let d = flight.durationText { r.append(Fact(label: "Duration", value: d)) }
        if let mi = flight.distance_miles { r.append(Fact(label: "Distance", value: "\(Fmt.number(mi)) mi")) }
        let aircraft = [flight.aircraft_manufacturer, flight.aircraft_model ?? flight.aircraft_type].compactMap { $0 }.joined(separator: " ")
        if !aircraft.isEmpty { r.append(Fact(label: "Aircraft", value: aircraft)) }
        if let cost = flight.cost { r.append(Fact(label: "Fare", value: Fmt.money(cost, flight.currency))) }
        if let src = flight.booking_source { r.append(Fact(label: "Booked via", value: src.capitalized)) }
        r.append(Fact(label: "Flight", value: flight.flight_number, mono: true))
        return r
    }

    private func factRow(_ f: Fact) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(f.label).type(.callout).foregroundStyle(Theme.textSecondary)
            Spacer(minLength: Theme.s3)
            if f.copyable {
                CopyableCode(value: f.value, label: f.label)
            } else {
                Text(f.value)
                    .type(f.mono ? .monoLarge : .headline)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.trailing)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 14)
    }
}
