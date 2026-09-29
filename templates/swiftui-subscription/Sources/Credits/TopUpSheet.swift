import RevenueCat
import SwiftUI

/// Top-Up sheet — upsell when a SUBSCRIBER runs out of credits (consumable credit packs).
/// NO "Subscribe" pitch (already a subscriber). A system sheet: the close button is a system
/// toolbar item (glass on iOS 26) and the surface is opaque (`sheetSurface`).
/// Header "You're out of credits" + (if any) "Your credits refill {date}" + 3 pack cards
/// (10 / 30 BEST VALUE / 60), each showing its OWN localizedPriceString. Purchase →
/// store.purchaseCredits → if sync confirms, dismiss + resume generation.
struct TopUpSheet: View {
    /// Pack purchased + redeem confirmed → the caller resumes generation.
    var onPurchased: () -> Void
    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var credits: CreditManager
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var purchasingID: String?

    /// "Your credits refill {relative time}" — hidden if nextReset is absent.
    private var refillText: String? {
        guard let reset = credits.nextReset, reset > Date() else { return nil }
        let rel = RelativeDateTimeFormatter()
        rel.unitsStyle = .full
        return rel.localizedString(for: reset, relativeTo: Date())
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView(showsIndicators: false) {
                    VStack(spacing: DS.Spacing.md) {
                        // Hero: app logo + glow ring.
                        ZStack {
                            Circle().fill(DS.Palette.primaryContainer.opacity(0.20))
                                .frame(width: 130, height: 130).blur(radius: 24)
                            AppLogoMark(size: 88)
                                .shadow(color: DS.Palette.primary.opacity(0.5), radius: 20)
                        }
                        .padding(.top, DS.Spacing.xs)

                        Text("You're out of credits")
                            .font(.system(size: 28, weight: .heavy, design: .rounded))
                            .foregroundStyle(DS.Palette.foreground)
                            .multilineTextAlignment(.center)
                            .accessibilityIdentifier("topup_title")

                        Text("Top up now to keep creating.")
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.secondaryText)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, DS.Spacing.lg)

                        // Refill info (if any) — periodic credit comes back in {time}.
                        if let refillText {
                            HStack(spacing: 6) {
                                Image(systemName: "clock.arrow.circlepath").font(.system(size: 13, weight: .bold))
                                Text("Your credits refill \(refillText)")
                                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                            }
                            .foregroundStyle(DS.Palette.primary)
                            .padding(.horizontal, 14).padding(.vertical, 7)
                            .background(DS.Palette.primaryContainer.opacity(0.18), in: Capsule())
                        }
                    }
                    .padding(.horizontal, DS.Spacing.lg)
                    .padding(.bottom, DS.Spacing.md)
                }

                // Pinned: (for weekly subscribers) upgrade to yearly + pack cards + legal.
                VStack(spacing: DS.Spacing.md) {
                    // Weekly subscriber → upgrade to yearly (more credits/month). RC manages the StoreKit upgrade;
                    // on success plan becomes .yearly → sync brings the new credit → sheet closes.
                    if store.plan == .weekly,
                       let yearly = store.products.first(where: { $0.productIdentifier == AppConfig.yearlyProductID }) {
                        upgradeCard(yearly)
                    }

                    if store.creditPackProducts.isEmpty {
                        // If products didn't load (no StoreKit config in the sim) fixed cards — the sheet is never empty.
                        HStack(spacing: DS.Spacing.md) {
                            demoCard(credits: 10, price: "$4.99", best: false)
                            demoCard(credits: 30, price: "$9.99", best: true)
                            demoCard(credits: 60, price: "$17.99", best: false)
                        }
                    } else {
                        HStack(spacing: DS.Spacing.md) {
                            ForEach(store.creditPackProducts, id: \.productIdentifier) { product in
                                packCard(product)
                            }
                        }
                    }

                    // Mandatory legal row (Apple): Restore · Terms of Use · Privacy Policy.
                    HStack(spacing: DS.Spacing.md) {
                        Button("Restore") { Task { await store.restore() } }
                        Text("·").foregroundStyle(DS.Palette.secondaryText.opacity(0.5))
                        Button("Terms of Use") { if let u = URL(string: AppConfig.termsURL) { openURL(u) } }
                        Text("·").foregroundStyle(DS.Palette.secondaryText.opacity(0.5))
                        Button("Privacy Policy") { if let u = URL(string: AppConfig.privacyURL) { openURL(u) } }
                    }
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(DS.Palette.secondaryText)

                    Text("Credit packs are a one-time purchase. They never expire.")
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DS.Palette.secondaryText.opacity(0.8))
                        .multilineTextAlignment(.center)
                }
                .padding(.horizontal, DS.Spacing.lg)
                .padding(.top, DS.Spacing.md)
                .padding(.bottom, DS.Spacing.lg)
            }
            .background(DS.Palette.background.ignoresSafeArea())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { closeButton }
            }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .sheetSurface()
    }

    /// The system close button: `role: .close` (a glass X) on iOS 26, an xmark before.
    @ViewBuilder private var closeButton: some View {
        if #available(iOS 26, *) {
            Button(role: .close) { dismiss() }
                .accessibilityIdentifier("topup_close")
        } else {
            Button { dismiss() } label: { Image(systemName: "xmark") }
                .accessibilityLabel(Text("Close"))
                .accessibilityIdentifier("topup_close")
        }
    }

    /// Upgrade-to-yearly card (weekly subscribers only). Single tap → RC yearly purchase (upgrade).
    private func upgradeCard(_ yearly: StoreProduct) -> some View {
        let busy = purchasingID == AppConfig.yearlyProductID
        return Button {
            Task {
                purchasingID = AppConfig.yearlyProductID
                await store.purchase(yearly)            // RC StoreKit upgrade
                purchasingID = nil
                if store.plan == .yearly { onPurchased(); dismiss() }  // switched to yearly credit → close
            }
        } label: {
            HStack(spacing: DS.Spacing.md) {
                Image(systemName: "arrow.up.circle.fill").font(.system(size: 26))
                    .foregroundStyle(DS.Palette.onAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Upgrade to Yearly")
                        .font(.system(size: 16, weight: .bold, design: .rounded))
                        .foregroundStyle(DS.Palette.onAccent)
                    Text("\(AppConfig.yearlyMonthlyCredits) credits / month")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(DS.Palette.onAccent.opacity(0.85))
                }
                Spacer()
                if busy { ProgressView().tint(DS.Palette.onAccent) }
                else {
                    Text(yearly.localizedPriceString)
                        .font(.system(size: 15, weight: .heavy, design: .rounded))
                        .foregroundStyle(DS.Palette.onAccent)
                }
            }
            .padding(.horizontal, DS.Spacing.md).padding(.vertical, 14)
            .background(DS.Palette.primary, in: RoundedRectangle(cornerRadius: DS.Radius.md))
        }
        .buttonStyle(.plain)
        .disabled(purchasingID != nil)
        .accessibilityIdentifier("topup_upgrade_yearly")
    }

    /// Real RevenueCat product card — its OWN localizedPriceString + credit count + (middle) BEST VALUE.
    private func packCard(_ product: StoreProduct) -> some View {
        let amount = AppConfig.creditPackAmount(for: product.productIdentifier)
        let best = product.productIdentifier == AppConfig.creditPackMediumID
        let busy = purchasingID == product.productIdentifier
        return Button {
            Task {
                purchasingID = product.productIdentifier
                let ok = await store.purchaseCredits(product)
                purchasingID = nil
                // Purchase confirmed → CLOSE the sheet (resume flag) + dismiss. Both clears the
                // caller's binding and guarantees via its own dismiss (never stays open).
                if ok {
                    Tracker.log(.topUpPurchase, ["pack": product.productIdentifier, "credits": String(amount)])
                    onPurchased(); dismiss()
                }
            }
        } label: {
            packCardBody(amount: amount, price: product.localizedPriceString, best: best, busy: busy)
        }
        .buttonStyle(.plain)
        .disabled(purchasingID != nil)
        .accessibilityIdentifier("topup_pack_\(amount)")
    }

    /// Screenshot/sim demo card (if products didn't load).
    private func demoCard(credits: Int, price: String, best: Bool) -> some View {
        packCardBody(amount: credits, price: price, best: best, busy: false)
    }

    /// Pack card body (surface rounded + primary emphasis).
    private func packCardBody(amount: Int, price: String, best: Bool, busy: Bool) -> some View {
        VStack(spacing: 5) {
            Image(systemName: "circlebadge.2.fill")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(best ? DS.Palette.primary : DS.Palette.foreground)
            Text("\(amount)")
                .font(.system(size: 24, weight: .heavy, design: .rounded))
                .foregroundStyle(best ? DS.Palette.primary : DS.Palette.foreground)
            Text("credits")
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(DS.Palette.secondaryText)
            if busy {
                ProgressView().tint(DS.Palette.primary).padding(.top, 2)
            } else {
                Text(price)
                    .font(.system(size: 14, weight: .bold, design: .rounded))
                    .foregroundStyle(DS.Palette.foreground)
                    .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 18).padding(.horizontal, DS.Spacing.sm)
        .background(best ? DS.Palette.surface : DS.Palette.surface.opacity(0.6),
                    in: RoundedRectangle(cornerRadius: DS.Radius.xxl))
        .overlay(RoundedRectangle(cornerRadius: DS.Radius.xxl)
            .stroke(best ? DS.Palette.primary : .clear, lineWidth: 2))
        .overlay(alignment: .top) {
            if best {
                Text("BEST VALUE")
                    .font(.system(size: 9, weight: .bold, design: .rounded)).tracking(0.8)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(DS.Palette.primary, in: Capsule())
                    .offset(y: -10)
            }
        }
        .scaleEffect(best ? 1.04 : 1)
        // Soft elevation shadow on the BEST VALUE card (others flat).
        .shadow(color: DS.Palette.foreground.opacity(best ? 0.10 : 0), radius: 18, x: 0, y: 10)
        .contentShape(Rectangle())
    }
}
