// @if revenuecat
import RevenueCat
// @endif
import SafariServices
import StoreKit
import SwiftUI

/// Close (×) button used by both paywalls. Hidden and disabled until `delay` seconds have passed
/// (hard paywall 2.5 s, offer 2 s), then fades in.
struct PaywallCloseButton: View {
    var delay: Double
    let action: () -> Void
    @State private var visible = false

    var body: some View {
        Button(action: action) {
            Image(systemName: "xmark")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(DS.Palette.secondaryText)
                .frame(width: 34, height: 34)
                .background(Circle().fill(DS.Palette.foreground.opacity(0.06)))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .opacity(visible ? 1 : 0)
        .allowsHitTesting(visible)
        .accessibilityHidden(!visible)
        .accessibilityLabel(Text("Close"))
        .accessibilityIdentifier("paywall_close")
        .task {
            try? await Task.sleep(for: .seconds(LaunchOptions.isUITest ? min(delay, 0.3) : delay))
            withAnimation(.easeIn(duration: 0.4)) { visible = true }
        }
    }
}

/// Buy / restore through RevenueCat and log the funnel with the paywall's `PaywallSource`.
@MainActor
struct PaywallPurchaser {
    let store: StoreManager
    let source: PaywallSource

    func buy(_ offer: PlanOffer, trial: Bool) async -> Bool {
        let props = ["product": offer.productID, "from": source.eventValue]
        Tracker.log(.purchaseStart, props)
        guard let product = store.product(offer.productID) else {
            // No RevenueCat product (placeholder key, or the store did not answer): no purchase path.
            store.lastError = StoreManager.storeUnavailable
            Tracker.log(.purchaseFail, props.merging(["reason": "store_not_ready"]) { $1 })
            return false
        }
        switch await store.purchase(product, package: store.package(for: offer.productID, source: source)) {
        case .success:
            Tracker.log(.purchaseSuccess, props.merging([
                "price": NSDecimalNumber(decimal: offer.price).stringValue,
                "currency": offer.currencyCode,
                "plan": store.plan.rawValue,
                "trial": trial ? "1" : "0",
            ]) { $1 })
            if trial { Tracker.log(.trialStart, ["product": offer.productID]) }
            return true
        case .paidButNotActive:
            Tracker.log(.purchaseFail, props.merging(["reason": "paid_not_active"]) { $1 })
            return false
        case .cancelled:
            Tracker.log(.purchaseCancel, props.merging(["reason": store.lastAbandonReason]) { $1 })
            return false
        }
    }

    func restore() async -> Bool {
        await store.restore()
        Tracker.log(.paywallRestore, ["from": source.eventValue, "result": store.isSubscribed ? "active" : "none"])
        return store.isSubscribed
    }
}

/// Terms · Privacy · Restore row (Apple requires all three on a paywall).
struct LegalLinks: View {
    let onRestore: () -> Void
    @State private var page: URL?

    var body: some View {
        HStack(spacing: 18) {
            if let terms = AppConfig.legalURL(.terms) {
                Button("Terms of Use") { page = terms }.accessibilityIdentifier("paywall_terms")
            }
            if let privacy = AppConfig.legalURL(.privacy) {
                Button("Privacy Policy") { page = privacy }.accessibilityIdentifier("paywall_privacy")
            }
            Button("Restore", action: onRestore).accessibilityIdentifier("paywall_restore")
        }
        .buttonStyle(.plain)
        .font(.system(size: 12, weight: .semibold))
        .foregroundStyle(DS.Palette.secondaryText)
        .legalSheet($page)
    }
}

/// Localized, already user-facing purchase error (never a raw StoreKit sentence).
struct PurchaseErrorNote: View {
    let message: String

