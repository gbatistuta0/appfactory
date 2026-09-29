import Foundation

/// Build-time configuration: the one place for everything the binary needs to know.
///
/// NO secrets live here — only the public Supabase anon key, the RevenueCat public SDK key and
/// product ids. AI provider keys stay server-side (Supabase Edge Functions). Product ids, prices,
/// trials, placements and locales come from `AppSpec` (generated from app.spec.json); the
/// `__TOKENS__` below are filled by `app_inject_config`. An unfilled token keeps the matching
/// feature silent (no network call), so a fresh scaffold builds and runs offline.
enum AppConfig {
    // MARK: - Backend (Supabase)

    static let supabaseURL = "__SUPABASE_URL__"
    static let supabaseAnonKey = "__SUPABASE_ANON_KEY__"
    /// Edge Functions base (AI proxy, usage, legal pages). AI keys are server-side.
    static var functionsURL: String { supabaseURL + "/functions/v1" }
    /// The Edge Function every AI call goes through.
    static let aiFunction = "ai-proxy"

    static var isSupabaseConfigured: Bool {
        supabaseURL.hasPrefix("https://") && !supabaseAnonKey.hasPrefix("__") && !isAutomatedTestRun
    }

    /// Unit and UI test runs never create anonymous users, RevenueCat customers or analytics
    /// events in the production project. Manual simulator runs are not affected.
    static let isAutomatedTestRun: Bool = {
        let info = ProcessInfo.processInfo
        return info.arguments.contains("-uiTest") || info.environment["XCTestConfigurationFilePath"] != nil
    }()

    // MARK: - RevenueCat

    /// Public SDK key (`appl_…`). `app_user_id` = Supabase user id.
    static let revenueCatKey = "__REVENUECAT_KEY__"
    /// RC entitlement lookup key: an active subscription means this entitlement is active.
    static var entitlementID: String { AppSpec.entitlementID }

    static var isRevenueCatConfigured: Bool {
        revenueCatKey.hasPrefix("appl_") && revenueCatKey != "appl_PENDING" && !isAutomatedTestRun
    }

    // MARK: - Products (all from app.spec.json)

    /// Offer paywall after the hard paywall is dismissed (shown once). `app_inject_config`
    /// (paywall_strategy="hard_only") flips this line.
    static let showOfferPaywall = true // appfactory:paywall_strategy

    /// Full-price products on the hard paywall (RevenueCat offering "default").
    static var hardProductIDs: [String] { AppSpec.products.filter { $0.offering == "default" }.map(\.id) }
    /// Separate discounted products on the offer paywall (offering "offer"). Not a promotional offer.
    static var offerProductIDs: [String] {
        showOfferPaywall ? AppSpec.products.filter { $0.offering == "offer" }.map(\.id) : []
    }
    static var allProductIDs: [String] { hardProductIDs + offerProductIDs }

    static func product(_ id: String) -> AppSpec.Product? { AppSpec.products.first { $0.id == id } }

    /// The full-price product an offer product is compared with (same billing period).
    static func regularProductID(forOffer offerID: String) -> String? {
        guard let offer = product(offerID) else { return nil }
        return AppSpec.products.first { $0.offering == "default" && $0.period == offer.period }?.id
    }

    /// Length of the free trial the spec declares (demo cards only; real trials come from the
    /// StoreProduct, and the paywall shows trial copy only when RevenueCat says eligible).
    static var trialDays: Int { AppSpec.products.compactMap(\.introDays).max() ?? 0 }

    /// DEBUG/QA override of the trial eligibility check: `-trialEligible YES|NO`.
    /// nil = ask RevenueCat (the only answer a release build uses).
    static var trialEligibilityOverride: Bool? {
        #if DEBUG
        guard ProcessInfo.processInfo.arguments.contains("-trialEligible") else { return nil }
        return darkFlag("-trialEligible", default: false)
        #else
        return nil
        #endif
    }

    // MARK: - Dark flags (DEBUG launch arguments only)

