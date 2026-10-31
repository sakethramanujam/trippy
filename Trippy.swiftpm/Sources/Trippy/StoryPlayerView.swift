import SwiftUI
import UIKit

/// Full-screen, Instagram-style trip story: segmented progress bars, tap right/left to move,
/// hold to pause, swipe down to close. Slides: cover → each visible stop → highlights → numbers.
struct StoryPlayerView: View {
    @ObservedObject var network: NetworkManager
    let tripId: Int
    /// Plays a journey's combined story (all linked trips) instead; not editable.
    var journeyId: Int? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var story: ApiStory?
    @State private var errorText: String?
    @State private var index = max(UserDefaults.standard.integer(forKey: "TrippyStorySlide"), 0)
    @State private var progress: Double = 0
    @State private var held = false
    @State private var pressStart: Date?
    @State private var drag: CGSize = .zero
    @State private var showEditor = UserDefaults.standard.bool(forKey: "TrippyStoryEdit")
    @State private var showShare = false
    @State private var maps: [String: UIImage] = [:]
    private let frozen = UserDefaults.standard.bool(forKey: "TrippyStoryPaused")

    enum Slide: Hashable {
        case cover, item(ApiStoryItem), highlights, numbers
        var duration: Double {
            switch self {
            case .cover: return 6
            case .item(let i): return i.note?.isEmpty == false || !i.photos.isEmpty ? 6.5 : 5
            case .highlights: return 6
            case .numbers: return 7
            }
        }
    }

    private var slides: [Slide] {
        guard let story else { return [] }
        var out: [Slide] = [.cover]
        out += story.visibleItems.map { .item($0) }
        if !story.highlights.isEmpty { out.append(.highlights) }
        out.append(.numbers)
        return out
    }

