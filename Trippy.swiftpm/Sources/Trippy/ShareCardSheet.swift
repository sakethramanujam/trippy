import SwiftUI
import Photos
import UIKit

/// Card picker + preview + Share / Save to Photos. Kinds available depend on where it opens:
/// a trip opens on its recap; the Driver's Log opens on Your Year / Driver's Log.
struct ShareCardSheet: View {
    @ObservedObject var network: NetworkManager
    let kinds: [CardKind]
    var tripId: Int? = nil
    /// Journey recap card (combined story of its linked trips) instead of a single trip.
    var journeyId: Int? = nil
    var year: Int
    var initialKind: CardKind? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var kind: CardKind = .trip
    @State private var format: CardFormat = .story
    @State private var hideMoney = UserDefaults.standard.bool(forKey: "TrippyCardsHideMoney")
    @State private var story: ApiStory?
    @State private var yearData: ApiYearInTravel?
    @State private var yearStays: ApiStayStats?
    @State private var maps: [String: UIImage] = [:]
    @State private var rendered: UIImage?
    @State private var fileURL: URL?
    @State private var loading = true
    @State private var errorText: String?
    @State private var savedToast: String?
    @State private var backgroundIndex: Int?
    @State private var backgroundPhoto: UIImage?

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                VStack(spacing: 14) {
                    if kinds.count > 1 {
                        Picker("Card", selection: $kind) {
                            ForEach(kinds) { Text($0.label).tag($0) }
                        }
                        .pickerStyle(.segmented)
                    }
                    preview
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    controls
                }
                .padding(.horizontal, Theme.pagePadding)
                .padding(.bottom, 8)
                if let savedToast {
                    Text(savedToast)
                        .type(.calloutStrong)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(Capsule().fill(Color(hex: 0x2C2C2E)))
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .frame(maxHeight: .infinity, alignment: .top)
                        .padding(.top, 8)
                }
            }
            .navigationTitle("Share card")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            }
        }
        .preferredColorScheme(.dark)
        .task {
            kind = initialKind ?? kinds.first ?? .trip
            if let f = UserDefaults.standard.string(forKey: "TrippyCardFormat"), let v = CardFormat(rawValue: f) { format = v }
            await load()
        }
        .onChange(of: kind) { _, _ in Task { await prepare() } }
        .onChange(of: format) { _, _ in Task { await prepare() } }
        .onChange(of: hideMoney) { _, v in
            UserDefaults.standard.set(v, forKey: "TrippyCardsHideMoney")
            Task { await prepare() }
        }
        .alert("Couldn't save", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(errorText ?? "") }
    }

    // MARK: Preview

    private var preview: some View {
        GeometryReader { geo in
            let size = format.size
            let k = min(geo.size.width / size.width, geo.size.height / size.height)
            ZStack {
                if let rendered {
                    Image(uiImage: rendered)
                        .resizable()
                        .interpolation(.high)
                        .frame(width: size.width * k, height: size.height * k)
                        .clipShape(RoundedRectangle(cornerRadius: 22 * k, style: .continuous))
                        .shadow(color: kind.gradient[0].opacity(0.45), radius: 30, y: 12)
                        .transition(.opacity)
                } else {
                    RoundedRectangle(cornerRadius: 22 * k, style: .continuous)
                        .fill(Theme.surface)
                        .frame(width: size.width * k, height: size.height * k)
                        .overlay(ProgressView().tint(.white))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
    }

    private var tripPhotos: [ApiTripPhoto] { story?.trip_photos ?? [] }

    /// Pick one of your trip photos as the card's background (or none).
    private var backgroundPicker: some View {
        HStack(spacing: 8) {
            Button {
                backgroundIndex = nil; backgroundPhoto = nil
                Task { await prepare() }
            } label: {
                Image(systemName: "nosign")
                    .frame(width: 52, height: 52)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(backgroundIndex == nil ? Theme.stay : .clear, lineWidth: 3))
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("No photo background")
            TripPhotoStrip(photos: tripPhotos, size: 52, selected: backgroundIndex) { i in
                backgroundIndex = i
                Task {
                    let p = tripPhotos[i]
                    var img: UIImage?
                    if p.isOnThisDevice { img = await PhotoLibrary.large(p.asset_id, maxSide: 1600) }
                    if img == nil { img = await PhotoThumbs.load(p) }
                    backgroundPhoto = img
                    await prepare()
                }
            }
        }
    }

    private var controls: some View {
        VStack(spacing: 12) {
            if kind == .trip && !tripPhotos.isEmpty { backgroundPicker }
            HStack(spacing: 10) {
                Picker("Format", selection: $format) {
                    ForEach(CardFormat.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                if kind != .year {
                    Toggle(isOn: $hideMoney) {
                        Image(systemName: hideMoney ? "eye.slash.fill" : "dollarsign.circle.fill")
                    }
                    .toggleStyle(.button)
                    .tint(hideMoney ? Theme.purple : Color.white.opacity(0.25))
                    .accessibilityLabel(hideMoney ? "Money hidden" : "Hide money")
                }
            }
            HStack(spacing: 10) {
                Button { Task { await saveToPhotos() } } label: {
                    Label("Save", systemImage: "square.and.arrow.down")
                        .type(.headline)
                        .frame(maxWidth: .infinity).frame(height: 50)
                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.surface))
                        .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
                .disabled(rendered == nil)
                if let fileURL, let rendered {
                    ShareLink(item: fileURL, preview: SharePreview(shareTitle, image: Image(uiImage: rendered))) {
                        Label("Share", systemImage: "square.and.arrow.up")
                            .type(.headline)
                            .frame(maxWidth: .infinity).frame(height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.purple))
                            .foregroundStyle(.white)
                    }
                } else {
                    Label("Share", systemImage: "square.and.arrow.up")
                        .type(.headline)
                        .frame(maxWidth: .infinity).frame(height: 50)
                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.purple.opacity(0.4)))
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
        }
    }

    private var shareTitle: String {
        switch kind {
        case .trip: return story?.title ?? "Trip"
        case .year: return "\(year) in travel"
        case .drivers: return "\(year) Driver's Log"
        }
    }

    // MARK: Data + rendering

    private func load() async {
        loading = true
        if kinds.contains(.trip), let journeyId {
            if case .success(let s) = await network.fetchJourneyStory(journeyId) { story = s }
        } else if kinds.contains(.trip), let tripId {
            if case .success(let s) = await network.fetchStory(tripId: tripId) { story = s }
        }
        if kinds.contains(.year) {
            async let y = network.fetchYearInTravel(year)
            async let st = network.fetchStayStats(year: year)
            yearData = await y
            yearStays = await st
        }
        if kinds.contains(.drivers), network.rentals.isEmpty { await network.fetchRentals() }
        loading = false
        await prepare()
    }

    private func prepare() async {
        UserDefaults.standard.set(format.rawValue, forKey: "TrippyCardFormat")
        let assets = await ShareCardFactory.maps(kind: kind, format: format, story: story, year: yearData, cache: maps)
        maps.merge(assets) { $1 }
        let image = ShareCardFactory.render(kind: kind, format: format, story: story, year: yearData,
                                            rentals: network.rentals, yearNumber: year, hideMoney: hideMoney,
                                            name: AuthManager.shared.profile?.name ?? "", maps: maps, stays: yearStays,
                                            photo: kind == .trip ? backgroundPhoto : nil)
        withAnimation(.easeOut(duration: 0.2)) { rendered = image }
        fileURL = image.flatMap { CardRenderer.pngFile($0, name: "\(shareTitle)-\(format.rawValue)") }
    }

    private func saveToPhotos() async {
        guard let rendered else { return }
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            errorText = "Allow Trippy to add photos in Settings › Privacy & Security › Photos."
            return
        }
        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetCreationRequest.creationRequestForAsset(from: rendered)
            }
            withAnimation(.snappy) { savedToast = "Saved to Photos" }
            try? await Task.sleep(nanoseconds: 1_600_000_000)
            withAnimation(.snappy) { savedToast = nil }
        } catch {
            errorText = error.localizedDescription
        }
    }
}

