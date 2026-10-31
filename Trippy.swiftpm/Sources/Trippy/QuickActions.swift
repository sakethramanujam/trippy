import SwiftUI
import UIKit
import EventKit
import EventKitUI

// MARK: - Copy with haptic + toast

@MainActor
final class Toasts: ObservableObject {
    static let shared = Toasts()
    @Published var message: String?
    private var hide: Task<Void, Never>?

    func show(_ text: String) {
        withAnimation(.snappy) { message = text }
        hide?.cancel()
        hide = Task { [weak self] in
            try? await Task.sleep(for: .seconds(UserDefaults.standard.bool(forKey: "TrippyHoldToast") ? 60 : 1.8))
            guard !Task.isCancelled else { return }
            withAnimation(.snappy) { self?.message = nil }
        }
    }

    static func copy(_ value: String, label: String = "Copied") {
        UIPasteboard.general.string = value
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        shared.show("\(label) copied")
    }
}

struct ToastHost: ViewModifier {
    @ObservedObject private var toasts = Toasts.shared
    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            if let m = toasts.message {
                Label(m, systemImage: "checkmark.circle.fill")
                    .type(.headline).foregroundStyle(.white)
                    .padding(.horizontal, 16).padding(.vertical, 11)
                    .background(Theme.surfaceRaised, in: Capsule())
                    .overlay(Capsule().stroke(Theme.divider, lineWidth: 0.5))
                    .padding(.bottom, 28)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .accessibilityAddTraits(.isStaticText)
                    .onAppear { UIAccessibility.post(notification: .announcement, argument: m) }
            }
        }
    }
}

extension View {
    func toastHost() -> some View { modifier(ToastHost()) }
}

/// A confirmation / PNR you can tap anywhere to copy.
struct CopyableCode: View {
    let value: String
    var label = "Confirmation"
    var body: some View {
        Button { Toasts.copy(value, label: label) } label: {
            HStack(spacing: 6) {
                Text(value).type(.monoLarge).foregroundStyle(.white)
                Image(systemName: "doc.on.doc").font(TType.glyph(13, .medium)).foregroundStyle(Theme.blue)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(label) \(value)")
        .accessibilityHint("Double-tap to copy")
    }
}

// MARK: - Maps, phone, directions

enum Links {
    static func maps(_ query: String) -> URL? {
        var c = URLComponents(string: "https://maps.apple.com/")
        c?.queryItems = [URLQueryItem(name: "q", value: query)]
        return c?.url
    }

    static func directions(to destination: String) -> URL? {
        var c = URLComponents(string: "https://maps.apple.com/")
        c?.queryItems = [URLQueryItem(name: "daddr", value: destination), URLQueryItem(name: "dirflg", value: "d")]
        return c?.url
    }

    static func airportQuery(_ code: String) -> String {
        if let city = Airports.city(code) { return "\(code) Airport, \(city)" }
        return "\(code) Airport"
    }

    static func phone(_ text: String) -> URL? {
        let digits = text.filter { $0.isNumber || $0 == "+" }
        return digits.count >= 6 ? URL(string: "tel:\(digits)") : nil
    }

    /// Phone numbers inside free text (notes), via the system detector.
    static func phones(in text: String) -> [String] {
        guard let d = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.phoneNumber.rawValue) else { return [] }
        return d.matches(in: text, range: NSRange(text.startIndex..., in: text)).compactMap(\.phoneNumber)
    }
}

/// Address row that opens Apple Maps; long-press to copy.
struct AddressLink: View {
    let address: String
    @Environment(\.openURL) private var openURL
    var body: some View {
        Button { if let u = Links.maps(address) { openURL(u) } } label: {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(address).type(.headline).foregroundStyle(Theme.blue)
                    .multilineTextAlignment(.trailing).lineLimit(3)
                Image(systemName: "map").font(TType.glyph(12, .medium)).foregroundStyle(Theme.blue)
            }
        }
        .buttonStyle(.plain)
        .contextMenu { Button("Copy address", systemImage: "doc.on.doc") { Toasts.copy(address, label: "Address") } }
        .accessibilityHint("Opens in Maps")
    }
}

struct PhoneLink: View {
    let number: String
    @Environment(\.openURL) private var openURL
    var body: some View {
        Button { if let u = Links.phone(number) { openURL(u) } } label: {
            Label(number, systemImage: "phone.fill").type(.headline).foregroundStyle(Theme.blue)
        }
        .buttonStyle(.plain)
        .accessibilityHint("Calls this number")
    }
}

// MARK: - Add to Calendar (EventKitUI: no calendar permission needed on iOS 17+)

struct CalendarEventDraft: Identifiable {
    let id = UUID()
    var title: String
    var start: Date
    var end: Date
    var location: String?
    var notes: String?
    var timeZone: TimeZone? = nil
}

