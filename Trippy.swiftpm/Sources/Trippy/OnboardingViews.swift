import SwiftUI

// MARK: - Root

/// Shows onboarding until there's a session, then the app. The app is rebuilt per account
/// (`.id`) so nothing from a previous account stays on screen after switching.
struct RootView: View {
    @StateObject private var auth = AuthManager.shared

    var body: some View {
        Group {
            switch auth.state {
            case .signedOut:
                OnboardingFlow()
                    .transition(.opacity)
            case .signedIn(let p):
                MainTabView().id("user-\(p.id)")
                    .transition(.opacity)
            case .devBypass:
                MainTabView().id("bypass")
            }
        }
        .animation(.easeInOut(duration: 0.25), value: auth.state)
        .environmentObject(auth)
        .preferredColorScheme(.dark)
        // Respect Dynamic Type, but stop before hero numbers and codes break their rows.
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .task {
            await auth.reloadProfile()
            #if DEBUG
            // Screenshots/UI checks only: `-TrippyAutoLoginEmail a@b.c -TrippyAutoLoginPassword …`.
            let d = UserDefaults.standard
            if case .signedOut = auth.state,
               let email = d.string(forKey: "TrippyAutoLoginEmail"),
               let password = d.string(forKey: "TrippyAutoLoginPassword") {
                try? await auth.logIn(email: email, password: password)
            }
            #endif
        }
    }
}

struct OnboardingFlow: View {
    enum Step: Hashable { case signUp, logIn, forgot }
    @StateObject private var server = ServerStatus()

    /// `-TrippyOnboarding signup|login|forgot` opens a screen directly (screenshots).
    @State private var path: [Step] = {
        switch UserDefaults.standard.string(forKey: "TrippyOnboarding") {
        case "signup": return [.signUp]
        case "login": return [.logIn]
        case "forgot": return [.logIn, .forgot]
        default: return []
        }
    }()

    var body: some View {
        NavigationStack(path: $path) {
            WelcomeView(signUp: { path.append(.signUp) }, logIn: { path.append(.logIn) })
                .navigationDestination(for: Step.self) { step in
                    switch step {
                    case .signUp: SignUpView(logInInstead: { path = [.logIn] })
                    case .logIn: LogInView(forgot: { path.append(.forgot) }, signUpInstead: { path = [.signUp] })
                    case .forgot: ForgotPasswordView(done: { path = [.logIn] })
                    }
                }
        }
        .environmentObject(server)
        .tint(Theme.blue)
    }
}

// MARK: - Welcome

struct WelcomeView: View {
    var signUp: () -> Void
    var logIn: () -> Void
    @EnvironmentObject private var server: ServerStatus

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            // A faint brand-blue glow behind the route, like a runway at night.
            RadialGradient(colors: [Theme.brand.opacity(0.16), Theme.brand.opacity(0.04), .clear],
                           center: .init(x: 0.5, y: 0.2), startRadius: 10, endRadius: 380)
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 0) {
                TrippyWordmark()
                    .padding(.top, Theme.s4)
                    .opacity(appeared ? 1 : 0)
                Spacer(minLength: Theme.s6)
                WelcomeRouteArt()
                    .frame(height: 150)
                    .padding(.bottom, Theme.s8)
                    .opacity(appeared ? 1 : 0)
                    .offset(y: appeared ? 0 : 12)

                Text("Every trip,\nin one place.")
                    .type(.display)
                    .foregroundStyle(Theme.textPrimary)
                Text("Flights, rental cars, hotels and the money you split, shared with the people you travel with.")
                    .type(.body)
                    .foregroundStyle(Theme.textSecondary)
                    .padding(.top, Theme.s3)

                VStack(alignment: .leading, spacing: Theme.s3) {
                    FeatureRow(icon: "airplane", tint: Theme.blue, text: "Import from Calendar, Flighty and TripIt")
                    FeatureRow(icon: "person.2.fill", tint: Theme.green, text: "Invite travelers by email")
                    FeatureRow(icon: "creditcard.fill", tint: Theme.orange, text: "Split costs and settle up")
                }
                .padding(.top, Theme.s6)
                .opacity(appeared ? 1 : 0)

                Spacer()

                Button("Create account", action: signUp)
                    .buttonStyle(PrimaryButtonStyle())
                Button(action: logIn) {
                    Text("I already have an account")
                        .type(.headline)
                        .foregroundStyle(Theme.textPrimary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                }
                .padding(.top, 4)
                ServerStatusRow(status: server)
                    .padding(.top, 6)
            }
            .padding(.horizontal, Theme.s6)
            .padding(.bottom, Theme.s3)
        }
        .toolbar(.hidden, for: .navigationBar)
        .onAppear { withAnimation(Theme.gentle.delay(0.05)) { appeared = true } }
    }

    @State private var appeared = false
}

