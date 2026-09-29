// @if siwa
import AuthenticationServices
// @endif
import SwiftUI

// One view per step kind. Copy comes from `OnboardingCatalog`; these views only lay it out.

// MARK: - Info / emotional

struct InfoStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel

    var body: some View {
        StepLayout(spacing: 22, centered: true) {
            StepHero(icon: step.icon, size: step.kind == .emotional ? 150 : 128)
            StepTitle(title: step.title, subtitle: step.subtitle, centered: true)
            if !step.bullets.isEmpty {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(step.bullets.enumerated()), id: \.offset) { i, bullet in
                        HStack(spacing: 12) {
                            Text(verbatim: "\(i + 1)")
                                .font(.system(size: 15, weight: .bold, design: .rounded))
                                .foregroundStyle(DS.Palette.onAccent)
                                .frame(width: 30, height: 30)
                                .background(Circle().fill(DS.Palette.primary))
                            Text(bullet)
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(DS.Palette.foreground)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
                .padding(DS.Spacing.md)
                .background(RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface))
            }
        } cta: {
            CTAButton(title: step.cta) { model.next() }
        }
    }
}

// MARK: - Question

struct QuestionStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel

    var body: some View {
        StepLayout(spacing: 22) {
            StepTitle(title: step.title, subtitle: step.subtitle)
            if step.multi {
                Text("Select all that apply")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(DS.Palette.secondaryText)
                    .padding(.top, -12)
            }
            VStack(spacing: 12) {
                ForEach(step.options) { option in
                    OptionCard(title: option.title, subtitle: option.subtitle, icon: option.icon,
                               selected: model.isSelected(option.id, in: step),
                               identifier: "option_\(step.id)_\(option.id)") {
                        model.toggle(option.id, in: step)
                        Tracker.log(.onboardingAnswer, ["step": step.id, "question": step.id, "answer": option.id])
                    }
                }
            }
        } cta: {
            CTAButton(title: step.cta, enabled: model.canContinue(step)) { model.next() }
        }
    }
}

// MARK: - Picker

struct PickerStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel
    @State private var weight: WeightPickerState?

    var body: some View {
        StepLayout(spacing: 28) {
            StepTitle(title: step.title, subtitle: step.subtitle)
            picker
        } cta: {
            CTAButton(title: step.cta) {
                let value = model.number(for: step).map { String(Int($0.rounded())) } ?? ""
                Tracker.log(.onboardingAnswer, ["step": step.id, "question": step.id, "answer": value])
                model.next()
            }
        }
    }

    @ViewBuilder private var picker: some View {
        switch step.picker {
        case .wheel(let range, let initial, let unit):
            let values = Array(range)
            WheelPicker(items: values.map { label($0, unit) },
                        selection: intBinding(values: values, initial: initial),
                        identifier: "picker_\(step.id)")
                .padding(.top, 12)
        case .ruler(let range, let initial, let unit):
            let values = Array(range)
            let binding = intBinding(values: values, initial: initial)
            VStack(spacing: 18) {
                Text(verbatim: label(values[binding.wrappedValue], unit))
                    .font(.system(size: 44, weight: .heavy, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(DS.Palette.foreground)
                    .contentTransition(.numericText())
                    .frame(maxWidth: .infinity)
                    .accessibilityIdentifier("picker_\(step.id)_value")
                RulerPicker(count: values.count - 1, index: binding, label: { Units.plainNumber(values[$0]) },
                            identifier: "picker_\(step.id)", accessibilityValue: label(values[binding.wrappedValue], unit))
            }
            .padding(.top, 24)
        case .weight(let initialKg, let rangeKg):
            WeightPicker(state: weightBinding(initialKg: initialKg, rangeKg: rangeKg), identifier: "picker_\(step.id)")
                .padding(.top, 12)
        case .none:
            EmptyView()
        }
    }

    /// The user's digits (Arabic-Indic in Arabic), never grouped: years read "1995", not "1,995".
    private func label(_ value: Int, _ unit: LocalizedStringResource?) -> String {
        guard let unit else { return Units.plainNumber(value) }
        return Units.plainNumber(value) + "\u{00A0}" + String(localized: unit)
    }

    private func intBinding(values: [Int], initial: Int) -> Binding<Int> {
        Binding(get: {
            let current = Int((model.number(for: step) ?? Double(initial)).rounded())
            return values.firstIndex(of: min(values.last!, max(values.first!, current))) ?? 0
        }, set: { model.setNumber(Double(values[$0]), for: step) })
    }

    private func weightBinding(initialKg: Double, rangeKg: ClosedRange<Double>) -> Binding<WeightPickerState> {
        Binding(get: {
            weight ?? WeightPickerState(kg: model.number(for: step) ?? initialKg, unit: model.answers.unitSystem, rangeKg: rangeKg)
        }, set: { new in
            weight = new
            model.setNumber(new.kg, for: step)
            model.setUnitSystem(new.unit)
        })
    }
}

// MARK: - Permission (consent; Apple Health when the module is on)

struct PermissionStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel

    var body: some View {
        StepLayout(spacing: 22, centered: true) {
            StepHero(icon: step.icon)
            StepTitle(title: step.title, subtitle: step.subtitle, centered: true)
            if step.id == "consent" {
                HStack(spacing: 14) {
                    Text("I agree to AI processing of my photos and answers")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(DS.Palette.foreground)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    DesignSwitch(isOn: Binding(get: { model.hasConsent }, set: { agreed in
                        model.setConsent(agreed)
                        Tracker.log(.consentResult, ["result": agreed ? "granted" : "withdrawn"])
                    }), label: "I agree to AI processing of my photos and answers", identifier: "consent_switch")
                }
                .padding(DS.Spacing.md)
                .background(RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface))
                if let privacy = AppConfig.legalURL(.privacy) {
                    Link(destination: privacy) { Text("Privacy Policy") }
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(DS.Palette.secondaryText)
                }
            }
            // @if health
            if step.id == "health" {
                HealthPermissionCard(hasConsent: model.hasConsent || !AppSpec.consentRequired)
            }
            // @endif
        } cta: {
            CTAButton(title: step.cta, enabled: model.canContinue(step)) { model.next() }
        }
    }
}

