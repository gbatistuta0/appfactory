import Foundation
// @if revenuecat
import RevenueCat
// @endif
import StoreKit

/// One subscription as the paywall renders it. Built from a RevenueCat `StoreProduct` (the real
/// path), from StoreKit 2 metadata (DEBUG display shim while the RC key is a placeholder), or from
/// the spec's USD prices (demo cards while the store has not answered).
struct PlanOffer: Equatable {
    enum Period: Equatable { case week, month, year }
    enum Origin: Equatable { case revenueCat, localStoreKit, demo }

    let productID: String
    let price: Decimal
    let currencyCode: String
    let locale: Locale
    let period: Period
    /// Length of the free-trial introductory offer in days, if the product has one.
    let freeTrialDays: Int?
    let origin: Origin

    func format(_ amount: Decimal) -> String {
        amount.formatted(.currency(code: currencyCode).locale(locale))
    }

    var displayPrice: String { format(price) }

    /// "$49.99 / year" in the app language.
    var perPeriodText: String {
        switch period {
        case .year: return String(localized: "\(displayPrice) / year")
        case .month: return String(localized: "\(displayPrice) / month")
        case .week: return String(localized: "\(displayPrice) / week")
        }
    }

    /// Price per week, rounded to cents (yearly / 52).
    var pricePerWeek: Decimal {
        switch period {
        case .week: return price
        case .month: return Self.round(price * 12 / 52)
        case .year: return Self.round(price / 52)
        }
    }

    /// Price per month, rounded to cents (yearly / 12).
    var pricePerMonth: Decimal {
        switch period {
        case .week: return Self.round(price * 52 / 12)
        case .month: return price
        case .year: return Self.round(price / 12)
        }
    }

    /// Price for a full year at this plan's rate.
    var pricePerYear: Decimal {
        switch period {
        case .week: return price * 52
        case .month: return price * 12
        case .year: return price
        }
    }

    static func round(_ value: Decimal) -> Decimal {
        var v = value, out = Decimal()
        NSDecimalRound(&out, &v, 2, .plain)
        return out
    }
}

enum PaywallPricing {
    /// "SAVE 87%": how much cheaper a year of `longer` is than a year of `shorter`.
    static func savingsPercent(yearly: PlanOffer, weekly: PlanOffer) -> Int {
        percentOff(price: yearly.pricePerYear, regular: weekly.pricePerYear)
    }

    /// "40% OFF": discount of the offer product against the regular product.
    static func discountPercent(offer: PlanOffer, regular: PlanOffer) -> Int {
        percentOff(price: offer.pricePerYear, regular: regular.pricePerYear)
    }

    /// Rounded DOWN: a discount badge must never overstate the saving.
    static func percentOff(price: Decimal, regular: Decimal) -> Int {
        guard regular > 0, price < regular else { return 0 }
        var ratio = (1 - price / regular) * 100, floored = Decimal()
        NSDecimalRound(&floored, &ratio, 0, .down)
        return NSDecimalNumber(decimal: floored).intValue
    }
}

// MARK: - Sources

extension PlanOffer {
    // @if revenuecat
    init?(storeProduct p: StoreProduct) {
        guard let period = Self.period(p.subscriptionPeriod) else { return nil }
        var trial: Int?
        if let intro = p.introductoryDiscount, intro.paymentMode == .freeTrial {
            trial = Self.days(intro.subscriptionPeriod)
        }
        self.init(productID: p.productIdentifier, price: p.price, currencyCode: p.currencyCode ?? "USD",
                  locale: p.priceFormatter?.locale ?? .current, period: period,
                  freeTrialDays: trial, origin: .revenueCat)
    }
    // @endif
    // @if !revenuecat
    init?(storeProduct p: Product) { self.init(storeKit: p) }
    // @endif

    init?(storeKit p: Product) {
        guard let sub = p.subscription, let period = Self.period(sub.subscriptionPeriod) else { return nil }
        var trial: Int?
        if let intro = sub.introductoryOffer, intro.paymentMode == .freeTrial {
            trial = Self.days(value: intro.period.value, unit: intro.period.unit)
        }
        self.init(productID: p.id, price: p.price, currencyCode: p.priceFormatStyle.currencyCode,
                  locale: p.priceFormatStyle.locale, period: period, freeTrialDays: trial, origin: .localStoreKit)
    }

    /// Demo card straight from the spec (USD, en_US) — equal to Configuration.storekit.
    static func demo(_ product: AppSpec.Product) -> PlanOffer {
        PlanOffer(productID: product.id, price: product.usd, currencyCode: "USD", locale: Locale(identifier: "en_US"),
                  period: period(iso: product.period) ?? .year, freeTrialDays: product.introDays, origin: .demo)
    }

    static func demo(_ id: String) -> PlanOffer? {
        AppSpec.products.first { $0.id == id }.map(demo)
    }

    /// ISO 8601 subscription period ("P1W", "P1M", "P1Y", "P7D") → paywall period.
    static func period(iso: String) -> Period? {
        switch iso.last {
        case "W": return .week
        case "M": return iso == "P12M" ? .year : .month
        case "Y": return .year
        case "D": return iso == "P7D" ? .week : nil
        default: return nil
        }
    }

    // @if revenuecat
    private static func period(_ p: RevenueCat.SubscriptionPeriod?) -> Period? {
        guard let p else { return nil }
        switch p.unit {
        case .week: return .week
        case .month: return p.value == 12 ? .year : .month
        case .year: return .year
        case .day: return p.value == 7 ? .week : nil
        @unknown default: return nil
        }
    }
    // @endif