    private var paused: Bool { held || frozen || showEditor || showShare || story == nil }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()
                if let story {
                    let s = slides
                    let i = min(index, max(s.count - 1, 0))
                    slideView(s[i], story: story, size: geo.size)
                        .id(i)
                        .transition(.opacity)
                        .clipShape(RoundedRectangle(cornerRadius: drag.height > 0 ? 28 : 0, style: .continuous))
                    chrome(story, count: s.count, current: i)
                } else if let errorText {
                    EmptyStateCard(systemImage: "exclamationmark.triangle", title: "Couldn't load the story", message: errorText)
                        .padding()
                } else {
                    ProgressView().tint(.white)
                }
            }
            .scaleEffect(1 - min(max(drag.height, 0) / 1600, 0.12))
            .offset(y: max(drag.height, 0) * 0.6)
            .contentShape(Rectangle())
            .gesture(pressGesture(width: geo.size.width))
        }
        .ignoresSafeArea()
        .statusBarHidden()
        .preferredColorScheme(.dark)
        .task { await load() }
        .task(id: index) { await tick() }
        .sheet(isPresented: $showEditor) {
            if let story {
                StoryEditorView(network: network, story: story) { updated in
                    self.story = updated
                    index = min(index, max(slides.count - 1, 0))
                }
            }
        }
        .sheet(isPresented: $showShare) {
            ShareCardSheet(network: network, kinds: [.trip, .year], tripId: tripId, journeyId: journeyId,
                           year: story?.year ?? Calendar.current.component(.year, from: Date()))
        }
    }

    // MARK: Timing + gestures

    private func tick() async {
        progress = 0
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 33_000_000)
            guard !paused, let slide = slides[safe: index] else { continue }
            progress += 0.033 / slide.duration
            if progress >= 1 {
                if index < slides.count - 1 { withAnimation(.easeInOut(duration: 0.25)) { index += 1 } } else { progress = 1 }
                return
            }
        }
    }

    private func pressGesture(width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { v in
                if pressStart == nil { pressStart = Date() }
                if Date().timeIntervalSince(pressStart ?? Date()) > 0.18 || abs(v.translation.height) > 10 { held = true }
                drag = v.translation
            }
            .onEnded { v in
                let quick = Date().timeIntervalSince(pressStart ?? Date()) < 0.25
                pressStart = nil
                held = false
                let t = v.translation
                withAnimation(.spring(duration: 0.3)) { drag = .zero }
                if t.height > 120 { dismiss(); return }
                if abs(t.width) > 60 && abs(t.width) > abs(t.height) { go(t.width < 0 ? 1 : -1); return }
                if quick && abs(t.width) < 10 && abs(t.height) < 10 {
                    go(v.location.x < width * 0.3 ? -1 : 1)
                }
            }
    }

    private func go(_ delta: Int) {
        let next = index + delta
        if next < 0 { progress = 0; return }
        if next >= slides.count { dismiss(); return }
        withAnimation(.easeInOut(duration: 0.2)) { index = next }
    }

    private func load() async {
        let result: Result<ApiStory, StoryError>
        if let journeyId { result = await network.fetchJourneyStory(journeyId) } else { result = await network.fetchStory(tripId: tripId) }
        switch result {
        case .success(let s):
            story = s
            index = min(index, max(slides.count - 1, 0))
        case .failure(let e): errorText = e.message
        }
    }

    // MARK: Chrome (progress + header)

    private func chrome(_ story: ApiStory, count: Int, current: Int) -> some View {
        VStack(spacing: 10) {
            HStack(spacing: 4) {
                ForEach(0..<count, id: \.self) { i in
                    GeometryReader { g in
                        Capsule().fill(.white.opacity(0.28))
                            .overlay(alignment: .leading) {
                                Capsule().fill(.white)
                                    .frame(width: g.size.width * (i < current ? 1 : i == current ? progress : 0))
                            }
                    }
                    .frame(height: 2.5)
                }
            }
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(story.themeGradient.gradient)
                    Image(systemName: "airplane").type(.footnoteStrong).foregroundStyle(.white)
                        .rotationEffect(.degrees(-45))
                }
                .frame(width: 32, height: 32)
                .overlay(Circle().strokeBorder(.white.opacity(0.5), lineWidth: 1))
                VStack(alignment: .leading, spacing: 0) {
                    Text(story.title).type(.calloutStrong).lineLimit(1)
                    Text(story.dateText.uppercased()).type(.label).tracking(1.2).opacity(0.6).lineLimit(1)
                }
                .foregroundStyle(.white)
                Spacer(minLength: 6)
                if held {
                    Image(systemName: "pause.fill").type(.footnoteStrong).foregroundStyle(.white.opacity(0.8))
                }
                if journeyId == nil { chromeButton("pencil", label: "Edit story") { showEditor = true } }
                chromeButton("square.and.arrow.up", label: "Share card") { showShare = true }
                chromeButton("xmark", label: "Close") { dismiss() }
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 58)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(alignment: .top) {
            LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .bottom)
                .frame(height: 170).allowsHitTesting(false)
        }
    }

    private func chromeButton(_ icon: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .type(.calloutStrong)
                .foregroundStyle(.white)
                .frame(width: 34, height: 34)
                .background(.black.opacity(0.3), in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    // MARK: Slides

    @ViewBuilder
    private func slideView(_ slide: Slide, story: ApiStory, size: CGSize) -> some View {
        switch slide {
        case .cover: StoryCoverSlide(story: story, size: size, map: $maps)
        case .item(let item): StoryItemSlide(story: story, item: item, size: size, map: $maps)
        case .highlights: StoryHighlightsSlide(story: story)
        case .numbers: StoryNumbersSlide(story: story, onShare: { showShare = true }, onEdit: { if journeyId == nil { showEditor = true } })
        }
    }
}

extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}

// MARK: - Slide views

private struct SlideKicker: View {
    let text: String
    var color: Color = .white
    var body: some View {
        Text(text.uppercased())
            .type(.label).tracking(1.2)
            .foregroundStyle(color)
            .lineLimit(1)
    }
}

