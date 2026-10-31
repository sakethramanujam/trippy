import SwiftUI
import MapKit
import CoreImage
import UIKit

// MARK: - Card formats and kinds

enum CardFormat: String, CaseIterable, Identifiable {
    case story, square
    var id: String { rawValue }
    var label: String { self == .story ? "Story 9:16" : "Square 1:1" }
    /// Layout size in points; exported at @3x (1080×1920 / 1080×1080).
    var size: CGSize { self == .story ? CGSize(width: 360, height: 640) : CGSize(width: 360, height: 360) }
}

enum CardKind: String, CaseIterable, Identifiable {
    case trip, year, drivers
    var id: String { rawValue }
    var label: String {
        switch self {
        case .trip: return "Trip"
        case .year: return "Your Year"
        case .drivers: return "Driver's Log"
        }
    }
    var gradient: [Color] {
        switch self {
        case .trip: return StoryTheme.indigo.colors
        case .year: return [Color(hex: 0x5B3BF0), Color(hex: 0x2D138F), Color(hex: 0x10063A)]
        case .drivers: return [Color(hex: 0x18B48A), Color(hex: 0x0B5E52), Color(hex: 0x03201C)]
        }
    }
    var accent: Color {
        switch self {
        case .trip: return StoryTheme.indigo.accent
        case .year: return Color(hex: 0xC6B8FF)
        case .drivers: return Color(hex: 0x9CF5D2)
        }
    }
}

// MARK: - Driver's Log data (client-side from rentals)

struct DriverLogData {
    let yearLabel: String
    let rentals: Int
    let days: Int
    let miles: Int
    let cars: Int
    let companies: Int
    let spend: Double
    let topCompany: String?
    let topCompanyCount: Int
    let topCars: [(name: String, count: Int)]
    let longestDays: Int

    init(rentals list: [ApiRentalCar], year: Int?) {
        let s = RentalSummary(list)
        yearLabel = year.map(String.init) ?? "ALL-TIME"
        rentals = s.count
        days = Int(s.days.rounded())
        miles = Int(s.miles.rounded())
        cars = Set(list.map(\.vehicleName)).count
        companies = Set(list.map { RentalBrand.forCompany($0.rental_company).name }).count
        spend = s.spend
        topCompany = s.byCompany.first.map { RentalBrand.forCompany($0.company).name }
        topCompanyCount = s.byCompany.first?.count ?? 0
        topCars = Array(s.topCars.prefix(3))
        longestDays = list.compactMap(\.rentalDays).max() ?? 0
    }
}

// MARK: - Map art (MKMapSnapshotter + route drawing)

enum CardMapArt {
    private static func format() -> UIGraphicsImageRendererFormat {
        let f = UIGraphicsImageRendererFormat.default()
        f.scale = 3
        f.opaque = true
        f.preferredRange = .standard
        return f
    }

    private static let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    /// One-hue version of a map snapshot: keeps land/sea luminance, swaps the colors for `tint`.
    private static func tinted(_ image: UIImage, tint: UIColor, intensity: Double, contrast: Double, brightness: Double) -> UIImage {
        guard let cgInput = image.cgImage else { return image }
        let input = CIImage(cgImage: cgInput)
        // Explicit sRGB components: CIColor(color:) on a SwiftUI-bridged UIColor comes out black.
        var red: CGFloat = 0, green: CGFloat = 0, blue: CGFloat = 0, alpha: CGFloat = 0
        if !tint.resolvedColor(with: UITraitCollection(userInterfaceStyle: .dark)).getRed(&red, green: &green, blue: &blue, alpha: &alpha) {
            red = 0.75; green = 0.7; blue = 1; alpha = 1
        }
        let ciTint = CIColor(red: red, green: green, blue: blue, alpha: 1)
        let mono = CIFilter(name: "CIColorMonochrome", parameters: [kCIInputImageKey: input,
                                                                   kCIInputColorKey: ciTint,
                                                                   kCIInputIntensityKey: intensity])?.outputImage ?? input
        let adjusted = CIFilter(name: "CIColorControls", parameters: [kCIInputImageKey: mono,
                                                                     kCIInputContrastKey: contrast,
                                                                     kCIInputBrightnessKey: brightness,
                                                                     kCIInputSaturationKey: 1.15])?.outputImage ?? mono
        guard let cg = ciContext.createCGImage(adjusted, from: input.extent) else { return image }
        let out = UIImage(cgImage: cg, scale: image.scale, orientation: .up)
        return out
    }

    /// The snapshot as a plain bitmap. Drawing `Snapshot.image` straight into another renderer comes out black,
    /// so it's round-tripped through PNG data, which always decodes to a CGImage-backed image.
    private static func snapshotImage(_ options: MKMapSnapshotter.Options) async -> UIImage? {
        guard let snap = await snapshot(options), let data = snap.image.pngData(),
              let decoded = UIImage(data: data, scale: snap.image.scale) else { return nil }
        return decoded
    }

