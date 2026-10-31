import WidgetKit
import SwiftUI
import ActivityKit

// Widget extension target only (not compiled into the app).

struct SnapshotEntry: TimelineEntry {
    let date: Date
    let data: WidgetSnapshotData?
}

struct SnapshotProvider: TimelineProvider {
    static let sample = WidgetSnapshotData(
        nextTrip: .init(title: "Tokyo 2027", start: Date().addingTimeInterval(12 * 86400), end: nil),
        nextFlight: .init(number: "UA 837", airline: "United", from: "SFO", to: "NRT",
                          departs: Date().addingTimeInterval(26 * 3600), arrives: nil, confirmation: "ABC123"),
        written: Date())

    func placeholder(in context: Context) -> SnapshotEntry { SnapshotEntry(date: .now, data: Self.sample) }
    func getSnapshot(in context: Context, completion: @escaping (SnapshotEntry) -> Void) {
        completion(SnapshotEntry(date: .now, data: context.isPreview ? Self.sample : (WidgetSnapshotData.load() ?? Self.sample)))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<SnapshotEntry>) -> Void) {
        let data = WidgetSnapshotData.load()
        // Hourly entries so day counts roll over; the app reloads timelines whenever trips change.
        let entries = (0..<12).map { SnapshotEntry(date: Date().addingTimeInterval(Double($0) * 3600), data: data) }
        completion(Timeline(entries: entries, policy: .atEnd))
    }
}

private let ink = Color(red: 0.04, green: 0.52, blue: 1.0)

private func daysUntil(_ d: Date, from now: Date) -> Int {
    Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: now),
                                    to: Calendar.current.startOfDay(for: d)).day ?? 0
}

// MARK: Next trip countdown

