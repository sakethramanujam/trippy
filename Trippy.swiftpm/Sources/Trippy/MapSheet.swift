import SwiftUI
import MapKit

// MARK: - Draggable sheet over a full-screen map

private struct SheetScrollKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

/// A Flighty-style bottom sheet that snaps between detents (fractions of the available height).
/// Drag the grabber/header to resize, tap the grabber to toggle, or scroll the content while
/// collapsed to expand it. Reports its visible height so a map behind it can keep its content
/// framed above the sheet, and its scroll offset so headers can collapse.
struct DetentSheet<Header: View, Content: View>: View {
    var detents: [CGFloat]
    @Binding var selection: Int
    @Binding var scrollOffset: CGFloat
    @Binding var visibleHeight: CGFloat
    let header: () -> Header
    let content: () -> Content
    /// Pull to refresh on the sheet's list.
    var onRefresh: (() async -> Void)? = nil

    @GestureState(resetTransaction: Transaction(animation: DetentSheetMotion.spring))
    private var drag: CGFloat = 0

    init(detents: [CGFloat] = [0.5, 0.92],
         selection: Binding<Int>,
         scrollOffset: Binding<CGFloat> = .constant(0),
         visibleHeight: Binding<CGFloat> = .constant(0),
         onRefresh: (() async -> Void)? = nil,
         @ViewBuilder header: @escaping () -> Header,
         @ViewBuilder content: @escaping () -> Content) {
        self.onRefresh = onRefresh
        self.detents = detents
        self._selection = selection
        self._scrollOffset = scrollOffset
        self._visibleHeight = visibleHeight
        self.header = header
        self.content = content
    }

    static var windowTopInset: CGFloat {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap(\.windows).first { $0.isKeyWindow } ?? scenes.first?.windows.first
        return window?.safeAreaInsets.top ?? 54
    }

    private var index: Int { min(max(selection, 0), detents.count - 1) }

    var body: some View {
        GeometryReader { geo in
            // Detents are fractions of the space between the status bar and the bottom edge,
            // measured in window coordinates so the expanded sheet never slides under the clock.
            let frame = geo.frame(in: .global)
            let total = max(200, frame.maxY - max(frame.minY, Self.windowTopInset + 6))
            let target = total * detents[index]
            let height = rubberBand(target - drag,
                                    lower: total * (detents.first ?? 0.4),
                                    upper: total * (detents.last ?? 0.9))
            let shape = UnevenRoundedRectangle(topLeadingRadius: Theme.sheetRadius,
                                               topTrailingRadius: Theme.sheetRadius,
                                               style: .continuous)
            VStack(spacing: 0) {
                VStack(spacing: 0) {
                    Capsule().fill(Theme.surfaceHigh)
                        .frame(width: 38, height: 5)
                        .padding(.top, 8).padding(.bottom, 4)
                        .frame(maxWidth: .infinity)
                        .contentShape(Rectangle())
                        .onTapGesture { toggle(total) }
                        .accessibilityLabel(index == detents.count - 1 ? "Collapse sheet" : "Expand sheet")
                    header()
                }
                .contentShape(Rectangle())
                .gesture(dragGesture(total))

                ScrollView(showsIndicators: false) {
                    content()
                        .background(GeometryReader { g in
                            Color.clear.preference(key: SheetScrollKey.self,
                                                   value: -g.frame(in: .named("DetentSheetScroll")).minY)
                        })
                }
                .modifier(OptionalRefresh(action: onRefresh))
                .coordinateSpace(name: "DetentSheetScroll")
                .onPreferenceChange(SheetScrollKey.self) { value in
                    scrollOffset = max(0, value)
                    // Scrolling the content of a collapsed sheet pulls it up, like a system sheet.
                    if value > 28, index < detents.count - 1, drag == 0 {
                        withAnimation(DetentSheetMotion.spring) { selection = detents.count - 1 }
                    }
                }
            }
            .frame(width: geo.size.width, height: height, alignment: .top)
            .background(shape.fill(Theme.sheet).shadow(color: .black.opacity(0.5), radius: 20, y: -4))
            .clipShape(shape)
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
            .onAppear { visibleHeight = target }
            .onChange(of: index) { _, new in visibleHeight = total * detents[new] }
            .onChange(of: total) { _, new in visibleHeight = new * detents[index] }
        }
        .ignoresSafeArea(edges: .bottom)
    }

