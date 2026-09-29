// @if firebase
import FirebaseAnalytics
import FirebaseCore
// @endif
import Foundation
import OSLog
import UIKit

/// Live event tracking through Firebase Analytics (GA4). Named `Tracker` so it does not clash
/// with `FirebaseAnalytics.Analytics`.
///
/// Event names are a FIXED CATALOG (`Tracker.Event`). The portfolio review compares the same
/// funnel across apps, which only works when every app emits identical names — add a case
/// rather than passing a raw string. App-specific events go through `log(custom:)`, which
/// prefixes them with the spec's `analytics.event_prefix` (e.g. `hue_`).
///
/// Nothing leaves the device unless `AnalyticsGate` says this is a production App Store build;
/// Firebase is not even configured otherwise (see `AppFactoryApp.init`).
enum Tracker {
    enum Event: String, CaseIterable {
        // lifecycle
        case appOpen = "app_open"
        case appFirstOpen = "app_first_open"
        case screenEnter = "screen_enter"                  // screen, prev_screen, dwell_sec
        // onboarding funnel
        case onboardingStart = "onboarding_start"
        case onboardingStepView = "onboarding_step_view"   // step, kind
        case onboardingAnswer = "onboarding_answer"        // step, question, answer
        case onboardingComplete = "onboarding_complete"    // subscribed
        case authAttempt = "auth_attempt"                  // provider, result
        case consentResult = "consent_result"              // result
        // paywall funnel
        case paywallView = "paywall_view"                  // from (PaywallSource), variant
        case paywallPlanSelect = "paywall_plan_select"     // plan, from
        case paywallDismiss = "paywall_dismiss"            // from
        case paywallRestore = "paywall_restore"            // from, result
        // purchase
        case purchaseStart = "purchase_start"              // product, from
        case purchaseSuccess = "purchase_success"          // product, from, price, currency, plan
        case purchaseCancel = "purchase_cancel"            // product, from, reason
        case purchaseFail = "purchase_fail"                // product, from, reason
        case trialStart = "trial_start"                    // product
        case subscriptionActive = "subscription_active"    // plan
        case storeProductsEmpty = "store_products_empty"   // attempts
        // core value loop (the features stage wires the app's own action to these)
        case generateStart = "generate_start"              // style
        case generateSuccess = "generate_success"          // style, duration_ms
        case generateFail = "generate_fail"                // reason
        case limitReached = "limit_reached"                // reason (daily_cap / too_many_attempts)
        case resultView = "result_view"
        case resultSave = "result_save"
        case resultShare = "result_share"                  // viral signal
        case createAnother = "create_another"              // strongest retention signal
        case ratingPromptShown = "rating_prompt_shown"     // trigger (RatingPolicy, success moments only)
        // navigation
        case tabSelect = "tab_select"                      // tab
        case galleryView = "gallery_view"
        case settingsView = "settings_view"
        // @if credits
        // credits (credits monetization only)
        case creditsSpent = "credits_spent"                // amount, remaining, reason
        case creditsExhausted = "credits_exhausted"
        case topUpView = "top_up_view"
        case topUpPurchase = "top_up_purchase"             // pack, credits
        // @endif
    }

    /// The production-only gate (see `AnalyticsGate`). Starts from the launch decision and can
    /// only be tightened by the AppTransaction check.
    nonisolated(unsafe) private(set) static var gate = AnalyticsGate.launch()
    static var isSending: Bool { gate.allowsSending }

    /// Call once at launch: verify the store environment with AppTransaction.
    static func refineGate() async {
        guard gate.allowsSending, let env = await AnalyticsGate.verifiedStoreEnvironment(), env != .production else { return }
        gate.storeEnvironment = env
        // @if firebase
        if firebaseReady { FirebaseAnalytics.Analytics.setAnalyticsCollectionEnabled(false) }
        // @endif
    }

    private static let console = Logger(subsystem: Bundle.main.bundleIdentifier ?? "app", category: "analytics")

    private static let sessionID = UUID().uuidString
    private static let launchedAt = Date()
    private static let stateQueue = DispatchQueue(label: "tracker.state")
    nonisolated(unsafe) private static var seq = 0
    nonisolated(unsafe) private static var currentScreen = "launch"
    nonisolated(unsafe) private static var previousScreen = ""
    nonisolated(unsafe) private static var screenEnteredAt = Date()

