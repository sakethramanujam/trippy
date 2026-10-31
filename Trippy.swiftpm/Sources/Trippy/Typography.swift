import SwiftUI

// MARK: - Trippy type system
//
// One place for every text style in the app. Flighty-like rules:
// - SF Pro Display for words, SF Pro Rounded for numbers people glance at (countdowns,
//   money, stats), SF Mono only for flight numbers, PNRs and server addresses.
// - Four weights only: regular, medium, semibold, bold.
// - Tabular digits wherever a number can change or sit in a column.
// - Large sizes get negative tracking; tiny uppercase labels get positive tracking.
// - Sizes scale with Dynamic Type (relative to the matching UIKit text style). The root view
//   caps Dynamic Type at .accessibility1 so big numbers don't blow up layouts.
//
// Use `.type(.title)` on views. `TType.font(.title)` returns a plain Font for the few places
// that need one (Text concatenation, UIKit appearance). Share cards and stories render at a
// fixed size and use `CardType`, which follows the same families, weights and tracking.

enum TType: CaseIterable {
    /// 56pt rounded: countdown days, trip totals ("2", "$1,045").
    case hero
    /// 40pt rounded: secondary big numbers (stat heroes, balances).
    case heroSmall
    /// 40pt: marketing-size statement (welcome screen headline).
    case display
    /// 34pt: screen large titles ("Trips", "Today").
    case largeTitle
    /// 34pt: IATA / station codes on flight and rental cards ("SFO").
    case code
    /// 26pt: smaller IATA codes in rows.
    case codeSmall
    /// 28pt: sheet titles, trip name in a detail header.
    case title
    /// 22pt: card titles ("Tokyo 2027" on a row).
    case title2
    /// 20pt: section titles ("Itinerary", "Expenses").
    case title3
    /// 17pt semibold: row titles, emphasized body.
    case headline
    /// 17pt regular: body copy.
    case body
    /// 15pt medium: secondary row text, button labels in lists.
    case callout
    /// 15pt semibold: emphasized secondary text, small buttons.
    case calloutStrong
    /// 13pt regular: supporting lines under rows.
    case footnote
    /// 13pt semibold: emphasized supporting text, chip values.
    case footnoteStrong
    /// 12pt regular: captions, timestamps.
    case caption
    /// 11pt semibold, tracked: section labels (pass uppercased text) ("UP NEXT", "TOTAL SPENT").
    case label
    /// 10pt semibold, tracked: units under big numbers ("DAYS").
    case micro
    /// 22pt rounded semibold: stat values in tiles.
    case number
    /// 17pt rounded semibold: inline amounts and counts.
    case numberSmall
    /// 22pt semibold tabular: departure / arrival times.
    case time
    /// 15pt medium tabular: small times and countdown chips.
    case timeSmall
    /// 13pt medium SF Mono: flight numbers, confirmation codes, server URLs.
    case mono
    /// 17pt semibold SF Mono: a highlighted PNR / gate.
    case monoLarge

    struct Spec {
        let size: CGFloat
        let weight: Font.Weight
        let design: Font.Design
        let relativeTo: Font.TextStyle
        let tracking: CGFloat
        let tabular: Bool
        let uppercase: Bool
    }

