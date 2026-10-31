import SwiftUI
import UIKit

// MARK: - Email-in: forward bookings to your server's Trippy address (GET /inbound/…)

struct ApiInboundSettings: Decodable {
    var enabled: Bool
    var mode: String
    var address: String?
    var sender_match: Bool
    var account_email: String?
    var message: String
}

struct ApiInboundItem: Decodable, Hashable {
    var kind: String
    var id: Int?
    var trip_id: Int?
    var reason: String?
    var summary: String?
}

struct ApiInboundPart: Decodable, Hashable {
    var part: String
    var found: Int
    var note: String?
}

struct ApiInboundEmail: Decodable, Identifiable, Hashable {
    var id: Int
    var subject: String?
    var sender: String?
    var received_at: String?
    var status: String
    var routed_by: String?
    var error: String?
    var seen: Bool
    var attempts: Int
    var can_retry: Bool
    var created: [ApiInboundItem]
    var skipped: [ApiInboundItem]
    var new_trip_ids: [Int]
    var parts: [ApiInboundPart]

    var statusColor: Color {
        switch status {
        case "imported": return Theme.green
        case "failed": return Theme.red
        case "duplicate", "nothing_found": return Theme.textSecondary
        default: return Theme.orange
        }
    }

    var statusText: String {
        switch status {
        case "imported": return "Added \(created.count) item\(created.count == 1 ? "" : "s")"
        case "duplicate": return "Already imported"
        case "failed": return "Couldn't import"
        case "nothing_found": return "No bookings found"
        case "pending": return "Waiting"
        default: return status.capitalized
        }
    }
}

struct ApiInboundUnread: Decodable { var unread: Int; var failed: Int }

extension NetworkManager {
    func fetchInboundSettings(regenerate: Bool = false) async -> ApiInboundSettings? {
        let r: (data: Data?, status: Int, error: String?)
        if regenerate { r = await send("POST", "/inbound/address/regenerate") } else { r = await send("GET", "/inbound/settings") }
        let s = r.data.flatMap { try? JSONDecoder().decode(ApiInboundSettings.self, from: $0) }
        if let s { inboundEnabled = s.enabled }
        return s
    }

    func fetchInboundEmails() async -> Result<[ApiInboundEmail], StoryError> {
        let r = await send("GET", "/inbound/emails")
        if let err = r.error { return .failure(StoryError(message: err)) }
        do { return .success(try JSONDecoder().decode([ApiInboundEmail].self, from: r.data ?? Data())) }
        catch { return .failure(StoryError(message: "Couldn't read the list: \(error.localizedDescription)")) }
    }

    func refreshInboundBadge() async {
        let r = await send("GET", "/inbound/emails/unread")
        if let d = r.data, let u = try? JSONDecoder().decode(ApiInboundUnread.self, from: d) { inboundUnread = u.unread }
    }

    func markInboundSeen() async {
        _ = await send("POST", "/inbound/emails/seen")
        inboundUnread = 0
    }

    func retryInbound(_ id: Int) async -> (ApiInboundEmail?, String?) {
        let r = await send("POST", "/inbound/emails/\(id)/retry")
        let e = r.data.flatMap { try? JSONDecoder().decode(ApiInboundEmail.self, from: $0) }
        if e != nil { await fetchTrips(); await fetchFlights(); await fetchRentals() }
        return (e, r.error)
    }

    func deleteInbound(_ id: Int) async -> String? {
        await send("DELETE", "/inbound/emails/\(id)").error
    }
}

// MARK: - Profile card: your forwarding address

struct InboundAddressCard: View {
    @ObservedObject var network: NetworkManager
    @State private var settings: ApiInboundSettings?
    @State private var copied = false
    @State private var confirmRegenerate = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "envelope.badge.fill").type(.headline).foregroundStyle(settings?.enabled == true ? Theme.blue : Theme.textTertiary)
                Text("Forward bookings").type(.headline).foregroundStyle(.white)
                Spacer()
                if let s = settings, s.enabled { GrayChip(text: s.mode.uppercased()) }
            }
            if let s = settings {
                if let address = s.address, s.enabled {
                    Text(address)
                        .type(.mono).foregroundStyle(.white)
                        .textSelection(.enabled)
                        .lineLimit(2).minimumScaleFactor(0.7)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.surfaceHigh, in: RoundedRectangle(cornerRadius: 10))
                    HStack(spacing: 10) {
                        Button {
                            UIPasteboard.general.string = address
                            copied = true
                            Haptics.success()
                        } label: { Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc") }
                            .buttonStyle(TintedButtonStyle(tint: Theme.blue))
                        Button { confirmRegenerate = true } label: { Label("New address", systemImage: "arrow.clockwise") }
                            .buttonStyle(TintedButtonStyle(tint: Theme.textSecondary))
                    }
                }
                Text(s.message).type(.footnote).foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if s.enabled, s.sender_match, let me = s.account_email {
                    Text("Mail sent from \(me) is also accepted.").type(.caption).foregroundStyle(Theme.textTertiary)
                }
            } else {
                ProgressView().tint(.white)
            }
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16))
        .task { settings = await network.fetchInboundSettings() }
        .confirmationDialog("Make a new address?", isPresented: $confirmRegenerate, titleVisibility: .visible) {
            Button("New address", role: .destructive) {
                Task { if let s = await network.fetchInboundSettings(regenerate: true) { settings = s; copied = false } }
            }
        } message: {
            Text("The old address stops working right away. Use this if it leaked or you're getting spam.")
        }
    }
}

// MARK: - Forwarded emails log