    private func dragGesture(_ total: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 4, coordinateSpace: .global)
            .updating($drag) { value, state, _ in state = value.translation.height }
            .onEnded { value in
                let projected = total * detents[index] - value.predictedEndTranslation.height
                let nearest = detents.indices.min { abs(total * detents[$0] - projected) < abs(total * detents[$1] - projected) } ?? index
                withAnimation(DetentSheetMotion.spring) { selection = nearest }
            }
    }

    private func toggle(_ total: CGFloat) {
        withAnimation(DetentSheetMotion.spring) {
            selection = index == detents.count - 1 ? 0 : detents.count - 1
        }
    }

    private func rubberBand(_ x: CGFloat, lower: CGFloat, upper: CGFloat) -> CGFloat {
        if x > upper { return upper + (x - upper) * 0.18 }
        if x < lower { return lower - (lower - x) * 0.35 }
        return x
    }
}

enum DetentSheetMotion {
    static let spring = Animation.spring(response: 0.38, dampingFraction: 0.86)
}

/// Reads detent overrides for screenshots / UI tests: `-TrippyDetent 1` opens sheets expanded.
enum LaunchOptions {
    static var detent: Int { UserDefaults.standard.integer(forKey: "TrippyDetent") }
}

// MARK: - Map framing

enum MapFraming {
    /// Smallest map rect containing every coordinate (wrapping across the antimeridian when that
    /// is shorter, e.g. SFO → NRT), padded and with a minimum size so a single city isn't a street map.
    static func rect(_ coords: [CLLocationCoordinate2D], minMeters: Double = 40_000, padding: Double = 0.22) -> MKMapRect? {
        guard let first = coords.first else { return nil }
        let world = MKMapRect.world.width
        let points = coords.map(MKMapPoint.init)
        let sortedX = points.map(\.x).sorted()
        var bestGap = world - (sortedX.last! - sortedX.first!)
        var cut = sortedX.first!
        if sortedX.count > 1 {
            for i in 1..<sortedX.count where sortedX[i] - sortedX[i - 1] > bestGap {
                bestGap = sortedX[i] - sortedX[i - 1]
                cut = sortedX[i]
            }
        }
        let xs = points.map { $0.x < cut ? $0.x + world : $0.x }
        let ys = points.map(\.y)
        var r = MKMapRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
        let minPoints = minMeters * MKMapPointsPerMeterAtLatitude(first.latitude)
        if r.width < minPoints { r = r.insetBy(dx: -(minPoints - r.width) / 2, dy: 0) }
        if r.height < minPoints { r = r.insetBy(dx: 0, dy: -(minPoints - r.height) / 2) }
        return r.insetBy(dx: -r.width * padding, dy: -r.height * padding)
    }

    /// True when `c` sits in the eastern half of the route's (antimeridian-aware) bounding rect.
    static func isEastHalf(_ c: CLLocationCoordinate2D, of coords: [CLLocationCoordinate2D]) -> Bool {
        guard coords.count > 1, let r = rect(coords, minMeters: 0, padding: 0) else { return false }
        var x = MKMapPoint(c).x
        if x < r.minX - 1 { x += MKMapRect.world.width }
        return x > r.midX
    }

    /// Routes wider than ~80° of longitude hit MapKit's zoom-out floor in a portrait window,
    /// so their labels drop the city name to stay on screen.
    static func isWide(_ coords: [CLLocationCoordinate2D]) -> Bool {
        (rect(coords, minMeters: 0, padding: 0)?.width ?? 0) > MKMapRect.world.width * 0.22
    }

    static var windowSize: CGSize {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap(\.windows).first { $0.isKeyWindow } ?? scenes.first?.windows.first
        return window?.bounds.size ?? CGSize(width: 402, height: 874)
    }

    /// Full-view map rect (exact view aspect) in which the route sits centred inside the unobscured
    /// window between `top` and `bottom`.
    static func target(_ coords: [CLLocationCoordinate2D], minMeters: Double = 40_000, padding: Double = 0.22,
                       top: CGFloat = 70, bottom: CGFloat = 0, side: CGFloat = 24) -> MKMapRect? {
        guard let r = rect(coords, minMeters: minMeters, padding: padding) else { return nil }
        let size = windowSize
        let visW = max(80, size.width - side * 2), visH = max(80, size.height - top - bottom)
        let k = max(r.width / Double(visW), r.height / Double(visH))      // map points per screen point
        let centreY = Double(top + (size.height - top - bottom) / 2)
        return MKMapRect(x: r.midX - Double(size.width) * k / 2, y: r.midY - centreY * k,
                         width: Double(size.width) * k, height: Double(size.height) * k)
    }