    private static func snapshot(_ options: MKMapSnapshotter.Options) async -> MKMapSnapshotter.Snapshot? {
        let snap: MKMapSnapshotter.Snapshot? = await withCheckedContinuation { cont in
            MKMapSnapshotter(options: options).start(with: .global(qos: .userInitiated)) { snap, error in
                if let error { print("TRIPPY_SNAPSHOT_ERROR \(error)") }
                cont.resume(returning: snap)
            }
        }
        return snap
    }

    /// Expands `r` to the aspect ratio of `size`.
    private static func fit(_ r: MKMapRect, to size: CGSize) -> MKMapRect {
        let want = size.width / size.height
        let have = r.width / r.height
        if have > want {
            let h = r.width / want
            return MKMapRect(x: r.minX, y: r.midY - h / 2, width: r.width, height: h)
        }
        let w = r.height * want
        return MKMapRect(x: r.midX - w / 2, y: r.minY, width: w, height: r.height)
    }

    /// Dark, label-light map of a trip's route with a glowing curved path and stop dots.
    static func route(_ stops: [ApiStoryPlace], size: CGSize, tint: UIColor, accent: UIColor) async -> UIImage {
        let coords = stops.compactMap(\.coordinate)
        guard let base = MapFraming.rect(coords, minMeters: 120_000, padding: 0.32) else {
            return fallback(size: size, tint: tint, accent: accent, points: [], arcs: [])
        }
        let rect = fit(base, to: size)
        let o = MKMapSnapshotter.Options()
        o.mapRect = rect
        o.size = size
        o.scale = 3
        o.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        let cfg = MKStandardMapConfiguration(elevationStyle: .flat, emphasisStyle: .muted)
        cfg.pointOfInterestFilter = .excludingAll
        cfg.showsTraffic = false
        o.preferredConfiguration = cfg

        // Project with our own Mercator math so routes across the antimeridian stay continuous.
        let world = MKMapRect.world.width
        func project(_ c: CLLocationCoordinate2D) -> CGPoint {
            let mp = MKMapPoint(c)
            var x = mp.x
            while x < rect.minX - world * 0.25 { x += world }
            while x > rect.maxX + world * 0.25 { x -= world }
            return CGPoint(x: (x - rect.minX) / rect.width * size.width, y: (mp.y - rect.minY) / rect.height * size.height)
        }
        let pts = coords.map(project)
        var labels: [(CGPoint, String)] = []
        var seen = Set<String>()
        for s in stops {
            guard let c = s.coordinate else { continue }
            let p = project(c)
            let name = (s.code?.isEmpty == false ? s.code! : (s.city ?? "")).uppercased()
            if seen.insert(name).inserted { labels.append((p, name)) }
        }

        guard let snapImage = await snapshotImage(o) else {
            return fallback(size: size, tint: tint, accent: accent, points: pts, arcs: zip(pts, pts.dropFirst()).map { ($0, $1, 1) })
        }
        let mapArt = tinted(snapImage, tint: accent, intensity: 1, contrast: 1.15, brightness: -0.02)
        return composite(base: mapArt, size: size, tint: tint, tintAlpha: 0.35) { cg in
            drawArcs(cg, segments: zip(pts, pts.dropFirst()).map { ($0, $1, 1) }, accent: accent, width: 2.6)
            drawDots(cg, pts.map { ($0, 1) }, accent: accent)
            drawLabels(labels, size: size)
        }
    }

