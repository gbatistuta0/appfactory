import SwiftUI

/// What a step is, for layout and analytics (`onboarding_step_view.kind`).
enum StepKind: String {
    case info, question, picker, emotional, permission, loading, finale, account, paywall
}

/// Picker steps. Every weight picker carries the kg/lb toggle (`UnitSystem`).
enum PickerStyle {
    /// Scroll wheel over whole numbers (e.g. birth year).
    case wheel(range: ClosedRange<Int>, initial: Int, unit: LocalizedStringResource?)
    /// Horizontal tick ruler over whole numbers (e.g. minutes a day).
    case ruler(range: ClosedRange<Int>, initial: Int, unit: LocalizedStringResource?)
    /// Body weight in kg or lb (unit toggle, whole-pound imperial state, 0.5 kg / 1 lb snapping).
    case weight(initialKg: Double, rangeKg: ClosedRange<Double>)
}

struct OnboardingOption: Identifiable {
    /// Stable analytics / backend value (snake_case, never localized).
    let id: String
    let title: LocalizedStringResource
    var subtitle: LocalizedStringResource? = nil
    /// SF Symbol name.
    var icon: String? = nil
}

struct OnboardingStep: Identifiable {
    /// Stable analytics / accessibility name (snake_case).
    let id: String
    let kind: StepKind
    let title: LocalizedStringResource
    var subtitle: LocalizedStringResource? = nil
    /// SF Symbol for the hero (the mascot replaces it when the design stage adds one).
    var icon: String = "sparkles"
    var options: [OnboardingOption] = []
    var multi = false
    var picker: PickerStyle? = nil
    var bullets: [LocalizedStringResource] = []
    var cta: LocalizedStringResource = "Continue"

    /// Welcome, loading, finale, account and paywalls run full-screen without the header.
    var showsHeader: Bool { ![.loading, .finale, .account, .paywall].contains(kind) && id != "welcome" }
}

/// The onboarding funnel (Cal AI pattern): no login friction → personalization questions →
/// attribution → emotional beats → loading → personal result → account → hard paywall → offer.
///
/// APP-SPECIFIC EXTENSION POINT: the questions below are generic placeholders. The features stage
/// replaces their copy and options with the app's own (keep ids snake_case, keep >= 5 questions,
/// keep the step count equal to spec `design.onboarding_screens`). Rules that stay: nothing is
/// preselected, no notification permission, no rating prompt, no invented statistics.
///
/// `// @step <id>` markers let the scaffold trim or pad the list to the spec's screen count.
enum OnboardingCatalog {
    /// Steps whose answers feed the paywall personalization (goal first).
    // @if quiz
    static let personalizationSteps = ["goal", "achieve", "priority"]
    // @endif
    // @if !quiz
    static let personalizationSteps: [String] = []
    // @endif

