import SwiftUI
import CoreLocation

// MARK: - Timeline row

/// A hotel stay on the trip timeline: bed glyph, property, nights as the hero number,
/// check-in → check-out times, chain badge and cost.
struct StayRow: View {
    let stay: ApiLodging
    let now: Date
    let isLast: Bool

    private var phase: String { stay.phase(at: now) }
    private var dotColor: Color {
        switch phase {
        case "completed": return Theme.green
        case "cancelled": return Theme.textTertiary
        default: return Theme.stay
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                Circle().fill(dotColor)
                    .frame(width: 12, height: 12)
                    .overlay(Circle().strokeBorder(Theme.sheet, lineWidth: 2))
                    .padding(.top, 4)
                Rectangle().fill(isLast ? Color.clear : Theme.divider)
                    .frame(width: 2)
                    .frame(maxHeight: .infinity)
            }
            .frame(width: 14)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    GlyphImage(glyph: .bed, size: 15, color: stay.isCancelled ? Theme.textTertiary : Theme.stay)
                    Text(stay.microLine)
                        .type(.label).tracking(0.4)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if phase == "in_progress" {
                        StatusPill(text: "Checked in", color: Theme.green)
                    } else if stay.isCancelled {
                        StatusPill(text: "Cancelled", color: Theme.red)
                    }
                }

                HStack(alignment: .center, spacing: 12) {
                    HotelBadge(brand: stay.brand, name: stay.name, size: 40)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(stay.name)
                            .type(.headline)
                            .foregroundStyle(.white)
                            .strikethrough(stay.isCancelled, color: Theme.textTertiary)
                            .lineLimit(2).minimumScaleFactor(0.85)
                        if let sub = subline {
                            Text(sub).type(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(1)
                        }
                    }
                    Spacer(minLength: 4)
                    VStack(alignment: .trailing, spacing: 0) {
                        Text("\(stay.nightCount)")
                            .type(.heroSmall)
                            .foregroundStyle(stay.isCancelled ? Theme.textTertiary : .white)
                        Text(stay.nightsLabel.uppercased())
                            .type(.micro)
                            .foregroundStyle(Theme.textSecondary)
                    }
                    .fixedSize()
                }