    /// Satellite map framed on the year's places (Pacific-centred when that is shorter), tinted to one hue, with arcs.
    static func world(points: [ApiYearPoint], arcs: [ApiYearArc], size: CGSize, tint: UIColor, accent: UIColor) async -> UIImage {
        var coords = points.compactMap { p -> CLLocationCoordinate2D? in
            guard let lat = p.lat, let lng = p.lng else { return nil }
            return CLLocationCoordinate2D(latitude: lat, longitude: lng)
        }
        for a in arcs where a.from.count == 2 && a.to.count == 2 {
            coords.append(CLLocationCoordinate2D(latitude: a.from[0], longitude: a.from[1]))
            coords.append(CLLocationCoordinate2D(latitude: a.to[0], longitude: a.to[1]))
        }
        // Longitude window: the complement of the widest empty gap, so US↔Japan goes over the Pacific.
        var centerLng = 0.0, lngSpan = 360.0
        let lngs = coords.map(\.longitude).sorted()
        if let first = lngs.first, let last = lngs.last {
            var gap = first + 360 - last, gapEnd = first
            for (x, y) in zip(lngs, lngs.dropFirst()) where y - x > gap { gap = y - x; gapEnd = y }
            lngSpan = 360 - gap
            var c = gapEnd + lngSpan / 2
            if c > 180 { c -= 360 }
            centerLng = c
        }
        let lats = coords.map(\.latitude)
        let minLat = lats.min() ?? -50, maxLat = lats.max() ?? 70
        let aspect = size.height / size.width
        var spanLng = min(max(lngSpan * 1.5, 70), 300)
        var spanLat = spanLng * aspect * 0.85
        if spanLat < (maxLat - minLat) * 1.5 {
            spanLat = min((maxLat - minLat) * 1.5, 140)
            spanLng = min(spanLat / aspect / 0.85, 300)
        }
        let centerLat = min(max((minLat + maxLat) / 2, -60 + spanLat / 2), 75 - spanLat / 2)

        let o = MKMapSnapshotter.Options()
        o.region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: centerLat, longitude: centerLng),
                                      span: MKCoordinateSpan(latitudeDelta: spanLat, longitudeDelta: spanLng))
        o.size = size
        o.scale = 3
        o.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        o.preferredConfiguration = MKImageryMapConfiguration(elevationStyle: .flat)

        guard let snap = await snapshot(o), let data = snap.image.pngData(),
              let snapImage = UIImage(data: data, scale: snap.image.scale) else {
            return fallback(size: size, tint: tint, accent: accent, points: [], arcs: [])
        }
        // Project through the snapshot itself so dots always sit on the rendered land.
        func project(_ lat: Double, _ lng: Double) -> CGPoint {
            var best = snap.point(for: CLLocationCoordinate2D(latitude: lat, longitude: lng))
            for shift in [-360.0, 360.0] where best.x < -size.width * 0.1 || best.x > size.width * 1.1 {
                let alt = snap.point(for: CLLocationCoordinate2D(latitude: lat, longitude: lng + shift))
                if abs(alt.x - size.width / 2) < abs(best.x - size.width / 2) { best = alt }
            }
            return best
        }
        let dots = points.compactMap { p -> (CGPoint, Int)? in
            guard let lat = p.lat, let lng = p.lng else { return nil }
            return (project(lat, lng), p.visits)
        }
        let segs: [(CGPoint, CGPoint, Int)] = arcs.compactMap { a in
            guard a.from.count == 2, a.to.count == 2 else { return nil }
            return (project(a.from[0], a.from[1]), project(a.to[0], a.to[1]), a.count)
        }
        let mapArt = tinted(snapImage, tint: accent, intensity: 1, contrast: 1.3, brightness: 0.0)
        return composite(base: mapArt, size: size, tint: tint, tintAlpha: 0.3) { cg in
            cg.saveGState()
            cg.clip(to: CGRect(origin: .zero, size: size))
            drawArcs(cg, segments: segs, accent: accent, width: 1.8)
            cg.restoreGState()
            drawDots(cg, dots, accent: accent)
        }
    }

    // MARK: Drawing

    /// Map bitmap + transparent vector overlay, merged in Core Image. Drawing the bitmap into a
    /// UIGraphicsImageRenderer drops it (the panel came out flat), while Core Image output renders reliably.
    private static func composite(base: UIImage, size: CGSize, tint: UIColor, tintAlpha: CGFloat,
                                  overlay: (CGContext) -> Void) -> UIImage {
        let f = format()
        f.opaque = false
        let over = UIGraphicsImageRenderer(size: size, format: f).image { ctx in
            tint.withAlphaComponent(tintAlpha).setFill()
            ctx.fill(CGRect(origin: .zero, size: size))
            overlay(ctx.cgContext)
        }
        guard let b = base.cgImage, let o = over.cgImage else { return over }
        let overImage = CIImage(cgImage: o)
        var baseImage = CIImage(cgImage: b)
        baseImage = baseImage.transformed(by: CGAffineTransform(scaleX: overImage.extent.width / baseImage.extent.width,
                                                                y: overImage.extent.height / baseImage.extent.height))
        let backdrop = CIImage(color: CIColor(red: 0.04, green: 0.04, blue: 0.05)).cropped(to: overImage.extent)
        let merged = overImage.composited(over: baseImage.composited(over: backdrop))
        guard let cg = ciContext.createCGImage(merged, from: overImage.extent,
                                               format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)) else { return over }
        return UIImage(cgImage: cg, scale: over.scale, orientation: .up)
    }

    private static func control(_ a: CGPoint, _ b: CGPoint) -> CGPoint {
        let mid = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
        let dx = b.x - a.x, dy = b.y - a.y
        let len = max(hypot(dx, dy), 0.001)
        var nx = -dy / len, ny = dx / len
        if ny > 0 { nx = -nx; ny = -ny }   // bulge toward the top of the map, like a great circle
        let bend = min(len * 0.22, 60)
        return CGPoint(x: mid.x + nx * bend, y: mid.y + ny * bend)
    }

    private static func drawArcs(_ cg: CGContext, segments: [(CGPoint, CGPoint, Int)], accent: UIColor, width: CGFloat) {
        for (a, b, count) in segments where hypot(b.x - a.x, b.y - a.y) > 1 {
            let path = UIBezierPath()
            path.move(to: a)
            path.addQuadCurve(to: b, controlPoint: control(a, b))
            let w = width + CGFloat(min(count - 1, 3)) * 0.5
            cg.saveGState()
            cg.setShadow(offset: .zero, blur: 8, color: accent.withAlphaComponent(0.9).cgColor)
            cg.setStrokeColor(accent.cgColor)
            cg.setLineWidth(w)
            cg.setLineCap(.round)
            cg.addPath(path.cgPath)
            cg.strokePath()
            cg.restoreGState()
            cg.saveGState()
            cg.setStrokeColor(UIColor.white.withAlphaComponent(0.85).cgColor)
            cg.setLineWidth(max(w * 0.35, 0.8))
            cg.setLineCap(.round)
            cg.addPath(path.cgPath)
            cg.strokePath()
            cg.restoreGState()
        }
    }

    private static func drawDots(_ cg: CGContext, _ dots: [(CGPoint, Int)], accent: UIColor) {
        for (p, visits) in dots {
            let r = 3.2 + CGFloat(min(max(visits, 1) - 1, 4)) * 0.6
            cg.setFillColor(accent.withAlphaComponent(0.35).cgColor)
            cg.fillEllipse(in: CGRect(x: p.x - r * 2.2, y: p.y - r * 2.2, width: r * 4.4, height: r * 4.4))
            cg.setFillColor(UIColor.white.cgColor)
            cg.fillEllipse(in: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2))
        }
    }

    private static func drawLabels(_ labels: [(CGPoint, String)], size: CGSize) {
        let attrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 10, weight: .semibold),
            .foregroundColor: UIColor.white,
            .kern: 1.0,
        ]
        var placed: [CGRect] = []
        for (p, text) in labels.prefix(7) {
            let t = text.count > 12 ? String(text.prefix(11)) + "…" : text
            let s = (t as NSString).size(withAttributes: attrs)
            var box = CGRect(x: p.x + 9, y: p.y - s.height / 2 - 3, width: s.width + 10, height: s.height + 6)
            if box.maxX > size.width - 6 { box.origin.x = p.x - 9 - box.width }
            if placed.contains(where: { $0.intersects(box) }) { box.origin.y += box.height + 2 }
            box.origin.y = min(max(box.minY, 4), size.height - box.height - 4)
            placed.append(box)
            UIColor.black.withAlphaComponent(0.6).setFill()
            UIBezierPath(roundedRect: box, cornerRadius: box.height / 2).fill()
            (t as NSString).draw(at: CGPoint(x: box.minX + 5, y: box.minY + 3), withAttributes: attrs)
        }
    }

    /// Offline fallback: a dotted graticule with the same arcs.
    private static func fallback(size: CGSize, tint: UIColor, accent: UIColor, points: [CGPoint], arcs: [(CGPoint, CGPoint, Int)]) -> UIImage {
        UIGraphicsImageRenderer(size: size, format: format()).image { ctx in
            let r = CGRect(origin: .zero, size: size)
            tint.withAlphaComponent(0.35).setFill()
            ctx.fill(r)
            UIColor.white.withAlphaComponent(0.12).setFill()
            stride(from: CGFloat(6), to: size.width, by: 9).forEach { x in
                stride(from: CGFloat(6), to: size.height, by: 9).forEach { y in
                    ctx.cgContext.fillEllipse(in: CGRect(x: x, y: y, width: 1.6, height: 1.6))
                }
            }
            drawArcs(ctx.cgContext, segments: arcs, accent: accent, width: 2)
            drawDots(ctx.cgContext, points.map { ($0, 1) }, accent: accent)
        }
    }
}

