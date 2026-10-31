import SwiftUI
import PhotosUI

/// Edit a trip story: title, subtitle, theme, cover photo, and per stop order / visibility /
/// caption / photos. Saves to PUT /trips/{id}/story (edits are per signed-in user).
struct StoryEditorView: View {
    @ObservedObject var network: NetworkManager
    let onSaved: (ApiStory) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draft: ApiStory
    @State private var saving = false
    @State private var errorText: String?
    @State private var confirmReset = false
    @State private var coverPick: PhotosPickerItem?
    @State private var importingCover = false

    init(network: NetworkManager, story: ApiStory, onSaved: @escaping (ApiStory) -> Void) {
        self.network = network
        self.onSaved = onSaved
        _draft = State(initialValue: story)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Title", text: Binding(get: { draft.title }, set: { draft.title = String($0.prefix(80)) }))
                        .type(.title3)
                    TextField("Subtitle (optional)", text: Binding(get: { draft.subtitle ?? "" },
                                                                    set: { draft.subtitle = String($0.prefix(80)) }))
                } header: { Text("Story") }

                Section {
                    themePicker
                    coverRow
                } header: { Text("Look") }

                Section {
                    ForEach($draft.items) { $item in
                        StoryItemEditorRow(item: $item)
                    }
                    .onMove { from, to in draft.items.move(fromOffsets: from, toOffset: to) }
                } header: {
                    Text("Timeline")
                } footer: {
                    Text("Drag to reorder. Hidden stops stay out of the story and its cards. Photos stay on this iPhone; captions and order sync to your account.")
                }

