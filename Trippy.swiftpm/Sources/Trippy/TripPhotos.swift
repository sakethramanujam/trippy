import SwiftUI
import Photos
import PhotosUI
import ImageIO
import CoreLocation
import UIKit

// MARK: - API (GET/POST /trips/{id}/photos, GET /photos/{id}/thumb, DELETE /photos/{id})

/// A trip photo's server copy: a ≤512 px JPEG thumbnail. The full photo stays in the Photos
/// library of the device named by `device_id`; `asset_id` is that device's PHAsset localIdentifier.
struct ApiTripPhoto: Codable, Hashable, Identifiable {
    let id: Int
    let trip_id: Int?
    let device_id: String
    let asset_id: String
    let taken_at: String?
    let lat: Double?
    let lng: Double?
    let width: Int?
    let height: Int?
    let thumb_url: String
    // Story extras (GET /trips/{id}/story → trip_photos)
    let day: Int?
    let item_key: String?

    var takenAt: Date? { Fmt.parse(taken_at) }
    var isOnThisDevice: Bool { device_id == PhotoDevice.id }
}

/// Stable per-install id so the server can tell which device holds each full photo.
enum PhotoDevice {
    static var id: String {
        let key = "TrippyPhotoDeviceId"
        if let v = UserDefaults.standard.string(forKey: key) { return v }
        let v = "ios-" + (UIDevice.current.identifierForVendor?.uuidString ?? UUID().uuidString).lowercased()
        UserDefaults.standard.set(v, forKey: key)
        return v
    }
}

extension NetworkManager {
    func fetchTripPhotos(_ tripId: Int) async -> [ApiTripPhoto] {
        let r = await send("GET", "/trips/\(tripId)/photos")
        guard let data = r.data, r.error == nil else { return [] }
        return (try? JSONDecoder().decode([ApiTripPhoto].self, from: data)) ?? []
    }

    /// Adds (or refreshes) one photo. The same asset from this device is one photo.
    func uploadTripPhoto(_ tripId: Int, _ photo: PreparedPhoto) async -> String? {
        var body: [String: Any] = ["device_id": PhotoDevice.id, "asset_id": photo.assetId,
                                   "thumb_base64": photo.thumb.base64EncodedString()]
        if let t = photo.takenAt { body["taken_at"] = PhotoLibrary.wallClock(t) }
        if let c = photo.location { body["lat"] = c.latitude; body["lng"] = c.longitude }
        return await send("POST", "/trips/\(tripId)/photos", json: body).error
    }

    func deleteTripPhoto(_ id: Int) async -> String? {
        await send("DELETE", "/photos/\(id)").error
    }
}

/// Thumbnails come from the server with your token; cached in memory.
@MainActor
enum PhotoThumbs {
    private static let cache = NSCache<NSString, UIImage>()

    static func cached(_ p: ApiTripPhoto) -> UIImage? { cache.object(forKey: p.thumb_url as NSString) }

    static func load(_ p: ApiTripPhoto) async -> UIImage? {
        if let hit = cached(p) { return hit }
        guard let url = APIConfig.url(p.thumb_url),
              let (data, resp) = try? await APIClient.data(from: url),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let img = UIImage(data: data) else { return nil }
        cache.setObject(img, forKey: p.thumb_url as NSString)
        return img
    }
}

// MARK: - Photos library (PhotoKit)

/// What gets uploaded: a ≤512 px JPEG plus the asset id, date and place. Never the full photo.
struct PreparedPhoto {
    let assetId: String
    let takenAt: Date?
    let location: CLLocationCoordinate2D?
    let thumb: Data
}

struct PhotoSuggestion: Identifiable {
    let asset: PHAsset
    let reason: String
    var id: String { asset.localIdentifier }
}

enum PhotoLibrary {
    static let thumbMax: CGFloat = 512
    /// Farther than this from every place on the trip means "not this trip".
    static let nearKm: Double = 250

    static var status: PHAuthorizationStatus { PHPhotoLibrary.authorizationStatus(for: .readWrite) }

    static func requestAccess() async -> PHAuthorizationStatus {
        let s = status
        if s != .notDetermined { return s }
        return await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    /// "2026-04-11T10:12:00": wall clock where the photo was taken, like the rest of Trippy.
    static func wallClock(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: d)
    }