// MARK: - Card typography
//
// Every card uses at most three sizes (display / value / label) and an 8 pt spacing rhythm.
// SF Pro throughout: bold display numbers with tight tracking and tabular digits, small uppercase
// semibold labels at 55 % white. Units sit on the number's baseline at ~35-40 % of its size.

/// Fixed-size type for share cards and stories (rendered to images, so no Dynamic Type).
/// Same families and weights as `TType`: rounded bold numbers, Display bold titles,
/// medium supporting text, semibold tracked labels, SF Mono only for MRZ/codes.
enum CardType {
    static let label: CGFloat = 12

    static func number(_ size: CGFloat) -> Font { TType.font(.hero, size: size) }
    static func title(_ size: CGFloat) -> Font { .system(size: size, weight: .bold) }
    static func text(_ size: CGFloat) -> Font { .system(size: size, weight: .medium) }
    static func labelFont(_ size: CGFloat = label) -> Font { .system(size: size, weight: .semibold).monospacedDigit() }
    static func mono(_ size: CGFloat) -> Font { .system(size: size, weight: .regular, design: .monospaced) }
    static func tracking(for size: CGFloat) -> CGFloat { size >= 60 ? -2.2 : (size >= 28 ? -1.1 : -0.4) }
}

/// Small uppercase caption: stat labels, kickers, route codes.
struct CardLabel: View {
    let text: String
    var opacity: Double = 0.55
    var body: some View {
        Text(text.uppercased())
            .font(CardType.labelFont())
            .tracking(1.2)
            .foregroundStyle(.white.opacity(opacity))
            .lineLimit(1)
    }
}

/// "NOV 1 – 15, 2026": SF Pro Text semibold, uppercase, tracking 1.5, 60 %.
struct CardDateLine: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(CardType.labelFont())
            .tracking(1.5)
            .foregroundStyle(.white.opacity(0.6))
            .lineLimit(1)
    }
}

