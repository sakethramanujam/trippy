import SwiftUI
import UniformTypeIdentifiers

/// One importer the server offers (`GET /import/sources` lists the same ids).
struct ImportSource: Identifiable, Hashable {
    let id: String
    let title: String
    let detail: String
    let icon: String
    let tint: Color
    let types: [UTType]
    let acceptsFile: Bool
    let acceptsPaste: Bool
    let acceptsURL: Bool

    static let all: [ImportSource] = [
        ImportSource(id: "ics", title: "Calendar file", detail: "An .ics from Google, Outlook, Apple Calendar or a TripIt trip",
                     icon: "calendar", tint: Theme.red, types: [UTType(filenameExtension: "ics") ?? .calendarEvent, .calendarEvent],
                     acceptsFile: true, acceptsPaste: true, acceptsURL: false),
        ImportSource(id: "ics_url", title: "Calendar feed", detail: "A webcal:// or https:// link, like TripIt's calendar feed",
                     icon: "link", tint: Theme.teal, types: [], acceptsFile: false, acceptsPaste: false, acceptsURL: true),
        ImportSource(id: "flighty_csv", title: "Flighty", detail: "The CSV from Flighty's flight export",
                     icon: "airplane.departure", tint: Theme.blue, types: [.commaSeparatedText, .plainText],
                     acceptsFile: true, acceptsPaste: false, acceptsURL: false),
        ImportSource(id: "pkpass", title: "Wallet boarding pass", detail: "A .pkpass file saved from an airline app or email",
                     icon: "wallet.pass.fill", tint: Theme.green, types: [UTType(filenameExtension: "pkpass") ?? .data, .data],
                     acceptsFile: true, acceptsPaste: false, acceptsURL: false),
        ImportSource(id: "email", title: "Confirmation email", detail: "Rental car receipts, flights and hotels: an .eml file or pasted text",
                     icon: "envelope.fill", tint: Theme.orange, types: [UTType(filenameExtension: "eml") ?? .emailMessage, .emailMessage, .plainText],
                     acceptsFile: true, acceptsPaste: true, acceptsURL: false),
        ImportSource(id: "google_timeline", title: "Google Maps Timeline", detail: "Your drives from a Timeline export: the routes, miles and stops on each trip",
                     icon: "point.topleft.down.to.point.bottomright.curvepath.fill", tint: Theme.teal, types: [.json],
                     acceptsFile: true, acceptsPaste: false, acceptsURL: false),
        ImportSource(id: "csv", title: "Spreadsheet (CSV)", detail: "Any CSV: you choose which column is which",
                     icon: "tablecells", tint: Theme.purple, types: [.commaSeparatedText, .tabSeparatedText, .plainText],
                     acceptsFile: true, acceptsPaste: false, acceptsURL: false),
    ]
}

/// One row of a preview. `fields` is sent back unchanged when adding.
struct ImportItem: Identifiable {
    let index: Int
    let kind: String
    let summary: String
    let confidence: String
    let warnings: [String]
    let duplicate: Bool
    let duplicateInBatch: Bool
    let fields: [String: Any]
    /// Drives: the trip/journey this drive matched ("trip_title", "journey_title").
    var match: [String: Any] = [:]
    var suggested: Bool = true
    var id: Int { index }

    var matchText: String? {
        if let j = match["journey_title"] as? String { return "Journey: \(j)" }
        if let t = match["trip_title"] as? String { return "Trip: \(t)" }
        return kind == "drive" ? "Not during a trip" : nil
    }

    var icon: String {
        switch kind {
        case "flight": return "airplane"
        case "rental": return "car.fill"
        case "drive": return "steeringwheel"
        default: return "bed.double.fill"
        }
    }
}

struct CSVMappingInfo {
    var columns: [String]
    var sampleRow: [String]
    var rowCount: Int
    var targets: [String: (required: [String], optional: [String])]
    var mapping: [String: String]
}

struct ImportView: View {
    @ObservedObject var network: NetworkManager
    var initialSource: ImportSource? = nil
    @Environment(\.dismiss) private var dismiss

    enum Stage { case pick, input, mapping, preview, done }

    @State private var stage: Stage = .pick
    @State private var source: ImportSource?
    @State private var pasted = ""
    @State private var feedURL = ""
    @State private var fileName: String?
    @State private var fileData: Data?
    @State private var showFiles = false
    @State private var busy = false
    @State private var error: String?