    var spec: Spec {
        switch self {
        case .hero:          return Spec(size: 56, weight: .bold, design: .rounded, relativeTo: .largeTitle, tracking: -1.6, tabular: true, uppercase: false)
        case .heroSmall:     return Spec(size: 40, weight: .bold, design: .rounded, relativeTo: .largeTitle, tracking: -1.0, tabular: true, uppercase: false)
        case .display:       return Spec(size: 40, weight: .bold, design: .default, relativeTo: .largeTitle, tracking: -1.3, tabular: false, uppercase: false)
        case .largeTitle:    return Spec(size: 34, weight: .bold, design: .default, relativeTo: .largeTitle, tracking: -0.9, tabular: false, uppercase: false)
        case .code:          return Spec(size: 34, weight: .bold, design: .default, relativeTo: .largeTitle, tracking: -0.6, tabular: true, uppercase: false)
        case .codeSmall:     return Spec(size: 26, weight: .bold, design: .default, relativeTo: .title, tracking: -0.4, tabular: true, uppercase: false)
        case .title:         return Spec(size: 28, weight: .bold, design: .default, relativeTo: .title, tracking: -0.7, tabular: false, uppercase: false)
        case .title2:        return Spec(size: 22, weight: .semibold, design: .default, relativeTo: .title2, tracking: -0.45, tabular: false, uppercase: false)
        case .title3:        return Spec(size: 20, weight: .semibold, design: .default, relativeTo: .title3, tracking: -0.35, tabular: false, uppercase: false)
        case .headline:      return Spec(size: 17, weight: .semibold, design: .default, relativeTo: .headline, tracking: -0.2, tabular: false, uppercase: false)
        case .body:          return Spec(size: 17, weight: .regular, design: .default, relativeTo: .body, tracking: -0.2, tabular: false, uppercase: false)
        case .callout:       return Spec(size: 15, weight: .medium, design: .default, relativeTo: .callout, tracking: -0.1, tabular: false, uppercase: false)
        case .calloutStrong: return Spec(size: 15, weight: .semibold, design: .default, relativeTo: .callout, tracking: -0.1, tabular: false, uppercase: false)
        case .footnote:      return Spec(size: 13, weight: .regular, design: .default, relativeTo: .footnote, tracking: 0, tabular: false, uppercase: false)
        case .footnoteStrong:return Spec(size: 13, weight: .semibold, design: .default, relativeTo: .footnote, tracking: 0, tabular: true, uppercase: false)
        case .caption:       return Spec(size: 12, weight: .regular, design: .default, relativeTo: .caption, tracking: 0, tabular: false, uppercase: false)
        case .label:         return Spec(size: 11, weight: .semibold, design: .default, relativeTo: .caption2, tracking: 0.9, tabular: true, uppercase: false)
        case .micro:         return Spec(size: 10, weight: .semibold, design: .default, relativeTo: .caption2, tracking: 0.8, tabular: true, uppercase: false)
        case .number:        return Spec(size: 22, weight: .semibold, design: .rounded, relativeTo: .title2, tracking: -0.4, tabular: true, uppercase: false)
        case .numberSmall:   return Spec(size: 17, weight: .semibold, design: .rounded, relativeTo: .headline, tracking: -0.2, tabular: true, uppercase: false)
        case .time:          return Spec(size: 22, weight: .semibold, design: .default, relativeTo: .title2, tracking: -0.4, tabular: true, uppercase: false)
        case .timeSmall:     return Spec(size: 15, weight: .medium, design: .default, relativeTo: .callout, tracking: -0.1, tabular: true, uppercase: false)
        case .mono:          return Spec(size: 13, weight: .medium, design: .monospaced, relativeTo: .footnote, tracking: 0, tabular: true, uppercase: false)
        case .monoLarge:     return Spec(size: 17, weight: .semibold, design: .monospaced, relativeTo: .headline, tracking: 0, tabular: true, uppercase: false)
        }
    }

    /// Unscaled font (UIKit appearance, Text concatenation). Prefer `.type(_:)` on views.
    static func font(_ style: TType, size: CGFloat? = nil) -> Font {
        let s = style.spec
        let f = Font.system(size: size ?? s.size, weight: s.weight, design: s.design)
        return s.tabular ? f.monospacedDigit() : f
    }

    /// Fixed-size glyph font for SF Symbols inside fixed frames (avatars, circle buttons).
    static func glyph(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight)
    }
}

private struct TypeModifier: ViewModifier {
    let style: TType
    @ScaledMetric private var size: CGFloat

    init(_ style: TType) {
        self.style = style
        _size = ScaledMetric(wrappedValue: style.spec.size, relativeTo: style.spec.relativeTo)
    }

    func body(content: Content) -> some View {
        let s = style.spec
        content
            .font(TType.font(style, size: size))
            .tracking(s.tracking)
            .textCase(s.uppercase ? .uppercase : nil)
    }
}

extension View {
    /// Applies a named Trippy text style (font, tracking, digits, case), scaled for Dynamic Type.
    func type(_ style: TType) -> some View { modifier(TypeModifier(style)) }
}

// MARK: - Haptics

enum Haptics {
    static func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle) { UIImpactFeedbackGenerator(style: style).impactOccurred() }
    static func tap() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func select() { UISelectionFeedbackGenerator().selectionChanged() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
}
