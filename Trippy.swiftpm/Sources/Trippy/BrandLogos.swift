import SwiftUI
import UIKit

/// Bundled brand marks (Assets.xcassets, see LOGOS_SOURCES.md). Each asset is a square
/// tile with its own background; views clip it to a rounded square like Flighty.
enum BrandLogos {
    /// Asset name for a rental company, or nil when we don't bundle a logo.
    static func rental(_ company: String) -> String? {
        let key = company.lowercased()
            .replacingOccurrences(of: #"(rent[\s-]*a[\s-]*car|car rental|rentals?|car hire|inc\.?|llc)"#,
                                  with: "", options: .regularExpression)
            .filter { $0.isLetter }
        return existing("logo-rental-\(key)")
    }

    /// Asset name for an airline by name ("Delta Air Lines") or flight number prefix ("DL123").
    static func airline(name: String, flightNumber: String? = nil) -> String? {
        let n = name.lowercased().filter { $0.isLetter || $0 == " " }
        let stripped = n.replacingOccurrences(of: #"\b(air ?lines?|airways|international|intl)\b"#,
                                              with: "", options: .regularExpression)
            .filter { $0.isLetter }
        if let key = airlineAliases[stripped] ?? airlineAliases[n.filter { $0.isLetter }],
           let asset = existing("logo-airline-\(key)") { return asset }
        if let asset = existing("logo-airline-\(stripped)") { return asset }
        if let code = iata(name) ?? flightNumber.flatMap(iata), let key = iataCodes[code] {
            return existing("logo-airline-\(key)")
        }
        return nil
    }

    private static func iata(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespaces).uppercased()
        guard t.count >= 2 else { return nil }
        let code = String(t.prefix(2))
        guard code.allSatisfy({ $0.isLetter || $0.isNumber }), code.contains(where: \.isLetter) else { return nil }
        let rest = t.dropFirst(2).trimmingCharacters(in: .whitespaces)
        return (rest.isEmpty || rest.allSatisfy(\.isNumber)) ? code : nil
    }

    /// Hotel chain mark, e.g. "logo-hotel-hyatt". None ship yet, so callers fall back to a letter badge.
    static func hotel(_ brand: String?) -> String? {
        guard let brand, !brand.isEmpty else { return nil }
        let key = brand.lowercased().filter(\.isLetter)
        return existing("logo-hotel-\(key)")
    }

    private static var cache: [String: Bool] = [:]
    private static func existing(_ asset: String) -> String? {
        if let hit = cache[asset] { return hit ? asset : nil }
        let ok = UIImage(named: asset) != nil
        cache[asset] = ok
        return ok ? asset : nil
    }

    private static let airlineAliases: [String: String] = [
        "delta": "delta", "unitedairlines": "united", "united": "united", "american": "american",
        "southwest": "southwest", "jetblue": "jetblue", "alaska": "alaska", "hawaiian": "hawaiian",
        "spirit": "spirit", "frontier": "frontier", "allegiant": "allegiant", "aircanada": "aircanada",
        "westjet": "westjet", "aeromexico": "aeromexico", "british": "britishairways", "lufthansa": "lufthansa",
        "klm": "klm", "klmroyaldutch": "klm", "airfrance": "airfrance", "emirates": "emirates",
        "qatar": "qatar", "etihad": "etihad", "singapore": "singapore", "ana": "ana", "allnippon": "ana",
        "japan": "jal", "jal": "jal", "qantas": "qantas", "turkish": "turkish", "iberia": "iberia",
        "virginatlantic": "virginatlantic", "ryanair": "ryanair", "easyjet": "easyjet", "norwegian": "norwegian",
        "norwegianairshuttle": "norwegian", "wizzair": "wizzair", "wizz": "wizzair", "airindia": "airindia",
        "airchina": "airchina", "chinaeastern": "chinaeastern", "chinasouthern": "chinasouthern", "copa": "copa",
        "avianca": "avianca", "ethiopian": "ethiopian", "lotpolish": "lot", "lot": "lot", "indigo": "indigo",
        "saudia": "saudia", "saudi": "saudia", "airasia": "airasia", "pegasus": "pegasus", "airtransat": "airtransat",
        "transat": "airtransat", "cathaypacific": "cathay", "cathay": "cathay", "korean": "korean", "koreanair": "korean",
        "eva": "eva", "evaair": "eva", "finnair": "finnair", "scandinavian": "sas", "sas": "sas", "aerlingus": "aerlingus",
        "airnewzealand": "airnz", "swiss": "swiss", "austrian": "austrian", "icelandair": "icelandair",
    ]

    private static let iataCodes: [String: String] = [
        "DL": "delta", "UA": "united", "AA": "american", "WN": "southwest", "B6": "jetblue", "AS": "alaska",
        "HA": "hawaiian", "NK": "spirit", "F9": "frontier", "G4": "allegiant", "AC": "aircanada", "WS": "westjet",
        "AM": "aeromexico", "BA": "britishairways", "LH": "lufthansa", "KL": "klm", "AF": "airfrance", "EK": "emirates",
        "QR": "qatar", "EY": "etihad", "SQ": "singapore", "NH": "ana", "JL": "jal", "QF": "qantas", "TK": "turkish",
        "IB": "iberia", "VS": "virginatlantic", "FR": "ryanair", "U2": "easyjet", "DY": "norwegian", "W6": "wizzair",
        "AI": "airindia", "CA": "airchina", "MU": "chinaeastern", "CZ": "chinasouthern", "CM": "copa", "AV": "avianca",
        "ET": "ethiopian", "LO": "lot", "6E": "indigo", "SV": "saudia", "AK": "airasia", "PC": "pegasus", "TS": "airtransat",
        "CX": "cathay", "KE": "korean", "BR": "eva", "AY": "finnair", "SK": "sas", "EI": "aerlingus", "NZ": "airnz",
        "LX": "swiss", "OS": "austrian", "FI": "icelandair",
    ]
}

/// Rounded-square logo tile; a hairline keeps dark tiles visible on black.
struct LogoTile: View {
    let asset: String
    var size: CGFloat

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: size * 0.26, style: .continuous)
        Image(asset)
            .resizable()
            .interpolation(.high)
            .scaledToFill()
            .frame(width: size, height: size)
            .clipShape(shape)
            .overlay(shape.strokeBorder(.white.opacity(0.12), lineWidth: 0.5))
            .accessibilityHidden(true)
    }
}

/// Airline mark, falling back to a two-letter badge when we don't bundle one.
struct AirlineBadge: View {
    let airline: String
    var flightNumber: String? = nil
    var size: CGFloat = 30

    var body: some View {
        if let asset = BrandLogos.airline(name: airline, flightNumber: flightNumber) {
            LogoTile(asset: asset, size: size)
        } else {
            let letters = fallbackLetters
            Group {
                if letters.isEmpty {
                    Image(systemName: "airplane").font(.system(size: size * 0.42, weight: .bold))
                } else {
                    Text(letters).font(.system(size: size * 0.36, weight: .heavy, design: .rounded))
                }
            }
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Theme.surfaceHigh, in: RoundedRectangle(cornerRadius: size * 0.26, style: .continuous))
        }
    }

    private var fallbackLetters: String {
        let words = airline.split(separator: " ").filter {
            !["air", "airlines", "airways", "lines"].contains($0.lowercased())
        }
        if words.count >= 2 { return String(words.prefix(2).compactMap(\.first)).uppercased() }
        if let w = words.first { return String(w.prefix(2)).uppercased() }
        return ""
    }
}