    private static func period(_ p: Product.SubscriptionPeriod) -> Period? {
        switch p.unit {
        case .week: return .week
        case .month: return p.value == 12 ? .year : .month
        case .year: return .year
        case .day: return p.value == 7 ? .week : nil
        @unknown default: return nil
        }
    }

    // @if revenuecat
    private static func days(_ p: RevenueCat.SubscriptionPeriod) -> Int {
        switch p.unit {
        case .day: return p.value
        case .week: return p.value * 7
        case .month: return p.value * 30
        case .year: return p.value * 365
        @unknown default: return p.value
        }
    }
    // @endif

    private static func days(value: Int, unit: Product.SubscriptionPeriod.Unit) -> Int {
        switch unit {
        case .day: return value
        case .week: return value * 7
        case .month: return value * 30
        case .year: return value * 365
        @unknown default: return value
        }
    }
}

/// Resolves the paywall products and the user's trial eligibility.
@MainActor
final class PaywallCatalog: ObservableObject {
    /// Hard paywall plans ("default" offering), shortest period first (weekly, then yearly).
    @Published private(set) var hard: [PlanOffer]
    /// The one-time offer product ("offer" offering).
    @Published private(set) var offer: PlanOffer?
    /// Intro-offer (free trial) eligibility. All plans share one subscription group, so Apple
    /// grants one intro offer per user; checking one product answers for all. False until confirmed.
    @Published private(set) var trialEligible = false
    @Published private(set) var loaded = false

    init() {
        hard = AppConfig.hardProductIDs.compactMap(PlanOffer.demo).sorted(by: Self.shorterFirst)
        offer = AppConfig.offerProductIDs.first.flatMap(PlanOffer.demo)
    }

    var origin: PlanOffer.Origin { hard.first?.origin ?? .demo }
    /// The plan with the longest period (the highlighted one).
    var bestValue: PlanOffer? { hard.last }
    /// The plan with the shortest period (the SAVE x% baseline).
    var shortest: PlanOffer? { hard.first }

    /// Trial copy is shown only when the product really has a trial AND the user is eligible.
    func showsTrial(_ offer: PlanOffer) -> Bool { trialEligible && offer.freeTrialDays != nil }

    /// The full-price plan the offer is compared with (same period).
    var offerRegular: PlanOffer? {
        guard let offer, let id = AppConfig.regularProductID(forOffer: offer.productID) else { return nil }
        return hard.first { $0.productID == id }
    }

    /// "SAVE x%" of the best-value plan against the shortest plan, floored; nil when there is none.
    var savingsPercent: Int? {
        guard let best = bestValue, let base = shortest, best != base else { return nil }
        let pct = PaywallPricing.savingsPercent(yearly: best, weekly: base)
        return pct > 0 ? pct : nil
    }

    func load(store: StoreManager) async {
        await store.load()
        if store.isReady {
            apply(store.products.compactMap(PlanOffer.init(storeProduct:)))
            // @if revenuecat
            // Prefer what the offerings actually sell (same ids, placement-attributed packages).
            // @if offer_paywall
            for source in [PaywallSource.onboarding, .offerAfterOnboarding] {
            // @endif
            // @if !offer_paywall
            for source in [PaywallSource.onboarding] {
            // @endif
                if let packages = store.offering(for: source)?.availablePackages {
                    apply(packages.compactMap { PlanOffer(storeProduct: $0.storeProduct) })
                }
            }
            trialEligible = await revenueCatTrialEligibility()
            // @endif
            // @if !revenuecat
            if let trialID = trialProductID, let sub = store.product(trialID)?.subscription {
                trialEligible = await sub.isEligibleForIntroOffer
            }
            // @endif
        } else {
            #if DEBUG
            // Display-only shim while RevenueCat is unavailable (placeholder key): read prices and
            // the intro offer through StoreKit 2 (the scheme's Configuration.storekit when run from
            // Xcode). No purchase path here. Automated test runs stay on the demo prices.
            if !AppConfig.isAutomatedTestRun, let products = try? await Product.products(for: AppConfig.allProductIDs) {
                apply(products.compactMap(PlanOffer.init(storeKit:)))
                if let trialID = trialProductID,
                   let sub = products.first(where: { $0.id == trialID })?.subscription {
                    trialEligible = await sub.isEligibleForIntroOffer
                }
            }
            #endif
        }
        if let forced = AppConfig.trialEligibilityOverride { trialEligible = forced }
        loaded = true
    }

    /// First hard-paywall product that declares a trial in the spec.
    private var trialProductID: String? {
        AppSpec.products.first { $0.offering == "default" && $0.introDays != nil }?.id
    }

    private func apply(_ offers: [PlanOffer]) {
        for o in offers {
            if let i = hard.firstIndex(where: { $0.productID == o.productID }) {
                hard[i] = o
            } else if o.productID == offer?.productID {
                offer = o
            }
        }
    }

    // @if revenuecat
    private func revenueCatTrialEligibility() async -> Bool {
        guard Purchases.isConfigured, let id = trialProductID else { return false }
        let result = await Purchases.shared.checkTrialOrIntroDiscountEligibility(productIdentifiers: [id])
        return result[id]?.status == .eligible
    }
    // @endif

    nonisolated static func shorterFirst(_ a: PlanOffer, _ b: PlanOffer) -> Bool {
        rank(a.period) < rank(b.period)
    }

    nonisolated private static func rank(_ p: PlanOffer.Period) -> Int {
        switch p {
        case .week: return 0
        case .month: return 1
        case .year: return 2
        }
    }
}
