import SwiftUI

@main
struct TrippyApp: App {
    init() { BackgroundRefresh.register() }

    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