/// Big number with an optional baseline-aligned unit ("5,130 mi").
struct CardNumber: View {
    let value: String
    var unit: String? = nil
    let size: CGFloat
    var unitSize: CGFloat = CardType.label

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: size * 0.08) {
            Text(value)
                .font(CardType.number(size))
                .tracking(CardType.tracking(for: size))
                .foregroundStyle(.white)
            if let unit {
                Text(unit)
                    .font(CardType.text(unitSize))
                    .foregroundStyle(.white.opacity(0.6))
            }
        }
        .lineLimit(1)
        .fixedSize()
    }
}

/// Hero figure with its label underneath, left-aligned ("27" / "days away").
struct CardHero: View {
    let value: String
    let label: String
    let size: CGFloat
    let labelSize: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value)
                .font(CardType.number(size))
                .tracking(CardType.tracking(for: size))
                .foregroundStyle(.white)
                .lineLimit(1)
                .padding(.vertical, -size * 0.1)   // trim the font's built-in leading
            Text(label)
                .font(CardType.text(labelSize))
                .tracking(-0.3)
                .foregroundStyle(.white.opacity(0.6))
                .lineLimit(1)
        }
    }
}

// MARK: - Shared card pieces

struct CardBackground: View {
    let colors: [Color]
    let accent: Color
    var body: some View {
        ZStack {
            LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottom)
            RadialGradient(colors: [accent.opacity(0.35), .clear], center: .init(x: 0.85, y: 0.05), startRadius: 0, endRadius: 320)
            RadialGradient(colors: [Color.black.opacity(0.35), .clear], center: .bottom, startRadius: 0, endRadius: 360)
        }
    }
}

/// Small brand watermark on every card: the passport-stamp mark plus "Trippy".
struct CardWordmark: View {
    var body: some View {
        HStack(spacing: 5) {
            TrippyMark(height: 14)
            Text("Trippy")
                .font(.system(size: 13, weight: .bold))
                .tracking(-0.3)
        }
        .foregroundStyle(.white)
        .opacity(0.75)
    }
}

/// "2026 Passport" + multilingual kicker, with the wordmark on the right.
struct PassportHeader: View {
    let title: String
    let subtitle: String
    let size: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(title)
                    .font(CardType.title(size))
                    .tracking(-0.5)
                    .foregroundStyle(.white)
                    .lineLimit(1).minimumScaleFactor(0.7)
                Spacer(minLength: 8)
                CardWordmark()
            }
            CardLabel(text: subtitle)
        }
    }
}

/// "✈ SFO ‒ ‒ NRT" strip, in label type.
struct RouteStrip: View {
    let codes: [String]
    var body: some View {
        let shown = Array(codes.prefix(6))
        HStack(spacing: 8) {
            Image(systemName: "airplane")
            ForEach(Array(shown.enumerated()), id: \.offset) { i, c in
                Text(String(c.prefix(7)).uppercased()).tracking(1.2).fixedSize()
                if i < shown.count - 1 {
                    Path { p in p.move(to: CGPoint(x: 0, y: 0.5)); p.addLine(to: CGPoint(x: 16, y: 0.5)) }
                        .stroke(style: StrokeStyle(lineWidth: 1.2, lineCap: .round, dash: [2.5, 3]))
                        .frame(width: 16, height: 1)
                        .opacity(0.6)
                }
            }
            if codes.count > shown.count { Text("+\(codes.count - shown.count)").opacity(0.6) }
        }
        .font(CardType.labelFont())
        .foregroundStyle(.white.opacity(0.8))
        .lineLimit(1)
    }
}

/// Label over value. Every stat on a card uses the same value size so baselines line up.
struct CardStat: View {
    let label: String
    let value: String
    var unit: String? = nil
    var size: CGFloat = 30

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            CardLabel(text: label)
            CardNumber(value: value, unit: unit, size: size)
        }
    }
}

/// Rows of stats in fixed-fraction columns, top-aligned so label and value baselines match across a row.
struct CardStatGrid: View {
    let cells: [(String, String, String?)]
    let columns: [CGFloat]   // fractions of the width, summing to 1
    let size: CGFloat
    var rowSpacing: CGFloat = 16

    var body: some View {
        GeometryReader { geo in
            VStack(alignment: .leading, spacing: rowSpacing) {
                ForEach(0..<rowCount, id: \.self) { r in
                    HStack(alignment: .top, spacing: 0) {
                        ForEach(0..<columns.count, id: \.self) { c in
                            let i = r * columns.count + c
                            Group {
                                if i < cells.count {
                                    CardStat(label: cells[i].0, value: cells[i].1, unit: cells[i].2, size: size)
                                } else {
                                    Color.clear
                                }
                            }
                            .frame(width: geo.size.width * columns[c], alignment: .leading)
                        }
                    }
                }
            }
        }
        .frame(height: CGFloat(rowCount) * (CardType.label * 1.2 + 4 + size * 1.2) + CGFloat(max(rowCount - 1, 0)) * rowSpacing)
    }

    private var rowCount: Int { max(1, Int((Double(cells.count) / Double(columns.count)).rounded(.up))) }
}