                HStack(alignment: .top, spacing: 0) {
                    timeColumn("Check in", stay.checkInDate, .leading)
                    Image(systemName: "arrow.right")
                        .font(TType.glyph(11, .bold))
                        .foregroundStyle(Theme.textTertiary)
                        .padding(.top, 18)
                        .frame(width: 28)
                    timeColumn("Check out", stay.checkOutDate, .leading)
                    Spacer(minLength: 6)
                    if let cost = stay.costText {
                        VStack(alignment: .trailing, spacing: 2) {
                            MicroLabel(text: "Total", color: Theme.textTertiary)
                            Text(cost).type(.numberSmall).foregroundStyle(.white)
                        }
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(Color.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .padding(.bottom, isLast ? 4 : 18)

            Image(systemName: "chevron.right")
                .type(.footnoteStrong)
                .foregroundStyle(Theme.textTertiary)
                .padding(.top, 44)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private var subline: String? {
        let parts = [stay.room_type, stay.booking_source.map { "via \($0)" }].compactMap { $0?.isEmpty == false ? $0 : nil }
        return parts.isEmpty ? stay.place : parts.joined(separator: " · ")
    }

    private func timeColumn(_ label: String, _ date: Date?, _ align: HorizontalAlignment) -> some View {
        VStack(alignment: align, spacing: 2) {
            MicroLabel(text: label, color: Theme.textTertiary)
            Text(stay.timeText(date)).type(.timeSmall).foregroundStyle(.white)
            Text(date.map(Fmt.day) ?? "Not set").type(.caption).foregroundStyle(Theme.textSecondary)
        }
        .lineLimit(1)
    }

    private var accessibilityText: String {
        var parts = ["\(stay.name)", "\(stay.nightCount) \(stay.nightsLabel)"]
        if let a = stay.checkInDate { parts.append("check in \(Fmt.day(a)) \(stay.timeText(a))") }
        if let b = stay.checkOutDate { parts.append("check out \(Fmt.day(b)) \(stay.timeText(b))") }
        if let c = stay.costText { parts.append(c) }
        return parts.joined(separator: ", ")
    }
}

// MARK: - Detail sheet

struct StayDetailSheet: View {
    @ObservedObject var network: NetworkManager
    let stayId: Int
    let tripId: Int?
    let initial: ApiLodging
    @Environment(\.dismiss) private var dismiss
    @State private var editing = UserDefaults.standard.bool(forKey: "TrippyEditStay")
    @State private var confirmDelete = false
    @State private var errorText: String?
    @State private var moving = false
    @State private var calendarDraft: CalendarEventDraft?
    @Environment(\.openURL) private var openURL

    init(network: NetworkManager, stay: ApiLodging, tripId: Int?) {
        self.network = network
        self.stayId = stay.id
        self.tripId = tripId
        self.initial = stay
    }

    /// Live copy, so edits show up as soon as the trip reloads.
    private var stay: ApiLodging {
        network.trips.first { $0.id == tripId }?.lodgings.first { $0.id == stayId } ?? initial
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: Theme.sectionGap) {
                    header
                    hero(now: ctx.date)
                    times
                    stayQuickActions
                    facts
                    actions
                    Color.clear.frame(height: Theme.s8)
                }
                .padding(.horizontal, Theme.pagePadding)
                .padding(.top, Theme.s6)
            }
        }
        .background(Theme.canvas.ignoresSafeArea())
        .presentationDragIndicator(.visible)
        .presentationBackground(Theme.canvas)
        .preferredColorScheme(.dark)
        .toastHost()
        .addToCalendar($calendarDraft)
        .sheet(isPresented: $editing) {
            StayFormSheet(network: network, tripId: tripId, editing: stay)
        }
        .sheet(isPresented: $moving) {
            MoveToTripSheet(network: network, items: [ItemRef(kind: .lodging, id: stayId)], fromTrip: tripId) { err in
                if let err { errorText = err } else { dismiss() }
            }
        }
        .alert("Delete this stay?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) {
                Task {
                    if let err = await network.deleteLodging(stayId, tripId: tripId) { errorText = err } else { dismiss() }
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: { Text("\(stay.name) is removed from this trip and your stats.") }
        .alert("Something went wrong", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(errorText ?? "") }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: Theme.s3) {
            HotelBadge(brand: stay.brand, name: stay.name, size: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(stay.name)
                    .type(.title2)
                    .foregroundStyle(.white)
                    .lineLimit(2).minimumScaleFactor(0.8)
                HStack(spacing: 5) {
                    GlyphImage(glyph: .bed, size: 13)
                    Text([stay.brand ?? DisplayName.propertyType(stay.property_type), stay.place].compactMap { $0 }.joined(separator: " · "))
                        .type(.callout)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer()
            Button { dismiss() } label: { CircleIcon(systemName: "xmark", size: 32) }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
        }
    }

    private func hero(now: Date) -> some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
        HStack(alignment: .lastTextBaseline, spacing: 8) {
            Text("\(stay.nightCount)")
                .type(.hero)
                .foregroundStyle(.white)
            Text(stay.nightsLabel)
                .type(.title2)
                .foregroundStyle(Theme.textSecondary)
            Spacer()
            if let cost = stay.costText {
                VStack(alignment: .trailing, spacing: 2) {
                    Text(cost).type(.number).foregroundStyle(.white)
                    if stay.nightCount > 0, let c = stay.cost {
                        Text("\(Fmt.money(c / Double(stay.nightCount), stay.currency, decimals: false)) / night")
                            .type(.caption).foregroundStyle(Theme.textSecondary)
                    }
                }
            }
        }
            StatusBanner(title: statusTitle(now), subtitle: statusSubtitle, color: statusColor(now))
        }
    }

    private func statusTitle(_ now: Date) -> String {
        switch stay.phase(at: now) {
        case "cancelled": return "Cancelled"
        case "in_progress":
            guard let b = stay.checkOutDate else { return "Checked in" }
            let d = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: now),
                                                    to: Calendar.current.startOfDay(for: b)).day ?? 0
            return d <= 0 ? "Check out today" : (d == 1 ? "Check out tomorrow" : "\(d) nights left")
        case "completed": return "Stayed"
        default:
            guard let a = stay.checkInDate else { return "Dates not set" }
            let d = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: now),
                                                    to: Calendar.current.startOfDay(for: a)).day ?? 0
            return d == 0 ? "Check in today" : (d == 1 ? "Check in tomorrow" : "Check in in \(d) days")
        }
    }

    private var statusSubtitle: String? {
        [stay.room_type, stay.guests.map { $0 == 1 ? "1 guest" : "\($0) guests" },
         stay.rooms.flatMap { $0 > 1 ? "\($0) rooms" : nil }].compactMap { $0 }.joined(separator: " · ").nilIfEmpty
    }

    private func statusColor(_ now: Date) -> Color {
        switch stay.phase(at: now) {
        case "cancelled": return Theme.red
        case "in_progress": return Theme.green
        case "completed": return Color(hex: 0xD1D1D6)
        default: return Theme.stay
        }
    }

    private var times: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(alignment: .top, spacing: 0) {
                timeBlock("Check in", stay.checkInDate, .leading)
                Rectangle().fill(Theme.divider).frame(width: 0.5).padding(.vertical, 4)
                timeBlock("Check out", stay.checkOutDate, .trailing)
            }
            if stay.timesApprox {
                Label(stay.time_approx == true
                      ? "The booking only had dates, so these are the hotel's usual times."
                      : "The booking only had dates. Check the hotel for times.",
                      systemImage: "clock.badge.questionmark")
                    .type(.caption).foregroundStyle(Theme.textSecondary)
            }
        }
        .card(padding: Theme.s5)
    }

    private func timeBlock(_ label: String, _ date: Date?, _ align: HorizontalAlignment) -> some View {
        VStack(alignment: align, spacing: Theme.s1) {
            MicroLabel(text: label)
            Text(stay.timeText(date)).type(.time).foregroundStyle(.white)
            Text(date.map(Fmt.dayYear) ?? "Not set").type(.footnote).foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: Alignment(horizontal: align, vertical: .top))
    }

    private enum FactKind { case text, address, phone }
    private struct Fact { let label: String; let value: String; var mono = false; var copyable = false; var kind: FactKind = .text }

    private var factRows: [Fact] {
        var r: [Fact] = []
        if let c = stay.confirmation_number, !c.isEmpty { r.append(Fact(label: "Confirmation", value: c, mono: true, copyable: true)) }
        if let a = stay.address, !a.isEmpty { r.append(Fact(label: "Address", value: a, kind: .address)) }
        for p in Links.phones(in: [stay.notes, stay.address].compactMap { $0 }.joined(separator: "\n")).prefix(2) {
            r.append(Fact(label: "Phone", value: p, kind: .phone))
        }
        if let rt = stay.room_type, !rt.isEmpty { r.append(Fact(label: "Room", value: rt)) }
        if let g = stay.guests { r.append(Fact(label: "Guests", value: "\(g)")) }
        if let c = stay.cost { r.append(Fact(label: "Total", value: Fmt.money(c, stay.currency))) }
        if let t = stay.taxes_fees { r.append(Fact(label: "Taxes & fees", value: Fmt.money(t, stay.currency))) }
        if let s = stay.booking_source, !s.isEmpty { r.append(Fact(label: "Booked via", value: s)) }
        if let p = stay.loyalty_program, !p.isEmpty {
            r.append(Fact(label: "Loyalty", value: p + (stay.loyalty_points.map { " · \(Fmt.number(Double($0))) pts" } ?? "")))
        }
        if let n = stay.notes, !n.isEmpty { r.append(Fact(label: "Notes", value: n)) }
        return r
    }

    @ViewBuilder private var facts: some View {
        let rows = factRows
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: Theme.s3) {
                SectionHeader(title: "Stay details")
                VStack(spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                        if i > 0 { Hairline() }
                        factRow(row)
                    }
                }
            }
        }
    }

    private func factRow(_ f: Fact) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(f.label).type(.callout).foregroundStyle(Theme.textSecondary)
            Spacer(minLength: Theme.s3)
            switch f.kind {
            case .address: AddressLink(address: f.value)
            case .phone: PhoneLink(number: f.value)
            case .text:
                if f.copyable {
                    CopyableCode(value: f.value, label: f.label)
                } else {
                    Text(f.value)
                        .type(f.mono ? .monoLarge : .headline)
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.trailing)
                        .lineLimit(3)
                }
            }
        }
        .padding(.vertical, 14)
    }

    private var stayQuery: String {
        [stay.address?.isEmpty == false ? stay.address! : stay.name, stay.city].compactMap { $0 }.joined(separator: ", ")
    }

    private var stayQuickActions: some View {
        HStack(spacing: 10) {
            Button { if let u = Links.directions(to: stayQuery) { openURL(u) } } label: {
                Label("Directions", systemImage: "car.fill")
            }
            .buttonStyle(TintedButtonStyle(tint: Theme.stay))
            Button {
                guard let a = stay.checkInDate else { return }
                var notes = [stay.name]
                if let c = stay.confirmation_number, !c.isEmpty { notes.append("Confirmation: \(c)") }
                calendarDraft = CalendarEventDraft(title: "🛏 \(stay.name)", start: a,
                                                   end: stay.checkOutDate ?? a.addingTimeInterval(86400),
                                                   location: stayQuery, notes: notes.joined(separator: "\n"),
                                                   timeZone: stay.check_in_tz.flatMap(TimeZone.init(identifier:)))
            } label: { Label("Add to Calendar", systemImage: "calendar.badge.plus") }
                .buttonStyle(TintedButtonStyle(tint: Theme.stay))
                .disabled(stay.checkInDate == nil)
        }
    }

    private var actions: some View {
        HStack(spacing: 10) {
            Button { editing = true } label: { Label("Edit", systemImage: "pencil") }
                .buttonStyle(TintedButtonStyle(tint: Theme.stay))
            Button { moving = true } label: { Label("Move…", systemImage: "arrow.right.doc.on.clipboard") }
                .buttonStyle(TintedButtonStyle(tint: Theme.blue))
            Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
                .buttonStyle(TintedButtonStyle(tint: Theme.red))
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

// MARK: - Add / edit form

struct StayFormSheet: View {
    @ObservedObject var network: NetworkManager
    let tripId: Int?
    var editing: ApiLodging? = nil
    var defaultCheckIn: Date? = nil
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var brand = ""
    @State private var propertyType = "hotel"
    @State private var city = ""
    @State private var country = ""
    @State private var address = ""
    @State private var checkIn = Date()
    @State private var checkOut = Date()
    @State private var confirmation = ""
    @State private var cost = ""
    @State private var currency = "USD"
    @State private var bookingSource = ""
    @State private var roomType = ""
    @State private var guests = 1
    @State private var cancelled = false
    @State private var notes = ""
    @State private var saving = false
    @State private var error: String?
    @State private var loaded = false

    private var nights: Int {
        let cal = Calendar.current
        return max(0, cal.dateComponents([.day], from: cal.startOfDay(for: checkIn), to: cal.startOfDay(for: checkOut)).day ?? 0)
    }

    private var valid: Bool { !name.trimmingCharacters(in: .whitespaces).isEmpty && checkOut > checkIn }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Property name", text: $name, prompt: Text("e.g. Park Hyatt Tokyo"))
                    TextField("Chain", text: $brand, prompt: Text("Chain (optional), e.g. Hyatt"))
                    Picker("Type", selection: $propertyType) {
                        Text("Hotel").tag("hotel"); Text("Rental").tag("rental")
                        Text("Motel").tag("motel"); Text("Hostel").tag("hostel")
                    }
                } header: { formHeader("Property") }

                Section {
                    DatePicker("Check in", selection: $checkIn)
                    DatePicker("Check out", selection: $checkOut, in: checkIn...)
                    HStack {
                        Text("Nights").foregroundStyle(Theme.textSecondary)
                        Spacer()
                        Text("\(nights)").type(.numberSmall).foregroundStyle(Theme.stay)
                    }
                } header: { formHeader("Dates") } footer: {
                    Text("Times are local to the property.")
                }

                Section {
                    TextField("City", text: $city)
                    TextField("Country", text: $country)
                    TextField("Address", text: $address, axis: .vertical)
                } header: { formHeader("Where") } footer: {
                    Text("Used to place the stay on the trip map.")
                }

                Section {
                    TextField("Confirmation", text: $confirmation)
                        .textInputAutocapitalization(.characters).autocorrectionDisabled()
                        .font(TType.font(.mono, size: 16))
                    HStack {
                        TextField("Total cost", text: $cost).keyboardType(.decimalPad)
                        Picker("", selection: $currency) {
                            ForEach(["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "INR", "MXN"], id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden().fixedSize()
                    }
                    TextField("Booked via", text: $bookingSource, prompt: Text("Booked via, e.g. Direct, Booking.com"))
                    TextField("Room", text: $roomType, prompt: Text("Room, e.g. King Deluxe"))
                    Stepper("Guests: \(guests)", value: $guests, in: 1...20)
                } header: { formHeader("Booking") }

                Section {
                    TextField("Notes", text: $notes, axis: .vertical)
                    if editing != nil { Toggle("Cancelled", isOn: $cancelled).tint(Theme.red) }
                }

                if let error {
                    Section { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Theme.red) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.sheet.ignoresSafeArea())
            .navigationTitle(editing == nil ? "Add Stay" : "Edit Stay")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textSecondary)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(saving ? "Saving…" : "Save") { Task { await save() } }
                        .fontWeight(.bold)
                        .disabled(!valid || saving)
                }
            }
            .onAppear(perform: load)
        }
        .tint(Theme.stay)
        .presentationDetents([.large])
        .presentationBackground(Theme.sheet)
        .preferredColorScheme(.dark)
    }

    private func formHeader(_ t: String) -> some View {
        Text(t.uppercased()).type(.label).tracking(0.5).foregroundStyle(Theme.textSecondary)
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        let cal = Calendar.current
        if let s = editing {
            name = s.name; brand = s.brand ?? ""; propertyType = s.property_type ?? "hotel"
            city = s.city ?? ""; country = s.country ?? ""; address = s.address ?? ""
            checkIn = s.checkInDate ?? Date()
            checkOut = s.checkOutDate ?? cal.date(byAdding: .day, value: 1, to: checkIn)!
            confirmation = s.confirmation_number ?? ""
            cost = s.cost.map { $0.rounded() == $0 ? String(Int($0)) : String(format: "%.2f", $0) } ?? ""
            currency = s.currency ?? "USD"; bookingSource = s.booking_source ?? ""; roomType = s.room_type ?? ""
            guests = s.guests ?? 1; cancelled = s.isCancelled; notes = s.notes ?? ""
        } else {
            let day = cal.startOfDay(for: defaultCheckIn ?? Date())
            checkIn = cal.date(bySettingHour: 15, minute: 0, second: 0, of: day) ?? day
            checkOut = cal.date(bySettingHour: 11, minute: 0, second: 0, of: cal.date(byAdding: .day, value: 1, to: day)!) ?? day
        }
    }

    private static let wire: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    private func save() async {
        saving = true
        error = nil
        func opt(_ s: String) -> Any { let t = s.trimmingCharacters(in: .whitespacesAndNewlines); return t.isEmpty ? NSNull() : t }
        var body: [String: Any] = [
            "name": name.trimmingCharacters(in: .whitespaces),
            "brand": opt(brand), "property_type": propertyType,
            "city": opt(city), "country": opt(country), "address": opt(address),
            "check_in": Self.wire.string(from: checkIn), "check_out": Self.wire.string(from: checkOut),
            "nights": nights,
            "confirmation_number": opt(confirmation),
            "currency": currency, "booking_source": opt(bookingSource), "room_type": opt(roomType),
            "guests": guests, "notes": opt(notes),
        ]
        body["cost"] = Double(cost.replacingOccurrences(of: ",", with: "")) ?? NSNull()
        if editing != nil { body["status"] = cancelled ? "cancelled" : NSNull() }
        // Place it on the map: geocode when the place changed or has no coordinate yet.
        let placeChanged = editing.map { ($0.city ?? "") != city || ($0.address ?? "") != address || $0.coordinate == nil } ?? true
        if placeChanged, let c = await geocode() {
            body["lat"] = c.latitude; body["lng"] = c.longitude
        }
        let err: String?
        if let s = editing {
            err = await network.updateLodging(s.id, tripId: tripId, body).1
        } else {
            err = await network.createLodging(tripId: tripId, body).1
        }
        saving = false
        if let err { error = err } else { Haptics.success(); dismiss() }
    }

    private func geocode() async -> CLLocationCoordinate2D? {
        let query = [address.isEmpty ? name : address, city, country].filter { !$0.isEmpty }.joined(separator: ", ")
        guard !query.isEmpty else { return nil }
        let marks = try? await CLGeocoder().geocodeAddressString(query)
        return marks?.first?.location?.coordinate
    }
}
