import StoreKit
import SwiftUI
import UIKit

/// App Store rating requests at success moments — mandatory in every AppFactory app, never inside
/// onboarding (App Review rejects an onboarding rating step).
///
/// This type only decides WHETHER to ask; asking is SwiftUI's `requestReview`, called from a view on
/// screen through `.ratingRequest($trigger)`. Every rule is a pure function of injected state
/// (`UserDefaults`, a clock, the rules), so the tests drive it without dates or the real app:
/// - Triggers: the core action succeeded `successCount` times on `distinctDays` different local days;
///   and each milestone (active days or a streak — the app decides what it counts) once, ever. The
///   highest unfired milestone reached wins, so a user who skipped past 7 is asked about 30, not 7.
/// - Guards: at least `minDaysBetween` days since the last request of any kind, at most `maxPerYear`
///   per trailing 365 days, never in a launch that saw a failed core action, a failed purchase or an
///   unsuccessful restore (`Tracker.log` flags those itself), never in test runs.
/// The rules come from app.spec.json (`rating`, rendered into `AppSpec`).
final class RatingPolicy {
    static let shared = RatingPolicy()

    struct Rules: Equatable {
        var successCount: Int
        var distinctDays: Int
        var milestones: [Int]
        var minDaysBetween: Double
        var maxPerYear: Int

        static let spec = Rules(successCount: AppSpec.ratingSuccessCount, distinctDays: AppSpec.ratingDistinctDays,
                                milestones: AppSpec.ratingMilestones, minDaysBetween: Double(AppSpec.ratingMinDaysBetween),
                                maxPerYear: AppSpec.ratingMaxPerYear)
    }

    enum Trigger: Hashable {
        case successes
        case milestone(Int)

        /// `rating_prompt_shown`'s `trigger` value.
        var source: String {
            switch self {
            case .successes: return "successes"
            case .milestone(let n): return "milestone_\(n)"
            }
        }
    }

    static let ledgerKey = "rating.ledger"          // [String]: ISO 8601 request times
    static let milestoneKey = "rating.milestones"   // [Int]: milestones already asked about
    static let yearWindowDays: Double = 365

    let rules: Rules
    private let defaults: UserDefaults
    /// A closure, not a stored date, so a test can move time forward.
    var now: () -> Date
    var isTestRun: Bool
    /// Session-scoped, never persisted: a bad moment taints the rest of this launch only.
    private(set) var badSessionThisLaunch = false

    /// Unit and UI tests never see the prompt; `-uiNoRatingPrompt` turns it off in a manual run.
    static var defaultIsTestRun: Bool {
        AppConfig.isAutomatedTestRun || ProcessInfo.processInfo.arguments.contains("-uiNoRatingPrompt")
    }

    init(rules: Rules = .spec, defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init,
         isTestRun: Bool = defaultIsTestRun) {
        self.rules = rules
        self.defaults = defaults
        self.now = now
        self.isTestRun = isTestRun
    }

    // MARK: - Session gate

    func markBadSession() { badSessionThisLaunch = true }

    /// Called by `Tracker.log` for every event: a failed core action, a failed purchase or a restore
    /// that found nothing makes this launch ineligible, so no call site can forget it.
    func note(_ event: Tracker.Event, _ props: [String: String]) {
        switch event {
        case .generateFail, .purchaseFail: markBadSession()
        case .paywallRestore where props["result"] != "active": markBadSession()
        default: break
        }
    }

    #if DEBUG
    func resetSessionForTests() { badSessionThisLaunch = false }
    #endif

    // MARK: - Triggers

    /// The core action succeeded; `total` successes so far on `distinctDays` local days. No flag of its
    /// own: once asked, the gap and the yearly cap stop it from firing on every later success.
    func request(forSuccessCount total: Int, distinctDays: Int) -> Trigger? {
        guard total >= rules.successCount, distinctDays >= rules.distinctDays else { return nil }
        return eligible() ? .successes : nil
    }

    /// Active days or a streak reached `value`: the highest milestone not asked about yet.
    func request(forMilestone value: Int) -> Trigger? {
        let fired = Set(defaults.array(forKey: Self.milestoneKey) as? [Int] ?? [])
        guard let m = rules.milestones.filter({ value >= $0 && !fired.contains($0) }).max() else { return nil }
        return eligible() ? .milestone(m) : nil
    }

    /// After `requestReview()` actually ran: the ledger entry, and a milestone never asks again.
    func recordRequest(_ trigger: Trigger) {
        var raw = defaults.stringArray(forKey: Self.ledgerKey) ?? []
        raw.append(ISO8601DateFormatter().string(from: now()))
        defaults.set(raw, forKey: Self.ledgerKey)
        if case .milestone(let m) = trigger {
            var fired = defaults.array(forKey: Self.milestoneKey) as? [Int] ?? []
            // Everything at or below the one asked about counts as done (the user is past them).
            fired += rules.milestones.filter { $0 <= m && !fired.contains($0) }
            defaults.set(fired, forKey: Self.milestoneKey)
        }
    }

    // MARK: - Guards

    private var ledger: [Date] {
        (defaults.stringArray(forKey: Self.ledgerKey) ?? []).compactMap { ISO8601DateFormatter().date(from: $0) }
    }

    private func eligible() -> Bool {
        guard !isTestRun, !badSessionThisLaunch else { return false }
        let requests = ledger
        if let last = requests.max(), now().timeIntervalSince(last) < rules.minDaysBetween * 86_400 { return false }
        let cutoff = now().addingTimeInterval(-Self.yearWindowDays * 86_400)
        return requests.filter { $0 >= cutoff }.count < rules.maxPerYear
    }

    // MARK: - Presentation

    /// Nothing is presented over the key window (no sheet, cover, alert or paywall): a rating request
    /// never lands on top of another modal.
    @MainActor static var nothingPresented: Bool {
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        guard let root = windows.first(where: \.isKeyWindow)?.rootViewController else { return false }
        return root.presentedViewController == nil
    }
}

extension View {
    /// Asks for an App Store rating when `trigger` is set: ~1.5 s later, once nothing is presented
    /// (waits up to a minute for a sheet to close, else drops it — the next success moment asks
    /// again, since nothing was recorded). Attach it to a view that stays on screen (the tab root).
    func ratingRequest(_ trigger: Binding<RatingPolicy.Trigger?>) -> some View {
        modifier(RatingRequestModifier(trigger: trigger))
    }
}

private struct RatingRequestModifier: ViewModifier {
    @Binding var trigger: RatingPolicy.Trigger?
    @Environment(\.requestReview) private var requestReview

    func body(content: Content) -> some View {
        content.task(id: trigger) {
            guard let pending = trigger else { return }
            for _ in 0..<40 {
                try? await Task.sleep(for: .milliseconds(1500))
                if Task.isCancelled { return }
                guard RatingPolicy.nothingPresented else { continue }
                requestReview()
                Tracker.log(.ratingPromptShown, ["trigger": pending.source])
                RatingPolicy.shared.recordRequest(pending)
                break
            }
            trigger = nil
        }
    }
}
