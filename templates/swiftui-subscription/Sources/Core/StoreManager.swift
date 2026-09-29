// @if revenuecat
import RevenueCat
// @endif
import StoreKit
import SwiftUI

// @if revenuecat
/// RevenueCat subscriptions: the "default" offering (hard paywall) and the "offer" offering
/// (one-time discounted product), both from app.spec.json. Purchase and Apple verification live in
/// RevenueCat. Usage quotas are enforced server-side, keyed by the Supabase user id (= RC
/// app_user_id); the server reads the subscription from RevenueCat on the next request. The one
/// client duty is to keep RevenueCat on that same id (`syncIdentity`), or the server cannot see what
/// was bought.
///
/// Billing resilience: the entitlement's billing issue (grace period / billing retry) is published
/// as `billingIssue`; the UI shows a banner that opens `manageSubscriptionsSheet`. The
/// `customerInfoStream` keeps the state live, so the banner disappears by itself when Apple
/// recovers the payment. StoreKit's own `.billingIssue` message is never suppressed: RevenueCat is
/// configured with `showStoreMessagesAutomatically: false` only so the message is deferred while
/// onboarding or a paywall is on screen; `RootTabView` calls `showDeferredStoreMessages()` as soon
/// as the main app is visible.
@MainActor
final class StoreManager: ObservableObject {
    enum Plan: String { case none, weekly, monthly, yearly }

    enum PurchaseOutcome: Equatable {
        /// The user backed out, or the store never opened. Nothing is owed.
        case cancelled
        /// Paid and the entitlement is active.
        case success
        /// Money was taken but the entitlement is not visible yet. The user MUST be told
        /// (and it is a separate analytics event — never fold it into "cancel").
        case paidButNotActive
    }

    @Published private(set) var products: [StoreProduct] = []
    /// RevenueCat offerings: "default" and "offer".
    private(set) var offerings: Offerings?
    @Published private(set) var isSubscribed = false
    @Published private(set) var plan: Plan = .none
    /// Grace period / billing retry on the entitlement; nil when billing is healthy.
    @Published private(set) var billingIssue: BillingIssue?
    /// User-facing, already localized error line (never a raw StoreKit sentence).
    @Published var lastError: String?
    /// Reason of the last `.cancelled` outcome, for analytics (`user_cancelled`, `network`, …).
    private(set) var lastAbandonReason = "user_cancelled"

    private var configured = false
    private var loading: Task<Void, Never>?
    private var customerInfoUpdates: Task<Void, Never>?

    /// `Purchases.shared` is a `fatalError` when RevenueCat is not configured — `try?` cannot
    /// catch it. Every RC call goes through this gate.
    var isReady: Bool { configured && Purchases.isConfigured }

    static var storeUnavailable: String {
        String(localized: "The store isn't available right now. Please check your connection and try again.")
    }
    private static var purchaseFailed: String {
        String(localized: "The purchase didn't go through. Please try again.")
    }

    /// Configure RevenueCat with the Supabase identity. The guard is RevenueCat's own state,
    /// not a local latch: if identity failed on the first launch (offline), the next `load()`
    /// must still be able to configure.
    func configure(appUserID: String) {
        guard AppConfig.isRevenueCatConfigured else { return }
        guard !Purchases.isConfigured, !appUserID.isEmpty else {
            configured = Purchases.isConfigured
            return
        }
        Purchases.logLevel = .warn
        Purchases.configure(with: Configuration.Builder(withAPIKey: AppConfig.revenueCatKey)
            .with(appUserID: appUserID)
            .with(showStoreMessagesAutomatically: false)
            .build())
        configured = true
        startCustomerInfoUpdates()
    }

    /// The Supabase identity changed (Sign in with Apple found an existing account).
    func logIn(appUserID: String) async {
        guard isReady else { return configure(appUserID: appUserID) }
        if let result = try? await Purchases.shared.logIn(appUserID) { apply(result.customerInfo) }
    }

