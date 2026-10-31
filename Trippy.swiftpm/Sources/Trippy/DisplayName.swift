import Foundation

/// One place that turns raw API / enum values ("premium_economy", "full_size", "ingestion")
/// into text fit for the UI ("Premium Economy", "Full Size", "Imported").
enum DisplayName {
    private static let acronyms: Set<String> = ["ev", "suv", "awd", "4wd", "2wd", "fwd", "rwd", "phev", "hev", "lpg", "vip", "usa", "uk", "jfk", "lax", "sfo"]

    /// "premium_economy" → "Premium Economy", "full-size SUV" → "Full Size SUV". Leaves already-nice text alone.
    static func humanize(_ raw: String?) -> String {
        let trimmed = (raw ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }
        let spaced = trimmed
            .replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: #"(?<=[a-z])-(?=[a-z])"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        let looksRaw = trimmed.contains("_") || trimmed == trimmed.lowercased() || trimmed == trimmed.uppercased()
        return spaced.split(separator: " ").map { word -> String in
            let w = String(word)
            if acronyms.contains(w.lowercased()) { return w.uppercased() }
            // Keep words that already carry intentional casing ("iPhone", "McLaren", "XC90").
            if !looksRaw { return w }
            return w.prefix(1).uppercased() + w.dropFirst().lowercased()
        }.joined(separator: " ")
    }

    static func optional(_ raw: String?) -> String? {
        let s = humanize(raw)
        return s.isEmpty ? nil : s
    }

    static func cabin(_ raw: String?) -> String? {
        switch norm(raw) {
        case "": return nil
        case "economy", "coach", "main", "main cabin": return "Economy"
        case "premium economy", "premium", "comfort", "comfort plus", "economy plus": return humanize(raw)
        case "business", "business class": return "Business"
        case "first", "first class": return "First"
        default: return humanize(raw)
        }
    }

    static func flightStatus(_ raw: String?) -> String? {
        switch norm(raw) {
        case "": return nil
        case "scheduled": return "Scheduled"
        case "on time", "ontime": return "On time"
        case "active", "en route", "enroute", "in air", "airborne": return "In flight"
        case "landed", "arrived": return "Landed"
        case "delayed": return "Delayed"
        case "cancelled", "canceled": return "Cancelled"
        case "diverted": return "Diverted"
        case "boarding": return "Boarding"
        default: return humanize(raw)
        }
    }

    static func vehicleClass(_ raw: String?) -> String? {
        switch norm(raw) {
        case "": return nil
        case "full size", "fullsize": return "Full Size"
        case "mid size", "midsize", "intermediate": return norm(raw) == "intermediate" ? "Intermediate" : "Midsize"
        case "suv": return "SUV"
        default: return humanize(raw)
        }
    }

    static func fuel(_ raw: String?) -> String? {
        switch norm(raw) {
        case "": return nil
        case "ev", "electric", "bev", "battery electric": return "Electric"
        case "phev", "plug in hybrid": return "Plug-in hybrid"
        case "hybrid", "hev": return "Hybrid"
        case "gas", "gasoline", "petrol", "unleaded": return "Gas"
        case "diesel": return "Diesel"
        default: return humanize(raw)
        }
    }

    static func bookingSource(_ raw: String?) -> String? {
        switch norm(raw) {
        case "": return nil
        case "ingestion", "ingested", "email", "import", "imported": return "Imported from email"
        case "manual": return "Added manually"
        case "api": return "Synced"
        default: return humanize(raw)
        }
    }

    /// Short phrase for how an expense is divided ("split equally", "by percent").
    static func splitMode(_ raw: String?) -> String {
        switch norm(raw) {
        case "equal", "equally": return "split equally"
        case "exact", "amount", "amounts": return "exact amounts"
        case "percent", "percentage": return "by percent"
        case "shares", "share": return "by shares"
        default: return humanize(raw).lowercased()
        }
    }

    private static func norm(_ raw: String?) -> String {
        (raw ?? "").lowercased()
            .replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "-", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