private struct FeatureRow: View {
    let icon: String
    let tint: Color
    let text: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(TType.glyph(14, .semibold))
                .foregroundStyle(Theme.textSecondary)
                .frame(width: 32, height: 32)
                .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            Text(text)
                .type(.callout)
                .foregroundStyle(Theme.textPrimary.opacity(0.92))
        }
    }
}

/// SFO ✈︎ NRT arc with the plane part-way along, drawn with shapes (no image assets).
private struct WelcomeRouteArt: View {
    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            let a = CGPoint(x: 18, y: h - 30), b = CGPoint(x: w - 18, y: h - 30)
            let c = CGPoint(x: w / 2, y: -h * 0.35)
            ZStack {
                Path { p in p.move(to: a); p.addQuadCurve(to: b, control: c) }
                    .stroke(Theme.textTertiary.opacity(0.6), style: StrokeStyle(lineWidth: 1, lineCap: .round, dash: [1, 6]))
                Path { p in p.move(to: a); p.addQuadCurve(to: b, control: c) }
                    .trim(from: 0, to: 0.58)
                    .stroke(LinearGradient(colors: [Theme.route.opacity(0.3), Theme.route], startPoint: .leading, endPoint: .trailing),
                            style: StrokeStyle(lineWidth: 2, lineCap: .round))
                let t = 0.58
                let pt = CGPoint(x: pow(1 - t, 2) * a.x + 2 * (1 - t) * t * c.x + t * t * b.x,
                                 y: pow(1 - t, 2) * a.y + 2 * (1 - t) * t * c.y + t * t * b.y)
                Image(systemName: "airplane")
                    .font(TType.glyph(20, .semibold))
                    .foregroundStyle(.white)
                    .rotationEffect(.degrees(12))
                    .shadow(color: Theme.route.opacity(0.8), radius: 8)
                    .position(pt)
                ForEach([(a, "SFO"), (b, "NRT")], id: \.1) { point, code in
                    VStack(spacing: 6) {
                        Circle().fill(.white).frame(width: 7, height: 7)
                        Text(code).type(.codeSmall).foregroundStyle(.white)
                    }
                    .position(x: point.x + (code == "SFO" ? 14 : -14), y: point.y + 12)
                }
            }
        }
    }
}

// MARK: - Shared form pieces

struct AuthField: View {
    let label: String
    @Binding var text: String
    var placeholder: String = ""
    var secure = false
    var content: UITextContentType? = nil
    var keyboard: UIKeyboardType = .default
    var capitalize: TextInputAutocapitalization = .never

    @State private var reveal = false

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(label.uppercased())
                .type(.label)
                .tracking(0.6)
                .foregroundStyle(Theme.textSecondary)
            HStack {
                Group {
                    if secure && !reveal {
                        SecureField(placeholder, text: $text)
                    } else {
                        TextField(placeholder, text: $text)
                    }
                }
                .textContentType(content)
                .keyboardType(keyboard)
                .textInputAutocapitalization(capitalize)
                .autocorrectionDisabled()
                .type(.body)
                .foregroundStyle(Theme.textPrimary)
                if secure {
                    Button { reveal.toggle() } label: {
                        Image(systemName: reveal ? "eye.slash" : "eye")
                            .foregroundStyle(Theme.textTertiary)
                    }
                    .accessibilityLabel(reveal ? "Hide password" : "Show password")
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.hairline))
        }
    }
}

struct FormErrorBanner: View {
    let message: String
    var tint: Color = Theme.red
    var icon = "exclamationmark.triangle.fill"

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon).foregroundStyle(tint)
            Text(message)
                .type(.callout)
                .foregroundStyle(Theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .transition(.move(edge: .top).combined(with: .opacity))
    }
}