    var body: some View {
        Text(verbatim: message)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(DS.Palette.destructive)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("purchase_error")
    }
}

/// One plan tile on the hard paywall.
struct PlanTile: View {
    let name: LocalizedStringResource
    let offer: PlanOffer
    let selected: Bool
    let badge: String?
    let sub: String
    let subAccent: Bool
    let identifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(name)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(DS.Palette.secondaryText)
                    Spacer()
                    CheckCircle(selected: selected).scaleEffect(0.85)
                }
                Text(verbatim: offer.displayPrice)
                    .font(.system(size: 23, weight: .heavy, design: .rounded))
                    .foregroundStyle(DS.Palette.foreground)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                Text(verbatim: sub)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(subAccent ? DS.Palette.primary : DS.Palette.secondaryText)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .padding(EdgeInsets(top: 16, leading: 14, bottom: 14, trailing: 14))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: DS.Radius.lg, style: .continuous)
                .fill(selected ? DS.Palette.primaryContainer.opacity(0.4) : DS.Palette.surface))
            .overlay(RoundedRectangle(cornerRadius: DS.Radius.lg, style: .continuous)
                .strokeBorder(selected ? DS.Palette.primary : DS.Palette.border, lineWidth: 2.5))
            .overlay(alignment: .top) {
                if let badge {
                    Text(verbatim: badge)
                        .font(.system(size: 12, weight: .heavy))
                        .foregroundStyle(DS.Palette.onAccent)
                        .padding(.vertical, 4)
                        .padding(.horizontal, 12)
                        .background(Capsule().fill(DS.Palette.primary))
                        .fixedSize()
                        .offset(y: -13)
                        .accessibilityIdentifier("\(identifier)_badge")
                }
            }
            .scaleEffect(selected ? 1.03 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.65), value: selected)
            .contentShape(RoundedRectangle(cornerRadius: DS.Radius.lg))
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.selection, trigger: selected)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier(identifier)
    }
}

// MARK: - Billing issue banner (grace period / billing retry)

/// Shown in the main app while the subscription has a billing problem. Opens Apple's manage
/// subscriptions sheet, where the user updates the payment method. Disappears by itself when the
/// entitlement recovers (StoreManager's customerInfo stream).
struct BillingIssueBanner: View {
    let issue: BillingIssue
    @State private var manage = false
    @State private var paywall = false

    var body: some View {
        Button {
            Tracker.log(custom: "billing_banner_tap", ["reason": reason])
            manage = true
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(DS.Palette.destructive)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(DS.Palette.foreground)
                    Text("Update your payment method to keep Premium.")
                        .font(.system(size: 13))
                        .foregroundStyle(DS.Palette.secondaryText)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "chevron.right").foregroundStyle(DS.Palette.secondaryText)
            }
            .padding(DS.Spacing.md)
            .background(RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface))
            .overlay(RoundedRectangle(cornerRadius: DS.Radius.lg).strokeBorder(DS.Palette.destructive.opacity(0.5), lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("billing_issue_banner")
        .overlay(alignment: .bottomTrailing) {
            if issue == .billingRetry {
                // The entitlement lapsed: besides fixing the payment, the user can pick a plan again.
                Button("See plans") { paywall = true }
                    .font(.system(size: 12, weight: .bold))
                    .padding(.trailing, DS.Spacing.xl).padding(.bottom, 6)
                    .accessibilityIdentifier("billing_issue_plans")
            }
        }
        .manageSubscriptionsSheet(isPresented: $manage)
        .fullScreenCover(isPresented: $paywall) {
            UpgradePaywall(source: .billingIssue) { paywall = false }
        }
    }

    private var title: LocalizedStringResource {
        switch issue {
        case .gracePeriod: return "There's a problem with your payment"
        case .billingRetry: return "Your subscription is on hold"
        }
    }

    private var reason: String {
        switch issue {
        case .gracePeriod: return "grace_period"
        case .billingRetry: return "billing_retry"
        }
    }
}

// MARK: - Legal sheet

extension View {
    /// Presents `url` in SFSafariViewController (backend CONTRACT: legal pages open in Safari view).
    func legalSheet(_ url: Binding<URL?>) -> some View {
        sheet(isPresented: Binding(get: { url.wrappedValue != nil }, set: { if !$0 { url.wrappedValue = nil } })) {
            if let u = url.wrappedValue { SafariView(url: u).ignoresSafeArea() }
        }
    }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> SFSafariViewController { SFSafariViewController(url: url) }
    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