// MARK: - Loading

struct LoadingStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel
    @State private var percent = 0
    @State private var finished = false

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            Text(verbatim: "\(percent)%")
                .font(.system(size: 64, weight: .heavy, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(DS.Palette.foreground)
                .contentTransition(.numericText())
                .accessibilityIdentifier("loading_percent")
            StepTitle(title: step.title, centered: true)
            ProgressView(value: Double(percent), total: 100)
                .tint(DS.Palette.primary)
                .padding(.horizontal, DS.Spacing.xl)
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(step.bullets.enumerated()), id: \.offset) { i, item in
                    let done = percent >= (i + 1) * 100 / max(1, step.bullets.count)
                    HStack(spacing: 12) {
                        Image(systemName: done ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(done ? DS.Palette.primary : DS.Palette.border)
                            .font(.system(size: 20))
                            .contentTransition(.symbolEffect(.replace))
                        Text(item)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(done ? DS.Palette.foreground : DS.Palette.secondaryText)
                    }
                }
            }
            .padding(.horizontal, DS.Spacing.xl)
            Spacer()
        }
        .padding(.horizontal, DS.Spacing.lg)
        .sensoryFeedback(.success, trigger: finished)
        .task { await run() }
    }

    private func run() async {
        let total: Double = LaunchOptions.fastLoading ? 0.8 : 3.6
        let ticks = 50
        for i in 1...ticks {
            try? await Task.sleep(for: .seconds(total / Double(ticks)))
            if Task.isCancelled { return }
            withAnimation(.easeOut(duration: 0.1)) { percent = i * 100 / ticks }
        }
        finished = true
        try? await Task.sleep(for: .milliseconds(350))
        if !Task.isCancelled { model.next() }
    }
}

// MARK: - Finale

struct FinaleStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel
    @State private var appeared = false

    var body: some View {
        StepLayout(spacing: 22, centered: true) {
            StepHero(icon: step.icon, size: 140)
                .scaleEffect(appeared ? 1 : 0.6)
                .opacity(appeared ? 1 : 0)
            StepTitle(title: step.title, subtitle: step.subtitle, centered: true)
            let highlights = PaywallPersonalization(answers: model.answers).highlights
            if !highlights.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(highlights, id: \.self) { h in
                        HStack(spacing: 10) {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(DS.Palette.primary)
                            Text(verbatim: h)
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(DS.Palette.foreground)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(DS.Spacing.md)
                .background(RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface))
                .accessibilityIdentifier("finale_highlights")
            }
        } cta: {
            CTAButton(title: step.cta) { model.next() }
        }
        .sensoryFeedback(.success, trigger: appeared)
        .onAppear { withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) { appeared = true } }
    }
}

// @if siwa
// MARK: - Account (Sign in with Apple links the anonymous user)

struct AccountStepScreen: View {
    let step: OnboardingStep
    @EnvironmentObject private var model: OnboardingModel
    @EnvironmentObject private var store: StoreManager
    @State private var nonce = AppleSignIn.randomNonce()
    @State private var busy = false

    var body: some View {
        StepLayout(spacing: 22, centered: true) {
            StepHero(icon: step.icon)
            StepTitle(title: step.title, subtitle: step.subtitle, centered: true)
        } cta: {
            VStack(spacing: 10) {
                ForEach(AuthProviders.visible, id: \.self) { kind in
                    switch kind {
                    case .apple:
                        SignInWithAppleButton(.continue) { request in
                            nonce = AppleSignIn.randomNonce()
                            AppleSignIn.configure(request, rawNonce: nonce)
                        } onCompletion: { result in
                            handle(AppleSignIn.outcome(from: result, rawNonce: nonce), kind: kind)
                        }
                        .signInWithAppleButtonStyle(.black)
                        .frame(height: 54)
                        .clipShape(Capsule())
                        .disabled(busy)
                        .accessibilityIdentifier("account_apple")
                    }
                }
                Button { skip() } label: {
                    Text("Not now")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(DS.Palette.secondaryText)
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("account_skip")
            }
            .padding(.horizontal, DS.Spacing.lg)
            .padding(.bottom, DS.Spacing.md)
        }
    }

    private func skip() {
        Tracker.log(.authAttempt, ["provider": "none", "result": "skipped"])
        model.next()
    }

    private func handle(_ outcome: AppleSignIn.Outcome, kind: AuthProviderKind) {
        switch outcome {
        case .finished(let result):
            Tracker.log(.authAttempt, ["provider": kind.rawValue, "result": Self.name(result)])
            if result != .cancelled { model.next() }
        case .credential(let credential):
            busy = true
            Task {
                let result = await AuthProviders.provider(for: kind).link(credential)
                if case .switchedAccount(let uid) = result { await store.logIn(appUserID: uid) }
                if result.isSignedIn { model.setLinkedProvider(kind.rawValue) }
                Tracker.log(.authAttempt, ["provider": kind.rawValue, "result": Self.name(result)])
                busy = false
                model.next()
            }
        }
    }

    static func name(_ r: AuthResult) -> String {
        switch r {
        case .linked: return "linked"
        case .switchedAccount: return "switched_account"
        case .unavailable: return "unavailable"
        case .cancelled: return "cancelled"
        case .failed: return "failed"
        }
    }
}
// @endif
