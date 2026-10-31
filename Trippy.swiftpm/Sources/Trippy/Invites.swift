import SwiftUI
import UIKit

/// One-time invite codes: a placeholder traveler on a trip gets a code from someone on that trip,
/// then uses it at sign-up (or, with an existing account, in Profile > Join with invite code).
struct ApiInviteCode: Decodable {
    var code: String
    var expires_at: String
    var trip_id: Int
    var user_id: Int
    var name: String
}

struct ApiInviteRedeemed: Decodable {
    var trip_id: Int
    var joined: Int
}

extension NetworkManager {
    func issueInviteCode(tripId: Int, userId: Int) async -> (invite: ApiInviteCode?, error: String?) {
        let r = await send("POST", "/trips/\(tripId)/travelers/\(userId)/invite-code")
        if let err = r.error { return (nil, err) }
        return (r.data.flatMap { try? JSONDecoder().decode(ApiInviteCode.self, from: $0) }, nil)
    }

    func redeemInvite(code: String) async -> (result: ApiInviteRedeemed?, error: String?) {
        let r = await send("POST", "/invites/redeem", json: ["code": code.trimmingCharacters(in: .whitespaces)])
        if let err = r.error { return (nil, err) }
        return (r.data.flatMap { try? JSONDecoder().decode(ApiInviteRedeemed.self, from: $0) }, nil)
    }
}

/// Creates (or replaces) a traveler's invite code and offers to copy or share it.
struct InviteCodeSheet: View {
    @ObservedObject var network: NetworkManager
    let tripId: Int
    let tripTitle: String
    let person: ApiParticipant
    @Environment(\.dismiss) private var dismiss
    @State private var invite: ApiInviteCode?
    @State private var error: String?
    @State private var copied = false

    private var expiry: String {
        guard let invite, let d = Fmt.parse(invite.expires_at) else { return "" }
        return d.formatted(.dateTime.month(.abbreviated).day())
    }

    private var shareText: String {
        guard let invite else { return "" }
        return "Join me on \(tripTitle) in Trippy. Server: \(APIConfig.baseURL)\nInvite code: \(invite.code) (single use, expires \(expiry))"
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 18) {
                Text("Send this code to \(person.displayName). They enter it when they create their account, or in Profile > Join with invite code if they already have one. Their trips, stays and expenses on this trip become theirs.")
                    .type(.callout).foregroundStyle(Theme.textSecondary)
                    .multilineTextAlignment(.center)
                if let invite {
                    Text(invite.code)
                        .font(.system(size: 32, weight: .bold, design: .monospaced))
                        .foregroundStyle(Theme.textPrimary)
                        .textSelection(.enabled)
                        .padding(.vertical, 14).frame(maxWidth: .infinity)
                        .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityLabel("Invite code \(invite.code.map { String($0) }.joined(separator: " "))")
                    Text("Single use. Expires \(expiry). Making a new code cancels this one.")
                        .type(.caption).foregroundStyle(Theme.textTertiary)
                    HStack(spacing: 12) {
                        Button {
                            UIPasteboard.general.string = invite.code
                            UINotificationFeedbackGenerator().notificationOccurred(.success)
                            copied = true
                        } label: { Label(copied ? "Copied" : "Copy code", systemImage: copied ? "checkmark" : "doc.on.doc") }
                            .buttonStyle(PrimaryButtonStyle())
                        ShareLink(item: shareText) { Label("Share…", systemImage: "square.and.arrow.up") }
                            .buttonStyle(PrimaryButtonStyle())
                    }
                } else if let error {
                    FormErrorBanner(message: error)
                } else {
                    ProgressView().padding(30)
                }
                Spacer()
            }
            .padding(Theme.pagePadding + 4)
            .trippyScreen()
            .navigationTitle("Invite \(person.firstName)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task {
                let r = await network.issueInviteCode(tripId: tripId, userId: person.id)
                invite = r.invite
                error = r.error ?? (r.invite == nil ? "Couldn't create an invite code." : nil)
            }
        }
        .preferredColorScheme(.dark)
    }
}

/// Profile > Join with invite code: an existing account takes over a placeholder traveler.
struct JoinInviteSheet: View {
    @ObservedObject var network: NetworkManager
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var busy = false
    @State private var error: String?
    @State private var done: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Text("Someone added you to a trip before you had an account, or under another email? Enter the invite code they sent to join it.")
                    .type(.callout).foregroundStyle(Theme.textSecondary)
                if let error { FormErrorBanner(message: error) }
                if let done { FormErrorBanner(message: done, tint: Theme.green, icon: "checkmark.circle.fill") }
                AuthField(label: "Invite code", text: $code, placeholder: "XXXXX-XXXXX", content: .oneTimeCode, capitalize: .characters)
                Button {
                    Task { await submit() }
                } label: { BusyButtonLabel(title: "Join", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy || code.trimmingCharacters(in: .whitespaces).count < 10 || done != nil)
                Spacer()
            }
            .padding(Theme.pagePadding + 4)
            .trippyScreen()
            .navigationTitle("Join with invite code")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .preferredColorScheme(.dark)
    }

    private func submit() async {
        busy = true
        defer { busy = false }
        error = nil
        let r = await network.redeemInvite(code: code)
        if let err = r.error { error = err; return }
        let n = r.result?.joined ?? 1
        done = n == 1 ? "You've joined the trip." : "You've joined \(n) trips."
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        await network.fetchTrips()
    }
}
