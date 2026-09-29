import SwiftUI

/// Hard paywall, personalized from the user's own onboarding answers. Close appears after 2.5 s.
/// Trial copy only when RevenueCat says the user is eligible; "SAVE x%" is floored; Restore,
/// Terms and Privacy are always on screen.
struct HardPaywallView: View {
    let source: PaywallSource
    let personalization: PaywallPersonalization
    let onPurchased: () -> Void
    let onClose: () -> Void

    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var catalog: PaywallCatalog
    @State private var selectedID: String?
    @State private var busy = false

    /// Benefits list. APP-SPECIFIC EXTENSION POINT: the features stage writes the app's own
    /// (truthful: usage has fair daily caps, so never promise more than the caps allow).
    static let benefits: [LocalizedStringResource] = [
        "Personalized results in seconds",
        "Everything built from your answers",
        "New insights every day",
        "Cancel anytime",
    ]

    private var selected: PlanOffer? {
        catalog.hard.first { $0.productID == selectedID } ?? catalog.bestValue
    }
    private var trial: Bool { selected.map(catalog.showsTrial) ?? false }
    private var purchaser: PaywallPurchaser { PaywallPurchaser(store: store, source: source) }

    var body: some View {
        ZStack(alignment: .top) {
            DS.Palette.background.ignoresSafeArea()
            LinearGradient(colors: [DS.Palette.primaryContainer.opacity(0.7), DS.Palette.background.opacity(0)],
                           startPoint: .top, endPoint: .bottom)
                .frame(height: 320)
                .ignoresSafeArea(edges: .top)

            VStack(spacing: 0) {
                // Close sits in its own row above the ScrollView: overlaid on the scroll view it
                // did not receive taps (found by OnboardingFlowUITests on iOS 26).
                HStack {
                    Spacer()
                    PaywallCloseButton(delay: 2.5) {
                        Tracker.log(.paywallDismiss, ["from": source.eventValue])
                        onClose()
                    }
                }
                .padding(.top, DS.Spacing.sm)
                .padding(.horizontal, 20)
                ScrollView {
                    VStack(spacing: 20) {
                        header
                        // @if quiz
                        highlightsCard
                        // @endif
                        benefitsList
                    }
                    .padding(.top, 14)
                    .padding(.horizontal, DS.Spacing.lg)
                }
                .scrollBounceBehavior(.basedOnSize)
                .scrollIndicators(.hidden)

                purchaseBlock
            }

        }
        .onAppear {
            Tracker.screen("paywall_\(source.eventValue)")
            Tracker.log(.paywallView, ["from": source.eventValue, "variant": "hard",
                                        "trial": trial ? "1" : "0", "store_ready": store.isReady ? "1" : "0"])
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(spacing: 8) {
            AppLogoMark(size: 72)
                .shadow(color: DS.Palette.primary.opacity(0.3), radius: 16, y: 8)
            Text(verbatim: personalization.headline)
                .font(DS.Typography.largeTitle)
                .foregroundStyle(DS.Palette.foreground)
                .multilineTextAlignment(.center)
                .lineLimit(3)
                .minimumScaleFactor(0.75)
                .padding(.horizontal, 22)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("paywall_title")
        }
        .frame(maxWidth: .infinity)
    }

    // @if quiz
    private var highlightsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(verbatim: personalization.proofLine)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(DS.Palette.foreground)
            ForEach(personalization.highlights, id: \.self) { h in
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.seal.fill").foregroundStyle(DS.Palette.primary)
                    Text(verbatim: h)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(DS.Palette.foreground)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(DS.Spacing.md)
        .background(RoundedRectangle(cornerRadius: DS.Radius.xl).fill(DS.Palette.surface))
        .softShadow()
        .accessibilityIdentifier("paywall_highlights")
    }
    // @endif

    private var benefitsList: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(Self.benefits.enumerated()), id: \.offset) { _, b in
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(DS.Palette.primary)
                    Text(b)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(DS.Palette.foreground)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 6)
    }

    // MARK: Purchase block

    private var purchaseBlock: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                ForEach(catalog.hard, id: \.productID) { offer in
                    PlanTile(name: Self.planName(offer.period), offer: offer,
                             selected: selected?.productID == offer.productID,
                             badge: offer.productID == catalog.bestValue?.productID ? savingsBadge : nil,
                             sub: tileSub(offer), subAccent: catalog.showsTrial(offer) || offer.period == .year,
                             identifier: "plan_\(Self.planKey(offer.period))") { select(offer) }
                }
            }
            .padding(.top, 14)

            if let error = store.lastError {
                PurchaseErrorNote(message: error)
            } else if let selected {
                Text(verbatim: finePrint(selected))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(DS.Palette.secondaryText)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("paywall_fine_print")
            }

            Button(action: buy) {
                if busy { ProgressView().tint(DS.Palette.onAccent) } else { Text(trial ? "Start my free trial" : "Continue") }
            }
            .buttonStyle(.primary)
            .disabled(busy || selected == nil)
            .accessibilityIdentifier("paywall_cta")
            #if DEBUG
            // Where the prices came from (revenueCat / localStoreKit / demo), for UI tests.
            .accessibilityValue(Text(verbatim: "\(catalog.origin)"))
            #endif

            LegalLinks(onRestore: restore)
        }
        .padding(.top, 8)
        .padding(.horizontal, DS.Spacing.lg)
        .padding(.bottom, DS.Spacing.sm)
    }

    /// "SAVE 87%" on the best-value tile — floored, never overstated.
    private var savingsBadge: String? {
        catalog.savingsPercent.map { String(localized: "SAVE \($0)%") }
    }

    static func planName(_ p: PlanOffer.Period) -> LocalizedStringResource {
        switch p {
        case .week: return "Weekly"
        case .month: return "Monthly"
        case .year: return "Yearly"
        }
    }

    static func planKey(_ p: PlanOffer.Period) -> String {
        switch p {
        case .week: return "weekly"
        case .month: return "monthly"
        case .year: return "yearly"
        }
    }

    private func tileSub(_ offer: PlanOffer) -> String {
        if catalog.showsTrial(offer), let days = offer.freeTrialDays {
            return String(localized: "\(days) days free")
        }
        switch offer.period {
        case .year, .month: return String(localized: "\(offer.format(offer.pricePerWeek)) / week")
        case .week: return String(localized: "Billed weekly")
        }
    }

    private func finePrint(_ offer: PlanOffer) -> String {
        if catalog.showsTrial(offer), let days = offer.freeTrialDays {
            return String(localized: "\(days) days free, then \(offer.perPeriodText) · Cancel anytime")
        }
        return String(localized: "Billed \(offer.perPeriodText) · Cancel anytime")
    }

    private func select(_ offer: PlanOffer) {
        selectedID = offer.productID
        store.lastError = nil
        Tracker.log(.paywallPlanSelect, ["plan": Self.planKey(offer.period), "from": source.eventValue])
    }

    private func buy() {
        guard let offer = selected else { return }
        busy = true
        let withTrial = trial
        Task {
            let ok = await purchaser.buy(offer, trial: withTrial)
            busy = false
            if ok { onPurchased() }
        }
    }

    private func restore() {
        busy = true
        Task {
            let ok = await purchaser.restore()
            busy = false
            if ok { onPurchased() }
        }
    }
}