    /// Photos taken on the trip's days (and near its places when both sides know). With limited
    /// access, only the photos you shared with Trippy are searched.
    static func suggest(start: Date?, end: Date?, places: [CLLocationCoordinate2D], skip: Set<String>) -> [PhotoSuggestion] {
        guard let s = start else { return [] }
        let cal = Calendar.current
        let from = cal.startOfDay(for: min(s, end ?? s))
        guard let to = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: max(s, end ?? s))) else { return [] }
        let opts = PHFetchOptions()
        opts.predicate = NSPredicate(format: "mediaType == %d AND creationDate >= %@ AND creationDate < %@",
                                     PHAssetMediaType.image.rawValue, from as NSDate, to as NSDate)
        opts.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]
        let result = PHAsset.fetchAssets(with: opts)
        var out: [PhotoSuggestion] = []
        result.enumerateObjects { a, _, _ in
            guard !skip.contains(a.localIdentifier) else { return }
            if let loc = a.location?.coordinate, !places.isEmpty {
                let nearest = places.map { km($0, loc) }.min() ?? 0
                if nearest > nearKm { return }
                out.append(PhotoSuggestion(asset: a, reason: "Taken near a place on this trip"))
            } else {
                out.append(PhotoSuggestion(asset: a, reason: "Taken during the trip"))
            }
        }
        return out
    }

    static func km(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D) -> Double {
        CLLocation(latitude: a.latitude, longitude: a.longitude)
            .distance(from: CLLocation(latitude: b.latitude, longitude: b.longitude)) / 1000
    }

    static func asset(_ localId: String) -> PHAsset? {
        PHAsset.fetchAssets(withLocalIdentifiers: [localId], options: nil).firstObject
    }

    static func image(_ asset: PHAsset, maxSide: CGFloat) async -> UIImage? {
        await withCheckedContinuation { cont in
            let o = PHImageRequestOptions()
            o.deliveryMode = .highQualityFormat
            o.resizeMode = .exact
            o.isNetworkAccessAllowed = true
            o.isSynchronous = false
            var done = false
            PHImageManager.default().requestImage(for: asset, targetSize: CGSize(width: maxSide, height: maxSide),
                                                  contentMode: .aspectFit, options: o) { img, info in
                if done { return }
                if (info?[PHImageResultIsDegradedKey] as? Bool) == true { return }
                done = true
                cont.resume(returning: img)
            }
        }
    }

    /// The full photo, when it's in this device's library (for the gallery and share cards).
    static func large(_ localId: String, maxSide: CGFloat = 2048) async -> UIImage? {
        guard let a = asset(localId) else { return nil }
        return await image(a, maxSide: maxSide)
    }

    static func jpegThumb(_ image: UIImage) -> Data? {
        image.scaledToFit(maxSide: thumbMax).jpegData(compressionQuality: 0.8)
    }

    static func prepare(_ asset: PHAsset) async -> PreparedPhoto? {
        guard let img = await image(asset, maxSide: thumbMax), let thumb = jpegThumb(img) else { return nil }
        return PreparedPhoto(assetId: asset.localIdentifier, takenAt: asset.creationDate,
                             location: asset.location?.coordinate, thumb: thumb)
    }

    /// A Photos picker pick. With full or limited access including this photo, PhotoKit has its
    /// date and place; otherwise the image data's EXIF is used (the picker may strip location).
    static func prepare(_ item: PhotosPickerItem) async -> PreparedPhoto? {
        if let id = item.itemIdentifier, let a = asset(id) { return await prepare(a) }
        guard let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data),
              let thumb = jpegThumb(img) else { return nil }
        let meta = exif(data)
        let assetId = item.itemIdentifier ?? "picker:" + String(data.hashValue, radix: 16)
        return PreparedPhoto(assetId: assetId, takenAt: meta.date, location: meta.location, thumb: thumb)
    }

    static func exif(_ data: Data) -> (date: Date?, location: CLLocationCoordinate2D?) {
        guard let src = CGImageSourceCreateWithData(data as CFData, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] else { return (nil, nil) }
        var date: Date?
        if let ex = props[kCGImagePropertyExifDictionary] as? [CFString: Any],
           let raw = ex[kCGImagePropertyExifDateTimeOriginal] as? String {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = .current
            f.dateFormat = "yyyy:MM:dd HH:mm:ss"
            date = f.date(from: String(raw.prefix(19)))
        }
        var loc: CLLocationCoordinate2D?
        if let gps = props[kCGImagePropertyGPSDictionary] as? [CFString: Any],
           var lat = gps[kCGImagePropertyGPSLatitude] as? Double, var lng = gps[kCGImagePropertyGPSLongitude] as? Double {
            if (gps[kCGImagePropertyGPSLatitudeRef] as? String) == "S" { lat = -lat }
            if (gps[kCGImagePropertyGPSLongitudeRef] as? String) == "W" { lng = -lng }
            loc = CLLocationCoordinate2D(latitude: lat, longitude: lng)
        }
        return (date, loc)
    }

    /// Limited access: let people share more photos with Trippy.
    @MainActor
    static func presentLimitedPicker() {
        guard let root = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
            .flatMap(\.windows).first(where: \.isKeyWindow)?.rootViewController else { return }
        var top = root
        while let next = top.presentedViewController { top = next }
        PHPhotoLibrary.shared().presentLimitedLibraryPicker(from: top)
    }
}