struct NextTripView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SnapshotEntry

    var body: some View {
        if let t = entry.data?.nextTrip {
            let days = daysUntil(t.start, from: entry.date)
            switch family {
            case .accessoryCircular:
                VStack(spacing: 0) {
                    Text(days <= 0 ? "Now" : "\(days)").font(.system(size: 20, weight: .bold, design: .rounded))
                    Text(days == 1 ? "day" : "days").font(.system(size: 9)).opacity(days <= 0 ? 0 : 1)
                }
                .widgetAccentable()
            case .accessoryRectangular:
                VStack(alignment: .leading, spacing: 1) {
                    Label(t.title, systemImage: "airplane").font(.headline).lineLimit(1)
                    Text(days <= 0 ? "Happening now" : "in \(days) day\(days == 1 ? "" : "s")").font(.caption)
                    Text(t.start, format: .dateTime.month(.abbreviated).day()).font(.caption2).foregroundStyle(.secondary)
                }
            case .accessoryInline:
                Text(days <= 0 ? "✈︎ \(t.title) now" : "✈︎ \(t.title) in \(days)d")
            default:
                VStack(alignment: .leading, spacing: 4) {
                    Text("NEXT TRIP").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    Text(t.title).font(.headline).foregroundStyle(.white).lineLimit(2)
                    Spacer(minLength: 0)
                    Text(days <= 0 ? "Now" : "\(days)").font(.system(size: 40, weight: .bold, design: .rounded))
                        .foregroundStyle(ink).minimumScaleFactor(0.6)
                    Text(days <= 0 ? "Have a great trip" : (days == 1 ? "day to go" : "days to go"))
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            Text(family == .accessoryInline ? "No trips planned" : "No upcoming trips.\nOpen Trippy to sync.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct NextTripWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "NextTrip", provider: SnapshotProvider()) { entry in
            NextTripView(entry: entry).containerBackground(Color(white: 0.07), for: .widget)
        }
        .configurationDisplayName("Next trip")
        .description("Days until your next trip.")
        .supportedFamilies([.systemSmall, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

// MARK: Next flight

struct NextFlightView: View {
    @Environment(\.widgetFamily) private var family
    let entry: SnapshotEntry

    var body: some View {
        if let f = entry.data?.nextFlight {
            switch family {
            case .accessoryRectangular:
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(f.number) · \(f.from)→\(f.to)").font(.headline).lineLimit(1)
                    Text(f.departs, style: .relative).font(.caption).monospacedDigit()
                    Text(f.departs, format: .dateTime.weekday(.abbreviated).hour().minute()).font(.caption2).foregroundStyle(.secondary)
                }
            case .accessoryInline:
                Text("✈︎ \(f.number) \(f.departs.formatted(.dateTime.hour().minute()))")
            case .systemMedium:
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("NEXT FLIGHT").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                        Text("\(f.airline) \(f.number)").font(.subheadline.weight(.semibold)).foregroundStyle(.white)
                        HStack(spacing: 8) {
                            Text(f.from).font(.system(size: 30, weight: .bold, design: .rounded)).foregroundStyle(.white)
                            Image(systemName: "airplane").foregroundStyle(ink)
                            Text(f.to).font(.system(size: 30, weight: .bold, design: .rounded)).foregroundStyle(.white)
                        }
                        if let c = f.confirmation { Text("Conf \(c)").font(.caption.monospaced()).foregroundStyle(.secondary) }
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(f.departs, format: .dateTime.weekday(.abbreviated).month(.abbreviated).day())
                            .font(.caption).foregroundStyle(.secondary)
                        Text(f.departs, format: .dateTime.hour().minute()).font(.title2.weight(.semibold)).foregroundStyle(.white)
                        Text(f.departs, style: .relative).font(.caption).foregroundStyle(ink).multilineTextAlignment(.trailing)
                    }
                }
            default:
                VStack(alignment: .leading, spacing: 4) {
                    Text(f.number).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    Text("\(f.from) → \(f.to)").font(.headline).foregroundStyle(.white)
                    Spacer(minLength: 0)
                    Text(f.departs, format: .dateTime.hour().minute()).font(.title2.weight(.bold)).foregroundStyle(.white)
                    Text(f.departs, style: .relative).font(.caption).foregroundStyle(ink)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            Text(family == .accessoryInline ? "No flights" : "No upcoming flights.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct NextFlightWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "NextFlight", provider: SnapshotProvider()) { entry in
            NextFlightView(entry: entry).containerBackground(Color(white: 0.07), for: .widget)
        }
        .configurationDisplayName("Next flight")
        .description("Your next flight, with a countdown.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular, .accessoryInline])
    }
}

// MARK: Live Activity

struct FlightLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: FlightActivityAttributes.self) { ctx in
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(ctx.attributes.number).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text("\(ctx.attributes.from) → \(ctx.attributes.to)").font(.title3.weight(.bold))
                    Text(ctx.state.status + (ctx.state.gate.map { " · Gate \($0)" } ?? "")).font(.caption)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Text(ctx.state.departs, format: .dateTime.hour().minute()).font(.title3.weight(.semibold))
                    Text(timerInterval: Date()...max(ctx.state.departs, Date()), countsDown: true)
                        .font(.caption).monospacedDigit().foregroundStyle(ink).multilineTextAlignment(.trailing)
                }
            }
            .padding()
            .activityBackgroundTint(Color(white: 0.08))
            .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { ctx in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { Text(ctx.attributes.from).font(.title2.bold()) }
                DynamicIslandExpandedRegion(.trailing) { Text(ctx.attributes.to).font(.title2.bold()) }
                DynamicIslandExpandedRegion(.center) { Text(ctx.attributes.number).font(.caption) }
                DynamicIslandExpandedRegion(.bottom) {
                    Text(ctx.state.status + (ctx.state.gate.map { " · Gate \($0)" } ?? "") + " · "
                         + ctx.state.departs.formatted(.dateTime.hour().minute())).font(.caption)
                }
            } compactLeading: {
                Image(systemName: "airplane").foregroundStyle(ink)
            } compactTrailing: {
                Text(timerInterval: Date()...max(ctx.state.departs, Date()), countsDown: true)
                    .monospacedDigit().frame(maxWidth: 52)
            } minimal: {
                Image(systemName: "airplane").foregroundStyle(ink)
            }
        }
    }
}

@main
struct TrippyWidgetBundle: WidgetBundle {
    var body: some Widget {
        NextTripWidget()
        NextFlightWidget()
        FlightLiveActivity()
    }
}