private struct StoryCoverSlide: View {
    let story: ApiStory
    let size: CGSize
    @Binding var map: [String: UIImage]

    private var key: String { "cover-\(story.theme)-\(Int(size.width))" }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            story.themeGradient.gradient
            if let id = story.cover_photo, let img = StoryPhotoStore.image(id) {
                Image(uiImage: img).resizable().scaledToFill().frame(width: size.width, height: size.height).clipped()
            } else if let img = map[key] {
                VStack(spacing: 0) {
                    Image(uiImage: img).resizable().frame(width: size.width, height: size.height * 0.58)
                        .mask(LinearGradient(stops: [.init(color: .black, location: 0), .init(color: .black, location: 0.9),
                                                     .init(color: .black.opacity(0), location: 1)],
                                             startPoint: .top, endPoint: .bottom))
                    Spacer(minLength: 0)
                }
                .frame(width: size.width, height: size.height)
                .transition(.opacity)
            }
            LinearGradient(colors: [.clear, .black.opacity(0.25), .black.opacity(0.9)], startPoint: .center, endPoint: .bottom)
            VStack(alignment: .leading, spacing: 8) {
                SlideKicker(text: "TRIP STORY · \(story.stats.days ?? 0) DAYS", color: story.themeGradient.accent)
                Text(story.title)
                    .font(CardType.title(44)).tracking(-0.5)
                    .foregroundStyle(.white)
                    .lineLimit(3).minimumScaleFactor(0.6)
                if let sub = story.subtitle, !sub.isEmpty {
                    Text(sub).type(.body).foregroundStyle(.white.opacity(0.8)).lineLimit(3)
                }
                CardDateLine(text: story.dateText)
                HStack(alignment: .top, spacing: 24) {
                    StoryMiniStat(value: "\(story.stats.places)", label: "PLACES")
                    StoryMiniStat(value: Fmt.number(Double(story.stats.distance_miles)), label: "MILES")
                    if story.stats.flights > 0 { StoryMiniStat(value: "\(story.stats.flights)", label: "FLIGHTS") }
                    if story.stats.rentals > 0 { StoryMiniStat(value: "\(story.stats.rentals)", label: "DRIVES") }
                }
                .padding(.top, 16)
                if story.travelers.count > 1 {
                    HStack(spacing: -8) {
                        ForEach(story.travelers.prefix(6)) { p in
                            Text(p.initials)
                                .type(.footnoteStrong)
                                .foregroundStyle(.white)
                                .frame(width: 32, height: 32)
                                .background(Circle().fill(story.themeGradient.colors[1]))
                                .overlay(Circle().strokeBorder(.black, lineWidth: 2))
                        }
                        Text(story.travelers.map { $0.name.split(separator: " ").first.map(String.init) ?? $0.name }.joined(separator: ", "))
                            .type(.label).tracking(0.3).foregroundStyle(.white.opacity(0.8))
                            .padding(.leading, 16).lineLimit(1)
                    }
                    .padding(.top, 8)
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 64)
        }
        .frame(width: size.width, height: size.height)
        .task(id: key) {
            guard story.cover_photo == nil, map[key] == nil else { return }
            let t = story.themeGradient
            let img = await CardMapArt.route(story.route, size: CGSize(width: size.width, height: size.height * 0.58),
                                             tint: UIColor(t.colors[1]), accent: UIColor(t.accent))
            withAnimation(.easeOut(duration: 0.3)) { map[key] = img }
        }
    }
}

private struct StoryMiniStat: View {
    let value: String
    let label: String
    var body: some View {
        CardStat(label: label, value: value, size: 28)
    }
}

private struct StoryItemSlide: View {
    let story: ApiStory
    let item: ApiStoryItem
    let size: CGSize
    @Binding var map: [String: UIImage]

    private var photos: [UIImage] { item.photos.compactMap(StoryPhotoStore.image) }
    private var legStops: [ApiStoryPlace] { [item.from_place, item.place, item.to_place].compactMap { $0 }.filter { $0.coordinate != nil } }
    private var key: String { "leg-\(item.key)-\(story.theme)" }

