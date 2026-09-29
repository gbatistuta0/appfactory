import SwiftUI
import UIKit

/// Root tab structure — single-page apps may not pass App Review.
/// Every app: Create + Gallery (history) + Settings, in the SYSTEM TabView (Liquid Glass on iOS 26).
/// iOS 18+ uses the Tab API with the main action (Create) as the search-role tab: the trailing
/// glass circle on iOS 26; the bar minimizes on scroll. iOS 17 falls back to tab items.
/// Tab values: 0 Create, 1 Gallery, 2 Settings (`-uiTab`).
struct RootTabView: View {
    @EnvironmentObject private var store: StoreManager
    @StateObject private var history = GenerationStore()
    @State private var selection = LaunchOptions.initialTab
    // @if ratings
    /// Success-moment App Store rating request (mandatory; RatingPolicy decides, this view asks).
    @State private var ratingTrigger: RatingPolicy.Trigger?
    // @endif

    var body: some View {
        tabs
        .safeAreaInset(edge: .top, spacing: 0) {
            if let issue = store.billingIssue {
                BillingIssueBanner(issue: issue)
                    .padding(.horizontal, DS.Spacing.md)
                    .padding(.top, DS.Spacing.xs)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.3), value: store.billingIssue)
        // @if ratings
        // Success moment: a new result was saved (a delete lowers the count and never asks). A milestone
        // is the rarer, more meaningful moment, so it wins when both match the same save.
        .onChange(of: history.items.count) { old, new in
            guard new > old else { return }
            if let trigger = RatingPolicy.shared.request(forMilestone: history.activeDays)
                ?? RatingPolicy.shared.request(forSuccessCount: new, distinctDays: history.activeDays) {
                ratingTrigger = trigger
            }
        }
        .ratingRequest($ratingTrigger)
        // @endif
        .onChange(of: selection) { _, tab in
            let name = ["create", "gallery", "settings"][min(max(tab, 0), 2)]
            Tracker.screen(name)
            Tracker.log(.tabSelect, ["tab": name])
        }
        .task {
            Tracker.screen("create")
            // StoreKit messages (billing issue, price increase) were deferred while onboarding and
            // the paywalls were on screen; the main app is where they belong.
            await store.showDeferredStoreMessages()
        }
    }

    @ViewBuilder private var tabs: some View {
        if #available(iOS 18, *) {
            TabView(selection: $selection) {
                Tab("Gallery", systemImage: "square.grid.2x2", value: 1) {
                    GalleryView().environmentObject(history)
                }
                Tab("Settings", systemImage: "gearshape", value: 2) {
                    SettingsView()
                }
                // The main action: the search-role tab (its own glass circle on iOS 26).
                Tab(value: 0, role: .search) {
                    GenerationView().environmentObject(history)
                } label: {
                    createLabel
                }
            }
            .tint(DS.Palette.primary)
            .modifier(MinimizeOnScroll())
        } else {
            TabView(selection: $selection) {
                GenerationView()
                    .environmentObject(history)
                    .tabItem { createLabel }.tag(0)
                GalleryView()
                    .environmentObject(history)
                    .tabItem { Label("Gallery", systemImage: "square.grid.2x2") }.tag(1)
                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gearshape") }.tag(2)
            }
            .tint(DS.Palette.primary)
        }
    }

    /// The Create action looks the same whatever tab is selected (a white symbol on a brand disc):
    /// `.tint` only colours the selected item, so the icon is an original-rendering image.
    private var createLabel: some View {
        Label {
            Text("Create")
        } icon: {
            Image(uiImage: createActionIcon)
        }
        .accessibilityIdentifier("tab_create")
    }
}