// MARK: - Trip section

/// Photos on a trip: a strip of your photos (thumbnails from the server), Add (Photos picker)
/// and Suggest (PhotoKit by date taken and place). Suggestions are accepted or rejected one by one.
struct TripPhotosSection: View {
    @ObservedObject var network: NetworkManager
    let trip: ApiTrip
    let snapshot: TripSnapshot

    @State private var photos: [ApiTripPhoto] = []
    @State private var picks: [PhotosPickerItem] = []
    @State private var suggestions: [PhotoSuggestion] = []
    @State private var showSuggestions = false
    @State private var galleryIndex: Int?
    @State private var busy = false
    @State private var message: String?
    @State private var access = PhotoLibrary.status

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s3) {
            HStack(alignment: .firstTextBaseline) {
                Text("Photos").type(.title3).foregroundStyle(.white)
                Spacer()
                if !photos.isEmpty { MicroLabel(text: "\(photos.count)") }
            }
            if photos.isEmpty {
                Text("Add photos from this trip. They stay on your phone; your server keeps a small preview.")
                    .type(.footnote).foregroundStyle(Theme.textSecondary)
            } else {
                TripPhotoStrip(photos: photos, size: 88) { galleryIndex = $0 }
            }
            HStack(spacing: 10) {
                PhotosPicker(selection: $picks, maxSelectionCount: 30, matching: .images, photoLibrary: .shared()) {
                    Label("Add photos", systemImage: "photo.badge.plus")
                }
                .buttonStyle(TintedButtonStyle())
                Button { Task { await suggest() } } label: {
                    Label("Suggest", systemImage: "sparkles")
                }
                .buttonStyle(TintedButtonStyle(tint: Theme.teal))
            }
            .disabled(busy)
            if access == .limited {
                Button("Trippy sees only the photos you chose. Choose more…") { PhotoLibrary.presentLimitedPicker() }
                    .type(.caption).foregroundStyle(Theme.blue)
            }
            if busy { ProgressView().tint(.white) }
            if let message { Text(message).type(.caption).foregroundStyle(Theme.textSecondary) }
        }
        .task(id: trip.id) { await reload() }
        .onChange(of: picks) { _, items in
            guard !items.isEmpty else { return }
            Task { await upload(items: items) }
        }
        .sheet(isPresented: $showSuggestions) {
            PhotoSuggestionsSheet(suggestions: suggestions) { accepted in
                Task { await upload(assets: accepted) }
            }
        }
        .fullScreenCover(item: Binding(get: { galleryIndex.map { GalleryIndex(value: $0) } },
                                       set: { galleryIndex = $0?.value })) { g in
            TripPhotoGallery(network: network, photos: photos, start: g.value) { await reload() }
        }
    }

    private func reload() async { photos = await network.fetchTripPhotos(trip.id) }

    private func suggest() async {
        access = await PhotoLibrary.requestAccess()
        guard access == .authorized || access == .limited else {
            message = "Allow Photos access in Settings › Privacy & Security › Photos, or use Add photos."
            return
        }
        let mine = Set(photos.filter(\.isOnThisDevice).map(\.asset_id))
        let found = PhotoLibrary.suggest(start: snapshot.start, end: snapshot.end,
                                         places: snapshot.stops.compactMap(\.coordinate), skip: mine)
        if found.isEmpty {
            message = access == .limited ? "No shared photos from these dates. Choose more photos to search them."
                                         : "No new photos from these dates."
            return
        }
        suggestions = found
        showSuggestions = true
    }

    private func upload(items: [PhotosPickerItem]) async {
        busy = true; defer { busy = false; picks = [] }
        var n = 0
        for item in items {
            guard let p = await PhotoLibrary.prepare(item) else { continue }
            if await network.uploadTripPhoto(trip.id, p) == nil { n += 1 }
        }
        message = "Added \(n) photo\(n == 1 ? "" : "s")."
        await reload()
    }

    private func upload(assets: [PHAsset]) async {
        busy = true; defer { busy = false }
        var n = 0
        for a in assets {
            guard let p = await PhotoLibrary.prepare(a) else { continue }
            if await network.uploadTripPhoto(trip.id, p) == nil { n += 1 }
        }
        message = "Added \(n) photo\(n == 1 ? "" : "s")."
        await reload()
    }
}

private struct GalleryIndex: Identifiable { let value: Int; var id: Int { value } }

struct TripPhotoStrip: View {
    let photos: [ApiTripPhoto]
    var size: CGFloat = 88
    var selected: Int? = nil
    let onTap: (Int) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Array(photos.enumerated()), id: \.element.id) { i, p in
                    Button { onTap(i) } label: {
                        TripPhotoThumb(photo: p)
                            .frame(width: size, height: size)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .strokeBorder(selected == i ? Theme.stay : .white.opacity(0.1), lineWidth: selected == i ? 3 : 1))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Photo \(i + 1)")
                }
            }
        }
    }
}

