import Foundation
#if canImport(ActivityKit)
import ActivityKit
#endif

// Shared by the app and the widget extension.

/// What the widgets show; written by the app into the shared App Group.
struct WidgetSnapshotData: Codable {
    struct Trip: Codable { var title: String; var start: Date; var end: Date? }
    struct Flight: Codable {
        var number: String; var airline: String; var from: String; var to: String
        var departs: Date; var arrives: Date?; var confirmation: String?
    }
    var nextTrip: Trip?
    var nextFlight: Flight?
    var written: Date
}

extension WidgetSnapshotData {
    static let appGroup = "group.samalabs.trippy"
    static var fileURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?.appendingPathComponent("widget.json")
    }
    static func load() -> WidgetSnapshotData? {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(WidgetSnapshotData.self, from: data)
    }
}

#if canImport(ActivityKit)
/// Live Activity for one flight; the app starts and updates it (no push on free provisioning).
struct FlightActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var status: String       // "On time", "Delayed 25m", "Boarding"...
        var gate: String?
        var departs: Date
        var arrives: Date?
    }
    var number: String
    var from: String
    var to: String
}
#endif