/// Machine-readable-zone texture: SF Mono light, faint, so it reads as pattern rather than text.
struct MRZFooter: View {
    let lines: [String]
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(lines, id: \.self) { line in
                Text(MRZFooter.pad(line))
                    .font(CardType.mono(CardType.label))
                    .tracking(0.4)
                    .foregroundStyle(.white.opacity(0.2))
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
            }
        }
    }

    static let width = 34
    static func clean(_ s: String) -> String {
        let folded = s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .init(identifier: "en_US")).uppercased()
        return String(folded.map { $0.isLetter || $0.isNumber ? $0 : "<" })
            .replacingOccurrences(of: #"<{2,}"#, with: "<", options: .regularExpression)
    }
    static func pad(_ s: String) -> String {
        let t = String(s.prefix(width))
        return t + String(repeating: "<", count: max(0, width - t.count))
    }
}

private func grouped(_ n: Int) -> String { Fmt.number(Double(n)) }

private func compactMiles(_ n: Int) -> (String, String) {
    if n >= 100_000 { return (String(format: "%.0fk", Double(n) / 1000), "mi") }
    if n >= 10_000 { return (String(format: "%.1fk", Double(n) / 1000), "mi") }
    return (grouped(n), "mi")
}

private struct CardMapPanel: View {
    let map: UIImage?
    var body: some View {
        ZStack {
            Color.black.opacity(0.25)
            if let map { Image(uiImage: map).resizable().scaledToFill() }
        }
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(.white.opacity(0.14), lineWidth: 1))
    }
}

// MARK: - Trip recap
// Story: 40 title / 30 values / 12 labels. Square: 28 / 28 / 12.

struct TripRecapCard: View {
    let story: ApiStory
    let map: UIImage?
    let format: CardFormat
    var hideMoney = false

    private var theme: StoryTheme { story.themeGradient }

    private var stats: [(String, String, String?)] {
        let s = story.stats
        var out: [(String, String, String?)] = [("DAYS", "\(s.days ?? 0)", nil)]
        if s.distance_miles > 0 { out.append(("DISTANCE", compactMiles(s.distance_miles).0, "mi")) }
        out.append(("PLACES", "\(s.places)", nil))
        if s.flights > 0 { out.append(("FLIGHTS", "\(s.flights)", nil)) }
        if s.rentals > 0 { out.append(("DRIVES", "\(s.rentals)", nil)) }
        if s.nights > 0 { out.append(("NIGHTS", "\(s.nights)", nil)) }
        if s.countries > 1 { out.append(("COUNTRIES", "\(s.countries)", nil)) }
        if s.travelers > 1 { out.append(("TRAVELERS", "\(s.travelers)", nil)) }
        if !hideMoney, let spend = s.spend_text { out.append(("SPENT", spend, nil)) }
        return out
    }

    private var mrz: [String] {
        let codes = story.routeCodes.map(MRZFooter.clean).joined(separator: "<")
        let date = story.start.map { d -> String in
            let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "ddMMMyy"
            return f.string(from: d).uppercased()
        } ?? ""
        return ["TRP<" + MRZFooter.clean(story.title) + "<<" + codes,
                date + "<<\(story.stats.days ?? 0)D<<" + grouped(story.stats.distance_miles).filter(\.isNumber) + "MI<<TRIPPY"]
    }

    var body: some View {
        ZStack {
            CardBackground(colors: theme.colors, accent: theme.accent)
            if format == .story { storyLayout } else { squareLayout }
        }
        .frame(width: format.size.width, height: format.size.height)
        .clipped()
    }

    private var storyLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                CardLabel(text: "Trip recap")
                Spacer()
                CardWordmark()
            }
            Text(story.title)
                .font(CardType.title(40))
                .tracking(-0.5)
                .lineSpacing(-2)
                .foregroundStyle(.white)
                .lineLimit(2).minimumScaleFactor(0.7)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 16)
            CardDateLine(text: story.dateText)
                .padding(.top, 8)
            RouteStrip(codes: story.routeCodes)
                .padding(.top, 16)
            CardMapPanel(map: map)
                .frame(height: 216)
                .padding(.top, 24)
            CardStatGrid(cells: Array(stats.prefix(6)), columns: [0.28, 0.44, 0.28], size: 30)
                .padding(.top, 24)
            Spacer(minLength: 16)
            MRZFooter(lines: mrz)
        }
        .padding(.horizontal, 24)
        .padding(.top, 32)
        .padding(.bottom, 24)
    }

    private var squareLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(story.title)
                    .font(CardType.title(28))
                    .tracking(-0.5)
                    .foregroundStyle(.white)
                    .lineLimit(1).minimumScaleFactor(0.7)
                Spacer(minLength: 8)
                CardWordmark()
            }
            CardDateLine(text: story.dateText)
                .padding(.top, 8)
            CardMapPanel(map: map)
                .frame(height: 128)
                .padding(.top, 16)
            CardStatGrid(cells: Array(stats.prefix(3)), columns: [0.28, 0.44, 0.28], size: 28)
                .padding(.top, 16)
            Spacer(minLength: 8)
            RouteStrip(codes: story.routeCodes)
        }
        .padding(24)
    }
}

