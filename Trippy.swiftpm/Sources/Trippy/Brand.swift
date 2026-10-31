import SwiftUI

/// The Trippy mark: a coral passport stamp with plane, bed and car glyphs (vector asset, Assets.xcassets/TrippyMark).
struct TrippyMark: View {
    var height: CGFloat = 28
    var body: some View {
        Image("TrippyMark")
            .resizable()
            .interpolation(.high)
            .scaledToFit()
            .frame(height: height)
            .accessibilityHidden(true)
    }
}

/// Mark + "Trippy" set in the display face, tight tracking.
struct TrippyWordmark: View {
    var height: CGFloat = 26
    var body: some View {
        HStack(spacing: height * 0.3) {
            TrippyMark(height: height)
            Text("Trippy")
                .font(.system(size: height * 0.86, weight: .bold))
                .tracking(-height * 0.03)
                .foregroundStyle(.white)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Trippy")
    }
}