    /// Account deleted: RevenueCat forgets the user; the next launch creates a new anonymous one.
    func logOut() async {
        guard isReady else { return }
        if let info = try? await Purchases.shared.logOut() { apply(info) }
    }

    /// Fetch products and entitlements. Retries identity + configuration first, so a launch
    /// that missed it (cold network) heals when the paywall opens.
    func load() async {
        // Single flight: launch, foreground and the paywall all call load(); one fetch serves them.
        if let loading { return await loading.value }
        let task = Task { await self.performLoad() }
        loading = task
        await task.value
        loading = nil
    }

    private func performLoad() async {
        if !isReady, AppConfig.isRevenueCatConfigured, let uid = try? await SupabaseAuth.shared.userID() {
            configure(appUserID: uid)
        }
        guard isReady else { return }
        await syncIdentity()
        await refreshEntitlements()
        // Three attempts: a cold first StoreKit fetch left paying users facing an empty store.
        for attempt in 0..<3 {
            products = await Purchases.shared.products(Self.productIDsToLoad)
            if !products.isEmpty { break }
            if attempt < 2 { try? await Task.sleep(for: .seconds(2 << attempt)) }
        }
        if products.isEmpty { Tracker.log(.storeProductsEmpty, ["attempts": "3"]) }
        offerings = try? await Purchases.shared.offerings()
    }

    private static var productIDsToLoad: [String] {
        // @if credits
        return AppConfig.allProductIDs + AppConfig.creditPackIDs
        // @endif
        // @if subscription
        return AppConfig.allProductIDs
        // @endif
    }

    /// The offering a placement shows. Placement rules live in the RevenueCat dashboard; until a
    /// rule exists `currentOffering(forPlacement:)` returns the current offering, which would put
    /// hard-paywall products on the offer paywall — so the identifier is checked and the expected
    /// offering is used instead.
    func offering(for source: PaywallSource) -> Offering? {
        guard let offerings else { return nil }
        let expected = Self.offeringID(for: source)
        if let placed = offerings.currentOffering(forPlacement: source.placementID), placed.identifier == expected {
            return placed
        }
        return offerings.all[expected] ?? offerings.current
    }

    nonisolated static func offeringID(for source: PaywallSource) -> String {
        source.isOffer ? "offer" : "default"
    }

    /// The package for `productID` in the placement's offering: purchasing a package (not a bare
    /// product) attributes the sale to the placement in RevenueCat.
    func package(for productID: String, source: PaywallSource) -> Package? {
        offering(for: source)?.availablePackages.first { $0.storeProduct.productIdentifier == productID }
    }

    func product(_ id: String) -> StoreProduct? {
        products.first { $0.productIdentifier == id }
    }

    /// Buy a subscription. `.success` only once the entitlement is active.
    @discardableResult
    func purchase(_ product: StoreProduct, package: Package? = nil) async -> PurchaseOutcome {
        guard isReady else {
            lastError = Self.storeUnavailable
            lastAbandonReason = "store_not_ready"
            return .cancelled
        }
        lastError = nil
        await syncIdentity()
        do {
            let result: PurchaseResultData
            if let package {
                result = try await Purchases.shared.purchase(package: package)
            } else {
                result = try await Purchases.shared.purchase(product: product)
            }
            if result.userCancelled {
                lastAbandonReason = "user_cancelled"
                return .cancelled
            }
            apply(result.customerInfo)
            if isSubscribed { return .success }
            // Paid, entitlement not visible yet: re-read before telling the user to wait.
            for attempt in 0..<3 {
                try? await Task.sleep(for: .seconds(1 << attempt))
                await refreshEntitlements()
                if isSubscribed { return .success }
            }
            lastError = String(localized: "Purchase received. Your plan will unlock shortly — reopen the app or tap Restore.")
            return .paidButNotActive
        } catch {
            #if DEBUG
            print("[StoreManager] purchase failed:", error)
            #endif
            lastError = Self.purchaseFailed
            lastAbandonReason = Self.abandonReason(error)
            return .cancelled
        }
    }