// MARK: - Year in travel
// Story: 88 hero / 30 title + values / 12 labels. Square: 28 / 12.

struct YearInTravelCard: View {
    let year: ApiYearInTravel
    let map: UIImage?
    let format: CardFormat
    var name: String = ""
    /// From /stats/?year= (the year story has no stays). When there are stays, the
    /// grid trades its least personal stats for Nights and Hotels.
    var stays: ApiStayStats? = nil

    private var kind: CardKind { .year }
    private var hasStays: Bool { (stays?.count ?? 0) > 0 }

    private var mrz: [String] {
        let who = MRZFooter.clean(name.isEmpty ? "TRAVELER" : name)
        return ["P<TRIPPY<<\(year.year)<<" + who,
                "\(year.trips)T<<\(year.days_away)D<<\(year.miles)MI<<" + (hasStays ? "\(stays!.nights)N<<" : "") + year.country_codes.joined(separator: "<")]
    }

    private var aroundEarth: String { String(format: year.around_earth >= 1 ? "%.1f" : "%.2f", year.around_earth) }

    var body: some View {
        ZStack {
            CardBackground(colors: kind.gradient, accent: Color(hex: 0xE05BFF))
            if format == .story { storyLayout } else { squareLayout }
        }
        .frame(width: format.size.width, height: format.size.height)
        .clipped()
    }

    private func header(_ size: CGFloat) -> some View {
        PassportHeader(title: "\(String(year.year)) Passport",
                       subtitle: "Passport · Pass · Pasaporte · 护照",
                       size: size)
    }

    private var storyLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            header(30)
            CardMapPanel(map: map)
                .frame(height: 136)
                .padding(.top, 24)
            CardHero(value: "\(year.days_away)", label: year.days_away == 1 ? "day away" : "days away", size: 88, labelSize: 30)
                .padding(.top, 24)
            CardStatGrid(cells: hasStays
                            ? [("Trips", "\(year.trips)", nil),
                               ("Miles", grouped(year.miles), nil),
                               ("Countries", "\(year.countries)", nil),
                               ("Cities", "\(year.cities)", nil),
                               ("Nights", "\(stays!.nights)", nil),
                               ("Hotels", "\(stays!.count)", nil)]
                            : [("Trips", "\(year.trips)", nil),
                                 ("Miles", grouped(year.miles), nil),
                                 ("Countries", "\(year.countries)", nil),
                                 ("Cities", "\(year.cities)", nil),
                                 ("Around earth", aroundEarth, "×"),
                                 ("Flights", "\(year.flights)", nil)],
                         columns: [0.3, 0.4, 0.3], size: 30)
                .padding(.top, 24)
            if !year.top_destinations.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    CardLabel(text: "Top places")
                    CardLabel(text: year.top_destinations.prefix(3).map { $0.city.components(separatedBy: ",")[0] }.joined(separator: "  ·  "),
                              opacity: 0.9)
                }
                .padding(.top, 24)
            }
            Spacer(minLength: 16)
            MRZFooter(lines: mrz)
        }
        .padding(.horizontal, 24)
        .padding(.top, 32)
        .padding(.bottom, 24)
    }

    private var squareLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            header(28)
            CardMapPanel(map: map)
                .frame(height: 96)
                .padding(.top, 16)
            CardStatGrid(cells: hasStays
                            ? [("Days away", "\(year.days_away)", nil),
                               ("Miles", grouped(year.miles), nil),
                               ("Trips", "\(year.trips)", nil),
                               ("Cities", "\(year.cities)", nil),
                               ("Nights", "\(stays!.nights)", nil),
                               ("Hotels", "\(stays!.count)", nil)]
                            : [("Days away", "\(year.days_away)", nil),
                                 ("Miles", grouped(year.miles), nil),
                                 ("Trips", "\(year.trips)", nil),
                                 ("Cities", "\(year.cities)", nil),
                                 ("Countries", "\(year.countries)", nil),
                                 ("Flights", "\(year.flights)", nil)],
                         columns: [0.36, 0.36, 0.28], size: 28)
                .padding(.top, 16)
            Spacer(minLength: 0)
        }
        .padding(24)
    }
}

// MARK: - Driver's Log
// Story: 88 hero / 30 title + values / 12 labels. Square: 28 / 12.

struct DriverLogCard: View {
    let data: DriverLogData
    let format: CardFormat
    var hideMoney = false

    private var kind: CardKind { .drivers }

    private var avgDays: String {
        String(format: "%.1f", data.rentals > 0 ? Double(data.days) / Double(data.rentals) : 0)
    }

    private var cells: [(String, String, String?)] {
        var out: [(String, String, String?)] = [
            ("Days driving", grouped(data.days), nil),
            ("Cars", "\(data.cars)", nil),
            hideMoney ? ("Avg days", avgDays, nil) : ("Spent", Fmt.compactMoney(data.spend), nil),
            ("Longest", "\(data.longestDays)", "d"),
            ("Companies", "\(data.companies)", nil),
        ]
        out.append(data.miles > 0 ? ("Miles", compactMiles(data.miles).0, nil) : ("Avg days", avgDays, nil))
        if hideMoney && data.miles <= 0 { out[5] = ("Rentals", "\(data.rentals)", nil) }
        return out
    }