    @State private var csvKind = "flight"
    @State private var mapping: CSVMappingInfo?
    @State private var items: [ImportItem] = []
    @State private var selected: Set<Int> = []
    @State private var stats: [String: Any] = [:]
    @State private var autoTrip = true
    @State private var tripId: Int?
    @State private var result: (created: Int, skipped: Int)?
    @State private var drivesScope = "trips"

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let error { FormErrorBanner(message: error) }
                    switch stage {
                    case .pick: pickStage
                    case .input: inputStage
                    case .mapping: mappingStage
                    case .preview: previewStage
                    case .done: doneStage
                    }
                }
                .padding(.horizontal, Theme.pagePadding + 4)
                .padding(.vertical, 12)
                .padding(.bottom, stage == .preview ? 90 : 20)
                .animation(.default, value: error)
            }
            .scrollDismissesKeyboard(.interactively)
            .overlay(alignment: .bottom) { if stage == .preview { addBar } }
            .trippyScreen()
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if stage == .pick || stage == .done {
                        Button(stage == .done ? "Done" : "Close") { dismiss() }
                    } else {
                        Button { back() } label: { Label("Back", systemImage: "chevron.left") }
                    }
                }
            }
            .fileImporter(isPresented: $showFiles, allowedContentTypes: source?.types ?? [.data]) { picked in
                Task { await loadFile(picked) }
            }
            .task {
                if let initialSource { choose(initialSource) }
                if UserDefaults.standard.bool(forKey: "TrippyImportDemo") { await runDemo() }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var title: String {
        switch stage {
        case .pick: return "Import"
        case .input: return source?.title ?? "Import"
        case .mapping: return "Match columns"
        case .preview: return "Review"
        case .done: return "Imported"
        }
    }

    // MARK: Stages

    private var pickStage: some View {
        VStack(alignment: .leading, spacing: 14) {
            ScreenHeader(title: "Bring your trips", subtitle: "Pick where they are now. You'll see everything before it's added, and anything already in Trippy is skipped.")
            VStack(spacing: 10) {
                ForEach(ImportSource.all) { s in
                    Button { choose(s) } label: { SourceRow(source: s) }
                        .buttonStyle(.plain)
                }
            }
            Text("TripIt has no open API, so Trippy reads its calendar feed instead (tripit.com → Settings → Calendar Feed).")
                .type(.caption)
                .foregroundStyle(Theme.textTertiary)
        }
    }

    @ViewBuilder
    private var inputStage: some View {
        if let s = source {
            SourceRow(source: s, chevron: false)
            if s.acceptsURL {
                AuthField(label: "Calendar link", text: $feedURL, placeholder: "webcal://www.tripit.com/feed/ical/…", keyboard: .URL)
                Text("Trippy's server downloads the feed. Private links stay on your server.")
                    .type(.caption)
                    .foregroundStyle(Theme.textTertiary)
                Button { Task { await preview() } } label: { BusyButtonLabel(title: "Preview", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy || feedURL.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            if s.acceptsFile {
                Button { showFiles = true } label: {
                    Label(fileName ?? "Choose file", systemImage: fileName == nil ? "folder" : "doc.fill")
                }
                .buttonStyle(TintedButtonStyle(tint: s.tint))
                .disabled(busy)
            }
            if s.acceptsPaste {
                VStack(alignment: .leading, spacing: 7) {
                    Text(s.acceptsFile ? "OR PASTE THE TEXT" : "PASTE THE TEXT")
                        .type(.label).tracking(0.6)
                        .foregroundStyle(Theme.textSecondary)
                    TextEditor(text: $pasted)
                        .type(.mono)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 160)
                        .padding(8)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                Button { Task { await preview() } } label: { BusyButtonLabel(title: "Preview pasted text", busy: busy) }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy || pasted.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if s.id == "google_timeline" {
                Picker("Drives", selection: $drivesScope) {
                    Text("During my trips").tag("trips")
                    Text("All drives").tag("all")
                }
                .pickerStyle(.segmented)
                Text("On your phone: Settings → Location → Location Services → Timeline → Export Timeline data. From Google Takeout, choose a Semantic Location History month file. Only drives are imported, and they're private to you.")
                    .type(.caption)
                    .foregroundStyle(Theme.textTertiary)
            }
            if busy && !s.acceptsPaste && !s.acceptsURL {
                HStack { Spacer(); ProgressView().tint(.white); Spacer() }
            }
        }
    }

    @ViewBuilder
    private var mappingStage: some View {
        if let m = mapping {
            Text("\(m.rowCount) rows. Tell Trippy which column holds what.")
                .type(.callout)
                .foregroundStyle(Theme.textSecondary)
            Picker("Rows are", selection: $csvKind) {
                Text("Flights").tag("flight")
                Text("Rental cars").tag("rental")
                Text("Hotels").tag("lodging")
            }
            .pickerStyle(.segmented)
            .onChange(of: csvKind) { _, _ in Task { await preview(withMapping: false) } }

            let t = m.targets[csvKind] ?? (required: [], optional: [])
            VStack(spacing: 0) {
                ForEach(t.required + t.optional, id: \.self) { field in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(field.replacingOccurrences(of: "_", with: " ").capitalized + (t.required.contains(field) ? " *" : ""))
                                .type(.calloutStrong)
                                .foregroundStyle(Theme.textPrimary)
                            if let col = mapping?.mapping[field], let i = m.columns.firstIndex(of: col), i < m.sampleRow.count {
                                Text("e.g. \(m.sampleRow[i])")
                                    .type(.caption)
                                    .foregroundStyle(Theme.textTertiary)
                                    .lineLimit(1)
                            }
                        }
                        Spacer()
                        Picker(field, selection: Binding(
                            get: { mapping?.mapping[field] ?? "" },
                            set: { mapping?.mapping[field] = $0.isEmpty ? nil : $0 })) {
                            Text("—").tag("")
                            ForEach(m.columns, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden()
                        .tint(Theme.blue)
                    }
                    .padding(.vertical, 8)
                    Hairline()
                }
            }
            Button { Task { await preview(withMapping: true) } } label: { BusyButtonLabel(title: "Preview", busy: busy) }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(busy)
        }
    }

    private var previewStage: some View {
        VStack(alignment: .leading, spacing: 14) {
            let dupes = items.filter { $0.duplicate || $0.duplicateInBatch }.count
            HStack(spacing: 10) {
                MetricTile(value: "\(items.count - dupes)", label: "New", systemImage: "sparkles", tint: Theme.green)
                MetricTile(value: "\(dupes)", label: "In Trippy", systemImage: "checkmark.circle")
                if let outside = stats["outside_trips"] as? Int, source?.id == "google_timeline" {
                    MetricTile(value: "\(outside)", label: drivesScope == "trips" ? "Not on a trip" : "Outside trips", systemImage: "minus.circle")
                } else if let skipped = stats["skipped"] as? Int {
                    MetricTile(value: "\(skipped)", label: "Not travel", systemImage: "minus.circle")
                }
            }
            if items.isEmpty {
                EmptyStateCard(systemImage: "tray", title: "Nothing to import",
                               message: source?.id == "google_timeline"
                                   ? (drivesScope == "trips" ? "No drives during your trips. Choose All drives to see every drive." : "No drives in this file.")
                                   : "Trippy didn't find flights, rental cars or hotel stays in this \(source?.id == "email" ? "email" : "file").")
            } else {
                destinationPicker
                VStack(spacing: 8) {
                    ForEach(items) { item in
                        ImportItemRow(item: item, selected: selected.contains(item.index)) {
                            if selected.contains(item.index) { selected.remove(item.index) } else { selected.insert(item.index) }
                        }
                    }
                }
            }
        }
    }

    private var destinationPicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(isOn: $autoTrip) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Add to matching trips").type(.calloutStrong)
                    Text("Each booking goes on your trip covering its date.")
                        .type(.caption).foregroundStyle(Theme.textSecondary)
                }
            }
            .tint(Theme.green)
            if !autoTrip {
                Picker("Trip", selection: $tripId) {
                    Text("No trip").tag(Int?.none)
                    ForEach(network.trips) { t in Text(t.title).tag(Int?.some(t.id)) }
                }
                .tint(Theme.blue)
            }
        }
        .card(padding: 14)
    }

    private var addBar: some View {
        Button { Task { await commit() } } label: {
            BusyButtonLabel(title: selected.isEmpty ? "Select items to add" : "Add \(selected.count) to Trippy", busy: busy)
        }
        .buttonStyle(PrimaryButtonStyle())
        .disabled(busy || selected.isEmpty)
        .padding(.horizontal, Theme.pagePadding + 4)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }

    private var doneStage: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.circle.fill")
                .type(.hero)
                .foregroundStyle(Theme.green)
                .padding(.top, 30)
            Text("Added \(result?.created ?? 0)")
                .type(.title)
            if let skipped = result?.skipped, skipped > 0 {
                Text("\(skipped) skipped because they're already in Trippy.")
                    .type(.callout).foregroundStyle(Theme.textSecondary)
            }
            Button("Import more") { reset(); stage = .pick }
                .buttonStyle(TintedButtonStyle())
                .padding(.top, 10)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: Actions

    private func choose(_ s: ImportSource) {
        reset()
        source = s
        stage = .input
    }

    private func back() {
        error = nil
        switch stage {
        case .preview where mapping != nil: stage = .mapping
        case .preview, .mapping: stage = .input
        default: reset(); stage = .pick
        }
    }

    private func reset() {
        pasted = ""; feedURL = ""; fileName = nil; fileData = nil; error = nil
        mapping = nil; items = []; selected = []; stats = [:]; result = nil; csvKind = "flight"
    }

    private func loadFile(_ picked: Result<URL, Error>) async {
        do {
            let url = try picked.get()
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let data = try Data(contentsOf: url)
            guard data.count <= 5 * 1024 * 1024 else { error = "That file is larger than 5 MB."; return }
            fileName = url.lastPathComponent
            fileData = data
            pasted = ""
            await preview()
        } catch {
            self.error = "Couldn't open that file: \(error.localizedDescription)"
        }
    }

    private func preview(withMapping: Bool = false) async {
        guard let s = source else { return }
        var body: [String: Any] = ["source": s.id]
        if s.acceptsURL {
            body["url"] = feedURL.trimmingCharacters(in: .whitespacesAndNewlines)
        } else if !pasted.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body["text"] = pasted
        } else if let fileData {
            body["data_base64"] = fileData.base64EncodedString()
            body["filename"] = fileName ?? ""
        } else {
            error = "Choose a file first."
            return
        }
        if s.id == "google_timeline" {
            body["timezone"] = TimeZone.current.identifier
            body["drives_scope"] = drivesScope
        }
        if s.id == "csv" {
            body["csv_kind"] = csvKind
            if withMapping, let m = mapping?.mapping { body["mapping"] = m }
        }
        busy = true
        defer { busy = false }
        do {
            let data = try await APIClient.json("POST", "/import/preview", body)
            guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw APIError(status: 0, message: "Unexpected answer from the server") }
            error = nil
            if obj["needs_mapping"] as? Bool == true {
                mapping = Self.mappingInfo(obj)
                stage = .mapping
                return
            }
            items = ((obj["items"] as? [[String: Any]]) ?? []).map(Self.item)
            stats = obj["stats"] as? [String: Any] ?? [:]
            selected = Set(items.filter { !$0.duplicate && !$0.duplicateInBatch && $0.suggested }.map(\.index))
            stage = .preview
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func commit() async {
        let picked = items.filter { selected.contains($0.index) }.map { ["kind": $0.kind, "fields": $0.fields] as [String: Any] }
        var body: [String: Any] = ["items": picked, "auto_trip": autoTrip]
        if !autoTrip, let tripId { body["trip_id"] = tripId }
        busy = true
        defer { busy = false }
        do {
            let data = try await APIClient.json("POST", "/import/commit", body)
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            result = ((obj["created"] as? [Any])?.count ?? 0, (obj["skipped"] as? [Any])?.count ?? 0)
            stage = .done
            await network.fetchTrips()
            await network.fetchRentals()
            await network.fetchFlights()
            if source?.id == "google_timeline" { await network.fetchTrips() }
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// `-TrippyImportDemo YES`: previews a built-in synthetic calendar (screenshots).
    private func runDemo() async {
        guard let ics = ImportSource.all.first(where: { $0.id == "ics" }) else { return }
        choose(ics)
        pasted = Self.demoCalendar
        await preview()
    }

    private static let demoCalendar = """
    BEGIN:VCALENDAR
    VERSION:2.0
    PRODID:-//Trippy//Demo//EN
    BEGIN:VEVENT
    UID:demo-1@trippy
    DTSTART:20270412T111500
    DTEND:20270413T143000
    SUMMARY:Flight UA 837 SFO to NRT
    LOCATION:San Francisco International Airport (SFO)
    END:VEVENT
    BEGIN:VEVENT
    UID:demo-2@trippy
    DTSTART;VALUE=DATE:20270413
    DTEND;VALUE=DATE:20270418
    SUMMARY:Stay at Park Hyatt Tokyo
    LOCATION:3-7-1-2 Nishishinjuku, Tokyo
    END:VEVENT
    BEGIN:VEVENT
    UID:demo-3@trippy
    DTSTART:20270414T090000
    DTEND:20270417T180000
    SUMMARY:Car rental - Toyota Rent a Car pickup at NRT
    END:VEVENT
    BEGIN:VEVENT
    UID:demo-4@trippy
    DTSTART:20270418T170000
    DTEND:20270418T104500
    SUMMARY:Flight NH 8 NRT to SFO
    END:VEVENT
    BEGIN:VEVENT
    UID:demo-5@trippy
    DTSTART:20270410T190000
    DTEND:20270410T200000
    SUMMARY:Dinner with Maya
    END:VEVENT
    END:VCALENDAR
    """

    // MARK: Decoding

    private static func item(_ d: [String: Any]) -> ImportItem {
        ImportItem(index: d["index"] as? Int ?? 0,
                   kind: d["kind"] as? String ?? "flight",
                   summary: d["summary"] as? String ?? "",
                   confidence: d["confidence"] as? String ?? "high",
                   warnings: d["warnings"] as? [String] ?? [],
                   duplicate: !(d["duplicate_of"] is NSNull) && d["duplicate_of"] != nil,
                   duplicateInBatch: !(d["duplicate_in_batch"] is NSNull) && d["duplicate_in_batch"] != nil,
                   fields: d["fields"] as? [String: Any] ?? [:],
                   match: d["match"] as? [String: Any] ?? [:],
                   suggested: d["suggested"] as? Bool ?? true)
    }

    private static func mappingInfo(_ obj: [String: Any]) -> CSVMappingInfo {
        var targets: [String: (required: [String], optional: [String])] = [:]
        for (k, v) in obj["targets"] as? [String: [String: [String]]] ?? [:] {
            targets[k] = (v["required"] ?? [], v["optional"] ?? [])
        }
        let rows = obj["sample_rows"] as? [[String]] ?? []
        return CSVMappingInfo(columns: obj["columns"] as? [String] ?? [],
                              sampleRow: rows.first ?? [],
                              rowCount: obj["row_count"] as? Int ?? 0,
                              targets: targets,
                              mapping: obj["suggested_mapping"] as? [String: String] ?? [:])
    }
}

private struct SourceRow: View {
    let source: ImportSource
    var chevron = true

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: source.icon)
                .type(.headline)
                .foregroundStyle(source.tint)
                .frame(width: 42, height: 42)
                .background(source.tint.opacity(0.16), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(source.title).type(.headline).foregroundStyle(Theme.textPrimary)
                Text(source.detail).type(.footnote).foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            if chevron {
                Image(systemName: "chevron.right").type(.footnoteStrong).foregroundStyle(Theme.textTertiary)
            }
        }
        .card(padding: 14)
        .contentShape(Rectangle())
    }
}

