import XCTest
@testable import __APP_NAME__

/// Repository paths, for tests that read the source tree (the simulator can read the host disk).
enum TestPaths {
    static let appRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
    static let storekit = appRoot.appendingPathComponent("Resources/Configuration.storekit")
    static let spec = appRoot.appendingPathComponent("app.spec.json")
    static let catalog = appRoot.appendingPathComponent("Resources/Localizable.xcstrings")
    static let infoPlistCatalog = appRoot.appendingPathComponent("Resources/InfoPlist.xcstrings")
    static let sources = appRoot.appendingPathComponent("Sources")

    static func json(_ url: URL) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }
}

final class PaywallPricingTests: XCTestCase {
    private func demo(_ key: String) throws -> PlanOffer {
        try XCTUnwrap(AppSpec.products.first { $0.key == key }.map(PlanOffer.demo))
    }

    func testPerPeriodMathAndFlooredBadges() {
        let weekly = PlanOffer(productID: "w", price: Decimal(string: "7.99")!, currencyCode: "USD",
                               locale: Locale(identifier: "en_US"), period: .week, freeTrialDays: 3, origin: .demo)
        let yearly = PlanOffer(productID: "y", price: Decimal(string: "49.99")!, currencyCode: "USD",
                               locale: Locale(identifier: "en_US"), period: .year, freeTrialDays: 3, origin: .demo)
        let offer = PlanOffer(productID: "o", price: Decimal(string: "29.99")!, currencyCode: "USD",
                              locale: Locale(identifier: "en_US"), period: .year, freeTrialDays: nil, origin: .demo)
        XCTAssertEqual(yearly.pricePerWeek, Decimal(string: "0.96"))
        XCTAssertEqual(offer.pricePerMonth, Decimal(string: "2.5"))
        XCTAssertEqual(weekly.pricePerYear, Decimal(string: "415.48"))
        // 1 − 49.99 / 415.48 = 87.97% → floored to 87 (a badge never overstates the saving).
        XCTAssertEqual(PaywallPricing.savingsPercent(yearly: yearly, weekly: weekly), 87)
        XCTAssertEqual(PaywallPricing.discountPercent(offer: offer, regular: yearly), 40)
        XCTAssertEqual(PaywallPricing.percentOff(price: 10, regular: 5), 0, "never a negative badge")
        XCTAssertEqual(PaywallPricing.percentOff(price: 1, regular: 0), 0)
        XCTAssertEqual(yearly.displayPrice, "$49.99")
    }

    /// The demo cards (shown until the store answers) must equal Configuration.storekit, which the
    /// scaffold generates from app.spec.json — so demo, StoreKit and spec agree.
    func testDemoPricesMatchStoreKitFile() throws {
        let doc = try TestPaths.json(TestPaths.storekit)
        let groups = try XCTUnwrap(doc["subscriptionGroups"] as? [[String: Any]])
        let subs = groups.flatMap { ($0["subscriptions"] as? [[String: Any]]) ?? [] }
        XCTAssertEqual(subs.count, AppSpec.products.count)
        for product in AppSpec.products {
            let sk = try XCTUnwrap(subs.first { $0["productID"] as? String == product.id }, product.id)
            XCTAssertEqual(Decimal(string: sk["displayPrice"] as? String ?? ""), product.usd, product.id)
            XCTAssertEqual(sk["recurringSubscriptionPeriod"] as? String, product.period)
            XCTAssertEqual(sk["groupNumber"] as? Int, product.level)
            let intro = sk["introductoryOffer"] as? [String: Any]
            XCTAssertEqual(intro != nil, product.introDays != nil, "intro offer of \(product.id)")
            XCTAssertEqual(PlanOffer.demo(product).price, product.usd)
            XCTAssertEqual(PlanOffer.demo(product).freeTrialDays, product.introDays)
        }
    }

    func testOfferProductNeverCarriesATrialAndHasARegularPrice() throws {
        for id in AppConfig.offerProductIDs {
            XCTAssertNil(AppConfig.product(id)?.introDays, "the one-time offer bills today")
            XCTAssertNotNil(AppConfig.regularProductID(forOffer: id), "offer \(id) needs a full-price twin")
        }
    }

