import SwiftUI
import MapKit

/// Whole-route overview on a flat world map. MapKit can't zoom out far enough to show a
/// round-the-world route in a portrait window, so very wide journeys draw their own Mercator
/// world (a cached map snapshot, tiled sideways so routes may cross the antimeridian) and fit
/// every leg on screen.
struct FlatRouteMap: View {
    struct Line { let coords: [CLLocationCoordinate2D]; let color: Color }
    struct Pin { let coord: CLLocationCoordinate2D; let code: String }

    let lines: [Line]
    let pins: [Pin]
    var top: CGFloat = 60
    var bottom: CGFloat = 0
    var side: CGFloat = 20
    @State private var world: UIImage?

    private var all: [CLLocationCoordinate2D] { lines.flatMap(\.coords) + pins.map(\.coord) }

    var body: some View {
        Canvas { ctx, size in
            guard let r = MapFraming.rect(all, minMeters: 0, padding: 0.06) else { return }
            let W = MKMapRect.world.width
            let visW = max(80, size.width - side * 2), visH = max(80, size.height - top - bottom)
            let k = max(r.width / Double(visW), r.height / Double(visH))
            let cy = Double(top + visH / 2)
            func screen(_ x: Double, _ y: Double) -> CGPoint {
                CGPoint(x: (x - r.midX) / k + Double(size.width) / 2, y: (y - r.midY) / k + cy)
            }
            /// The copy of a point's x (± one world) closest to `near`.
            func unwrap(_ x: Double, near: Double) -> Double {
                [x - W, x, x + W, x + 2 * W].min { abs($0 - near) < abs($1 - near) }!
            }

            if let world {
                for n in -1...2 {
                    let o = screen(Double(n) * W, 0)
                    ctx.draw(Image(uiImage: world), in: CGRect(x: o.x, y: o.y, width: W / k, height: W / k))
                }
                ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black.opacity(0.35)))
            } else {
                // Graticule while the snapshot renders (or if it can't).
                var g = Path()
                for lng in stride(from: -180.0, through: 540, by: 30) {
                    let a = MKMapPoint(CLLocationCoordinate2D(latitude: 80, longitude: 0))
                    let b = MKMapPoint(CLLocationCoordinate2D(latitude: -80, longitude: 0))
                    let x = (lng + 180) / 360 * W - W
                    g.move(to: screen(x, a.y)); g.addLine(to: screen(x, b.y))
                }
                for lat in stride(from: -60.0, through: 60, by: 30) {
                    let y = MKMapPoint(CLLocationCoordinate2D(latitude: lat, longitude: 0)).y
                    g.move(to: screen(-W, y)); g.addLine(to: screen(3 * W, y))
                }
                ctx.stroke(g, with: .color(.white.opacity(0.08)), lineWidth: 0.5)
            }

            for line in lines where line.coords.count > 1 {
                var path = Path()
                var prev = r.midX
                var first = true
                for (a, b) in zip(line.coords, line.coords.dropFirst()) {
                    for (i, c) in Geodesic.points(a, b).enumerated() where !(i == 0 && !first) {
                        let p = MKMapPoint(c)
                        let x = unwrap(p.x, near: prev)
                        prev = x
                        if first { path.move(to: screen(x, p.y)); first = false } else { path.addLine(to: screen(x, p.y)) }
                    }
                }
                ctx.stroke(path, with: .color(line.color.opacity(0.25)), style: StrokeStyle(lineWidth: 9, lineCap: .round, lineJoin: .round))
                ctx.stroke(path, with: .color(line.color), style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
            }

            for pin in pins {
                let p = MKMapPoint(pin.coord)
                let s = screen(unwrap(p.x, near: r.midX), p.y)
                ctx.fill(Path(ellipseIn: CGRect(x: s.x - 5, y: s.y - 5, width: 10, height: 10)), with: .color(.white))
                ctx.fill(Path(ellipseIn: CGRect(x: s.x - 3.5, y: s.y - 3.5, width: 7, height: 7)), with: .color(Theme.blue))
                let label = ctx.resolve(Text(pin.code).font(.system(size: 11, weight: .bold, design: .rounded)).foregroundStyle(.white))
                let east = s.x > size.width * 0.75
                ctx.draw(label, at: CGPoint(x: east ? s.x - 8 : s.x + 8, y: s.y), anchor: east ? .trailing : .leading)
            }
        }
        .background(Theme.purpleNight)
        .task { world = await WorldSnapshot.image() }
        .accessibilityLabel("Route overview: " + pins.map(\.code).joined(separator: ", "))
    }
}

enum Geodesic {
    /// Points along the great circle from a to b (so long legs curve like they do on the MapKit map).
    static func points(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D, steps: Int = 48) -> [CLLocationCoordinate2D] {
        func v(_ c: CLLocationCoordinate2D) -> (Double, Double, Double) {
            let la = c.latitude * .pi / 180, lo = c.longitude * .pi / 180
            return (cos(la) * cos(lo), cos(la) * sin(lo), sin(la))
        }
        let p = v(a), q = v(b)
        let d = acos(max(-1, min(1, p.0 * q.0 + p.1 * q.1 + p.2 * q.2)))
        guard d > 1e-4 else { return [a, b] }
        return (0...steps).map { i in
            let t = Double(i) / Double(steps)
            let s1 = sin((1 - t) * d) / sin(d), s2 = sin(t * d) / sin(d)
            let x = s1 * p.0 + s2 * q.0, y = s1 * p.1 + s2 * q.1, z = s1 * p.2 + s2 * q.2
            return CLLocationCoordinate2D(latitude: atan2(z, sqrt(x * x + y * y)) * 180 / .pi, longitude: atan2(y, x) * 180 / .pi)
        }
    }
}

/// One dark, label-light snapshot of the whole world, rendered once per launch.
@MainActor
enum WorldSnapshot {
    private static var cached: UIImage?

    static func image() async -> UIImage? {
        if let cached { return cached }
        let o = MKMapSnapshotter.Options()
        o.mapRect = .world
        o.size = CGSize(width: 1400, height: 1400)
        o.scale = 2
        o.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        let config = MKStandardMapConfiguration(elevationStyle: .flat, emphasisStyle: .muted)
        config.pointOfInterestFilter = .excludingAll
        o.preferredConfiguration = config
        let shot = try? await MKMapSnapshotter(options: o).start()
        cached = shot?.image
        return cached
    }
}