    private var mrz: [String] {
        ["DL<TRIPPY<<\(data.yearLabel)<<" + MRZFooter.clean(data.topCompany ?? "RENTALS"),
         "\(data.rentals)R<<\(data.days)D<<\(data.miles)MI<<\(data.cars)CARS"]
    }

    var body: some View {
        ZStack {
            CardBackground(colors: kind.gradient, accent: Color(hex: 0x7CF7C8))
            roadLines
            if format == .story { storyLayout } else { squareLayout }
        }
        .frame(width: format.size.width, height: format.size.height)
        .clipped()
    }

    /// Faint dashed lane markings, the Driver's Log answer to Flighty's map.
    private var roadLines: some View {
        Canvas { ctx, size in
            for i in 0..<2 {
                var p = Path()
                let x = size.width * (0.62 + CGFloat(i) * 0.16)
                p.move(to: CGPoint(x: x, y: -20))
                p.addCurve(to: CGPoint(x: x - size.width * 0.5, y: size.height + 20),
                           control1: CGPoint(x: x + 40, y: size.height * 0.35),
                           control2: CGPoint(x: x - size.width * 0.55, y: size.height * 0.6))
                ctx.stroke(p, with: .color(.white.opacity(0.035)), style: StrokeStyle(lineWidth: 1.5, dash: [18, 14]))
            }
        }
        .allowsHitTesting(false)
    }

    private func header(_ size: CGFloat) -> some View {
        PassportHeader(title: "\(data.yearLabel) Driver's Log",
                       subtitle: "License · Licencia · Permis",
                       size: size)
    }

    private func companyBadge(_ size: CGFloat) -> some View {
        HStack(spacing: 16) {
            Group {
                if let company = data.topCompany, let asset = BrandLogos.rental(company) {
                    Image(asset).resizable().scaledToFit()
                } else {
                    Image(systemName: "car.fill")
                        .font(CardType.labelFont())
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.white.opacity(0.15))
                }
            }
            .frame(width: 48, height: 48)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.white.opacity(0.2)))
            VStack(alignment: .leading, spacing: 4) {
                CardLabel(text: "Top company")
                Text(data.topCompany ?? "—")
                    .font(CardType.title(size))
                    .tracking(-0.5)
                    .foregroundStyle(.white)
                    .lineLimit(1).minimumScaleFactor(0.7)
            }
            Spacer(minLength: 8)
            CardNumber(value: "\(data.topCompanyCount)", unit: "×", size: size)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.black.opacity(0.22)))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(.white.opacity(0.1)))
    }

    private var storyLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            header(30)
            CardHero(value: "\(data.rentals)", label: data.rentals == 1 ? "rental" : "rentals", size: 88, labelSize: 30)
                .padding(.top, 32)
            companyBadge(30)
                .padding(.top, 24)
            CardStatGrid(cells: cells, columns: [0.36, 0.3, 0.34], size: 30)
                .padding(.top, 24)
            if !data.topCars.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    CardLabel(text: "Most driven")
                    ForEach(Array(data.topCars.prefix(3).enumerated()), id: \.offset) { _, car in
                        HStack(spacing: 8) {
                            CardLabel(text: car.name, opacity: 0.9)
                            Spacer(minLength: 8)
                            CardLabel(text: "\(car.count)×", opacity: 0.55)
                        }
                    }
                }
                .padding(.top, 24)
            }
            Spacer(minLength: 16)
            MRZFooter(lines: mrz)
        }
        .padding(.horizontal, 24)
        .padding(.top, 32)
        .padding(.bottom, 24)
    }

    private var squareLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            header(28)
            companyBadge(28)
                .padding(.top, 16)
            CardStatGrid(cells: [("Rentals", "\(data.rentals)", nil)] + Array(cells.prefix(2)) + [cells[3], cells[4], cells[2]],
                         columns: [0.3, 0.4, 0.3], size: 28)
                .padding(.top, 16)
            Spacer(minLength: 0)
        }
        .padding(24)
    }
}

// MARK: - Rendering

@MainActor
enum CardRenderer {
    /// Renders a card at @3x (1080 px wide). Full-bleed, no rounded corners: ready for Stories.
    static func render<V: View>(_ view: V, format: CardFormat) -> UIImage? {
        let r = ImageRenderer(content: view
            .frame(width: format.size.width, height: format.size.height)
            .environment(\.colorScheme, .dark))
        r.scale = 3
        r.isOpaque = true
        return r.uiImage
    }

    /// Writes a PNG into tmp with a friendly name for the share sheet.
    static func pngFile(_ image: UIImage, name: String) -> URL? {
        guard let data = image.pngData() else { return nil }
        let safe = name.replacingOccurrences(of: #"[^A-Za-z0-9-]+"#, with: "-", options: .regularExpression)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("Trippy-\(safe).png")
        do { try data.write(to: url, options: .atomic) } catch { return nil }
        return url
    }
}