    /// Camera for a full-view rect; wrapped (antimeridian) or polar rects become a region.
    static func position(for full: MKMapRect) -> MapCameraPosition {
        let world = MKMapRect.world
        var full = full
        if full.minX < 0 && full.maxX < world.width / 2 { full.origin.x += world.width }
        if full.minX >= 0 && full.maxX <= world.width && full.minY >= 0 && full.maxY <= world.height {
            return .rect(full)
        }
        var mid = MKMapPoint(x: full.midX, y: min(max(full.midY, 1), world.height - 1))
        if mid.x > world.width { mid.x -= world.width }
        if mid.x < 0 { mid.x += world.width }
        let topLat = MKMapPoint(x: mid.x, y: max(full.minY, 1)).coordinate.latitude
        let bottomLat = MKMapPoint(x: mid.x, y: min(full.maxY, world.height - 1)).coordinate.latitude
        let span = MKCoordinateSpan(latitudeDelta: min(abs(topLat - bottomLat), 170),
                                    longitudeDelta: min(full.width / world.width * 360, 359))
        return .region(MKCoordinateRegion(center: mid.coordinate, span: span))
    }

    static func camera(_ coords: [CLLocationCoordinate2D], minMeters: Double = 40_000, padding: Double = 0.22,
                       top: CGFloat = 70, bottom: CGFloat = 0, side: CGFloat = 24) -> MapCameraPosition {
        target(coords, minMeters: minMeters, padding: padding, top: top, bottom: bottom, side: side)
            .map(position(for:)) ?? .automatic
    }
}

/// Frames `coords` above a bottom sheet and keeps it framed when the sheet moves. MapKit doesn't
/// honour very wide rects exactly (it shows roughly two-thirds of a hemisphere-wide request), so
/// after each programmatic move it reads back the visible region and corrects scale and centre.
struct MapAutoFit: ViewModifier {
    @Binding var camera: MapCameraPosition
    let coords: [CLLocationCoordinate2D]
    var minMeters: Double = 40_000
    var padding: Double = 0.22
    var top: CGFloat = 70
    var bottom: CGFloat = 0
    var side: CGFloat = 24

    @State private var goal: MKMapRect?
    @State private var request: MKMapRect?
    @State private var tries = 0
    @State private var lastScale: Double = 0

    private var key: String { coords.map { String(format: "%.3f,%.3f", $0.latitude, $0.longitude) }.joined(separator: ";") }

    func body(content: Content) -> some View {
        content
            .onAppear { apply(animated: false) }
            .onChange(of: key) { _, _ in apply(animated: true) }
            .onChange(of: bottom) { _, _ in apply(animated: true) }
            .onMapCameraChange(frequency: .onEnd) { ctx in correct(ctx.region, distance: ctx.camera.distance) }
    }

    private func apply(animated: Bool) {
        guard let t = MapFraming.target(coords, minMeters: minMeters, padding: padding,
                                        top: top, bottom: bottom, side: side) else { return }
        goal = t; request = t; tries = 0; lastScale = 0
        set(MapFraming.position(for: t), animated: animated)
    }

    private func correct(_ region: MKCoordinateRegion, distance: Double) {
        guard let goal, let req = request, tries < 3 else { return }
        let world = MKMapRect.world.width
        let gotWidth = region.span.longitudeDelta / 360 * world
        guard gotWidth > 0 else { return }
        var dx = MKMapPoint(region.center).x - goal.midX
        if dx > world / 2 { dx -= world } else if dx < -world / 2 { dx += world }
        let raw = goal.width / gotWidth
        // Keep the route centred in the window above the sheet at whatever zoom MapKit actually gave us.
        let viewW = Double(MapFraming.windowSize.width)
        let off = Double(bottom - top) / 2
        let wantY = goal.midY + off * (gotWidth / viewW - goal.width / viewW)
        let dy = MKMapPoint(region.center).y - wantY
        var scale = raw
        // MapKit has a zoom-out floor; once a bigger request no longer widens the view, only re-centre.
        if tries > 0 && abs(raw - lastScale) < 0.03 { scale = 1 }
        lastScale = raw
        guard abs(scale - 1) > 0.04 || abs(dx) > goal.width * 0.03 || abs(dy) > goal.height * 0.03 else {
            self.request = nil; return
        }
        tries += 1
        if scale != 1 {
            let w = req.width * scale, h = req.height * scale
            let next = MKMapRect(x: req.midX - dx - w / 2, y: req.midY - dy - h / 2, width: w, height: h)
            request = next
            set(MapFraming.position(for: next), animated: false)
        } else {
            // At MapKit's zoom floor: keep its zoom and just move the centre so the route sits mid-window.
            let here = MKMapPoint(region.center)
            var x = here.x - dx
            if x < 0 { x += world } else if x > world { x -= world }
            let y = min(max(here.y - dy, 1), MKMapRect.world.height - 1)
            set(.camera(MapCamera(centerCoordinate: MKMapPoint(x: x, y: y).coordinate, distance: distance)), animated: false)
        }
    }

    private func set(_ p: MapCameraPosition, animated: Bool) {
        if animated { withAnimation(.easeInOut(duration: 0.35)) { camera = p } } else { camera = p }
    }
}