    /// After Delete account RevenueCat stayed on its anonymous id while
    /// onboarding made a new Supabase user, so a purchase landed where the server never looks.
    func testRevenueCatFollowsTheSupabaseUser() {
        XCTAssertTrue(StoreManager.needsLogIn(current: "$RCAnonymousID:8c3adf898d8a4b44", supabaseUserID: "46ba2034-007b"))
        XCTAssertTrue(StoreManager.needsLogIn(current: "old-user", supabaseUserID: "new-user"))
        XCTAssertFalse(StoreManager.needsLogIn(current: "same-user", supabaseUserID: "same-user"))
        XCTAssertFalse(StoreManager.needsLogIn(current: "$RCAnonymousID:x", supabaseUserID: ""), "no Supabase user yet")
    }

    func testPlanMapping() {
        for p in AppSpec.products {
            let expected: StoreManager.Plan = p.period.hasSuffix("Y") ? .yearly : (p.period.hasSuffix("W") ? .weekly : .monthly)
            XCTAssertEqual(StoreManager.plan(forActiveProduct: p.id), expected)
        }
        XCTAssertEqual(StoreManager.plan(forActiveProduct: nil), .none)
        XCTAssertEqual(StoreManager.plan(forActiveProduct: "com.other"), .none)
    }

    @MainActor
    func testCatalogOrdersPlansAndNeedsEligibilityForTrialCopy() {
        let catalog = PaywallCatalog()
        XCTAssertEqual(catalog.hard.count, AppConfig.hardProductIDs.count)
        XCTAssertEqual(catalog.hard.map(\.period), catalog.hard.sorted(by: PaywallCatalog.shorterFirst).map(\.period))
        XCTAssertFalse(catalog.trialEligible)
        XCTAssertFalse(catalog.hard.contains(where: catalog.showsTrial), "no trial copy until RevenueCat confirms eligibility")
        if catalog.hard.count > 1 { XCTAssertNotNil(catalog.savingsPercent) }
    }
}

final class PaywallSourceTests: XCTestCase {
    /// Raw values are the RevenueCat placement ids and the analytics `from` value.
    func testRawValuesMatchSpecPlacements() throws {
        let spec = try TestPaths.json(TestPaths.spec)
        XCTAssertEqual(PaywallSource.allCases.map(\.rawValue), spec["placements"] as? [String])
        let offers = Set(spec["offer_placements"] as? [String] ?? [])
        for s in PaywallSource.allCases {
            XCTAssertEqual(s.placementID, s.eventValue)
            XCTAssertEqual(s.isOffer, offers.contains(s.rawValue))
            XCTAssertEqual(StoreManager.offeringID(for: s), s.isOffer ? "offer" : "default")
        }
        XCTAssertFalse(PaywallSource.billingIssue.isOffer, "billing_issue uses the default offering")
    }
}

final class ContractErrorTests: XCTestCase {
    /// backend/CONTRACT.md error table.
    func testErrorMapping() {
        XCTAssertNil(Proxy.error(status: 200, body: [:]))
        XCTAssertEqual(Proxy.error(status: 402, body: ["error": "paywall_required", "reason": "free_scan_used", "placement": "free_scan_used"]),
                       PaywallSource(rawValue: "free_scan_used").map(Proxy.APIError.paywallRequired) ?? .paywallRequired(.onboarding))
        XCTAssertEqual(Proxy.error(status: 402, body: ["error": "paywall_required", "placement": "nope"]),
                       .paywallRequired(.onboarding), "an unknown placement still opens the paywall")
        let resets = "2026-09-25T10:00:00.000Z"
        XCTAssertEqual(Proxy.error(status: 429, body: ["error": "daily_cap_reached", "placement": "daily_cap", "resets_at": resets]),
                       .dailyCap(resetsAt: Proxy.parseDate(resets)))
        XCTAssertNotNil(Proxy.parseDate(resets))
        XCTAssertEqual(Proxy.error(status: 429, body: ["error": "too_many_attempts"]), .tooManyAttempts(resetsAt: nil))
        XCTAssertEqual(Proxy.error(status: 503, body: ["error": "entitlement_unavailable", "retryable": true]),
                       .retryable(code: "entitlement_unavailable"))
        XCTAssertEqual(Proxy.error(status: 502, body: ["error": "analysis_failed"]), .retryable(code: "analysis_failed"))
        XCTAssertEqual(Proxy.error(status: 422, body: ["error": "not_applicable"]), .notApplicable)
        XCTAssertEqual(Proxy.error(status: 403, body: ["error": "consent_required"]), .consentRequired)
        XCTAssertEqual(Proxy.error(status: 413, body: ["error": "image_too_large"]), .invalidRequest(code: "image_too_large"))
        XCTAssertEqual(Proxy.error(status: 401, body: [:]), .unauthorized)
        XCTAssertEqual(Proxy.error(status: 504, body: [:]), .retryable(code: "http_504"))
    }