    func restore() async {
        guard isReady else { lastError = Self.storeUnavailable; return }
        await syncIdentity()
        if let info = try? await Purchases.shared.restorePurchases() {
            apply(info)
        }
    }

    /// Points RevenueCat at the current Supabase user. `configure` runs once per process, but Delete
    /// account and Sign out call `Purchases.logOut()` (RevenueCat falls back to an `$RCAnonymousID`)
    /// and onboarding then creates a NEW Supabase user. Without this, a purchase made in that state
    /// landed on the anonymous id, and the server, which asks RevenueCat by the Supabase id, kept
    /// answering 402 to a paying user. `logIn` from an anonymous id also
    /// moves that id's purchases to the user, so an account already caught in that state heals.
    func syncIdentity() async {
        guard isReady, AppConfig.isSupabaseConfigured,
              let uid = try? await SupabaseAuth.shared.userID(),
              Self.needsLogIn(current: Purchases.shared.appUserID, supabaseUserID: uid) else { return }
        if let result = try? await Purchases.shared.logIn(uid) { apply(result.customerInfo) }
    }

    /// RevenueCat must follow the Supabase user whenever there is one.
    nonisolated static func needsLogIn(current: String, supabaseUserID: String) -> Bool {
        !supabaseUserID.isEmpty && current != supabaseUserID
    }

    /// Shows StoreKit messages (billing issue, price increase) that were deferred while
    /// onboarding or a paywall was on screen. Never drops them.
    func showDeferredStoreMessages() async {
        guard isReady else { return }
        await Purchases.shared.showStoreMessages()
    }

    // MARK: - Entitlements

    private func refreshEntitlements() async {
        guard isReady else { return }
        if let info = try? await Purchases.shared.customerInfo() {
            apply(info)
        }
    }

    /// Live entitlement updates: renewals, expiries and billing recoveries arrive here without
    /// a relaunch, so the billing banner clears itself when Apple collects the payment.
    private func startCustomerInfoUpdates() {
        customerInfoUpdates?.cancel()
        customerInfoUpdates = Task { [weak self] in
            for await info in Purchases.shared.customerInfoStream {
                guard let self, !Task.isCancelled else { return }
                self.apply(info)
            }
        }
    }

    private func apply(_ info: CustomerInfo) {
        let ent = info.entitlements.all[AppConfig.entitlementID]
        let active = ent?.isActive == true
        let wasIssue = billingIssue != nil
        isSubscribed = active
        plan = Self.plan(forActiveProduct: active ? ent?.productIdentifier : nil)
        billingIssue = BillingIssue.evaluate(isActive: active, billingIssueDetectedAt: ent?.billingIssueDetectedAt,
                                             expirationDate: ent?.expirationDate)
        if wasIssue && billingIssue == nil && active {
            Tracker.log(custom: "billing_recovered", ["plan": plan.rawValue])
        }
    }

    nonisolated static func plan(forActiveProduct id: String?) -> Plan {
        guard let id, let product = AppSpec.products.first(where: { $0.id == id }) else { return .none }
        switch product.period.last {
        case "W": return .weekly
        case "M": return .monthly
        case "Y": return .yearly
        default: return .none
        }
    }

    /// Narrow bucket for analytics — a raw localized description cannot be grouped.
    private static func abandonReason(_ error: Error) -> String {
        guard let code = error as? ErrorCode else { return "store_error" }
        switch code {
        case .purchaseNotAllowedError: return "not_allowed"
        case .paymentPendingError: return "payment_pending"
        case .storeProblemError: return "store_problem"
        case .networkError, .offlineConnectionError: return "network"
        case .productNotAvailableForPurchaseError: return "product_unavailable"
        case .purchaseInvalidError: return "payment_invalid"
        case .ineligibleError: return "ineligible"
        default: return "store_error"
        }
    }

    // @if credits
    // MARK: - Credits (credits monetization only)

    /// Top-up consumable pack products (small/medium/large in order).
    var creditPackProducts: [StoreProduct] {
        AppConfig.creditPackIDs.compactMap { id in products.first { $0.productIdentifier == id } }
    }