private struct ImportItemRow: View {
    let item: ImportItem
    let selected: Bool
    let toggle: () -> Void

    private var isDupe: Bool { item.duplicate || item.duplicateInBatch }

    var body: some View {
        Button(action: toggle) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .type(.title2)
                    .foregroundStyle(selected ? Theme.blue : Theme.textTertiary)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 6) {
                        Image(systemName: item.icon).type(.footnoteStrong).foregroundStyle(Theme.textSecondary)
                        Text(item.kind == "lodging" ? "HOTEL" : item.kind.uppercased())
                            .type(.label).tracking(0.5).foregroundStyle(Theme.textSecondary)
                        if item.confidence != "high" {
                            StatusPill(text: item.confidence == "low" ? "Check" : "Likely", color: item.confidence == "low" ? Theme.orange : Theme.amber)
                        }
                        if isDupe {
                            StatusPill(text: item.duplicate ? "In Trippy" : "Repeated", color: Theme.textSecondary)
                        }
                    }
                    Text(item.summary)
                        .type(.calloutStrong)
                        .foregroundStyle(isDupe ? Theme.textSecondary : Theme.textPrimary)
                        .multilineTextAlignment(.leading)
                    if let m = item.matchText {
                        Label(m, systemImage: item.match["trip_id"] is Int || item.match["journey_id"] is Int ? "suitcase.fill" : "questionmark.circle")
                            .type(.caption).foregroundStyle(Theme.teal)
                    }
                    ForEach(item.warnings, id: \.self) { w in
                        Text(w).type(.caption).foregroundStyle(Theme.orange)
                            .multilineTextAlignment(.leading)
                    }
                }
                Spacer(minLength: 0)
            }
            .card(padding: 14)
            .opacity(isDupe && !selected ? 0.7 : 1)
        }
        .buttonStyle(.plain)
    }
}
