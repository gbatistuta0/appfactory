import SwiftUI
import Lottie

// MARK: - Motion
//
// Two layers:
// 1. The design's CSS @keyframes translated to SwiftUI (design/project/*.dc.html share one BASE_CSS):
//    entrances `rise` / `pop` / `fadeIn` play once on appear; loops `bob` / `pulse` / `scanLine` /
//    `blinkDot` / `floatUp` run forever; `DrawOnAppear` drives stroke/ring/bar fills once.
//    Everything stops when motion is reduced: the system Reduce Motion setting, `-uiTest`, or an
//    explicit `.environment(\.motionReduced, true)`. Apply `.motionReducedRoot()` once at the root.
// 2. CUTE Lottie animations (lottie-spm), fetched from the LottieFiles free library and RECOLORED to
//    the palette at BUILD TIME (animation_fetch_recolor → Resources/Animations/<slot>.json). Swift just
//    renders them; a missing asset falls back gracefully. Slots: loading, onboarding_hero, success, empty.
enum Motion {
    // Slot → bundled JSON name (factory writes Resources/Animations/<name>.json). Rename per app if needed.
    enum Slot: String {
        case loading = "loading"
        case success = "success"
        case empty = "empty"
        case onboardingHero = "onboarding_hero"
    }

    /// `-uiTest` runs freeze every loop: infinite animations keep XCUITest from ever seeing the app idle.
    static var isReducedForTests: Bool {
        ProcessInfo.processInfo.arguments.contains("-uiTest")
    }

    /// cubic-bezier(.2,.8,.2,1) — the design's entrance curve (`rise`).
    static func entrance(_ duration: Double) -> Animation {
        .timingCurve(0.2, 0.8, 0.2, 1, duration: duration)
    }

    /// cubic-bezier(.3,1.6,.5,1) — the selection "spring" used by cards and checks.
    static let select = Animation.timingCurve(0.3, 1.6, 0.5, 1, duration: 0.3)
}

/// Renders a bundled (build-time recolored) Lottie by slot. Loops unless `once`.
/// If the JSON isn't bundled yet (asset not installed), shows a palette ProgressView so build/preview never break.
struct AppLottieView: View {
    let slot: Motion.Slot
    var once: Bool = false
    var onFinish: (() -> Void)? = nil

    private var hasAsset: Bool {
        Bundle.main.url(forResource: slot.rawValue, withExtension: "json", subdirectory: "Animations") != nil
            || Bundle.main.url(forResource: slot.rawValue, withExtension: "json") != nil
    }

    var body: some View {
        Group {
            if hasAsset {
                LottieView(animation: .named(slot.rawValue))
                    .configure { $0.contentMode = .scaleAspectFit }
                    .playbackMode(once
                        ? .playing(.fromProgress(0, toProgress: 1, loopMode: .playOnce))
                        : .playing(.fromProgress(0, toProgress: 1, loopMode: .loop)))
                    .animationDidFinish { _ in if once { onFinish?() } }
            } else {
                ProgressView().tint(DS.Palette.primary)   // ponytail: fallback until asset installed
            }
        }
    }
}

// MARK: - Loading badge (looping Lottie)
struct MotionSpinner: View {
    var size: CGFloat = 120
    var body: some View {
        AppLottieView(slot: .loading).frame(width: size, height: size)
    }
}

// MARK: - Success (play-once celebration)
struct MotionSuccess: View {
    var size: CGFloat = 120
    var onFinish: (() -> Void)? = nil
    var body: some View {
        AppLottieView(slot: .success, once: true, onFinish: onFinish).frame(width: size, height: size)
    }
}

// MARK: - Empty state (looping Lottie + text)
struct MotionEmpty: View {
    var title: String
    var subtitle: String? = nil
    var size: CGFloat = 140
    var body: some View {
        VStack(spacing: DS.Spacing.md) {
            AppLottieView(slot: .empty).frame(width: size, height: size)
            Text(title)
                .font(DS.Typography.headline).foregroundStyle(DS.Palette.foreground)
            if let subtitle {
                Text(subtitle)
                    .font(DS.Typography.caption).foregroundStyle(DS.Palette.secondaryText)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(DS.Spacing.xl)
    }
}

// MARK: - Reduced motion

private struct ReducedMotionKey: EnvironmentKey {
    static let defaultValue = Motion.isReducedForTests
}

extension EnvironmentValues {
    /// True when loops and entrances must not animate (Reduce Motion or `-uiTest`).
    var motionReduced: Bool {
        get { self[ReducedMotionKey.self] }
        set { self[ReducedMotionKey.self] = newValue }
    }
}

private struct MotionReducedRoot: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var systemReduced

    func body(content: Content) -> some View {
        content.environment(\.motionReduced, systemReduced || Motion.isReducedForTests)
    }
}

extension View {
    /// Put once on the root view: folds the system Reduce Motion setting and `-uiTest` into `motionReduced`.
    func motionReducedRoot() -> some View { modifier(MotionReducedRoot()) }
}

// MARK: - Entrances (`rise`, `pop`, `fadein`)

enum EntranceKind {
    /// fade in + move up 16 pt (`rise`)
    case rise
    /// scale .55 → 1.07 → 1 with fade (`pop`)
    case pop
    /// opacity only (`fadein`)
    case fade
}

private struct EntranceModifier: ViewModifier {
    let kind: EntranceKind
    let delay: Double
    let duration: Double
    @State private var shown = false
    @Environment(\.motionReduced) private var reduced

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: kind == .rise && !shown ? 16 : 0)
            .scaleEffect(kind == .pop && !shown ? 0.55 : 1)
            .onAppear {
                guard !shown else { return }
                if reduced {
                    shown = true
                    return
                }
                let animation: Animation = kind == .pop
                    ? .spring(response: duration * 0.9, dampingFraction: 0.62)
                    : Motion.entrance(duration)
                withAnimation(animation.delay(delay)) { shown = true }
            }
    }
}