    private var dayText: String {
        var parts: [String] = []
        if let d = item.day, d >= 1 { parts.append("DAY \(d)") }
        if let date = item.start { parts.append(Fmt.day(date).uppercased()) }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            story.themeGradient.gradient
            if let first = photos.first {
                Image(uiImage: first).resizable().scaledToFill().frame(width: size.width, height: size.height).clipped()
                LinearGradient(colors: [.black.opacity(0.35), .clear, .black.opacity(0.85)], startPoint: .top, endPoint: .bottom)
            } else {
                art
            }
            VStack(alignment: .leading, spacing: 8) {
                if photos.count > 1 {
                    HStack(spacing: 6) {
                        ForEach(Array(photos.dropFirst().prefix(4).enumerated()), id: \.offset) { _, p in
                            Image(uiImage: p).resizable().scaledToFill()
                                .frame(width: 64, height: 64)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.white.opacity(0.6), lineWidth: 1.5))
                        }
                    }
                    .padding(.bottom, 6)
                }
                HStack(spacing: 8) {
                    Label(item.kindLabel, systemImage: item.icon)
                        .type(.label).tracking(1.2)
                        .textCase(.uppercase)
                        .foregroundStyle(.black)
                        .padding(.horizontal, 9).padding(.vertical, 5)
                        .background(Capsule().fill(item.tint))
                    SlideKicker(text: dayText).opacity(0.6)
                }
                Text(item.title)
                    .font(CardType.title(36)).tracking(-0.5)
                    .foregroundStyle(.white)
                    .lineLimit(3).minimumScaleFactor(0.6)
                    .padding(.top, 8)
                if let sub = item.subtitle, !sub.isEmpty {
                    Text(sub).type(.body).foregroundStyle(.white.opacity(0.75)).lineLimit(3)
                }
                if let metric = item.metric, !metric.isEmpty {
                    Text(metric)
                        .font(CardType.number(56)).tracking(-1.5)
                        .foregroundStyle(item.tint)
                        .lineLimit(1).minimumScaleFactor(0.6)
                        .padding(.top, 8)
                }
                if let people = item.people, !people.isEmpty,
                   !(item.subtitle ?? "").contains(people.last?.name ?? "\u{0}") {
                    Text(people.map(\.name).joined(separator: " · "))
                        .type(.body).foregroundStyle(.white.opacity(0.8)).lineLimit(3)
                }
                if let note = item.note, !note.isEmpty {
                    Text("“\(note)”")
                        .type(.body)
                        .foregroundStyle(.white)
                        .lineSpacing(3)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.black.opacity(0.4)))
                        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(.white.opacity(0.12)))
                        .padding(.top, 8)
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 64)
        }
        .frame(width: size.width, height: size.height)
        .task(id: key) {
            guard photos.isEmpty, legStops.count > 0, map[key] == nil else { return }
            let t = story.themeGradient
            let img = await CardMapArt.route(legStops, size: CGSize(width: size.width - 48, height: size.height * 0.36),
                                             tint: UIColor(t.colors[1]), accent: UIColor(t.accent))
            withAnimation(.easeOut(duration: 0.3)) { map[key] = img }
        }
    }

    /// Without photos: a leg map for flights/drives/stays, a big glyph for the rest.
    @ViewBuilder
    private var art: some View {
        VStack {
            Spacer().frame(height: 130)
            if !legStops.isEmpty {
                ZStack {
                    RoundedRectangle(cornerRadius: 24, style: .continuous).fill(.black.opacity(0.25))
                    if let img = map[key] { Image(uiImage: img).resizable().scaledToFill().transition(.opacity) }
                }
                .frame(width: size.width - 48, height: size.height * 0.36)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).strokeBorder(.white.opacity(0.14)))
            } else {
                ZStack {
                    Circle().fill(item.tint.opacity(0.18)).frame(width: 220, height: 220)
                    Circle().fill(item.tint.opacity(0.28)).frame(width: 150, height: 150)
                    if item.kind == "lodging" {
                        GlyphImage(glyph: .bed, size: 84, color: .white)
                    } else {
                        Image(systemName: item.icon).font(TType.glyph(64, .bold)).foregroundStyle(.white)
                    }
                }
                .padding(.top, 30)
            }
            Spacer()
        }
        .frame(width: size.width)
    }
}