    static let steps: [OnboardingStep] = [
        // @step welcome
        .init(id: "welcome", kind: .info, title: "Your personal AI, ready in seconds",
              subtitle: "Answer a few quick questions and we'll build a plan around you.",
              icon: "sparkles", cta: "Get started"),
        // @if quiz
        // @step goal
        .init(id: "goal", kind: .question, title: "What's your main goal?",
              subtitle: "We'll shape everything around it.", icon: "target", options: [
                  .init(id: "look_best", title: "Look and feel my best", icon: "star"),
                  .init(id: "save_time", title: "Save time", icon: "clock"),
                  .init(id: "learn", title: "Learn something new", icon: "lightbulb"),
                  .init(id: "curious", title: "Just curious", icon: "sparkle.magnifyingglass"),
              ]),
        // @step source
        .init(id: "source", kind: .question, title: "Where did you hear about us?",
              icon: "megaphone", options: [
                  .init(id: "tiktok", title: "TikTok", icon: "music.note"),
                  .init(id: "instagram", title: "Instagram", icon: "camera"),
                  .init(id: "youtube", title: "YouTube", icon: "play.rectangle"),
                  .init(id: "app_store", title: "App Store", icon: "bag"),
                  .init(id: "google", title: "Google", icon: "magnifyingglass"),
                  .init(id: "friend", title: "Friend or family", icon: "person.2"),
                  .init(id: "other", title: "Other", icon: "ellipsis"),
              ]),
        // @step experience
        .init(id: "experience", kind: .question, title: "How familiar are you with this?",
              subtitle: "There are no wrong answers.", icon: "graduationcap", options: [
                  .init(id: "beginner", title: "I'm just starting"),
                  .init(id: "basics", title: "I know the basics"),
                  .init(id: "expert", title: "I'm an expert"),
              ]),
        // @endif
        // @step how_it_works
        .init(id: "how_it_works", kind: .info, title: "How it works",
              subtitle: "Three simple steps, every time.", icon: "wand.and.stars",
              bullets: ["Take or pick a photo", "Our AI analyzes it in seconds", "Get results made for you"]),
        // @if quiz
        // @step birth_year
        .init(id: "birth_year", kind: .picker, title: "What year were you born?",
              subtitle: "We use this to tailor your results.", icon: "calendar",
              picker: .wheel(range: BirthYears.range(), initial: 1995, unit: nil)),
        // @step frequency
        .init(id: "frequency", kind: .question, title: "How often would you use the app?",
              icon: "repeat", options: [
                  .init(id: "daily", title: "Every day"),
                  .init(id: "weekly", title: "A few times a week"),
                  .init(id: "occasionally", title: "Now and then"),
              ]),
        // @step right_place
        .init(id: "right_place", kind: .emotional, title: "You're in the right place",
              subtitle: "People with goals like yours make progress one small step at a time.",
              icon: "hand.thumbsup"),
        // @step daily_time
        .init(id: "daily_time", kind: .picker, title: "How much time can you spend each day?",
              subtitle: "Even a few minutes is enough.", icon: "timer",
              picker: .ruler(range: 5...60, initial: 15, unit: "min")),
        // @step obstacles
        .init(id: "obstacles", kind: .question, title: "What's holding you back?",
              icon: "exclamationmark.bubble", options: [
                  .init(id: "time", title: "Not enough time"),
                  .init(id: "start", title: "Not sure where to start"),
                  .init(id: "choices", title: "Too many choices"),
                  .init(id: "consistency", title: "Staying consistent"),
              ], multi: true),
        // @endif
        // @step comparison
        .init(id: "comparison", kind: .info, title: "Easier with a plan",
              subtitle: "A personal plan makes every step clearer than going it alone.",
              icon: "chart.line.uptrend.xyaxis"),
        // @if quiz
        // @step priority
        .init(id: "priority", kind: .question, title: "What matters most to you?",
              icon: "star.circle", options: [
                  .init(id: "accuracy", title: "Accuracy"),
                  .init(id: "speed", title: "Speed"),
                  .init(id: "simplicity", title: "Simplicity"),
                  .init(id: "inspiration", title: "Inspiration"),
              ]),
        // @step achieve
        .init(id: "achieve", kind: .question, title: "What would you like to achieve?",
              icon: "flag.checkered", options: [
                  .init(id: "confidence", title: "Feel more confident"),
                  .init(id: "better_choices", title: "Make better choices"),
                  .init(id: "save_money", title: "Save money"),
                  .init(id: "fun", title: "Have fun"),
              ], multi: true),
        // @step potential
        .init(id: "potential", kind: .emotional, title: "You have great potential",
              subtitle: "Your answers show you're ready. Small daily steps add up.", icon: "chart.xyaxis.line"),
        // @step schedule
        .init(id: "schedule", kind: .question, title: "When do you usually have time?",
              icon: "sun.max", options: [
                  .init(id: "morning", title: "Morning"),
                  .init(id: "afternoon", title: "Afternoon"),
                  .init(id: "evening", title: "Evening"),
                  .init(id: "varies", title: "It varies"),
              ]),
        // @step describe
        .init(id: "describe", kind: .question, title: "Which best describes you?",
              icon: "person.crop.circle", options: [
                  .init(id: "student", title: "Student"),
                  .init(id: "professional", title: "Professional"),
                  .init(id: "creator", title: "Creator"),
                  .init(id: "other", title: "Other"),
              ]),
        // @endif
        // @step privacy
        .init(id: "privacy", kind: .info, title: "Your privacy matters",
              subtitle: "You stay in control of your data.", icon: "lock.shield",
              bullets: ["We never sell your data", "Your answers stay private", "Delete everything anytime in Settings"]),
        // @step consent
        .init(id: "consent", kind: .permission, title: "Allow AI analysis",
              subtitle: "To personalize your results, your photos and answers are processed by our AI. You can withdraw consent anytime in Settings.",
              icon: "checkmark.shield"),
        // @if health
        // @step health
        .init(id: "health", kind: .permission, title: "Connect Apple Health",
              subtitle: "Sync your activity and weight so your plan stays accurate. You can change this anytime in Settings.",
              icon: "heart.text.square"),
        // @endif
        // @step trust
        .init(id: "trust", kind: .emotional, title: "Thank you for trusting us",
              subtitle: "We'll keep your information private and secure.", icon: "heart"),
        // @if quiz
        // @step tone
        .init(id: "tone", kind: .question, title: "How do you like your tips?",
              icon: "text.bubble", options: [
                  .init(id: "short", title: "Short and simple"),
                  .init(id: "detailed", title: "Detailed"),
                  .init(id: "visual", title: "Visual"),
              ]),
        // @step almost
        .init(id: "almost", kind: .info, title: "Almost there",
              subtitle: "We're using your answers to build a plan just for you.", icon: "hourglass"),
        // @endif
        // @step loading
        .init(id: "loading", kind: .loading, title: "Setting everything up for you",
              icon: "gearshape.2",
              bullets: ["Analyzing your answers", "Matching your goals", "Personalizing your plan"]),
        // @step finale
        .init(id: "finale", kind: .finale, title: "Your plan is ready!",
              subtitle: "Here's what we built from your answers.", icon: "checkmark.seal", cta: "Let's go"),
        // @if siwa
        // @step account
        .init(id: "account", kind: .account, title: "Save your progress",
              subtitle: "Sign in with Apple so your plan and purchases follow you to a new phone.",
              icon: "person.badge.key"),
        // @endif
        // @if hard_paywall
        // @step paywall
        .init(id: "paywall", kind: .paywall, title: "Unlock your plan"),
        // @endif
        // @if offer_paywall
        // @step offer
        .init(id: "offer", kind: .paywall, title: "One-time offer"),
        // @endif
        // @end-steps
    ]

    static func step(_ id: String) -> OnboardingStep? { steps.first { $0.id == id } }

    /// Localized title of an answer option, for the finale and the paywall.
    static func optionTitle(step: String, option: String) -> String? {
        guard let o = self.step(step)?.options.first(where: { $0.id == option }) else { return nil }
        return String(localized: o.title)
    }
}
