import SwiftUI
import UIKit

/// Design system — placeholder tokens; the design stage replaces them with the brief's tokens
/// (the approved Claude Design boards). The brief styles the CONTENT; the chrome (tab bar,
/// navigation bars, toolbars, sheets, controls) is always the system's, Liquid Glass on iOS 26.
/// Placeholder look: teal primary + blue accent + cool navy text.
enum DS {
    enum Palette {
        // Primary/secondary (light tokens + derived dark)
        static let primary = Color(light: 0x006A63, dark: 0x5EE9DC)        // teal — primary CTA
        static let secondary = Color(light: 0x00649A, dark: 0x8FD0FF)      // blue
        static let accent = Color(light: 0x00649A, dark: 0x8FD0FF)         // links/Share
        static let onAccent = Color.white
        static let primaryContainer = Color(light: 0x9CF2E8, dark: 0x004842)
        static let background = Color(light: 0xFAF8FF, dark: 0x0A0E1A)     // screen background
        static let surface = Color(light: 0xFFFFFF, dark: 0x141926)        // cards (container-lowest)
        static let surfaceMuted = Color(light: 0xEAEDFF, dark: 0x1C2436)   // surface-container
        static let foreground = Color(light: 0x113069, dark: 0xE6EAF5)     // on-surface (navy)
        static let secondaryText = Color(light: 0x445D99, dark: 0x98A6C9)  // on-surface-variant
        static let muted = Color(light: 0xEAEDFF, dark: 0x1C2436)
        static let border = Color(light: 0xD9E2FF, dark: 0x2A3550)         // outline-variant (soft)
        static let destructive = Color(light: 0x9F403D, dark: 0xF08A86)    // error
    }

    enum Spacing {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 16
        static let lg: CGFloat = 24
        static let xl: CGFloat = 32
        static let xxl: CGFloat = 48
    }

    // Rounded scale (md 12, lg 16, xl 24)
    enum Radius {
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 28
    }

    // Typography scale (system SF).
    enum Typography {
        static let largeTitle = Font.system(size: 32, weight: .bold, design: .default)    // headline-lg
        static let title = Font.system(size: 24, weight: .bold, design: .default)         // headline-md
        static let headline = Font.system(size: 20, weight: .semibold, design: .default)
        static let body = Font.system(size: 16, weight: .regular, design: .default)       // body-md
        static let callout = Font.system(size: 15, weight: .medium, design: .default)
        static let caption = Font.system(size: 14, weight: .medium, design: .default)     // label-md
    }
}

// MARK: - Color hex / adaptive (light & dark)
extension Color {
    init(_ rgb: UInt) {
        self.init(.sRGB,
                  red: Double((rgb >> 16) & 0xFF) / 255,
                  green: Double((rgb >> 8) & 0xFF) / 255,
                  blue: Double(rgb & 0xFF) / 255,
                  opacity: 1)
    }

    init(light: UInt, dark: UInt) {
        self.init(UIColor { trait in
            trait.userInterfaceStyle == .dark ? UIColor(rgb: dark) : UIColor(rgb: light)
        })
    }
}

extension UIColor {
    convenience init(rgb: UInt) {
        self.init(red: CGFloat((rgb >> 16) & 0xFF) / 255,
                  green: CGFloat((rgb >> 8) & 0xFF) / 255,
                  blue: CGFloat(rgb & 0xFF) / 255,
                  alpha: 1)
    }
}

// MARK: - BoundedImage — BULLETPROOF image box (NO overflow, padding preserved)
// Color.clear defines the box; the image fills it via overlay and is cropped with clipped().
// The image can never widen/stretch the layout — edge overflow is impossible on any screen.
// If height is given, fixed height; otherwise an aspect (w/h) ratio square is used.
struct BoundedImage<Content: View>: View {
    var height: CGFloat? = nil
    var aspect: CGFloat? = nil
    var cornerRadius: CGFloat = DS.Radius.xl
    @ViewBuilder var content: () -> Content   // the Image(...).resizable().scaledToFill()
    var body: some View {
        box
            .frame(maxWidth: .infinity)
            .overlay(content())
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
    }

    // height takes priority; otherwise aspect; if neither, a square (1:1).
    @ViewBuilder private var box: some View {
        if let height {
            Color.clear.frame(height: height)
        } else {
            Color.clear.aspectRatio(aspect ?? 1, contentMode: .fit)
        }
    }
}

// MARK: - App logo marker (app icon, rounded square)
struct AppLogoMark: View {
    var size: CGFloat = 30
    var body: some View {
        Image("AppLogo")
            .resizable()
            .scaledToFill()
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
    }
}

// MARK: - Native iOS 26 chrome (Liquid Glass)
// Every app uses the SYSTEM chrome: TabView (Tab API) for tabs, NavigationStack with
// .navigationTitle / .toolbar for top bars (system back button), system sheets with
// presentationDetents. Built with the iOS 26 SDK these become Liquid Glass on iOS 26 by
// themselves; iOS 26-only APIs sit behind #available with an iOS 17 fallback. Never draw a
// custom tab bar, top bar or fake glass (the features gate fails on one).
extension View {
    /// A floating primary control (a pinned bottom CTA): prominent glass tinted with the brand
    /// color on iOS 26, the brand-filled `PrimaryButtonStyle` before. The label should fill the
    /// width itself (`.frame(maxWidth: .infinity)`).
    @ViewBuilder func primaryActionStyle() -> some View {
        if #available(iOS 26, *) {
            buttonStyle(.glassProminent)
                .tint(DS.Palette.primary)
                .controlSize(.large)
                .font(DS.Typography.headline)
        } else {
            buttonStyle(.primary)
        }
    }

    /// A small floating control (close, back): a glass circle on iOS 26, the given fill before.
    @ViewBuilder func glassCircleButton(fallback: Color = DS.Palette.surfaceMuted, size: CGFloat = 40) -> some View {
        if #available(iOS 26, *) {
            buttonStyle(.glass).buttonBorderShape(.circle)
        } else {
            buttonStyle(.plain)
                .frame(width: size, height: size)
                .background(Circle().fill(fallback))
        }
    }

    /// System sheet surface: iOS 26 sheets keep the system's floating shape and corner (no custom
    /// corner) but get an opaque background, because on glass the screen behind ghosts through the
    /// text and buttons. Earlier systems paint the background behind the content.
    @ViewBuilder func sheetSurface(_ background: Color = DS.Palette.background) -> some View {
        if #available(iOS 26, *) {
            presentationBackground(background)
        } else {
            self.background(background.ignoresSafeArea())
        }
    }
}

// MARK: - Soft card shadow (soft elevation shadow)
extension View {
    func softShadow() -> some View {
        shadow(color: DS.Palette.foreground.opacity(0.10), radius: 18, x: 0, y: 10)
    }
    /// glow-shadow: primary color halo (result/CTA emphasis)
    func glowShadow(_ opacity: Double = 0.30) -> some View {
        shadow(color: DS.Palette.primary.opacity(opacity), radius: 22, x: 0, y: 14)
    }
}

// MARK: - Reusable primary CTA button (single primary action per screen)
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(DS.Typography.headline)
            .foregroundStyle(DS.Palette.onAccent)
            .frame(maxWidth: .infinity)
            .padding(.vertical, DS.Spacing.md)
            .background(DS.Palette.primary, in: RoundedRectangle(cornerRadius: DS.Radius.md))
            .shadow(color: DS.Palette.primary.opacity(0.28), radius: 12, y: 6)
            .opacity(configuration.isPressed ? 0.9 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.15), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var primary: PrimaryButtonStyle { PrimaryButtonStyle() }
}