struct AddToCalendarSheet: UIViewControllerRepresentable {
    let draft: CalendarEventDraft
    var onDone: (Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onDone: onDone) }

    func makeUIViewController(context: Context) -> EKEventEditViewController {
        let store = EKEventStore()
        let event = EKEvent(eventStore: store)
        event.title = draft.title
        event.startDate = draft.start
        event.endDate = max(draft.end, draft.start.addingTimeInterval(15 * 60))
        event.location = draft.location
        event.notes = draft.notes
        event.timeZone = draft.timeZone
        let vc = EKEventEditViewController()
        vc.eventStore = store
        vc.event = event
        vc.editViewDelegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: EKEventEditViewController, context: Context) {}

    final class Coordinator: NSObject, EKEventEditViewDelegate {
        let onDone: (Bool) -> Void
        init(onDone: @escaping (Bool) -> Void) { self.onDone = onDone }
        func eventEditViewController(_ controller: EKEventEditViewController, didCompleteWith action: EKEventEditViewAction) {
            controller.dismiss(animated: true)
            onDone(action == .saved)
        }
    }
}

extension View {
    func addToCalendar(_ draft: Binding<CalendarEventDraft?>) -> some View {
        sheet(item: draft) { d in
            AddToCalendarSheet(draft: d) { saved in
                draft.wrappedValue = nil
                if saved { Toasts.shared.show("Added to Calendar") }
            }
            .ignoresSafeArea()
        }
    }
}

// MARK: - Online check-in

/// Airline check-in pages and when check-in usually opens. Hours are the airline's usual
/// rule; some fares and routes differ, so the UI says "usually".
enum AirlineCheckIn {
    struct Info { let url: URL; let opensHours: Int; let known: Bool }

    private static let table: [String: (String, Int)] = [
        "UA": ("https://www.united.com/en/us/checkin", 24),
        "AA": ("https://www.aa.com/reservation/view/find-your-trip", 24),
        "DL": ("https://www.delta.com/mytrips/", 24),
        "WN": ("https://www.southwest.com/air/check-in/", 24),
        "AS": ("https://www.alaskaair.com/booking/check-in", 24),
        "B6": ("https://www.jetblue.com/check-in", 24),
        "NK": ("https://www.spirit.com/check-in", 24),
        "F9": ("https://www.flyfrontier.com/travel/my-trips/manage-trip/", 24),
        "HA": ("https://www.hawaiianairlines.com/manage-flights/check-in", 24),
        "AC": ("https://www.aircanada.com/us/en/aco/home/app.html#/olci", 24),
        "WS": ("https://www.westjet.com/en-us/check-in", 24),
        "BA": ("https://www.britishairways.com/travel/olcilandingpageauthreq/public/en_us", 24),
        "VS": ("https://www.virginatlantic.com/check-in", 24),
        "LH": ("https://www.lufthansa.com/us/en/online-check-in", 23),
        "AF": ("https://wwws.airfrance.us/check-in", 30),
        "KL": ("https://www.klm.com/check-in", 30),
        "EK": ("https://www.emirates.com/us/english/manage-booking/online-check-in/", 48),
        "QR": ("https://www.qatarairways.com/en/manage-booking/olci.html", 24),
        "SQ": ("https://www.singaporeair.com/en_UK/us/travel-info/check-in/", 48),
        "CX": ("https://www.cathaypacific.com/cx/en_US/manage-booking/check-in.html", 48),
        "NH": ("https://www.ana.co.jp/en/us/guide/boarding-procedures/checkin/online/", 24),
        "JL": ("https://www.jal.co.jp/jp/en/inter/boarding/online/", 24),
        "AI": ("https://www.airindia.com/in/en/manage/web-checkin.html", 48),
        "6E": ("https://www.goindigo.in/check-in.html", 48),
        "TK": ("https://www.turkishairlines.com/en-us/flights/manage-booking/online-check-in/", 24),
        "QF": ("https://www.qantas.com/us/en/travel-info/check-in.html", 24),
        "AM": ("https://aeromexico.com/en-us/web-check-in", 24),
        "IB": ("https://www.iberia.com/us/online-check-in/", 24),
        "EI": ("https://www.aerlingus.com/html/flightSearch.html#/checkin", 30),
    ]

    static func carrier(_ flightNumber: String) -> String {
        let t = flightNumber.trimmingCharacters(in: .whitespaces).uppercased()
        if let sp = t.firstIndex(of: " ") { return String(t[..<sp]) }
        return String(t.prefix(2))
    }

    static func info(for flight: ApiFlight) -> Info? {
        let code = carrier(flight.flight_number)
        if let (s, h) = table[code], let u = URL(string: s) { return Info(url: u, opensHours: h, known: true) }
        var c = URLComponents(string: "https://www.google.com/search")
        c?.queryItems = [URLQueryItem(name: "q", value: "\(flight.airline) online check-in")]
        return c?.url.map { Info(url: $0, opensHours: 24, known: false) }
    }

    /// nil when there's nothing useful to say (far away, or departed).
    static func countdown(for flight: ApiFlight, at now: Date) -> (text: String, open: Bool)? {
        guard let dep = flight.departureDate, let info = info(for: flight) else { return nil }
        let opens = dep.addingTimeInterval(-Double(info.opensHours) * 3600)
        let closes = dep.addingTimeInterval(-45 * 60)
        if now >= closes { return nil }
        if now >= opens { return ("Check-in is open", true) }
        if opens.timeIntervalSince(now) > 7 * 86400 { return nil }
        return ("Check-in opens in " + Fmt.duration(opens.timeIntervalSince(now)), false)
    }

    static func opensAt(_ flight: ApiFlight) -> Date? {
        guard let dep = flight.departureDate, let info = info(for: flight) else { return nil }
        return dep.addingTimeInterval(-Double(info.opensHours) * 3600)
    }
}