    /// Forwards the server balance to CreditManager (wired by the App).
    var onBalance: ((CreditManager.Balance) -> Void)?

    /// Purchase a consumable credit pack; the server reconciles it from RevenueCat on `sync`.
    @discardableResult
    func purchaseCredits(_ product: StoreProduct) async -> Bool {
        guard isReady else { lastError = Self.storeUnavailable; return false }
        do {
            let result = try await Purchases.shared.purchase(product: product)
            if result.userCancelled { return false }
            await syncBalance()
            return true
        } catch {
            lastError = Self.purchaseFailed
            return false
        }
    }

    func syncBalance() async {
        guard let obj = try? await Proxy.post(AppConfig.aiFunction, body: ["action": "sync"]),
              let json = obj["balance"] as? [String: Any], let balance = CreditManager.Balance(json: json) else { return }
        onBalance?(balance)
    }
    // @endif
}
// @endif
// @if !revenuecat
/// StoreKit 2 subscriptions (the RevenueCat service is off): products, purchase, restore and the
/// entitlement come straight from StoreKit, and Apple verifies every transaction on device. The same
/// surface as the RevenueCat StoreManager, so the paywalls and settings do not change.
@MainActor
final class StoreManager: ObservableObject {
    enum Plan: String { case none, weekly, monthly, yearly }

    enum PurchaseOutcome: Equatable {
        case cancelled
        case success
        /// Paid, but the entitlement is not visible yet (tell the user; separate analytics event).
        case paidButNotActive
    }

    @Published private(set) var products: [Product] = []
    @Published private(set) var isSubscribed = false
    @Published private(set) var plan: Plan = .none
    @Published private(set) var billingIssue: BillingIssue?
    @Published var lastError: String?
    private(set) var lastAbandonReason = "user_cancelled"

    private var loading: Task<Void, Never>?
    private var transactionUpdates: Task<Void, Never>?

    /// StoreKit needs no configuration: ready once the products answered.
    var isReady: Bool { !products.isEmpty }

    static var storeUnavailable: String {
        String(localized: "The store isn't available right now. Please check your connection and try again.")
    }
    private static var purchaseFailed: String {
        String(localized: "The purchase didn't go through. Please try again.")
    }

    /// No account system to follow: identity calls are no-ops with StoreKit alone.
    func configure(appUserID: String) { startTransactionUpdates() }
    func logIn(appUserID: String) async {}
    func logOut() async {}
    func syncIdentity() async {}
    /// StoreKit shows its own messages (billing issue, price increase); nothing is deferred.
    func showDeferredStoreMessages() async {}

    func load() async {
        if let loading { return await loading.value }
        let task = Task { await self.performLoad() }
        loading = task
        await task.value
        loading = nil
    }

    private func performLoad() async {
        startTransactionUpdates()
        guard !AppConfig.isAutomatedTestRun else { return }
        await refreshEntitlements()
        for attempt in 0..<3 {
            products = (try? await Product.products(for: AppConfig.allProductIDs)) ?? []
            if !products.isEmpty { break }
            if attempt < 2 { try? await Task.sleep(for: .seconds(2 << attempt)) }
        }
        if products.isEmpty { Tracker.log(.storeProductsEmpty, ["attempts": "3"]) }
    }

    nonisolated static func offeringID(for source: PaywallSource) -> String {
        source.isOffer ? "offer" : "default"
    }

    /// No RevenueCat packages: a purchase goes straight to the product.
    func package(for productID: String, source: PaywallSource) -> Product? { nil }

    func product(_ id: String) -> Product? {
        products.first { $0.id == id }
    }