extension View {
    func rise(_ delay: Double = 0, duration: Double = 0.5) -> some View {
        modifier(EntranceModifier(kind: .rise, delay: delay, duration: duration))
    }

    func pop(_ delay: Double = 0, duration: Double = 0.5) -> some View {
        modifier(EntranceModifier(kind: .pop, delay: delay, duration: duration))
    }

    func fadeIn(_ delay: Double = 0, duration: Double = 0.5) -> some View {
        modifier(EntranceModifier(kind: .fade, delay: delay, duration: duration))
    }
}

// MARK: - Loops (`bob`, `pulse`, `scan`, `dot`, `float`)

/// Drives a 0 → 1 phase forever (or holds `rest` when motion is reduced) and hands it to `effect`.
struct LoopModifier<Effect: ViewModifier>: ViewModifier {
    let animation: Animation
    let delay: Double
    var rest: Double = 0
    let effect: (Double) -> Effect
    @State private var phase = 0.0
    @Environment(\.motionReduced) private var reduced

    func body(content: Content) -> some View {
        content
            .modifier(effect(reduced ? rest : phase))
            .onAppear {
                guard !reduced else { return }
                withAnimation(animation.delay(delay)) { phase = 1 }
            }
    }
}

struct OffsetEffect: ViewModifier {
    let x: CGFloat
    let y: CGFloat
    func body(content: Content) -> some View { content.offset(x: x, y: y) }
}

struct PulseEffect: ViewModifier {
    let phase: Double
    func body(content: Content) -> some View {
        content
            .scaleEffect(0.85 + 0.75 * phase)
            .opacity(0.5 * (1 - phase))
    }
}

struct OpacityEffect: ViewModifier {
    let value: Double
    func body(content: Content) -> some View { content.opacity(value) }
}

struct FloatEffect: ViewModifier {
    let phase: Double
    func body(content: Content) -> some View {
        // float: rise 120 pt; opacity 0 → 1 (first 20 %) → 0
        let opacity = phase < 0.2 ? phase / 0.2 : 1 - (phase - 0.2) / 0.8
        return content.offset(y: -120 * phase).opacity(opacity)
    }
}

extension View {
    /// `bob`: 0 → −8 pt → 0, ease-in-out, forever.
    func bob(duration: Double = 2.6, amplitude: CGFloat = 8, delay: Double = 0) -> some View {
        modifier(LoopModifier(animation: .easeInOut(duration: duration / 2).repeatForever(autoreverses: true),
                              delay: delay) { p in OffsetEffect(x: 0, y: -amplitude * p) })
    }

    /// `pulse`: a ring expands to 1.6× and fades, forever.
    func pulse(duration: Double = 2.8, delay: Double = 0) -> some View {
        modifier(LoopModifier(animation: .easeOut(duration: duration).repeatForever(autoreverses: false),
                              delay: delay, rest: 1) { p in PulseEffect(phase: p) })
    }

    /// `scan`: 0 → distance → 0, ease-in-out.
    func scanLine(distance: CGFloat, duration: Double = 3.2) -> some View {
        modifier(LoopModifier(animation: .easeInOut(duration: duration / 2).repeatForever(autoreverses: true),
                              delay: 0) { p in OffsetEffect(x: 0, y: distance * p) })
    }

    /// `dot`: opacity .25 ↔ 1.
    func blinkDot(duration: Double = 1.2, delay: Double = 0) -> some View {
        modifier(LoopModifier(animation: .easeInOut(duration: duration / 2).repeatForever(autoreverses: true),
                              delay: delay, rest: 1) { p in OpacityEffect(value: 0.25 + 0.75 * p) })
    }

    /// `float`: floats up 120 pt while fading in and out.
    func floatUp(duration: Double = 3.2, delay: Double = 0) -> some View {
        modifier(LoopModifier(animation: .easeOut(duration: duration).repeatForever(autoreverses: false),
                              delay: delay, rest: 0.2) { p in FloatEffect(phase: p) })
    }
}

// MARK: - Drawn strokes (`draw`, `ring`, `growY`, `barIn`)

/// Animates a 0 → 1 progress once, after `delay` (1 immediately when motion is reduced).
struct DrawOnAppear<Content: View>: View {
    var delay: Double = 0
    var duration: Double = 1.6
    var animation: ((Double) -> Animation)? = nil
    @ViewBuilder var content: (Double) -> Content
    @State private var progress = 0.0
    @Environment(\.motionReduced) private var reduced

    var body: some View {
        content(reduced ? 1 : progress)
            .onAppear {
                guard !reduced, progress == 0 else { return }
                let anim = animation?(duration) ?? .timingCurve(0.4, 0, 0.2, 1, duration: duration)
                withAnimation(anim.delay(delay)) { progress = 1 }
            }
    }
}