private struct StoryHighlightsSlide: View {
    let story: ApiStory
    var body: some View {
        ZStack(alignment: .topLeading) {
            story.themeGradient.gradient
            VStack(alignment: .leading, spacing: 16) {
                SlideKicker(text: "HIGHLIGHTS", color: story.themeGradient.accent)
                Text("The best bits")
                    .font(CardType.title(40)).tracking(-0.5)
                    .foregroundStyle(.white)
                ForEach(story.highlights, id: \.self) { h in
                    HStack(spacing: 16) {
                        Image(systemName: h.icon)
                            .type(.title3)
                            .foregroundStyle(.white)
                            .frame(width: 50, height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white.opacity(0.14)))
                        VStack(alignment: .leading, spacing: 4) {
                            CardLabel(text: h.label)
                            Text(h.value)
                                .font(CardType.number(28)).tracking(-1)
                                .foregroundStyle(.white)
                                .lineLimit(1).minimumScaleFactor(0.5)
                            if let d = h.detail {
                                Text(d).type(.footnoteStrong).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(.black.opacity(0.25)))
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 136)
        }
    }
}

private struct StoryNumbersSlide: View {
    let story: ApiStory
    let onShare: () -> Void
    let onEdit: () -> Void

    var body: some View {
        let s = story.stats
        ZStack(alignment: .topLeading) {
            story.themeGradient.gradient
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    SlideKicker(text: "BY THE NUMBERS", color: story.themeGradient.accent)
                    Text(story.title)
                        .font(CardType.title(40)).tracking(-0.5)
                        .foregroundStyle(.white)
                        .lineLimit(2).minimumScaleFactor(0.6)
                }
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 24) {
                    GridRow {
                        CardStat(label: "DAYS", value: "\(s.days ?? 0)", size: 44)
                        CardStat(label: "DISTANCE", value: Fmt.number(Double(s.distance_miles)), unit: "mi", size: 44)
                    }
                    GridRow {
                        CardStat(label: "PLACES", value: "\(s.places)", size: 44)
                        CardStat(label: "COUNTRIES", value: "\(s.countries)", size: 44)
                    }
                    GridRow {
                        CardStat(label: "FLIGHTS", value: "\(s.flights)", size: 44)
                        CardStat(label: s.nights > 0 ? "NIGHTS" : "DRIVES", value: "\(s.nights > 0 ? s.nights : s.rentals)", size: 44)
                    }
                }
                if !s.cities.isEmpty {
                    Text(s.cities.joined(separator: "  ·  ").uppercased())
                        .type(.label).tracking(1.2)
                        .foregroundStyle(.white.opacity(0.7))
                        .lineLimit(3)
                }
                Spacer()
                HStack(spacing: 10) {
                    Button(action: onEdit) {
                        Label("Edit", systemImage: "pencil")
                            .frame(maxWidth: .infinity).frame(height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white.opacity(0.16)))
                    }
                    Button(action: onShare) {
                        Label("Share card", systemImage: "square.and.arrow.up")
                            .frame(maxWidth: .infinity).frame(height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white))
                            .foregroundStyle(.black)
                    }
                }
                .type(.headline)
                .foregroundStyle(.white)
                .buttonStyle(.plain)
                HStack { Spacer(); CardWordmark(); Spacer() }
            }
            .padding(.horizontal, 24)
            .padding(.top, 136)
            .padding(.bottom, 44)
        }
    }
}