    /// Buy a subscription. `.success` only once the entitlement is active.
    @discardableResult
    func purchase(_ product: Product, package: Product? = nil) async -> PurchaseOutcome {
        lastError = nil
        do {
            switch try await product.purchase() {
            case .success(.verified(let transaction)):
                await transaction.finish()
                await refreshEntitlements()
                if isSubscribed { return .success }
                lastError = String(localized: "Purchase received. Your plan will unlock shortly — reopen the app or tap Restore.")
                return .paidButNotActive
            case .success(.unverified):
                lastError = Self.purchaseFailed
                lastAbandonReason = "unverified"
            case .pending:
                lastAbandonReason = "payment_pending"
            case .userCancelled:
                lastAbandonReason = "user_cancelled"
            @unknown default:
                lastAbandonReason = "store_error"
            }
        } catch {
            lastError = Self.purchaseFailed
            lastAbandonReason = "store_error"
        }
        return .cancelled
    }

    func restore() async {
        try? await AppStore.sync()
        await refreshEntitlements()
    }

    /// Unused without RevenueCat; kept so the shared unit tests compile.
    nonisolated static func needsLogIn(current: String, supabaseUserID: String) -> Bool {
        !supabaseUserID.isEmpty && current != supabaseUserID
    }

    private func refreshEntitlements() async {
        var active: StoreKit.Transaction?
        for await result in StoreKit.Transaction.currentEntitlements {
            if case .verified(let tx) = result, tx.revocationDate == nil,
               AppSpec.products.contains(where: { $0.id == tx.productID }) {
                active = tx
            }
        }
        isSubscribed = active != nil
        plan = Self.plan(forActiveProduct: active?.productID)
        if let group = products.first?.subscription?.subscriptionGroupID {
            billingIssue = await BillingIssue.currentFromStoreKit(groupID: group)
        }
    }

    /// Renewals, refunds and purchases made outside the app arrive here without a relaunch.
    private func startTransactionUpdates() {
        guard transactionUpdates == nil else { return }
        transactionUpdates = Task { [weak self] in
            for await result in StoreKit.Transaction.updates {
                if case .verified(let tx) = result { await tx.finish() }
                await self?.refreshEntitlements()
            }
        }
    }

    nonisolated static func plan(forActiveProduct id: String?) -> Plan {
        guard let id, let product = AppSpec.products.first(where: { $0.id == id }) else { return .none }
        switch product.period.last {
        case "W": return .weekly
        case "M": return .monthly
        case "Y": return .yearly
        default: return .none
        }
    }
}
// @endif

/// Billing problem on the subscription, from RevenueCat's entitlement or StoreKit's renewal state.
enum BillingIssue: Equatable {
    /// Payment failed but Apple's grace period keeps the entitlement active until `expires`.
    case gracePeriod(expires: Date?)
    /// Payment failed and the entitlement lapsed; Apple keeps retrying (up to 60 days).
    case billingRetry

    /// Apple retries a failed renewal for up to 60 days; after that the banner stops nagging.
    static let retryWindow: TimeInterval = 60 * 24 * 3600

    /// RevenueCat entitlement → banner state.
    static func evaluate(isActive: Bool, billingIssueDetectedAt: Date?, expirationDate: Date?, now: Date = Date()) -> BillingIssue? {
        guard billingIssueDetectedAt != nil else { return nil }
        if isActive { return .gracePeriod(expires: expirationDate) }
        if let expirationDate, now.timeIntervalSince(expirationDate) > retryWindow { return nil }
        return .billingRetry
    }

    /// StoreKit 2 renewal state → banner state (local StoreKit testing, SKTestSession tests).
    static func evaluate(renewalState: Product.SubscriptionInfo.RenewalState, expirationDate: Date?) -> BillingIssue? {
        switch renewalState {
        case .inGracePeriod: return .gracePeriod(expires: expirationDate)
        case .inBillingRetryPeriod: return .billingRetry
        default: return nil
        }
    }

    /// Reads StoreKit 2 directly (used by tests and while RevenueCat is not configured).
    static func currentFromStoreKit(groupID: String) async -> BillingIssue? {
        guard let statuses = try? await Product.SubscriptionInfo.status(for: groupID) else { return nil }
        for status in statuses {
            var expiration: Date?
            if case .verified(let tx) = status.transaction { expiration = tx.expirationDate }
            if let issue = evaluate(renewalState: status.state, expirationDate: expiration) { return issue }
        }
        return nil
    }
}