/// Builds map art and rendered cards; shared by the sheet and the DEBUG exporter.
@MainActor
enum ShareCardFactory {
    static func mapSize(_ kind: CardKind, _ format: CardFormat) -> CGSize {
        switch (kind, format) {
        case (.trip, .story): return CGSize(width: 316, height: 210)
        case (.trip, .square): return CGSize(width: 320, height: 150)
        case (.year, .story): return CGSize(width: 316, height: 176)
        case (.year, .square): return CGSize(width: 320, height: 128)
        default: return .zero
        }
    }

    static func key(_ kind: CardKind, _ format: CardFormat, _ theme: String = "") -> String { "\(kind.rawValue)-\(format.rawValue)-\(theme)" }

    static func maps(kind: CardKind, format: CardFormat, story: ApiStory?, year: ApiYearInTravel?,
                     cache: [String: UIImage]) async -> [String: UIImage] {
        let size = mapSize(kind, format)
        switch kind {
        case .trip:
            guard let story else { return [:] }
            let k = key(kind, format, story.theme + story.route.map(\.label).joined())
            if cache[k] != nil { return [:] }
            let t = story.themeGradient
            let img = await CardMapArt.route(story.route, size: size, tint: UIColor(t.colors[1]), accent: UIColor(t.accent))
            return [k: img]
        case .year:
            guard let year else { return [:] }
            let k = key(kind, format, "\(year.year)")
            if cache[k] != nil { return [:] }
            let img = await CardMapArt.world(points: year.points, arcs: year.arcs, size: size,
                                             tint: UIColor(Color(hex: 0x6A4CFF)), accent: UIColor(Color(hex: 0xD9CCFF)))
            return [k: img]
        case .drivers:
            return [:]
        }
    }

