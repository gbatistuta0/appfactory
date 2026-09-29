import SwiftUI

/// Onboarding container: persistent header (back + progress) and one step at a time. Ends with
/// the hard paywall and, when dismissed, the one-time offer (shown once).
struct OnboardingView: View {
    @StateObject private var model: OnboardingModel
    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var profiles: ProfileStore
    @StateObject private var catalog = PaywallCatalog()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    // @if offer_paywall
    @AppStorage(OnboardingView.offerSeenKey) private var offerSeen = false
    // @endif
    let onFinish: () -> Void

    // @if offer_paywall
    static let offerSeenKey = "offer_paywall_seen"
    // @endif

    init(start: String? = nil, onFinish: @escaping () -> Void) {
        _model = StateObject(wrappedValue: OnboardingModel(start: start, unitSystem: LaunchOptions.unitSystem ?? .default()))
        self.onFinish = onFinish
    }

    var body: some View {
        ZStack {
            DS.Palette.background.ignoresSafeArea()
            VStack(spacing: 0) {
                if model.step.showsHeader {
                    OnboardingHeader(progress: model.progress, canGoBack: model.canGoBack) { model.back() }
                        .transition(.opacity)
                }
                screen(model.step)
                    .id(model.step.id)
                    .transition(transition)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.3), value: model.index)
        }
        .environmentObject(model)
        .environmentObject(catalog)
        .onAppear {
            Tracker.log(.onboardingStart, ["step": model.step.id])
            logStep(model.step)
        }
        .onChange(of: model.index) { _, _ in logStep(model.step) }
        // @if !hard_paywall
        // No paywall step: the last step ends onboarding.
        .onChange(of: model.finished) { _, done in if done { finish() } }
        // @endif
        .task { await catalog.load(store: store) }
    }

    private var transition: AnyTransition {
        .asymmetric(insertion: .opacity.combined(with: .offset(x: model.direction > 0 ? 24 : -24)),
                    removal: .opacity)
    }

    private func logStep(_ step: OnboardingStep) {
        Tracker.screen("onboarding_\(step.id)")
        Tracker.log(.onboardingStepView, ["step": step.id, "kind": step.kind.rawValue])
    }

    @ViewBuilder
    private func screen(_ step: OnboardingStep) -> some View {
        switch step.kind {
        case .info, .emotional: InfoStepScreen(step: step)
        case .question: QuestionStepScreen(step: step)
        case .picker: PickerStepScreen(step: step)
        case .permission: PermissionStepScreen(step: step)
        case .loading: LoadingStepScreen(step: step)
        case .finale: FinaleStepScreen(step: step)
        // @if siwa
        case .account: AccountStepScreen(step: step)
        // @endif
        // @if !siwa
        case .account: EmptyView() // this app has no account step
        // @endif
        // @if hard_paywall
        case .paywall:
            // @if offer_paywall
            if step.id == "offer" {
                OfferPaywallView(source: .offerAfterOnboarding, onPurchased: finish, onClose: finish)
            } else {
                HardPaywallView(source: .onboarding, personalization: personalization, onPurchased: finish, onClose: {
                    if AppConfig.showOfferPaywall && !offerSeen && !AppConfig.offerProductIDs.isEmpty {
                        model.jump(to: "offer")
                    } else {
                        finish()
                    }
                })
            }
            // @endif
            // @if !offer_paywall
            HardPaywallView(source: .onboarding, personalization: personalization, onPurchased: finish, onClose: finish)
            // @endif
        // @endif
        // @if !hard_paywall
        case .paywall: EmptyView() // the paywall opens from placements only
        // @endif
        }
    }

    /// The paywall renders only from the user's own answers.
    private var personalization: PaywallPersonalization {
        PaywallPersonalization(answers: model.answers)
    }

    /// Persist the answers and leave onboarding.
    private func finish() {
        let answers = model.completedAnswers()
        profiles.save(answers)
        Task.detached { await ProfileSync.upsert(answers) }
        Tracker.log(.onboardingComplete, ["subscribed": store.isSubscribed ? "1" : "0"])
        onFinish()
    }
}

// MARK: - Step layout

/// Content column above a pinned CTA. Scrolls only when the content does not fit (iPhone SE);
/// `centered` steps center their content vertically.
struct StepLayout<Content: View, CTA: View>: View {
    var spacing: CGFloat = 24
    var centered = false
    @ViewBuilder var content: () -> Content
    @ViewBuilder var cta: () -> CTA

    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { geo in
                ScrollView(.vertical) {
                    VStack(alignment: centered ? .center : .leading, spacing: spacing) {
                        content()
                    }
                    .padding(.top, DS.Spacing.lg)
                    .padding(.horizontal, DS.Spacing.lg)
                    .frame(maxWidth: .infinity, alignment: centered ? .center : .topLeading)
                    .frame(minHeight: geo.size.height, alignment: centered ? .center : .top)
                }
                .scrollBounceBehavior(.basedOnSize)
                .scrollIndicators(.hidden)
            }
            cta()
        }
    }
}

/// Title + subtitle of a step.
struct StepTitle: View {
    let title: LocalizedStringResource
    var subtitle: LocalizedStringResource? = nil
    var centered = false

    var body: some View {
        VStack(alignment: centered ? .center : .leading, spacing: 8) {
            Text(title)
                .font(DS.Typography.largeTitle)
                .foregroundStyle(DS.Palette.foreground)
                .multilineTextAlignment(centered ? .center : .leading)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("onb_title")
            if let subtitle {
                Text(subtitle)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.secondaryText)
                    .multilineTextAlignment(centered ? .center : .leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: centered ? .center : .leading)
    }
}

/// Round hero badge with an SF Symbol. Extension point: the design stage swaps in the mascot.
struct StepHero: View {
    let icon: String
    var size: CGFloat = 120

    var body: some View {
        ZStack {
            Circle().fill(DS.Palette.primaryContainer.opacity(0.55))
            Circle().fill(DS.Palette.primaryContainer).padding(size * 0.12)
            Image(systemName: icon)
                .font(.system(size: size * 0.36, weight: .semibold))
                .foregroundStyle(DS.Palette.primary)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