    func testRoutesNeverShowAPaywallForServerTrouble() {
        XCTAssertEqual(Proxy.route(for: .retryable(code: "entitlement_unavailable"), isSubscribed: false), .message(.retry))
        XCTAssertEqual(Proxy.route(for: .retryable(code: "entitlement_unavailable"), isSubscribed: true), .message(.retry))
        XCTAssertEqual(Proxy.route(for: .paywallRequired(.dailyCap), isSubscribed: false), .paywall(.dailyCap))
        XCTAssertEqual(Proxy.route(for: .dailyCap(resetsAt: nil), isSubscribed: false), .paywall(.dailyCap))
        XCTAssertEqual(Proxy.route(for: .dailyCap(resetsAt: nil), isSubscribed: true), .message(.dailyLimit(resetsAt: nil)))
        XCTAssertEqual(Proxy.route(for: .tooManyAttempts(resetsAt: nil), isSubscribed: false), .message(.tooManyAttempts))
        XCTAssertEqual(Proxy.route(for: .consentRequired, isSubscribed: true), .consent)
    }

    /// Only a rejected refresh (400/401/403) drops the identity; network errors never do.
    func testSessionIsOnlyDroppedOnAuthRejection() {
        for s in [400, 401, 403] { XCTAssertTrue(SupabaseAuth.isTokenRejection(status: s)) }
        for s in [-1, 0, 408, 429, 500, 502, 503] { XCTAssertFalse(SupabaseAuth.isTokenRejection(status: s)) }
    }

    // @if siwa
    func testIdentityConflictDetection() {
        XCTAssertTrue(SupabaseAuth.isIdentityConflict(status: 422, body: ["error_code": "identity_already_exists"]))
        XCTAssertTrue(SupabaseAuth.isIdentityConflict(status: 400, body: ["code": "identity_already_exists"]))
        XCTAssertFalse(SupabaseAuth.isIdentityConflict(status: 400, body: ["error_code": "bad_jwt"]))
    }

    func testAppleNonceIsHashed() {
        let raw = AppleSignIn.randomNonce()
        XCTAssertEqual(raw.count, 32)
        XCTAssertEqual(AppleSignIn.sha256("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }
    // @endif

    func testAutomatedRunsNeverTouchProductionServices() {
        XCTAssertTrue(AppConfig.isAutomatedTestRun)
        XCTAssertFalse(AppConfig.isSupabaseConfigured)
        XCTAssertFalse(AppConfig.isRevenueCatConfigured)
    }
}

final class LegalURLTests: XCTestCase {
    func testLegalURLsCarryTheLanguage() throws {
        // Unconfigured template: no https base → buttons hide.
        if !AppConfig.supabaseURL.hasPrefix("https://") {
            XCTAssertNil(AppConfig.legalURL(.privacy))
            return
        }
        let privacy = try XCTUnwrap(AppConfig.legalURL(.privacy, lang: "pt-BR"))
        XCTAssertTrue(privacy.path.hasSuffix("/functions/v1/legal/privacy"))
        XCTAssertEqual(URLComponents(url: privacy, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "pt-BR")
        XCTAssertTrue(AppConfig.legalURL(.terms)?.path.hasSuffix("/legal/terms") ?? false)
    }

    func testContractLocaleMapping() {
        XCTAssertEqual(AppConfig.contractLocale("ja_JP"), "en")
        XCTAssertEqual(AppConfig.contractLocale("en-GB"), "en")
        for loc in AppSpec.appLocales { XCTAssertEqual(AppConfig.contractLocale(loc), loc) }
        if AppSpec.appLocales.contains("pt-BR") { XCTAssertEqual(AppConfig.contractLocale("pt_BR"), "pt-BR") }
        if AppSpec.appLocales.contains("de") { XCTAssertEqual(AppConfig.contractLocale("de-AT"), "de") }
    }
}
