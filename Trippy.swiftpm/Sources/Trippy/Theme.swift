import SwiftUI

/// Trippy's design system: a near-black canvas, quiet dark surfaces separated by hairlines,
/// one action blue, and color only where it means something (green = on track,
/// amber = attention, red = problem, yellow = the one thing to look at).
/// Type lives in Typography.swift; spacing is an 8pt grid.
enum Theme {
    // Surfaces
    static let canvas = Color(hex: 0x000000)
    /// Bottom-sheet background (sits over the map)
    static let sheet = Color(hex: 0x161618)
    static let surface = Color(hex: 0x161618)
    static let surfaceRaised = Color(hex: 0x242426)
    static let surfaceHigh = Color(hex: 0x323235)
    static let hairline = Color.white.opacity(0.08)
    static let divider = Color.white.opacity(0.11)

    // Text: three grays, used the same way everywhere
    static let textPrimary = Color.white
    /// Supporting text (dates, subtitles, values' labels)
    static let textSecondary = Color(hex: 0x8E8E93)
    /// Least important text (hints, units, trailing counts)
    static let textTertiary = Color(hex: 0x5C5C61)

    // Accents & status
    static let blue = Color(hex: 0x0A84FF)
    static let green = Color(hex: 0x30D158)
    static let amber = Color(hex: 0xFFD60A)
    /// Highlight block (parking spot / counter / UP NEXT): yellow with black text
    static let highlight = Color(hex: 0xFFD60A)
    static let orange = Color(hex: 0xFF9F0A)
    /// Hotel stays: the coral from the passport-stamp logo.
    static let stay = Color(hex: 0xFF7A59)
    static let red = Color(hex: 0xFF453A)
    static let purple = Color(hex: 0x5E5CE6)
    static let purpleDeep = Color(hex: 0x2A1B7A)
    static let purpleNight = Color(hex: 0x140C3D)
    static let teal = Color(hex: 0x40C8E0)
    /// Brand accent used by the logo, the wordmark and share-card watermarks.
    static let brand = Color(hex: 0x5EA8FF)

    // Shape
    static let radius: CGFloat = 20
    static let sheetRadius: CGFloat = 28
    static let radiusSmall: CGFloat = 12
    static let pagePadding: CGFloat = 20

    /// Route line on every map: a light, slightly glowing blue (Flighty's flight path).
    static let route = Color(hex: 0x5EA8FF)

    // 8pt grid (4 is the half step for tight pairs like a label over a value)
    static let s1: CGFloat = 4
    static let s2: CGFloat = 8
    static let s3: CGFloat = 12
    static let s4: CGFloat = 16
    static let s5: CGFloat = 20
    static let s6: CGFloat = 24
    static let s8: CGFloat = 32
    /// Gap between major sections (big air, not boxes).
    static let sectionGap: CGFloat = 32
    /// Standard inner padding of a card.
    static let cardPadding: CGFloat = 20
    /// Extra room so the last row can scroll clear of the floating tab bar.
    static let tabBarClearance: CGFloat = 96

    /// Springs used for state changes across the app.
    static let snappy = Animation.snappy(duration: 0.32)
    static let gentle = Animation.smooth(duration: 0.45)
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}

// MARK: - Card

private struct CardStyle: ViewModifier {
    var padding: CGFloat
    var fill: Color

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(fill, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .strokeBorder(Theme.hairline, lineWidth: 0.5))
    }
}

extension View {
    func card(padding: CGFloat = Theme.cardPadding, fill: Color = Theme.surface) -> some View {
        modifier(CardStyle(padding: padding, fill: fill))
    }

    /// Transparent card with a hairline outline (the "Good to know" look).
    func outlinedCard(padding: CGFloat = Theme.s4) -> some View {
        self
            .padding(padding)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .strokeBorder(Theme.divider, lineWidth: 0.5)
            )
    }

    /// Dark canvas + dark navigation bar used by every screen.
    func trippyScreen() -> some View {
        self
            .background(Theme.canvas.ignoresSafeArea())
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbarBackground(Theme.canvas, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
    }
}

// MARK: - Building blocks

/// Quiet status capsule, e.g. ACTIVE / UPCOMING / RETURNED: a dot plus tracked caps.
struct StatusPill: View {
    let text: String
    let color: Color
    var systemImage: String?

