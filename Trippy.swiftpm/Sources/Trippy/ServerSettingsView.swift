import SwiftUI

/// Lets you point the app at any self-hosted Trippy server (LAN address, Tailscale name,
/// or a public https URL). The setting is stored in UserDefaults.
struct ServerSettingsView: View {
    var onSaved: () -> Void = {}
    @Environment(\.dismiss) private var dismiss

    @State private var text = APIConfig.overrideURL ?? APIConfig.bundledBaseURL
    @State private var status: String?
    @State private var statusOK = false
    @State private var testing = false

    init(onSaved: @escaping () -> Void = {}) {
        self.onSaved = onSaved
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://trippy.example.com", text: $text)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .type(.mono)
                } header: {
                    Text("Trippy server")
                } footer: {
                    Text("The address of a Trippy server you or a friend runs, e.g. https://trippy.example.com, http://192.168.1.20:8000 or http://my-server:8000 over Tailscale.\nCurrently using \(APIConfig.baseURL)")
                }

                Section {
                    Button {
                        Task { await test() }
                    } label: {
                        HStack {
                            Text("Test connection")
                            Spacer()
                            if testing { ProgressView() }
                        }
                    }
                    .disabled(testing)
                    if let status {
                        Label(status, systemImage: statusOK ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(statusOK ? Theme.green : Theme.orange)
                            .type(.footnote)
                    }
                }

                Section {
                    Button("Reset to default", role: .destructive) {
                        text = APIConfig.bundledBaseURL
                        APIConfig.setOverride(nil)
                        status = nil
                        onSaved()
                    }
                }
            }
            .navigationTitle("Server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        guard let url = APIConfig.normalize(text) else {
                            status = "Enter a URL like https://trippy.example.com"
                            statusOK = false
                            return
                        }
                        APIConfig.setOverride(url)
                        onSaved()
                        dismiss()
                    }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private func test() async {
        testing = true
        defer { testing = false }
        switch await ServerHealth.check(text) {
        case .success(let health):
            statusOK = true
            status = "Connected · \(health.summary)"
        case .failure(let error):
            statusOK = false
            status = error.localizedDescription
        }
    }
}
