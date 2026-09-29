import Foundation

/// DEBUG launch arguments for UI tests, screenshots and QA. Release builds read none of them.
///
/// | Argument | Effect |
/// |---|---|
/// | `-uiTest` | Test run: no analytics, no Supabase/RevenueCat network, demo prices, instant loaders |
/// | `-resetOnboarding` | Start from a clean install state |
/// | `-uiUnits metric\|imperial` | Force the unit default |
/// | `-uiFastLoading` | The "setting up" counter finishes in ~1 s |
/// | `-uiOnboardingStep <id>` | Open onboarding at that step |
/// | `-uiPaywall` | Open the hard paywall with sample answers |
/// | `-uiOffer` | Open the offer paywall |
/// | `-uiSeedProfile` | Skip onboarding with sample answers |
/// | `-uiTab 0\|1\|2` | Initial main tab |
/// | `-uiResult`, `-uiSeedGallery` | Screenshot states of the create flow |
/// | `-trialEligible YES\|NO` | Override the intro-offer eligibility check |
enum LaunchOptions {
    private static var args: [String] { ProcessInfo.processInfo.arguments }

    static func has(_ flag: String) -> Bool {
        #if DEBUG
        return args.contains(flag)
        #else
        return false
        #endif
    }

    static func value(_ flag: String) -> String? {
        #if DEBUG
        guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
        return args[i + 1]
        #else
        return nil
        #endif
    }

    static var isUITest: Bool { has("-uiTest") }
    static var resetOnboarding: Bool { has("-resetOnboarding") }
    static var unitSystem: UnitSystem? { value("-uiUnits").flatMap(UnitSystem.init(rawValue:)) }
    static var fastLoading: Bool { has("-uiFastLoading") || has("-uiTest") }
    static var onboardingStep: String? { value("-uiOnboardingStep") }
    static var showPaywall: Bool { has("-uiPaywall") }
    static var showOffer: Bool { has("-uiOffer") }
    static var seedProfile: Bool { has("-uiSeedProfile") }
    static var showResult: Bool { has("-uiResult") }
    static var seedGallery: Bool { has("-uiSeedGallery") }
    static var initialTab: Int { value("-uiTab").flatMap(Int.init) ?? 0 }

    /// Sample image in the bundle (screenshots / previews).
    static var sampleURL: URL? { Bundle.main.url(forResource: "sample", withExtension: "jpg") }
}