    var body: some View {
        HStack(spacing: 5) {
            if let systemImage {
                Image(systemName: systemImage).font(TType.glyph(8, .bold))
            } else {
                Circle().fill(color).frame(width: 5, height: 5)
            }
            Text(text.uppercased())
        }
        .type(.micro)
        .foregroundStyle(color)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.12), in: Capsule())
        .lineLimit(1)
        .fixedSize()
    }
}

/// Small label/value chip used on cards ("CLASS Full Size", "CONF 1234…").
struct InfoChip: View {
    var label: String?
    let value: String
    var systemImage: String?
    var tint: Color = .white

    var body: some View {
        HStack(spacing: 6) {
            if let systemImage {
                Image(systemName: systemImage)
                    .type(.micro)
                    .foregroundStyle(Theme.textTertiary)
            }
            if let label {
                Text(label.uppercased())
                    .type(.micro)
                    .foregroundStyle(Theme.textTertiary)
            }
            Text(value)
                .type(label == "CONF" || label == "PNR" ? .mono : .footnoteStrong)
                .foregroundStyle(tint)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .fixedSize()
    }
}

struct SectionHeader: View {
    let title: String
    var trailing: String?
    var systemImage: String?

    var body: some View {
        HStack(spacing: 6) {
            if let systemImage {
                Image(systemName: systemImage)
            }
            Text(title.uppercased())
            Spacer()
            if let trailing {
                Text(trailing.uppercased())
                    .foregroundStyle(Theme.textTertiary)
            }
        }
        .type(.label)
        .foregroundStyle(Theme.textSecondary)
    }
}

/// Large screen header (title + supporting line), Flighty-style, inside the scroll view.
struct ScreenHeader: View {
    let title: String
    var subtitle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s1) {
            Text(title)
                .type(.largeTitle)
                .foregroundStyle(Theme.textPrimary)
            if let subtitle {
                Text(subtitle)
                    .type(.callout)
                    .foregroundStyle(Theme.textSecondary)
                    .contentTransition(.numericText())
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Big number + caption tile.
struct MetricTile: View {
    let value: String
    let label: String
    var systemImage: String?
    var tint: Color = Theme.textPrimary

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: 5) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .foregroundStyle(tint == Theme.textPrimary ? Theme.textTertiary : tint)
                }
                Text(label.uppercased()).lineLimit(1)
            }
            .type(.micro)
            .foregroundStyle(Theme.textSecondary)
            Text(value)
                .type(.number)
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
                .contentTransition(.numericText())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: Theme.s4)
    }
}

/// Primary filled button style.
struct PrimaryButtonStyle: ButtonStyle {
    var tint: Color = Theme.blue

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .type(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(tint.opacity(configuration.isPressed ? 0.75 : 1),
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.snappy, value: configuration.isPressed)
            .sensoryFeedback(.impact(flexibility: .soft, intensity: 0.6), trigger: configuration.isPressed) { _, pressed in pressed }
    }
}

/// Subtle tinted button style (e.g. "Add Expense").
struct TintedButtonStyle: ButtonStyle {
    var tint: Color = Theme.blue

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .type(.calloutStrong)
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(tint.opacity(configuration.isPressed ? 0.22 : 0.12),
                        in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.snappy, value: configuration.isPressed)
            .sensoryFeedback(.impact(flexibility: .soft, intensity: 0.5), trigger: configuration.isPressed) { _, pressed in pressed }
    }
}

/// Plain row/card button that dims and shrinks a touch while pressed.
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.7 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(Theme.snappy, value: configuration.isPressed)
    }
}

/// Thin progress track with a glyph riding along it.
struct RouteProgressBar: View {
    let progress: Double
    let color: Color
    var glyph: String? = "car.side.fill"

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let p = min(max(progress, 0), 1)
            ZStack(alignment: .leading) {
                Capsule().fill(Color.white.opacity(0.10)).frame(height: 2)
                Capsule()
                    .fill(LinearGradient(colors: [color.opacity(0.35), color], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(2, width * p), height: 2)
                if let glyph {
                    Image(systemName: glyph)
                        .font(TType.glyph(11, .semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 3)
                        .background(Theme.surface)
                        .offset(x: min(max(width * p - 9, 0), max(width - 18, 0)))
                }
            }
            .frame(width: width, height: geo.size.height)
            .animation(Theme.gentle, value: p)
        }
        .frame(height: 16)
    }
}

/// Flighty-style route line between two big codes: hairline, end dots, a glyph in the middle.
struct DashedConnector: View {
    var glyph: String = "car.fill"
    var caption: String?
    var color: Color = Theme.textSecondary
    /// Background behind the glyph so the line appears to pass under it.
    var backdrop: Color = Theme.surface