                Section {
                    Button("Reset to automatic story", role: .destructive) { confirmReset = true }
                }
            }
            .environment(\.editMode, .constant(.active))
            .scrollContentBackground(.hidden)
            .background(Theme.canvas)
            .navigationTitle("Edit story")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("Save") { Task { await save() } }.fontWeight(.bold)
                    }
                }
            }
            .alert("Couldn't save", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
            .confirmationDialog("Reset this story?", isPresented: $confirmReset, titleVisibility: .visible) {
                Button("Reset", role: .destructive) { Task { await reset() } }
            } message: {
                Text("Your title, order, captions and photo picks for this trip are removed.")
            }
            .onChange(of: coverPick) { _, pick in
                guard let pick else { return }
                Task {
                    importingCover = true
                    defer { importingCover = false; coverPick = nil }
                    if let data = try? await pick.loadTransferable(type: Data.self), let id = StoryPhotoStore.save(data) {
                        draft.cover_photo = id
                    } else {
                        errorText = "That photo couldn't be imported. Try another one."
                    }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var themePicker: some View {
        HStack(spacing: 12) {
            ForEach(StoryTheme.allCases) { t in
                Button { draft.theme = t.rawValue } label: {
                    Circle().fill(t.gradient)
                        .frame(width: 38, height: 38)
                        .overlay(Circle().strokeBorder(.white, lineWidth: draft.theme == t.rawValue ? 3 : 0))
                        .overlay {
                            if draft.theme == t.rawValue {
                                Image(systemName: "checkmark").type(.calloutStrong).foregroundStyle(.white)
                            }
                        }
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("\(t.name) theme")
            }
        }
        .padding(.vertical, 4)
    }

    private var coverRow: some View {
        HStack(spacing: 12) {
            Group {
                if let id = draft.cover_photo, let img = StoryPhotoStore.image(id) {
                    Image(uiImage: img).resizable().scaledToFill()
                } else {
                    Image(systemName: "map.fill").type(.body).foregroundStyle(.white.opacity(0.8))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(draft.themeGradient.gradient)
                }
            }
            .frame(width: 44, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text("Cover").type(.headline)
                Text(draft.cover_photo == nil ? "Route map" : "Your photo")
                    .type(.footnote).foregroundStyle(Theme.textSecondary)
            }
            Spacer()
            if importingCover { ProgressView() }
            if draft.cover_photo != nil {
                Button("Use map") { draft.cover_photo = nil }.buttonStyle(.borderless)
            }
            PhotosPicker(selection: $coverPick, matching: .images, photoLibrary: .shared()) {
                Text("Choose").fontWeight(.semibold)
            }
            .buttonStyle(.borderless)
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        var items: [String: [String: Any]] = [:]
        for i in draft.items {
            let note = i.note?.trimmingCharacters(in: .whitespacesAndNewlines)
            items[i.key] = ["hidden": i.hidden, "note": note?.isEmpty == false ? String(note!.prefix(280)) : NSNull(),
                            "photos": Array(i.photos.prefix(10))]
        }
        let title = draft.title.trimmingCharacters(in: .whitespaces)
        let result = await network.saveStory(tripId: draft.trip_id,
                                             title: title.isEmpty ? draft.generated_title : title,
                                             subtitle: draft.subtitle?.trimmingCharacters(in: .whitespaces) ?? "",
                                             theme: draft.theme,
                                             coverPhoto: .some(draft.cover_photo),
                                             order: draft.items.map(\.key),
                                             items: items)
        switch result {
        case .success(let s): onSaved(s); dismiss()
        case .failure(let e): errorText = e.message
        }
    }

    private func reset() async {
        switch await network.resetStory(tripId: draft.trip_id) {
        case .success(let s): onSaved(s); dismiss()
        case .failure(let e): errorText = e.message
        }
    }
}

private struct StoryItemEditorRow: View {
    @Binding var item: ApiStoryItem
    @State private var picks: [PhotosPickerItem] = []
    @State private var importing = false
    @State private var failed = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                Image(systemName: item.icon)
                    .type(.calloutStrong)
                    .foregroundStyle(item.hidden ? Theme.textSecondary : .white)
                    .frame(width: 34, height: 34)
                    .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(item.hidden ? Theme.surfaceRaised : item.tint.opacity(0.85)))
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.title).type(.headline).lineLimit(1)
                        .foregroundStyle(item.hidden ? Theme.textSecondary : .white)
                    Text([item.day.map { "Day \($0)" }, item.subtitle].compactMap { $0 }.joined(separator: " · "))
                        .type(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                Button { item.hidden.toggle() } label: {
                    Image(systemName: item.hidden ? "eye.slash" : "eye")
                        .type(.headline)
                        .foregroundStyle(item.hidden ? Theme.textSecondary : Theme.blue)
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(item.hidden ? "Show in story" : "Hide from story")
            }
            if !item.hidden {
                TextField("Add a caption…", text: Binding(get: { item.note ?? "" }, set: { item.note = String($0.prefix(280)) }),
                          axis: .vertical)
                    .lineLimit(1...4)
                    .type(.callout)
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Theme.surfaceRaised))
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(item.photos, id: \.self) { id in
                            ZStack(alignment: .topTrailing) {
                                Group {
                                    if let img = StoryPhotoStore.image(id) {
                                        Image(uiImage: img).resizable().scaledToFill()
                                    } else {
                                        Image(systemName: "icloud.slash").foregroundStyle(Theme.textSecondary)
                                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                                            .background(Theme.surfaceRaised)
                                    }
                                }
                                .frame(width: 58, height: 58)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                Button { item.photos.removeAll { $0 == id } } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .symbolRenderingMode(.palette)
                                        .foregroundStyle(.white, .black.opacity(0.7))
                                        .type(.body)
                                }
                                .buttonStyle(.borderless)
                                .offset(x: 5, y: -5)
                                .accessibilityLabel("Remove photo")
                            }
                            .padding(.top, 5)
                        }
                        if item.photos.count < 10 {
                            PhotosPicker(selection: $picks, maxSelectionCount: 10 - item.photos.count,
                                         matching: .images, photoLibrary: .shared()) {
                                VStack(spacing: 3) {
                                    if importing { ProgressView() } else {
                                        Image(systemName: "photo.badge.plus").type(.headline)
                                    }
                                    Text("Photos").type(.label)
                                }
                                .foregroundStyle(Theme.blue)
                                .frame(width: 58, height: 58)
                                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Theme.blue.opacity(0.5), style: StrokeStyle(lineWidth: 1.5, dash: [4, 3])))
                            }
                            .buttonStyle(.borderless)
                            .padding(.top, 5)
                            .disabled(importing)
                        }
                    }
                }
                if failed > 0 {
                    Text("\(failed) photo\(failed == 1 ? "" : "s") couldn't be imported.")
                        .type(.caption).foregroundStyle(Theme.orange)
                }
            }
        }
        .padding(.vertical, 6)
        .onChange(of: picks) { _, new in
            guard !new.isEmpty else { return }
            Task {
                importing = true
                failed = 0
                for p in new {
                    if let data = try? await p.loadTransferable(type: Data.self), let id = StoryPhotoStore.save(data) {
                        if item.photos.count < 10 { item.photos.append(id) }
                    } else {
                        failed += 1
                    }
                }
                picks = []
                importing = false
            }
        }
    }
}