struct TripPhotoThumb: View {
    let photo: ApiTripPhoto
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            Theme.surfaceRaised
            if let image { Image(uiImage: image).resizable().scaledToFill() } else { ProgressView().tint(.white) }
        }
        .task(id: photo.id) { image = PhotoThumbs.cached(photo); if image == nil { image = await PhotoThumbs.load(photo) } }
    }
}

struct PhotoSuggestionsSheet: View {
    let suggestions: [PhotoSuggestion]
    let onAdd: ([PHAsset]) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var rejected: Set<String> = []
    @State private var thumbs: [String: UIImage] = [:]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("\(suggestions.count) photos look like this trip. Tap one to leave it out.")
                        .type(.callout).foregroundStyle(Theme.textSecondary)
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], spacing: 8) {
                        ForEach(suggestions) { s in
                            let out = rejected.contains(s.id)
                            Button {
                                if out { rejected.remove(s.id) } else { rejected.insert(s.id) }
                            } label: {
                                ZStack(alignment: .topTrailing) {
                                    Color(Theme.surfaceRaised)
                                    if let img = thumbs[s.id] { Image(uiImage: img).resizable().scaledToFill() }
                                    Image(systemName: out ? "xmark.circle.fill" : "checkmark.circle.fill")
                                        .font(.title3).foregroundStyle(out ? Theme.textSecondary : Theme.green)
                                        .background(Circle().fill(.black.opacity(0.5)))
                                        .padding(6)
                                }
                                .frame(height: 104)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .opacity(out ? 0.4 : 1)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(s.reason)
                            .task { if thumbs[s.id] == nil { thumbs[s.id] = await PhotoLibrary.image(s.asset, maxSide: 240) } }
                        }
                    }
                }
                .padding(Theme.pagePadding)
            }
            .trippyScreen()
            .navigationTitle("Suggested photos")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    let n = suggestions.count - rejected.count
                    Button("Add \(n)") {
                        onAdd(suggestions.filter { !rejected.contains($0.id) }.map(\.asset))
                        dismiss()
                    }
                    .disabled(n == 0)
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

/// Full-screen pager. Photos on this device show full size from the library; others show the thumbnail.
struct TripPhotoGallery: View {
    @ObservedObject var network: NetworkManager
    let photos: [ApiTripPhoto]
    let start: Int
    let onChange: () async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var index = 0
    @State private var confirmRemove = false

    var body: some View {
        ZStack(alignment: .top) {
            Color.black.ignoresSafeArea()
            TabView(selection: $index) {
                ForEach(Array(photos.enumerated()), id: \.element.id) { i, p in
                    GalleryPage(photo: p).tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            HStack {
                Button { dismiss() } label: { Image(systemName: "xmark").font(.headline).foregroundStyle(.white).padding(10).background(.black.opacity(0.4), in: Circle()) }
                    .accessibilityLabel("Close")
                Spacer()
                Text("\(index + 1) of \(photos.count)").type(.calloutStrong).foregroundStyle(.white)
                Spacer()
                Button { confirmRemove = true } label: { Image(systemName: "trash").font(.headline).foregroundStyle(.white).padding(10).background(.black.opacity(0.4), in: Circle()) }
                    .accessibilityLabel("Remove from trip")
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            if let p = photos[safe: index] {
                VStack(spacing: 4) {
                    Spacer()
                    if let d = p.takenAt { Text(Fmt.dayYear(d) + " · " + Fmt.time(d)).type(.footnoteStrong).foregroundStyle(.white) }
                    Text(p.isOnThisDevice ? "Full photo from this iPhone's library" : "Preview: the full photo is on another device")
                        .type(.caption).foregroundStyle(.white.opacity(0.7))
                }
                .padding(.bottom, 30)
            }
        }
        .onAppear { index = start }
        .preferredColorScheme(.dark)
        .confirmationDialog("Remove this photo from the trip?", isPresented: $confirmRemove, titleVisibility: .visible) {
            Button("Remove from trip", role: .destructive) {
                guard let p = photos[safe: index] else { return }
                Task { _ = await network.deleteTripPhoto(p.id); await onChange(); dismiss() }
            }
        } message: { Text("It stays in your Photos library.") }
    }
}

private struct GalleryPage: View {
    let photo: ApiTripPhoto
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            if let image { Image(uiImage: image).resizable().scaledToFit() } else { ProgressView().tint(.white) }
        }
        .task(id: photo.id) {
            image = PhotoThumbs.cached(photo)
            if photo.isOnThisDevice, let big = await PhotoLibrary.large(photo.asset_id) { image = big; return }
            if image == nil { image = await PhotoThumbs.load(photo) }
        }
    }
}