    var body: some View {
        VStack(spacing: Theme.s1) {
            ZStack {
                HStack(spacing: 0) {
                    Circle().stroke(Theme.textTertiary, lineWidth: 1).frame(width: 5, height: 5)
                    Rectangle().fill(Theme.textTertiary.opacity(0.8)).frame(height: 0.75)
                    Circle().fill(Theme.textTertiary).frame(width: 5, height: 5)
                }
                Image(systemName: glyph)
                    .font(TType.glyph(13, .semibold))
                    .foregroundStyle(color)
                    .padding(.horizontal, 6)
                    .background(backdrop)
            }
            if let caption {
                Text(caption)
                    .type(.caption)
                    .monospacedDigit()
                    .foregroundStyle(Theme.textTertiary)
                    .lineLimit(1)
            }
        }
    }
}

/// Generic empty / error state: no box, just a soft glyph, a title and one line.
struct EmptyStateCard: View {
    let systemImage: String
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: Theme.s3) {
            Image(systemName: systemImage)
                .font(TType.glyph(22, .medium))
                .foregroundStyle(Theme.textSecondary)
                .frame(width: 56, height: 56)
                .background(Theme.surfaceRaised, in: Circle())
                .padding(.bottom, Theme.s1)
            Text(title)
                .type(.headline)
                .foregroundStyle(Theme.textPrimary)
            Text(message)
                .type(.footnote)
                .foregroundStyle(Theme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 280)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.s8)
    }
}

// MARK: - Formatting

enum Fmt {
    private static let parsers: [DateFormatter] = {
        ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss.SSS", "yyyy-MM-dd'T'HH:mm:ss",
         "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd"].map { format in
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = .current
            f.dateFormat = format
            return f
        }
    }()

    /// Parses the API's naive ISO strings (local wall-clock time; offsets/Z are ignored).
    static func parse(_ string: String?) -> Date? {
        guard var s = string?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        if s.hasSuffix("Z") { s.removeLast() }
        if let r = s.range(of: #"[+-]\d{2}:\d{2}$"#, options: .regularExpression) { s.removeSubrange(r) }
        for p in parsers {
            if let d = p.date(from: s) { return d }
        }
        return nil
    }

    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale.current
        f.setLocalizedDateFormatFromTemplate(format)
        return f
    }

    private static let timeF = formatter("jmm")
    private static let dayF = formatter("EEEMMMd")
    private static let dayYearF = formatter("EEEMMMdyyyy")
    private static let monthDayF = formatter("MMMd")
    private static let monthDayYearF = formatter("MMMdyyyy")

    static func time(_ d: Date) -> String { timeF.string(from: d) }
    static func day(_ d: Date) -> String { dayF.string(from: d) }
    static func dayYear(_ d: Date) -> String { dayYearF.string(from: d) }
    static func monthDay(_ d: Date) -> String { monthDayF.string(from: d) }
    static func monthDayYear(_ d: Date) -> String { monthDayYearF.string(from: d) }

    /// "1d 4h", "3h 12m", "45m".
    static func duration(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded()))
        let d = total / 86_400, h = (total % 86_400) / 3_600, m = (total % 3_600) / 60
        if d > 0 { return h > 0 ? "\(d)d \(h)h" : "\(d)d" }
        if h > 0 { return m > 0 ? "\(h)h \(m)m" : "\(h)h" }
        return "\(m)m"
    }

    static func money(_ amount: Double, _ currency: String? = "USD", decimals: Bool = true) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = currency ?? "USD"
        f.maximumFractionDigits = decimals ? 2 : 0
        f.minimumFractionDigits = decimals ? 2 : 0
        return f.string(from: NSNumber(value: amount)) ?? String(format: "$%.2f", amount)
    }

    /// $11.6k style for hero numbers.
    static func compactMoney(_ amount: Double, _ currency: String? = "USD") -> String {
        if abs(amount) >= 10_000 {
            let symbol = (currency ?? "USD") == "USD" ? "$" : (currency ?? "") + " "
            return symbol + String(format: "%.1fk", amount / 1000)
        }
        return money(amount, currency, decimals: false)
    }

    static func number(_ value: Double) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.maximumFractionDigits = 0
        return f.string(from: NSNumber(value: value)) ?? "\(Int(value))"
    }
}