/// The main-action tab icon: a white symbol on a solid brand disc, drawn as is so the bar's tint
/// never recolours it. iOS 26 puts the search-role tab in its own glass circle, which a 56 pt
/// disc nearly fills; older systems draw it as a regular tab item, so it keeps a tab-icon size.
private let createActionIcon: UIImage = {
    let glassCircle: Bool = { if #available(iOS 26, *) { return true } else { return false } }()
    let side: CGFloat = glassCircle ? 56 : 30
    let config = UIImage.SymbolConfiguration(pointSize: glassCircle ? 22 : 13, weight: .semibold)
    let symbol = (UIImage(systemName: "wand.and.stars", withConfiguration: config) ?? UIImage())
        .withTintColor(.white, renderingMode: .alwaysOriginal)
    let image = UIGraphicsImageRenderer(size: CGSize(width: side, height: side)).image { _ in
        UIColor(DS.Palette.primary).setFill()
        UIBezierPath(ovalIn: CGRect(x: 0, y: 0, width: side, height: side)).fill()
        let s = symbol.size
        symbol.draw(in: CGRect(x: (side - s.width) / 2, y: (side - s.height) / 2, width: s.width, height: s.height))
    }
    return image.withRenderingMode(.alwaysOriginal)
}()

/// iOS 26: the tab bar collapses to the current tab and the main-action circle while scrolling.
private struct MinimizeOnScroll: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content.tabBarMinimizeBehavior(.onScrollDown)
        } else {
            content
        }
    }
}

// MARK: - Gallery (previous generations)

struct GalleryView: View {
    @EnvironmentObject private var history: GenerationStore
    private let cols = [GridItem(.flexible(), spacing: DS.Spacing.md),
                        GridItem(.flexible(), spacing: DS.Spacing.md)]

    var body: some View {
        NavigationStack {
            Group {
                if history.items.isEmpty {
                    emptyState.frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView(showsIndicators: false) {
                        VStack(alignment: .leading, spacing: DS.Spacing.md) {
                            Text("Everything you've created.")
                                .font(DS.Typography.body).foregroundStyle(DS.Palette.secondaryText)
                            LazyVGrid(columns: cols, spacing: DS.Spacing.md) {
                                ForEach(history.items) { item in
                                    NavigationLink(value: item) {
                                        GalleryCell(item: item)
                                    }
                                    .buttonStyle(.plain)
                                    .contextMenu {
                                        ShareLink(item: item.localURL) { Label("Share", systemImage: "square.and.arrow.up") }
                                        Button(role: .destructive) { history.remove(item) } label: {
                                            Label("Delete", systemImage: "trash")
                                        }
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, DS.Spacing.lg)
                        .padding(.bottom, DS.Spacing.xxl)
                    }
                }
            }
            .background(DS.Palette.background.ignoresSafeArea())
            .navigationTitle(Text("Gallery"))
            .navigationDestination(for: GenerationItem.self) { item in
                GalleryDetailView(item: item)
            }
            .onAppear { Tracker.log(.galleryView) }
        }
    }

    private var emptyState: some View {
        VStack(spacing: DS.Spacing.md) {
            ZStack {
                Circle().fill(DS.Palette.primaryContainer).frame(width: 84, height: 84)
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 32)).foregroundStyle(DS.Palette.primary)
            }
            Text("Nothing here yet").font(DS.Typography.headline)
                .foregroundStyle(DS.Palette.foreground)
            Text("Your creations will appear here.")
                .font(DS.Typography.body).foregroundStyle(DS.Palette.secondaryText)
                .multilineTextAlignment(.center)
        }
        .padding(DS.Spacing.xl)
    }
}

/// A gallery item: the system navigation bar (back button + title, glass on iOS 26) and Share in
/// its toolbar.
private struct GalleryDetailView: View {
    let item: GenerationItem
    var body: some View {
        VStack {
            if let ui = UIImage(contentsOfFile: item.localURL.path) {
                Image(uiImage: ui).resizable().scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: DS.Radius.lg))
                    .shadow(color: .black.opacity(0.12), radius: 16, y: 8)
                    .padding(DS.Spacing.lg)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DS.Palette.background.ignoresSafeArea())
        .navigationTitle(Text(item.style))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ShareLink(item: item.localURL) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .accessibilityIdentifier("gallery_share")
            }
        }
    }
}