    private static let appVersion: String =
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?")
        + "(" + (Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?") + ")"

    /// Screen transition with the dwell time of the previous screen. Real screen names replace
    /// Firebase's automatic screen_view (which reports mangled SwiftUI type names; disabled via
    /// `FirebaseAutomaticScreenReportingEnabled = NO`).
    static func screen(_ name: String) {
        let dwell = stateQueue.sync { () -> Double in
            let d = Date().timeIntervalSince(screenEnteredAt)
            previousScreen = currentScreen
            currentScreen = name
            screenEnteredAt = Date()
            return d
        }
        // @if firebase
        if isSending, firebaseReady {
            FirebaseAnalytics.Analytics.logEvent(AnalyticsEventScreenView, parameters: [
                AnalyticsParameterScreenName: name,
                AnalyticsParameterScreenClass: name,
            ])
        }
        // @endif
        log(.screenEnter, ["dwell_sec": String(format: "%.1f", dwell)])
    }

    static func log(_ event: Event, _ props: [String: String] = [:]) {
        // A failed core action, purchase or restore makes this launch ineligible for a rating request.
        // @if ratings
        RatingPolicy.shared.note(event, props)
        // @endif
        send(event.rawValue, props)
    }

    /// App-specific event with no portfolio-wide meaning. The spec's prefix is added when the
    /// name does not carry it yet, so it can never collide with the catalog.
    static func log(custom name: String, _ props: [String: String] = [:]) {
        send(customName(name), props)
    }

    static func customName(_ name: String) -> String {
        name.hasPrefix(AppSpec.eventPrefix) ? name : AppSpec.eventPrefix + name
    }

    private static func send(_ name: String, _ props: [String: String]) {
        guard isSending else {
            // Not production: keep the event on this device, visible in the console.
            console.debug("[\(gate.blockReason ?? "", privacy: .public)] \(name, privacy: .public) \(props.description, privacy: .public)")
            return
        }
        let ctx = stateQueue.sync { () -> [String: String] in
            seq += 1
            return [
                "session_id": sessionID,
                "seq": "\(seq)",
                "since_launch_sec": String(format: "%.1f", Date().timeIntervalSince(launchedAt)),
                "screen": currentScreen,
                "prev_screen": previousScreen,
                "screen_sec": String(format: "%.1f", Date().timeIntervalSince(screenEnteredAt)),
            ]
        }
        var full = ctx.merging(props) { _, new in new }
        full["app_version"] = appVersion
        full["locale"] = Locale.current.identifier
        full["device"] = UIDevice.current.model
        // @if firebase
        if firebaseReady {
            FirebaseAnalytics.Analytics.logEvent(name, parameters: firebaseParams(full))
        }
        // @endif
    }

    /// Firebase is only configured when the gate is open and GoogleService-Info.plist is bundled.
    // @if firebase
    private static var firebaseReady: Bool { FirebaseApp.app() != nil }
    // @endif

    /// Firebase allows 25 parameters and 100-character values. Only whitelisted keys are sent;
    /// high-cardinality context (session id, seq) stays out.
    static let firebaseKeys: Set<String> = [
        "screen", "prev_screen", "screen_sec", "dwell_sec", "since_launch_sec", "app_version", "locale", "device",
        "step", "kind", "question", "answer", "result", "provider", "subscribed",
        "from", "variant", "plan", "product", "price", "currency", "reason", "tab", "trial", "store_ready",
        "style", "duration_ms", "attempts", "trigger",
        // credits mode
        "amount", "remaining", "pack", "credits",
    ]

    static func firebaseParams(_ full: [String: String]) -> [String: String] {
        var out = full.filter { firebaseKeys.contains($0.key) }
        for (k, v) in out where v.count > 100 { out[k] = String(v.prefix(100)) }
        return out
    }

    /// Emits `app_first_open` once per install.
    static func logFirstOpenIfNeeded() {
        let key = "tracker_first_open_logged"
        guard !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)
        log(.appFirstOpen)
    }
}