struct BusyButtonLabel: View {
    let title: String
    let busy: Bool

    var body: some View {
        ZStack {
            Text(title).opacity(busy ? 0 : 1)
            if busy { ProgressView().tint(.white) }
        }
    }
}

private struct AuthScreen<Content: View>: View {
    let title: String
    let subtitle: String
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(title)
                        .type(.largeTitle)
                        .foregroundStyle(Theme.textPrimary)
                    Text(subtitle)
                        .type(.callout)
                        .foregroundStyle(Theme.textSecondary)
                }
                .padding(.bottom, 6)
                content
            }
            .padding(.horizontal, 24)
            .padding(.top, 8)
            .padding(.bottom, 40)
        }
        .scrollDismissesKeyboard(.interactively)
        .trippyScreen()
        .navigationBarTitleDisplayMode(.inline)
    }
}

enum AuthValidation {
    static func email(_ s: String) -> Bool {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard let at = t.firstIndex(of: "@") else { return false }
        return at > t.startIndex && t[t.index(after: at)...].contains(".") && !t.contains(" ")
    }

    static func passwordProblem(_ s: String) -> String? {
        if s.count < 8 { return "Use at least 8 characters." }
        if s.count > 256 { return "That password is too long." }
        return nil
    }

    static func airport(_ s: String) -> Bool {
        s.isEmpty || (s.count == 3 && s.allSatisfy { $0.isLetter && $0.isASCII })
    }
}

// MARK: - Sign up

struct SignUpView: View {
    var logInInstead: () -> Void
    @EnvironmentObject private var auth: AuthManager
    @EnvironmentObject private var server: ServerStatus
    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var airport = ""
    @State private var inviteCode = UserDefaults.standard.string(forKey: "TrippyInviteCode") ?? ""
    @State private var error: String?
    @State private var busy = false

    private var problem: String? {
        if name.trimmingCharacters(in: .whitespaces).isEmpty { return "Enter your name." }
        if !AuthValidation.email(email) { return "Enter a valid email address." }
        if let p = AuthValidation.passwordProblem(password) { return p }
        if !AuthValidation.airport(airport) { return "Home airport is a 3-letter code, like SFO." }
        return nil
    }

    var body: some View {
        AuthScreen(title: "Create account",
                   subtitle: "If someone added you to a trip, enter the invite code they sent you and it shows up as soon as you sign up.") {
            ServerStatusRow(status: server)
            if let note = signupNote {
                FormErrorBanner(message: note, tint: Theme.blue, icon: "info.circle.fill")
            }
            if let error { FormErrorBanner(message: error) }
            AuthField(label: "Name", text: $name, placeholder: "Your name", content: .name, capitalize: .words)
            AuthField(label: "Email", text: $email, placeholder: "you@example.com", content: .emailAddress, keyboard: .emailAddress)
            AuthField(label: "Password", text: $password, placeholder: "At least 8 characters", secure: true, content: .newPassword)
            AuthField(label: "Home airport (optional)", text: $airport, placeholder: "SFO", capitalize: .characters)
            AuthField(label: server.health?.signup == "open" ? "Invite code (optional)" : "Invite code",
                      text: $inviteCode, placeholder: "XXXXX-XXXXX", content: .oneTimeCode, capitalize: .characters)
            Button {
                Task { await submit() }
            } label: { BusyButtonLabel(title: "Create account", busy: busy) }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(busy)
                .padding(.top, 6)
            Button("Already have an account? Log in", action: logInInstead)
                .type(.calloutStrong)
                .frame(maxWidth: .infinity)
            Text("Sign in with Apple is coming later.")
                .type(.caption)
                .foregroundStyle(Theme.textTertiary)
                .frame(maxWidth: .infinity)
            // TODO(Sign in with Apple): needs a paid Apple Developer account for the capability.
        }
        .animation(.default, value: error)
    }

    /// Explains invite-only / closed servers before someone fills in the form.
    private var signupNote: String? {
        switch server.health?.signup {
        case "invite": return "This server is invite-only. Ask someone on it to add you to a trip and send you an invite code."
        case "closed": return "Sign-ups are closed on this server. Ask its owner to add your email."
        default: return nil
        }
    }