struct ForwardedEmailsView: View {
    @ObservedObject var network: NetworkManager
    @State private var emails: [ApiInboundEmail] = []
    @State private var loading = true
    @State private var errorText: String?
    @State private var busy: Int?
    @State private var expanded: Set<Int> = []

    var body: some View {
        List {
            if !network.inboundEnabled && !loading {
                FormErrorBanner(message: "Email forwarding isn't set up on this server. Older forwarded emails still show here.",
                                tint: Theme.orange, icon: "envelope.badge.shield.half.filled")
                    .listRowBackground(Color.clear)
            }
            if let errorText {
                FormErrorBanner(message: errorText).listRowBackground(Color.clear)
            }
            if emails.isEmpty && !loading {
                EmptyStateCard(systemImage: "tray", title: "No forwarded emails",
                               message: "Forward a booking confirmation, calendar invite, boarding pass or PDF receipt to your Trippy address and it shows up here.")
                    .listRowBackground(Color.clear)
            }
            ForEach(emails) { e in
                row(e)
                    .listRowBackground(Theme.surface)
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) { Task { await delete(e) } } label: { Label("Delete", systemImage: "trash") }
                        if e.can_retry {
                            Button { Task { await retry(e) } } label: { Label("Retry", systemImage: "arrow.clockwise") }
                                .tint(Theme.blue)
                        }
                    }
            }
        }
        .scrollContentBackground(.hidden)
        .background(Theme.canvas)
        .navigationTitle("Forwarded emails")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task {
            if !network.inboundEnabled { _ = await network.fetchInboundSettings() }
            await load()
            await network.markInboundSeen()
        }
        .overlay { if loading && emails.isEmpty { ProgressView().tint(.white) } }
    }

    private func row(_ e: ApiInboundEmail) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if !e.seen { Circle().fill(Theme.blue).frame(width: 8, height: 8) }
                Text(e.subject?.isEmpty == false ? e.subject! : "(no subject)")
                    .type(.headline).foregroundStyle(.white).lineLimit(2)
                Spacer(minLength: 4)
                Text(received(e)).type(.caption).monospacedDigit().foregroundStyle(Theme.textTertiary)
            }
            if let s = e.sender { Text(s).type(.footnote).foregroundStyle(Theme.textSecondary).lineLimit(1) }
            HStack(spacing: 6) {
                Text(e.statusText).type(.label).foregroundStyle(e.statusColor)
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(e.statusColor.opacity(0.15), in: Capsule())
                if !e.new_trip_ids.isEmpty { GrayChip(text: "New trip", systemImage: "suitcase.fill") }
                if e.attempts > 1 { GrayChip(text: "\(e.attempts) tries") }
                Spacer()
                if busy == e.id { ProgressView().controlSize(.small).tint(.white) }
            }
            if let err = e.error, e.status == "failed" {
                Text(err).type(.footnote).foregroundStyle(Theme.red.opacity(0.9))
            }
            if expanded.contains(e.id) { details(e) }
            HStack(spacing: 14) {
                Button(expanded.contains(e.id) ? "Hide details" : "Details") {
                    if expanded.contains(e.id) { expanded.remove(e.id) } else { expanded.insert(e.id) }
                }
                if e.can_retry { Button("Retry") { Task { await retry(e) } } }
                Button("Delete", role: .destructive) { Task { await delete(e) } }
            }
            .type(.footnoteStrong)
            .buttonStyle(.borderless)
            .padding(.top, 2)
        }
        .padding(.vertical, 6)
    }

    @ViewBuilder
    private func details(_ e: ApiInboundEmail) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Array(e.created.enumerated()), id: \.offset) { _, it in
                Label(it.summary ?? it.kind.capitalized, systemImage: "plus.circle.fill")
                    .type(.footnote).foregroundStyle(Theme.green)
            }
            ForEach(Array(e.skipped.enumerated()), id: \.offset) { _, it in
                Label("\(it.summary ?? it.kind.capitalized) — \(it.reason == "deleted" ? "in Recently Deleted" : it.reason ?? "skipped")", systemImage: "minus.circle")
                    .type(.footnote).foregroundStyle(Theme.textSecondary)
            }
            ForEach(Array(e.parts.enumerated()), id: \.offset) { _, p in
                Text("\(p.part): \(p.found) found\(p.note.map { " (\($0))" } ?? "")")
                    .type(.caption).foregroundStyle(Theme.textTertiary)
            }
            if let r = e.routed_by { Text("Matched by \(r)").type(.caption).foregroundStyle(Theme.textTertiary) }
        }
        .padding(.top, 2)
    }

    private func received(_ e: ApiInboundEmail) -> String {
        // received_at is UTC ("…Z"); Fmt.parse reads wall-clock times, so parse it as an instant.
        guard let raw = e.received_at else { return "" }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        guard let d = iso.date(from: raw) ?? plain.date(from: raw) ?? Fmt.parse(raw) else { return "" }
        return d.formatted(.relative(presentation: .named))
    }

    private func load() async {
        loading = true
        defer { loading = false }
        switch await network.fetchInboundEmails() {
        case .success(let list): emails = list; errorText = nil
        case .failure(let e): errorText = e.message
        }
    }

    private func retry(_ e: ApiInboundEmail) async {
        busy = e.id
        defer { busy = nil }
        let (updated, err) = await network.retryInbound(e.id)
        if let err { errorText = err }
        if let updated, let i = emails.firstIndex(where: { $0.id == e.id }) { emails[i] = updated }
    }

    private func delete(_ e: ApiInboundEmail) async {
        if let err = await network.deleteInbound(e.id) { errorText = err; return }
        emails.removeAll { $0.id == e.id }
    }
}