/// Yellow block with black text: the parking spot / counter / plate highlight.
struct HighlightBlock: View {
    var systemImage: String?
    let text: String

    var body: some View {
        HStack(spacing: 5) {
            if let systemImage {
                Image(systemName: systemImage).font(TType.glyph(13, .bold))
            }
            Text(text)
                .type(.headline)
                .monospacedDigit()
                .lineLimit(1).minimumScaleFactor(0.6)
        }
        .foregroundStyle(.black)
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(Theme.highlight, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .frame(maxWidth: 170, alignment: .trailing)
    }
}

// MARK: - Flighty-style primitives (hairlines instead of boxes)

/// 0.5pt separator used between rows and sections.
struct Hairline: View {
    var leading: CGFloat = 0
    var body: some View {
        Rectangle().fill(Theme.divider).frame(height: 0.5).padding(.leading, leading)
    }
}

/// Small uppercase muted label ("TOTAL SPENT", "2 TRAVELERS").
struct MicroLabel: View {
    let text: String
    var color: Color = Theme.textSecondary
    var body: some View {
        Text(text.uppercased())
            .type(.label)
            .foregroundStyle(color)
            .lineLimit(1)
    }
}

/// Flighty list section heading: title left, small uppercase count right.
struct ListSectionTitle: View {
    let title: String
    var trailing: String?
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).type(.title3).foregroundStyle(.white)
            Spacer()
            if let trailing { MicroLabel(text: trailing, color: Theme.textTertiary) }
        }
    }
}

/// Gray circular header button (share / add / more / close).
struct CircleIcon: View {
    let systemName: String
    var size: CGFloat = 36
    var body: some View {
        Image(systemName: systemName)
            .symbolRenderingMode(.hierarchical)
            .font(TType.glyph(size * 0.4, .semibold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Theme.surfaceRaised, in: Circle())
            .contentShape(Circle())
    }
}

/// Yellow pill with black text: the one highlight colour (UP NEXT, gate-style codes).
struct YellowPill: View {
    let text: String
    var systemImage: String?
    var body: some View {
        HStack(spacing: 4) {
            if let systemImage { Image(systemName: systemImage).font(TType.glyph(9, .bold)) }
            Text(text.uppercased())
        }
        .type(.micro)
        .foregroundStyle(.black)
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(Theme.highlight, in: Capsule())
        .fixedSize()
    }
}

/// Outlined capsule chip used in rows ("3h 57m", "A21N" in Flighty).
struct GrayChip: View {
    let text: String
    var systemImage: String?
    var body: some View {
        HStack(spacing: 4) {
            if let systemImage { Image(systemName: systemImage).font(TType.glyph(9, .semibold)) }
            Text(text).type(.caption).monospacedDigit()
        }
        .foregroundStyle(Theme.textSecondary)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .overlay(Capsule().strokeBorder(Theme.divider, lineWidth: 0.75))
        .fixedSize()
    }
}

/// Status banner (Flighty's "Arrived 21m Early"): tinted fill, tinted text, hairline tint border.
struct StatusBanner: View {
    let title: String
    var subtitle: String?
    var color: Color = Theme.green

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).type(.headline).monospacedDigit()
                .contentTransition(.numericText())
            if let subtitle {
                Text(subtitle).type(.footnote).monospacedDigit().opacity(0.8)
                    .lineLimit(1).minimumScaleFactor(0.8)
            }
        }
        .foregroundStyle(color)
        .padding(.horizontal, Theme.s4).padding(.vertical, Theme.s3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.10), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(color.opacity(0.20), lineWidth: 0.5))
        .animation(Theme.snappy, value: title)
    }
}

/// Big number over a tiny uppercase unit ("15 / DAYS") — the left column of Flighty rows.
/// The number rolls (numeric content transition) when it changes.
struct DayCount: View {
    let value: String
    let unit: String
    var color: Color = .white
    var size: CGFloat = 28
    @ScaledMetric(relativeTo: .title) private var scale: CGFloat = 1

    var body: some View {
        VStack(spacing: 2) {
            Text(value)
                .font(TType.font(.heroSmall, size: size * min(scale, 1.4)))
                .tracking(size > 40 ? -1.4 : -0.6)
                .foregroundStyle(color)
                .lineLimit(1).minimumScaleFactor(0.5)
                .contentTransition(.numericText())
                .animation(Theme.snappy, value: value)
            Text(unit.uppercased()).type(.micro)
                .foregroundStyle(Theme.textSecondary).lineLimit(1)
        }
    }
}
