import Foundation

/// Everything the hard paywall personalizes, derived from the user's own onboarding answers
/// (persisted `OnboardingAnswers`). No sample numbers ship: every string is built from answers.
///
/// APP-SPECIFIC EXTENSION POINT: the features stage may add richer derived values (a plan, a
/// target date, a score) computed from the same answers; keep them pure and unit-tested.
struct PaywallPersonalization: Equatable {
    let answers: OnboardingAnswers

    /// Localized title of the goal answer, if the user answered the goal question.
    var goalTitle: String? {
        guard let goalStep = OnboardingCatalog.personalizationSteps.first,
              let goal = answers.first(goalStep) else { return nil }
        return OnboardingCatalog.optionTitle(step: goalStep, option: goal)
    }

    /// "Your goal: Save time" — or a neutral headline when the goal was not answered.
    var headline: String {
        if let goalTitle { return String(localized: "Your goal: \(goalTitle)") }
        return String(localized: "Your personal plan is ready")
    }

    /// Up to three of the user's own answers (localized option titles) from the personalization
    /// steps, in catalog order, for the "Built from your answers" block.
    var highlights: [String] {
        var out: [String] = []
        for stepID in OnboardingCatalog.personalizationSteps {
            for option in answers.selected(stepID) {
                if let title = OnboardingCatalog.optionTitle(step: stepID, option: option), !out.contains(title) {
                    out.append(title)
                }
            }
        }
        return Array(out.prefix(3))
    }

    /// Proof line above the highlights (only claims what is true: the answers exist).
    var proofLine: String {
        answers.answeredCount > 0 ? String(localized: "Built from your answers") : String(localized: "Built around you")
    }

    #if DEBUG
    /// Sample answers for UI tests and screenshots (`-uiPaywall`, `-uiSeedProfile`).
    static func sampleAnswers() -> OnboardingAnswers {
        var a = OnboardingAnswers()
        let goalStep = OnboardingCatalog.personalizationSteps.first ?? "goal"
        if let option = OnboardingCatalog.step(goalStep)?.options.dropFirst().first?.id {
            a.choices[goalStep] = [option]
        }
        for stepID in OnboardingCatalog.personalizationSteps.dropFirst() {
            if let option = OnboardingCatalog.step(stepID)?.options.first?.id { a.choices[stepID] = [option] }
        }
        a.unitSystem = LaunchOptions.unitSystem ?? .metric
        return a
    }
    #endif
}