extension View {
    func autoFit(_ camera: Binding<MapCameraPosition>, coords: [CLLocationCoordinate2D], minMeters: Double = 40_000,
                 padding: Double = 0.22, top: CGFloat = 70, bottom: CGFloat = 0, side: CGFloat = 24) -> some View {
        modifier(MapAutoFit(camera: camera, coords: coords, minMeters: minMeters, padding: padding,
                            top: top, bottom: bottom, side: side))
    }
}

// MARK: - Map look (Flighty: dark, desaturated, glowing route)

enum MapLook {
    /// Base map: dark satellite terrain with labels and no POIs (closest to Flighty, picked by
    /// screenshot A/B). `-TrippyMapLook standard|imagery` keeps the alternatives for comparison.
    static var style: MapStyle {
        switch UserDefaults.standard.string(forKey: "TrippyMapLook") {
        case "imagery": return .imagery(elevation: .flat)
        case "standard": return .standard(elevation: .flat, emphasis: .muted, pointsOfInterest: .excludingAll, showsTraffic: false)
        default: return .hybrid(elevation: .flat, pointsOfInterest: .excludingAll, showsTraffic: false)
        }
    }
    /// How much the dimmer layer darkens the base map (labels stay readable above it).
    static var dim: Double {
        let v = UserDefaults.standard.double(forKey: "TrippyMapDim")
        return v > 0 ? v : 0.52
    }
}

/// A translucent black layer over the whole map: pushes MapKit's navy ocean and gray land
/// toward Flighty's near-black, desaturated look while place labels draw on top.
struct MapDimmer: MapContent {
    /// 45°-wide slices: a single 180°-wide polygon is ambiguous to MapKit (it can wrap the
    /// short way and vanish at some camera positions), so tile the globe in narrower pieces.
    private static let slices: [(Double, Double)] = stride(from: -180.0, to: 180.0, by: 45.0).map { ($0, $0 + 45) }

    var body: some MapContent {
        ForEach(Array(Self.slices.enumerated()), id: \.offset) { _, slice in
            MapPolygon(coordinates: [.init(latitude: 85, longitude: slice.0), .init(latitude: 85, longitude: slice.1),
                                     .init(latitude: -85, longitude: slice.1), .init(latitude: -85, longitude: slice.0)])
                .foregroundStyle(Color.black.opacity(MapLook.dim))
                .mapOverlayLevel(level: .aboveRoads)
        }
    }
}

/// Route with a soft glow: a wide translucent stroke under a thin bright one.
struct GlowRoute: MapContent {
    let coords: [CLLocationCoordinate2D]
    var color: Color = Theme.route
    var geodesic = true
    var width: CGFloat = 3.5

    var body: some MapContent {
        MapPolyline(coordinates: coords, contourStyle: geodesic ? .geodesic : .straight)
            .stroke(color.opacity(0.22), style: StrokeStyle(lineWidth: width * 3.4, lineCap: .round, lineJoin: .round))
            .mapOverlayLevel(level: .aboveLabels)
        MapPolyline(coordinates: coords, contourStyle: geodesic ? .geodesic : .straight)
            .stroke(color, style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
            .mapOverlayLevel(level: .aboveLabels)
    }
}

/// Blue dot + "City CODE" pill used for route endpoints on every map.
struct MapCallout: View {
    let city: String?
    let code: String
    var color: Color = Theme.blue
    /// Put the dot on the right so the label reads inward from the east end of a route.
    var trailing = false

    var body: some View {
        HStack(spacing: 6) {
            if !trailing { dot }
            label
            if trailing { dot }
        }
    }

    private var dot: some View {
        Circle().fill(color).frame(width: 10, height: 10)
            .overlay(Circle().strokeBorder(.white, lineWidth: 1.5))
            .shadow(color: color.opacity(0.8), radius: 4)
    }

    private var label: some View {
            HStack(spacing: 0) {
                if let city, !city.isEmpty, city.uppercased() != code.uppercased() {
                    Text(city).padding(.horizontal, 5)
                }
                Text(code).padding(.horizontal, 5)
                    .background(Color.black.opacity(0.18))
            }
            .type(.footnoteStrong)
            .foregroundStyle(.white)
            .lineLimit(1)
            .padding(.vertical, 2)
            .background(color.opacity(0.92), in: RoundedRectangle(cornerRadius: 4))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}


/// `.refreshable` only when there is something to refresh (no empty spinner otherwise).
private struct OptionalRefresh: ViewModifier {
    let action: (() async -> Void)?
    @ViewBuilder func body(content: Content) -> some View {
        if let action { content.refreshable { await action() } } else { content }
    }
}