private struct GalleryCell: View {
    let item: GenerationItem
    var body: some View {
        BoundedImage(aspect: 4.0 / 5.0, cornerRadius: DS.Radius.lg) {
            Group {
                if let ui = UIImage(contentsOfFile: item.localURL.path) {
                    Image(uiImage: ui).resizable().scaledToFill()
                } else {
                    ZStack {
                        DS.Palette.surfaceMuted
                        Image(systemName: "photo").font(.system(size: 28))
                            .foregroundStyle(DS.Palette.secondaryText)
                    }
                }
            }
        }
    }
}

// MARK: - Settings (App Review: subscription, restore, legal, account)

struct SettingsView: View {
    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var profiles: ProfileStore
    // @if credits
    @EnvironmentObject private var credits: CreditManager
    @State private var showTopUp = false
    // @endif
    @State private var showPaywall = false
    @State private var showManageSubscriptions = false
    @State private var legalPage: URL?
    @State private var confirmDelete = false
    @State private var deleteFailed = false
    @AppStorage("onboarding_completed") private var onboarded = true

    private var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    }

    var body: some View {
        NavigationStack {
            ZStack {
                DS.Palette.background.ignoresSafeArea()
                List {
                    Section {
                        // @if credits
                        Button { showTopUp = true } label: {
                            HStack {
                                Label("Credits remaining", systemImage: "bolt.fill")
                                Spacer()
                                Text(verbatim: "\(credits.credits)").foregroundStyle(DS.Palette.primary).bold()
                            }
                        }
                        .accessibilityIdentifier("settings_credits")
                        // @endif
                        HStack {
                            Label("Subscription", systemImage: "crown.fill")
                            Spacer()
                            Text(store.isSubscribed ? "Active" : "Free")
                                .foregroundStyle(DS.Palette.secondaryText)
                        }
                        if !store.isSubscribed {
                            Button { showPaywall = true } label: {
                                Label("Upgrade to Premium", systemImage: "sparkles")
                            }
                            .accessibilityIdentifier("settings_upgrade")
                        }
                        Button { Task { await store.restore() } } label: {
                            Label("Restore Purchases", systemImage: "arrow.clockwise")
                        }
                        Button { showManageSubscriptions = true } label: {
                            Label("Manage Subscription", systemImage: "creditcard")
                        }
                    } header: { Text("Account") }

                    Section {
                        if profiles.answers?.consentAt != nil {
                            Button(role: .destructive) {
                                profiles.recordConsent(nil)
                                Tracker.log(.consentResult, ["result": "withdrawn"])
                                Task { await ProfileSync.upsertConsent(nil) }
                            } label: {
                                Label("Withdraw AI consent", systemImage: "hand.raised.slash")
                            }
                        }
                        // @if health
                        HealthSettingsRow()
                        // @endif
                    } header: { Text("Privacy") }

                    Section {
                        if let privacy = AppConfig.legalURL(.privacy) {
                            Button { legalPage = privacy } label: { Label("Privacy Policy", systemImage: "hand.raised") }
                        }
                        if let terms = AppConfig.legalURL(.terms) {
                            Button { legalPage = terms } label: { Label("Terms of Use", systemImage: "doc.text") }
                        }
                        if AppConfig.supportEmail.contains("@"), let mail = URL(string: "mailto:\(AppConfig.supportEmail)") {
                            Link(destination: mail) { Label("Contact Support", systemImage: "envelope") }
                        } else if let support = AppConfig.legalURL(.support) {
                            Button { legalPage = support } label: { Label("Contact Support", systemImage: "envelope") }
                        }
                    } header: { Text("About") }

                    Section {
                        Button(role: .destructive) { confirmDelete = true } label: {
                            Label("Delete account", systemImage: "trash")
                        }
                        .accessibilityIdentifier("settings_delete_account")
                        HStack {
                            Text("Version")
                            Spacer()
                            Text(verbatim: version).foregroundStyle(DS.Palette.secondaryText)
                        }
                    }
                }
                .scrollContentBackground(.hidden)
                .tint(DS.Palette.primary)
                .foregroundStyle(DS.Palette.foreground)
            }
            .navigationTitle(Text("Settings"))
            .manageSubscriptionsSheet(isPresented: $showManageSubscriptions)
            .legalSheet($legalPage)
            .confirmationDialog("Delete account", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete account", role: .destructive) { Task { await deleteAccount() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This deletes your data for good. It does not cancel your App Store subscription: cancel it in Settings → Apple ID → Subscriptions.")
            }
            .alert("We couldn't delete your account. Please try again.", isPresented: $deleteFailed) {
                Button("OK", role: .cancel) {}
            }
            .fullScreenCover(isPresented: $showPaywall) {
                UpgradePaywall(source: .settings) { showPaywall = false }
            }
            // @if credits
            .sheet(isPresented: $showTopUp) {
                TopUpSheet(onPurchased: { showTopUp = false })
                    .environmentObject(store).environmentObject(credits)
            }
            // @endif
            .onAppear { Tracker.log(.settingsView) }
        }
    }
}

