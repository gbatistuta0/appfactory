// @if firebase
import FirebaseAnalytics
import FirebaseCore
// @endif
import SwiftUI

@main
struct AppFactoryApp: App {
    @StateObject private var store = StoreManager()
    @StateObject private var profiles: ProfileStore
    // @if credits
    @StateObject private var credits = CreditManager()
    // @endif
    @AppStorage("onboarding_completed") private var onboarded = false
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // @if firebase
        // Firebase starts ONLY when the analytics gate is open (production App Store build) and
        // the plist is bundled: DEBUG, simulator, tests and TestFlight never configure it.
        if Tracker.isSending, Bundle.main.url(forResource: "GoogleService-Info", withExtension: "plist") != nil {
            FirebaseApp.configure()
            FirebaseAnalytics.Analytics.setAnalyticsCollectionEnabled(true)
        }
        // @endif
        if LaunchOptions.resetOnboarding {
            UserDefaults.standard.removeObject(forKey: "onboarding_completed")
            // @if offer_paywall
            UserDefaults.standard.removeObject(forKey: OnboardingView.offerSeenKey)
            // @endif
            UserDefaults.standard.removeObject(forKey: ProfileStore.answersKey)
        }
        #if DEBUG
        // `-uiSeedProfile` / screenshots: skip onboarding with sample answers.
        if LaunchOptions.seedProfile || ProcessInfo.processInfo.arguments.contains("-uiTab") {
            if let data = try? JSONEncoder().encode(PaywallPersonalization.sampleAnswers()) {
                UserDefaults.standard.set(data, forKey: ProfileStore.answersKey)
            }
            UserDefaults.standard.set(true, forKey: "onboarding_completed")
        }
        #endif
        _profiles = StateObject(wrappedValue: ProfileStore())
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if LaunchOptions.showPaywall || LaunchOptions.showOffer {
                    PaywallPreviewHost()
                } else if onboarded && LaunchOptions.onboardingStep == nil {
                    RootTabView()
                } else {
                    OnboardingView(start: LaunchOptions.onboardingStep) {
                        withAnimation(.easeInOut(duration: 0.35)) { onboarded = true }
                    }
                }
            }
            .environmentObject(store)
            .environmentObject(profiles)
            // @if credits
            .environmentObject(credits)
            // @endif
            .task {
                // RevenueCat identity = the Supabase anonymous user id (CONTRACT §1).
                if AppConfig.isRevenueCatConfigured, let uid = try? await SupabaseAuth.shared.userID() {
                    store.configure(appUserID: uid)
                }
                // @if credits
                store.onBalance = { [credits] b in credits.applyBalance(b) }
                await credits.refresh()
                // @endif
                await Tracker.refineGate()
                await store.load()
                Tracker.logFirstOpenIfNeeded()
                Tracker.log(.appOpen)
                if store.plan != .none {
                    Tracker.log(.subscriptionActive, ["plan": store.plan.rawValue])
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { await store.load() } }
            }
        }
    }
}

/// `-uiPaywall` / `-uiOffer` (DEBUG screenshots and UI tests): a paywall with sample answers.
private struct PaywallPreviewHost: View {
    @StateObject private var catalog = PaywallCatalog()
    @EnvironmentObject private var store: StoreManager

    var body: some View {
        Group {
            // @if offer_paywall
            if LaunchOptions.showOffer {
                OfferPaywallView(source: .offerAfterOnboarding, onPurchased: {}, onClose: {})
            } else {
                HardPaywallView(source: .onboarding, personalization: personalization, onPurchased: {}, onClose: {})
            }
            // @endif
            // @if !offer_paywall
            HardPaywallView(source: .onboarding, personalization: personalization, onPurchased: {}, onClose: {})
            // @endif
        }
        .environmentObject(catalog)
        .task { await catalog.load(store: store) }
    }

    private var personalization: PaywallPersonalization {
        #if DEBUG
        return PaywallPersonalization(answers: PaywallPersonalization.sampleAnswers())
        #else
        return PaywallPersonalization(answers: OnboardingAnswers())
        #endif
    }
}