    static func render(kind: CardKind, format: CardFormat, story: ApiStory?, year: ApiYearInTravel?,
                       rentals: [ApiRentalCar], yearNumber: Int, hideMoney: Bool, name: String,
                       maps: [String: UIImage], stays: ApiStayStats? = nil, photo: UIImage? = nil) -> UIImage? {
        switch kind {
        case .trip:
            guard let story else { return nil }
            let map = maps[key(kind, format, story.theme + story.route.map(\.label).joined())]
            return CardRenderer.render(TripRecapCard(story: story, map: map, format: format, hideMoney: hideMoney, photo: photo), format: format)
        case .year:
            guard let year else { return nil }
            return CardRenderer.render(YearInTravelCard(year: year, map: maps[key(kind, format, "\(year.year)")], format: format, name: name, stays: stays), format: format)
        case .drivers:
            let list = rentals.filter { $0.pickupYear == yearNumber }
            let data = DriverLogData(rentals: list.isEmpty ? rentals : list, year: list.isEmpty ? nil : yearNumber)
            return CardRenderer.render(DriverLogCard(data: data, format: format, hideMoney: hideMoney), format: format)
        }
    }

    #if DEBUG
    /// `-TrippyExportCards YES` writes every card × format into Documents/TrippyCards for review.
    /// `-TrippyExportTrip <id>` picks the trip (default: the past trip with the most stops).
    static func exportAll(network: NetworkManager) async {
        let fm = FileManager.default
        let dir = fm.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("TrippyCards", isDirectory: true)
        try? fm.removeItem(at: dir)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        for _ in 0..<40 where network.trips.isEmpty { try? await Task.sleep(nanoseconds: 500_000_000) }
        if network.rentals.isEmpty { await network.fetchRentals() }
        var log: [String] = []
        let wanted = UserDefaults.standard.integer(forKey: "TrippyExportTrip")
        let now = Date()
        let tripId = wanted > 0 ? wanted : network.trips
            .map { TripSnapshot(trip: $0, allRentals: network.rentals, now: now) }
            .filter { $0.phase == .past }
            .max { ($0.stops.count, $0.events.count) < ($1.stops.count, $1.events.count) }?.trip.id
        var story: ApiStory?
        if let tripId, case .success(let s) = await network.fetchStory(tripId: tripId) { story = s }
        let yearNumber = UserDefaults.standard.integer(forKey: "TrippyExportYear") > 0
            ? UserDefaults.standard.integer(forKey: "TrippyExportYear") : (story?.year ?? Calendar.current.component(.year, from: now))
        let year = await network.fetchYearInTravel(yearNumber)
        let stays = await network.fetchStayStats(year: yearNumber)
        log.append("trip=\(tripId.map(String.init) ?? "nil") story=\(story?.title ?? "nil") year=\(yearNumber) yearData=\(year != nil) rentals=\(network.rentals.count)")
        var maps: [String: UIImage] = [:]
        for kind in CardKind.allCases {
            for format in CardFormat.allCases {
                maps.merge(await self.maps(kind: kind, format: format, story: story, year: year, cache: maps)) { $1 }
                for hide in kind == .year ? [false] : [false, true] {
                    guard let img = render(kind: kind, format: format, story: story, year: year, rentals: network.rentals,
                                           yearNumber: yearNumber, hideMoney: hide, name: AuthManager.shared.profile?.name ?? "", maps: maps, stays: stays),
                          let png = img.pngData() else { log.append("FAILED \(kind) \(format)"); continue }
                    let file = "\(kind.rawValue)-\(format.rawValue)\(hide ? "-nomoney" : "").png"
                    try? png.write(to: dir.appendingPathComponent(file))
                    log.append("\(file) \(Int(img.size.width * img.scale))x\(Int(img.size.height * img.scale))")
                }
            }
        }
        try? log.joined(separator: "\n").write(to: dir.appendingPathComponent("done.txt"), atomically: true, encoding: .utf8)
        print("TRIPPY_EXPORT_DONE \(dir.path)")
    }
    #endif
}