extension SettingsView {
    fileprivate func deleteAccount() async {
        guard await AccountService.deleteAccount() == .deleted else { deleteFailed = true; return }
        await store.logOut()
        profiles.reset()
        onboarded = false
    }
}

/// Hard paywall opened from inside the app (Settings, a 402, the daily cap) at `source`.
struct UpgradePaywall: View {
    let source: PaywallSource
    let onDone: () -> Void
    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var profiles: ProfileStore
    @StateObject private var catalog = PaywallCatalog()

    var body: some View {
        Group {
            // @if offer_paywall
            if source.isOffer {
                OfferPaywallView(source: source, onPurchased: onDone, onClose: onDone)
            } else {
                HardPaywallView(source: source,
                                personalization: PaywallPersonalization(answers: profiles.answers ?? OnboardingAnswers()),
                                onPurchased: onDone, onClose: onDone)
            }
            // @endif
            // @if !offer_paywall
            HardPaywallView(source: source,
                            personalization: PaywallPersonalization(answers: profiles.answers ?? OnboardingAnswers()),
                            onPurchased: onDone, onClose: onDone)
            // @endif
        }
        .environmentObject(catalog)
        .task { await catalog.load(store: store) }
    }
}

/// Shown after a 403 `consent_required`: records consent, then the caller retries.
struct ConsentView: View {
    let onDone: (Bool) -> Void
    @EnvironmentObject private var profiles: ProfileStore
    @State private var agreed = false

    var body: some View {
        VStack(spacing: DS.Spacing.lg) {
            StepHero(icon: "checkmark.shield")
            StepTitle(title: "Allow AI analysis",
                      subtitle: "To personalize your results, your photos and answers are processed by our AI. You can withdraw consent anytime in Settings.",
                      centered: true)
            HStack(spacing: 14) {
                Text("I agree to AI processing of my photos and answers")
                    .font(.system(size: 15, weight: .semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                DesignSwitch(isOn: $agreed, label: "I agree to AI processing of my photos and answers", identifier: "consent_switch")
            }
            .padding(DS.Spacing.md)
            .background(RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface))
            Spacer()
            CTAButton(title: "Continue", enabled: agreed) {
                let now = Date()
                profiles.recordConsent(now)
                Tracker.log(.consentResult, ["result": "granted"])
                Task {
                    await ProfileSync.upsertConsent(now)
                    onDone(true)
                }
            }
            Button("Not now") { onDone(false) }
                .foregroundStyle(DS.Palette.secondaryText)
                .padding(.bottom, DS.Spacing.md)
        }
        .padding(.top, DS.Spacing.xl)
        .padding(.horizontal, DS.Spacing.lg)
        .presentationDetents([.large])
        .sheetSurface()
    }
}
