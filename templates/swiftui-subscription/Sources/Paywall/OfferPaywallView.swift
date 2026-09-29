import SwiftUI

/// One-time offer on the separate discounted product (RevenueCat offering "offer"; never a
/// promotional offer). Price anchor from the spec (`offer_anchor`: the offer's monthly price must
/// stay below that everyday item in every storefront). Close appears after 2 s; "No thanks".
struct OfferPaywallView: View {
    let source: PaywallSource
    let onPurchased: () -> Void
    let onClose: () -> Void

    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var catalog: PaywallCatalog
    @AppStorage(OnboardingView.offerSeenKey) private var offerSeen = false
    @State private var busy = false

    private var purchaser: PaywallPurchaser { PaywallPurchaser(store: store, source: source) }

    /// Emoji for the anchor item (spec `offer_anchor.item`).
    static func anchorSymbol(_ item: String) -> String {
        switch item {
        case "burger": return "🍔"
        case "coffee": return "☕️"
        case "pizza": return "🍕"
        case "movie", "cinema": return "🎬"
        case "sandwich": return "🥪"
        default: return "🛍️"
        }
    }

    var body: some View {
        ZStack(alignment: .top) {
            DS.Palette.background.ignoresSafeArea()
            VStack(spacing: 0) {
                // Badge + close in their own row above the ScrollView (see HardPaywallView).
                HStack {
                    Text("ONE-TIME OFFER")
                        .font(.system(size: 12, weight: .heavy))
                        .tracking(0.7)
                        .foregroundStyle(DS.Palette.background)
                        .padding(.vertical, 6)
                        .padding(.horizontal, 12)
                        .background(Capsule().fill(DS.Palette.foreground))
                    Spacer()
                    PaywallCloseButton(delay: 2) { dismiss() }
                }
                .padding(.top, DS.Spacing.sm)
                .padding(.horizontal, 20)
                ScrollView {
                    VStack(spacing: 22) {
                        anchorRow
                        VStack(spacing: 8) {
                            Text(LocalizedStringKey(AppSpec.offerAnchorKey))
                                .font(DS.Typography.largeTitle)
                                .foregroundStyle(DS.Palette.foreground)
                                .multilineTextAlignment(.center)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("offer_title")
                            Text("A one-time price, only right now.")
                                .font(DS.Typography.body)
                                .foregroundStyle(DS.Palette.secondaryText)
                                .multilineTextAlignment(.center)
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(Array(HardPaywallView.benefits.enumerated()), id: \.offset) { _, b in
                                HStack(spacing: 10) {
                                    Image(systemName: "checkmark.circle.fill").foregroundStyle(DS.Palette.primary)
                                    Text(b)
                                        .font(.system(size: 15, weight: .semibold))
                                        .foregroundStyle(DS.Palette.foreground)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 18)
                    }
                    .padding(.top, 18)
                    .padding(.horizontal, DS.Spacing.lg)
                }
                .scrollBounceBehavior(.basedOnSize)
                .scrollIndicators(.hidden)

                bottom
            }

        }
        .onAppear {
            offerSeen = true
            Tracker.screen("paywall_\(source.eventValue)")
            Tracker.log(.paywallView, ["from": source.eventValue, "variant": "offer", "store_ready": store.isReady ? "1" : "0"])
        }
    }

    private var anchorRow: some View {
        HStack(spacing: 18) {
            AppLogoMark(size: 96)
                .shadow(color: DS.Palette.primary.opacity(0.25), radius: 15, y: 12)
            Text(verbatim: "<")
                .font(.system(size: 44, weight: .heavy, design: .rounded))
                .foregroundStyle(DS.Palette.primary)
                .accessibilityHidden(true)
            Text(verbatim: Self.anchorSymbol(AppSpec.offerAnchorItem))
                .font(.system(size: 76))
                .accessibilityHidden(true)
        }
    }

    @ViewBuilder private var bottom: some View {
        if let offer = catalog.offer {
            let regular = catalog.offerRegular
            let discount = regular.map { PaywallPricing.discountPercent(offer: offer, regular: $0) } ?? 0
            VStack(spacing: 12) {
                HStack(spacing: 14) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(HardPaywallView.planName(offer.period))
                            .font(.system(size: 16, weight: .heavy))
                            .foregroundStyle(DS.Palette.foreground)
                        HStack(spacing: 6) {
                            if let regular {
                                Text(verbatim: regular.displayPrice).strikethrough()
                            }
                            Text(verbatim: offer.displayPrice)
                        }
                        .font(.system(size: 14))
                        .foregroundStyle(DS.Palette.secondaryText)
                        .accessibilityIdentifier("offer_price")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .trailing, spacing: 0) {
                        Text(verbatim: offer.format(offer.pricePerMonth))
                            .font(.system(size: 22, weight: .heavy, design: .rounded))
                            .foregroundStyle(DS.Palette.foreground)
                            .accessibilityIdentifier("offer_per_month")
                        Text("per month")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(DS.Palette.secondaryText)
                    }
                }
                .padding(.vertical, 16)
                .padding(.horizontal, 18)
                .background(RoundedRectangle(cornerRadius: DS.Radius.xl, style: .continuous).fill(DS.Palette.primaryContainer.opacity(0.35)))
                .overlay(RoundedRectangle(cornerRadius: DS.Radius.xl, style: .continuous).strokeBorder(DS.Palette.primary, lineWidth: 2.5))
                .overlay(alignment: .topTrailing) {
                    if discount > 0 {
                        Text(verbatim: String(localized: "\(discount)% OFF"))
                            .font(.system(size: 12, weight: .heavy))
                            .foregroundStyle(DS.Palette.onAccent)
                            .padding(.vertical, 4)
                            .padding(.horizontal, 10)
                            .background(Capsule().fill(DS.Palette.primary))
                            .fixedSize()
                            .offset(x: -16, y: -12)
                            .accessibilityIdentifier("offer_discount")
                    }
                }

                Button { buy(offer) } label: {
                    if busy { ProgressView().tint(DS.Palette.onAccent) } else { Text("Claim my offer") }
                }
                .buttonStyle(.primary)
                .disabled(busy)
                .accessibilityIdentifier("offer_cta")

                if let error = store.lastError {
                    PurchaseErrorNote(message: error)
                } else {
                    Text(verbatim: String(localized: "Billed \(offer.perPeriodText) · Cancel anytime"))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(DS.Palette.secondaryText)
                        .multilineTextAlignment(.center)
                }

                Button { dismiss() } label: {
                    Text("No thanks")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(DS.Palette.secondaryText)
                        .frame(maxWidth: .infinity, minHeight: 36)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("offer_no_thanks")

                LegalLinks(onRestore: restore)
            }
            .padding(.top, 12)
            .padding(.horizontal, DS.Spacing.lg)
            .padding(.bottom, DS.Spacing.sm)
        }
    }

    private func dismiss() {
        Tracker.log(.paywallDismiss, ["from": source.eventValue])
        onClose()
    }

    private func buy(_ offer: PlanOffer) {
        busy = true
        Task {
            let ok = await purchaser.buy(offer, trial: false)
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