    /// A launch argument can flip a flag for QA without a rebuild. Release builds never read
    /// the arguments, so a store binary cannot turn a flag on.
    static func darkFlag(_ argument: String, default defaultValue: Bool) -> Bool {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: argument), i + 1 < args.count {
            let v = args[i + 1].uppercased()
            if ["YES", "1", "TRUE"].contains(v) { return true }
            if ["NO", "0", "FALSE"].contains(v) { return false }
        }
        if args.contains(argument) { return true }
        #endif
        return defaultValue
    }

    // MARK: - Legal / support (paywall + Settings + App Review)

    enum LegalPage: String {
        case privacy
        case terms
        case support
    }

    static var appDisplayName: String { AppSpec.displayName }
    static let supportEmail = "__SUPPORT_EMAIL__"
    /// Hosted by the backend's `legal` Edge Function. The same bare URLs go into App Store Connect.
    static var privacyURL: String { functionsURL + "/legal/privacy" }
    static var termsURL: String { functionsURL + "/legal/terms" }

    /// A URL only when the placeholder has been replaced — buttons hide otherwise.
    static func url(_ string: String) -> URL? {
        guard string.hasPrefix("https://") else { return nil }
        return URL(string: string)
    }

    /// Legal page in the app's language: `<functions>/legal/{privacy,terms}?lang=<app language>`.
    static func legalURL(_ page: LegalPage, lang: String = appLanguage) -> URL? {
        guard let base = url(functionsURL + "/legal/" + page.rawValue),
              var comps = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        comps.queryItems = [URLQueryItem(name: "lang", value: lang)]
        return comps.url
    }

    /// The language the UI runs in, mapped to one of the shipped languages (spec locales.app).
    static var appLanguage: String {
        contractLocale(Bundle.main.preferredLocalizations.first ?? "en")
    }

    /// Maps any language tag to a shipped locale: exact match, then language + region
    /// (`pt_BR` → `pt-BR`), then bare language (`de-AT` → `de`), else the `en` fallback.
    static func contractLocale(_ identifier: String) -> String {
        let tag = identifier.replacingOccurrences(of: "_", with: "-")
        let shipped = AppSpec.appLocales
        if shipped.contains(tag) { return tag }
        let lower = tag.lowercased()
        if let match = shipped.first(where: { $0.lowercased() == lower }) { return match }
        let language = String(lower.split(separator: "-").first ?? "")
        if let regional = shipped.first(where: { $0.lowercased().hasPrefix(language + "-") && lower.hasPrefix($0.lowercased()) }) {
            return regional
        }
        if shipped.contains(language) { return language }
        if let regional = shipped.first(where: { $0.lowercased().hasPrefix(language + "-") }) { return regional }
        return "en"
    }

    // MARK: - AI generation (each app customizes this in the features stage)

    /// What the app generates (goes into the prompt). Placeholder until the features stage.
    static let appConcept = "__APP_CONCEPT__"
    /// Styles the user can choose from.
    static let generationStyles: [String] = ["Natural", "Vivid", "Soft", "Bold"]
    /// {style} and {concept} are filled in.
    static let promptTemplate = "__PROMPT_TEMPLATE__"

    // @if credits
    // MARK: - Credit economy (credits monetization only; ledger is server-side)

    static let freeCredits = 1
    /// Yearly subscriber: credits per 30 days. Weekly subscriber: credits per 7 days.
    static let yearlyMonthlyCredits = 60 // appfactory:yearly_credits
    static let weeklyCredits = 10 // appfactory:weekly_credits
    static var yearlyProductID: String { AppSpec.products.first { $0.key == "yearly" }?.id ?? "" }
    static var weeklyProductID: String { AppSpec.products.first { $0.key == "weekly" }?.id ?? "" }
    private static let creditPackBase = AppSpec.bundleID + ".credits"
    static let creditPackSmallID = creditPackBase + ".small"
    static let creditPackMediumID = creditPackBase + ".medium"
    static let creditPackLargeID = creditPackBase + ".large"
    static var creditPackIDs: [String] { [creditPackSmallID, creditPackMediumID, creditPackLargeID] }
    /// Pack id → credit count (must match the server PACK_MAP — inject_config fills both).
    static func creditPackAmount(for id: String) -> Int {
        switch id {
        case creditPackSmallID: return 10 // appfactory:credit_pack_small
        case creditPackMediumID: return 30 // appfactory:credit_pack_medium
        case creditPackLargeID: return 60 // appfactory:credit_pack_large
        default: return 0
        }
    }
    // @endif
}
