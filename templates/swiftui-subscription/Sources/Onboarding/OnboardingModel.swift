import Foundation
import SwiftUI

/// Onboarding state: the current step, the history for Back, and every answer. Answers are
/// published into `OnboardingAnswers`, which `ProfileStore` persists when the funnel finishes.
@MainActor
final class OnboardingModel: ObservableObject {
    let steps: [OnboardingStep]
    @Published private(set) var index: Int
    @Published private(set) var history: [Int] = []
    /// +1 forward, −1 back (drives the transition direction).
    @Published private(set) var direction = 1
    /// No preselection: an option is selected only after the user taps it.
    @Published private(set) var answers: OnboardingAnswers
    // @if !hard_paywall
    /// Set when the last step is done: without a paywall step that ends onboarding (the view observes it).
    @Published private(set) var finished = false
    // @endif

    /// Today, injectable for tests.
    let now: () -> Date

    init(steps: [OnboardingStep] = OnboardingCatalog.steps, start: String? = nil,
         unitSystem: UnitSystem = .default(), now: @escaping () -> Date = Date.init) {
        self.steps = steps
        self.index = start.flatMap { id in steps.firstIndex { $0.id == id } } ?? 0
        var a = OnboardingAnswers()
        a.unitSystem = unitSystem
        self.answers = a
        self.now = now
        for step in steps { seedPickerDefault(step) }
    }

    var step: OnboardingStep { steps[index] }
    var canGoBack: Bool { !history.isEmpty }

    /// Header progress over the steps that show the header.
    var progress: Double {
        let headed = steps.indices.filter { steps[$0].showsHeader }
        guard let pos = headed.firstIndex(of: index), headed.count > 1 else { return 0 }
        return Double(pos + 1) / Double(headed.count)
    }

    // MARK: - Navigation

    func next() {
        // @if !hard_paywall
        if index + 1 >= steps.count { finished = true; return }
        // @endif
        guard index + 1 < steps.count else { return }
        history.append(index)
        direction = 1
        index += 1
    }

    func back() {
        guard let previous = history.popLast() else { return }
        direction = -1
        index = previous
    }

    func jump(to id: String) {
        guard let target = steps.firstIndex(where: { $0.id == id }) else { return }
        history.append(index)
        direction = 1
        index = target
    }

    // MARK: - Answers

    func isSelected(_ option: String, in step: OnboardingStep) -> Bool {
        answers.selected(step.id).contains(option)
    }

    /// Single choice replaces, multi choice toggles.
    func toggle(_ option: String, in step: OnboardingStep) {
        var picked = answers.selected(step.id)
        if step.multi {
            if let i = picked.firstIndex(of: option) { picked.remove(at: i) } else { picked.append(option) }
        } else {
            picked = [option]
        }
        answers.choices[step.id] = picked
    }

    func number(for step: OnboardingStep) -> Double? { answers.number(step.id) }

    func setNumber(_ value: Double, for step: OnboardingStep) {
        answers.numbers[step.id] = value
    }

    func setUnitSystem(_ system: UnitSystem) {
        answers.unitSystem = system
    }

    func setConsent(_ agreed: Bool) {
        answers.consentAt = agreed ? now() : nil
    }

    var hasConsent: Bool { answers.consentAt != nil }

    // @if siwa
    func setLinkedProvider(_ provider: String?) {
        answers.linkedProvider = provider
    }

    // @endif
    /// Whether the CTA is enabled on `step`.
    func canContinue(_ step: OnboardingStep) -> Bool {
        switch step.kind {
        case .question: return !answers.selected(step.id).isEmpty
        case .permission where step.id == "consent": return !AppSpec.consentRequired || hasConsent
        default: return true
        }
    }

    /// Answers stamped as complete, ready to persist.
    func completedAnswers() -> OnboardingAnswers {
        var a = answers
        a.completedAt = now()
        return a
    }

    private func seedPickerDefault(_ step: OnboardingStep) {
        guard let picker = step.picker else { return }
        switch picker {
        case .wheel(_, let initial, _), .ruler(_, let initial, _):
            answers.numbers[step.id] = Double(initial)
        case .weight(let initialKg, _):
            answers.numbers[step.id] = initialKg
        }
    }
}
