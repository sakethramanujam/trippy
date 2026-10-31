import SwiftUI

/// Initials in a gradient circle (no photos are stored).
struct InitialsAvatar: View {
    let initials: String
    var size: CGFloat = 36

    var body: some View {
        Text(initials.isEmpty ? "?" : initials)
            .font(.system(size: size * 0.38, weight: .bold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(LinearGradient(colors: [Theme.purple, Theme.blue], startPoint: .topLeading, endPoint: .bottomTrailing),
                        in: Circle())
            .overlay(Circle().strokeBorder(Color.white.opacity(0.15)))
            .accessibilityLabel("Profile")
    }
}

/// Account and app settings: profile, server, import, password, log out, delete account.
struct ProfileView: View {
    @ObservedObject var network: NetworkManager
    @EnvironmentObject private var auth: AuthManager
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var airport = ""
    @State private var saving = false
    @State private var message: (text: String, ok: Bool)?
    @State private var showServer = false
    @State private var showImport = false
    @State private var showJoin = UserDefaults.standard.bool(forKey: "TrippyShowJoin")
    @State private var showPassword = false
    @State private var showDelete = false
    @State private var confirmLogout = false
    @State private var showEmails = UserDefaults.standard.bool(forKey: "TrippyShowEmails")
    @State private var showTrash = UserDefaults.standard.bool(forKey: "TrippyShowTrash")

    private var profile: AuthProfile? { auth.profile }
    private var dirty: Bool {
        guard let p = profile else { return false }
        return name.trimmingCharacters(in: .whitespaces) != p.name || airport.uppercased() != (p.home_airport ?? "")
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.sectionGap) {
                    header
                    if let message {
                        FormErrorBanner(message: message.text, tint: message.ok ? Theme.green : Theme.red,
                                        icon: message.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    }
                    if !auth.claimedOnSignup.isEmpty {
                        FormErrorBanner(message: "Added to your account: " + auth.claimedOnSignup.joined(separator: ", ") + ".",
                                        tint: Theme.green, icon: "tray.and.arrow.down.fill")
                    }
                    if profile != nil { profileCard }
                    InboundAddressCard(network: network)
                    settingsList
                    if profile != nil { accountList }
                    Text("Trippy \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · \(APIConfig.baseURL)")
                        .type(.caption)
                        .foregroundStyle(Theme.textTertiary)
                        .frame(maxWidth: .infinity)
                }
                .padding(.horizontal, Theme.pagePadding + 4)
                .padding(.vertical, 12)
            }
            .trippyScreen()
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .onAppear(perform: load)
            .onChange(of: auth.state) { _, _ in load() }
            .sheet(isPresented: $showServer) {
                ServerSettingsView { Task { await reloadAll() } }
            }
            .sheet(isPresented: $showImport) {
                ImportView(network: network)
            }
            .sheet(isPresented: $showJoin) { JoinInviteSheet(network: network) }
            .navigationDestination(isPresented: $showEmails) { ForwardedEmailsView(network: network) }
            .navigationDestination(isPresented: $showTrash) { RecentlyDeletedView(network: network) }
            .task { await network.refreshInboundBadge() }
            .sheet(isPresented: $showPassword) { ChangePasswordSheet() }
            .sheet(isPresented: $showDelete) { DeleteAccountSheet() }
            .confirmationDialog("Log out of Trippy?", isPresented: $confirmLogout, titleVisibility: .visible) {
                Button("Log out", role: .destructive) { Task { await auth.logOut() } }
            } message: {
                Text("This signs you out on every device.")
            }
            .animation(.default, value: message?.text)
        }
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        HStack(spacing: 16) {
            InitialsAvatar(initials: profile?.initials ?? "DEV", size: 64)
            VStack(alignment: .leading, spacing: 4) {
                Text(profile?.name ?? "Developer mode")
                    .type(.title2)
                    .foregroundStyle(Theme.textPrimary)
                Text(profile?.email ?? "Signed in with TRIPPY_DEV_AUTH_BYPASS")
                    .type(.callout)
                    .foregroundStyle(Theme.textSecondary)
                if let home = profile?.home_airport, !home.isEmpty {
                    InfoChip(value: "Home \(home)", systemImage: "house.fill")
                        .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 8)
    }

    private var profileCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            AuthField(label: "Name", text: $name, placeholder: "Your name", content: .name, capitalize: .words)
            AuthField(label: "Home airport", text: $airport, placeholder: "SFO", capitalize: .characters)
            if dirty {
                Button {
                    Task { await save() }
                } label: { BusyButtonLabel(title: "Save changes", busy: saving) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(saving)
            }
        }
    }

    private var settingsList: some View {
        VStack(spacing: 0) {
            Hairline()
            Button { showImport = true } label: {
                QuickActionTile(icon: "square.and.arrow.down.fill", title: "Import trips", color: Theme.green)
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            Button { showJoin = true } label: {
                QuickActionTile(icon: "ticket.fill", title: "Join with invite code", color: Theme.blue)
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            RemindersToggle(network: network)
            Hairline(leading: 44)
            Button { showEmails = true } label: {
                QuickActionTile(icon: "tray.full.fill", title: "Forwarded emails", color: Theme.purple)
                    .overlay(alignment: .trailing) {
                        if network.inboundUnread > 0 {
                            Text("\(network.inboundUnread)").type(.label).foregroundStyle(.white)
                                .padding(.horizontal, 7).padding(.vertical, 2)
                                .background(Theme.red, in: Capsule())
                                .padding(.trailing, 28)
                        }
                    }
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            Button { showTrash = true } label: {
                QuickActionTile(icon: "trash.fill", title: "Recently Deleted", color: Theme.red)
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            Button { showServer = true } label: {
                QuickActionTile(icon: "server.rack", title: "Server · \(APIConfig.baseURL.replacingOccurrences(of: "http://", with: ""))", color: Theme.blue)
            }.buttonStyle(.plain)
            Hairline()
        }
    }

    private var accountList: some View {
        VStack(spacing: 0) {
            Hairline()
            Button { showPassword = true } label: {
                QuickActionTile(icon: "key.fill", title: "Change password", color: Theme.amber)
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            Button { confirmLogout = true } label: {
                QuickActionTile(icon: "rectangle.portrait.and.arrow.right", title: "Log out", color: Theme.orange)
            }.buttonStyle(.plain)
            Hairline(leading: 44)
            Button { showDelete = true } label: {
                QuickActionTile(icon: "trash.fill", title: "Delete account", color: Theme.red)
            }.buttonStyle(.plain)
            Hairline()
        }
    }

    private func load() {
        name = profile?.name ?? ""
        airport = profile?.home_airport ?? ""
    }

    private func save() async {
        guard AuthValidation.airport(airport.uppercased()) else {
            message = ("Home airport is a 3-letter code, like SFO.", false)
            return
        }
        saving = true
        defer { saving = false }
        do {
            try await auth.updateProfile(name: name.trimmingCharacters(in: .whitespaces), homeAirport: airport)
            message = ("Saved", true)
        } catch {
            message = (error.localizedDescription, false)
        }
    }

    private func reloadAll() async {
        await network.fetchRentals()
        await network.fetchTrips()
        await network.fetchFlights()
        await network.fetchExpenses()
    }
}

private struct ChangePasswordSheet: View {
    @EnvironmentObject private var auth: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var new = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                if let error { FormErrorBanner(message: error) }
                AuthField(label: "Current password", text: $current, secure: true, content: .password)
                AuthField(label: "New password", text: $new, placeholder: "At least 8 characters", secure: true, content: .newPassword)
                Text("Other devices will be signed out.")
                    .type(.footnote)
                    .foregroundStyle(Theme.textSecondary)
                Button {
                    Task {
                        if let p = AuthValidation.passwordProblem(new) { error = p; return }
                        busy = true
                        defer { busy = false }
                        do { try await auth.changePassword(current: current, new: new); dismiss() }
                        catch { self.error = error.localizedDescription }
                    }
                } label: { BusyButtonLabel(title: "Change password", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy || current.isEmpty)
                Spacer()
            }
            .padding(20)
            .trippyScreen()
            .navigationTitle("Change password")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
        .preferredColorScheme(.dark)
    }
}

private struct DeleteAccountSheet: View {
    @EnvironmentObject private var auth: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                FormErrorBanner(message: "This deletes your account, the trips you own, and bookings that aren't on a trip. Shared expenses stay on other people's ledgers as \"Former member\". This can't be undone.",
                                tint: Theme.red, icon: "exclamationmark.octagon.fill")
                if let error { FormErrorBanner(message: error) }
                AuthField(label: "Password", text: $password, secure: true, content: .password)
                Button {
                    Task {
                        busy = true
                        defer { busy = false }
                        do { try await auth.deleteAccount(password: password) }
                        catch { self.error = error.localizedDescription }
                    }
                } label: { BusyButtonLabel(title: "Delete my account", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle(tint: Theme.red))
                    .disabled(busy || password.isEmpty)
                Spacer()
            }
            .padding(20)
            .trippyScreen()
            .navigationTitle("Delete account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.large])
        .preferredColorScheme(.dark)
    }
}


/// Local reminders: check-in opening, 3 hours before departure, and the morning of a hotel check-in.
struct RemindersToggle: View {
    @ObservedObject var network: NetworkManager
    @State private var on = TripReminders.enabled
    @State private var denied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle(isOn: Binding(get: { on }, set: { want in
                Task {
                    if want {
                        on = await TripReminders.requestAndEnable()
                        denied = !on
                        if on { await TripReminders.reschedule(trips: network.trips) }
                    } else {
                        TripReminders.disable(); on = false
                    }
                }
            })) {
                HStack(spacing: Theme.s3) {
                    Image(systemName: "bell.badge.fill").symbolRenderingMode(.hierarchical)
                        .type(.headline).foregroundStyle(Theme.amber).frame(width: 32)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Trip reminders").type(.body).foregroundStyle(.white)
                        Text("Check-in opening, 3h before flights, hotel check-in day").type(.caption).foregroundStyle(Theme.textTertiary)
                    }
                }
            }
            .tint(Theme.green)
            if denied {
                Text("Notifications are off for Trippy. Turn them on in Settings > Notifications.")
                    .type(.caption).foregroundStyle(Theme.amber).padding(.leading, 44)
            }
        }
        .padding(.vertical, 10)
    }
}