    private func submit() async {
        if let problem { error = problem; return }
        busy = true
        defer { busy = false }
        do {
            try await auth.signUp(name: name.trimmingCharacters(in: .whitespaces),
                                  email: email.trimmingCharacters(in: .whitespaces),
                                  password: password, homeAirport: airport, inviteCode: inviteCode)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Log in

struct LogInView: View {
    var forgot: () -> Void
    var signUpInstead: () -> Void
    @EnvironmentObject private var auth: AuthManager
    @EnvironmentObject private var server: ServerStatus
    @State private var email = ""
    @State private var password = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        AuthScreen(title: "Welcome back", subtitle: "Log in to see your trips.") {
            ServerStatusRow(status: server)
            if let error { FormErrorBanner(message: error) }
            AuthField(label: "Email", text: $email, placeholder: "you@example.com", content: .username, keyboard: .emailAddress)
            AuthField(label: "Password", text: $password, placeholder: "Password", secure: true, content: .password)
            HStack {
                Spacer()
                Button("Forgot password?", action: forgot)
                    .type(.calloutStrong)
            }
            Button {
                Task { await submit() }
            } label: { BusyButtonLabel(title: "Log in", busy: busy) }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(busy)
            Button("New to Trippy? Create an account", action: signUpInstead)
                .type(.calloutStrong)
                .frame(maxWidth: .infinity)
                .padding(.top, 4)
        }
        .animation(.default, value: error)
    }

    private func submit() async {
        guard AuthValidation.email(email), !password.isEmpty else {
            error = "Enter your email and password."
            return
        }
        busy = true
        defer { busy = false }
        do {
            try await auth.logIn(email: email.trimmingCharacters(in: .whitespaces), password: password)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Forgot password

struct ForgotPasswordView: View {
    var done: () -> Void
    @EnvironmentObject private var auth: AuthManager
    @EnvironmentObject private var server: ServerStatus
    @State private var email = ""
    @State private var code = ""
    @State private var newPassword = ""
    @State private var sent: String?
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        AuthScreen(title: "Reset password",
                   subtitle: sent == nil ? "We'll make a one-time reset code for your account."
                                         : "Enter the code and choose a new password.") {
            if let error { FormErrorBanner(message: error) }
            if sent == nil {
                AuthField(label: "Email", text: $email, placeholder: "you@example.com", content: .emailAddress, keyboard: .emailAddress)
                Button {
                    Task { await request() }
                } label: { BusyButtonLabel(title: "Get reset code", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy)
                if server.health?.password_reset != "email" {
                    FormErrorBanner(message: "This server can't send email, so the code appears in its log (docker compose logs api). Ask the server's owner for it.",
                                    tint: Theme.blue, icon: "info.circle.fill")
                }
            } else {
                if let sent { FormErrorBanner(message: sent, tint: Theme.green, icon: "checkmark.circle.fill") }
                AuthField(label: "Reset code", text: $code, placeholder: "XXXXXX-XXXXXX-XXXXXX", content: .oneTimeCode, capitalize: .characters)
                AuthField(label: "New password", text: $newPassword, placeholder: "At least 8 characters", secure: true, content: .newPassword)
                Button {
                    Task { await reset() }
                } label: { BusyButtonLabel(title: "Set new password", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy)
                Button("Back to log in", action: done)
                    .type(.calloutStrong)
                    .frame(maxWidth: .infinity)
            }
        }
        .animation(.default, value: sent)
        .animation(.default, value: error)
    }

    private func request() async {
        guard AuthValidation.email(email) else { error = "Enter a valid email address."; return }
        busy = true
        defer { busy = false }
        do {
            let r = try await auth.requestReset(email: email.trimmingCharacters(in: .whitespaces))
            if let dev = r.devCode { code = dev }  // server in dev mode
            sent = r.message
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func reset() async {
        if let p = AuthValidation.passwordProblem(newPassword) { error = p; return }
        guard !code.isEmpty else { error = "Enter the reset code."; return }
        busy = true
        defer { busy = false }
        do {
            try await auth.resetPassword(code: code, newPassword: newPassword)  // signs you in
        } catch {
            self.error = error.localizedDescription
        }
    }
}
