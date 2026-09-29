import XCTest
@testable import __APP_NAME__

/// Success-moment App Store rating requests (mandatory in every AppFactory app; never in onboarding —
/// App Review rejects an onboarding rating step). Every trigger and guard of `RatingPolicy`, with
/// injected `UserDefaults`, clock, rules and `isTestRun: false`.
final class RatingPolicyTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    private let rules = RatingPolicy.Rules(successCount: 5, distinctDays: 3, milestones: [7, 30], minDaysBetween: 60, maxPerYear: 3)

    private func policy(_ defaults: UserDefaults = UserDefaults(suiteName: "rating-\(UUID())")!,
                        at date: Date? = nil) -> RatingPolicy {
        let now = date ?? start
        return RatingPolicy(rules: rules, defaults: defaults, now: { now }, isTestRun: false)
    }

    private func days(_ n: Double) -> TimeInterval { n * 86_400 }

    // MARK: Triggers

    func testSuccessesNeedBothCounts() {
        let p = policy()
        XCTAssertNil(p.request(forSuccessCount: 4, distinctDays: 3))
        XCTAssertNil(p.request(forSuccessCount: 5, distinctDays: 2))
        XCTAssertEqual(p.request(forSuccessCount: 5, distinctDays: 3), .successes, "the first request a user can see")
    }

    func testSuccessesStopOnceAskedEvenIfCountsStillQualify() {
        let p = policy()
        p.recordRequest(.successes)
        XCTAssertNil(p.request(forSuccessCount: 9, distinctDays: 6), "the 60-day gap, not a separate flag")
    }

    func testHighestUnfiredMilestoneWinsAndNeverRepeats() {
        let defaults = UserDefaults(suiteName: "rating-\(UUID())")!
        let p = policy(defaults)
        XCTAssertNil(p.request(forMilestone: 6))
        XCTAssertEqual(p.request(forMilestone: 31), .milestone(30), "skipped past 7: asks about 30, not a stale 7")
        p.recordRequest(.milestone(30))
        let later = policy(defaults, at: start.addingTimeInterval(days(400)))
        XCTAssertNil(later.request(forMilestone: 45), "7 and 30 are both done")
    }

    func testMilestonesFireIndependentlyOverTime() {
        let defaults = UserDefaults(suiteName: "rating-\(UUID())")!
        let p = policy(defaults)
        XCTAssertEqual(p.request(forMilestone: 7), .milestone(7))
        p.recordRequest(.milestone(7))
        let later = policy(defaults, at: start.addingTimeInterval(days(61)))
        XCTAssertEqual(later.request(forMilestone: 30), .milestone(30))
    }

    // MARK: Guards

    func testAtLeastSixtyDaysBetweenRequests() {
        let defaults = UserDefaults(suiteName: "rating-\(UUID())")!
        policy(defaults).recordRequest(.successes)
        XCTAssertNil(policy(defaults, at: start.addingTimeInterval(days(59))).request(forMilestone: 7))
        XCTAssertEqual(policy(defaults, at: start.addingTimeInterval(days(61))).request(forMilestone: 7), .milestone(7))
    }

    func testAtMostThreePerTrailingYearAndTheCapRollsOff() {
        let defaults = UserDefaults(suiteName: "rating-\(UUID())")!
        var day = start
        for _ in 0..<3 {
            let p = policy(defaults, at: day)
            XCTAssertNotNil(p.request(forSuccessCount: 5, distinctDays: 3))
            p.recordRequest(.successes)
            day = day.addingTimeInterval(days(61))
        }
        XCTAssertNil(policy(defaults, at: day).request(forSuccessCount: 5, distinctDays: 3), "3 in the trailing year")
        XCTAssertNotNil(policy(defaults, at: start.addingTimeInterval(days(400))).request(forSuccessCount: 5, distinctDays: 3))
    }

    func testABadMomentBlocksTheRestOfTheLaunchOnly() {
        let defaults = UserDefaults(suiteName: "rating-\(UUID())")!
        let p = policy(defaults)
        p.note(.generateFail, ["reason": "server"])
        XCTAssertNil(p.request(forSuccessCount: 5, distinctDays: 3))
        XCTAssertNil(p.request(forMilestone: 7))
        XCTAssertNotNil(policy(defaults).request(forSuccessCount: 5, distinctDays: 3), "the next launch starts clean")
    }

    func testWhichEventsTaintTheSession() {
        for (event, props, bad) in [(Tracker.Event.purchaseFail, ["reason": "store_not_ready"], true),
                                    (.paywallRestore, ["result": "none"], true),
                                    (.paywallRestore, ["result": "active"], false),
                                    (.generateSuccess, [:], false), (.tabSelect, ["tab": "gallery"], false)] {
            let p = policy()
            p.note(event, props)
            XCTAssertEqual(p.badSessionThisLaunch, bad, "\(event) \(props)")
        }
    }

    func testTrackerFlagsTheSharedPolicy() {
        RatingPolicy.shared.resetSessionForTests()
        Tracker.log(.generateFail, ["reason": "bad_response"])
        XCTAssertTrue(RatingPolicy.shared.badSessionThisLaunch)
        RatingPolicy.shared.resetSessionForTests()
    }

    func testTestRunsNeverAsk() {
        let p = RatingPolicy(rules: rules, defaults: UserDefaults(suiteName: "rating-\(UUID())")!, isTestRun: true)
        XCTAssertNil(p.request(forSuccessCount: 100, distinctDays: 100))
        XCTAssertTrue(RatingPolicy.defaultIsTestRun, "unit tests count as a test run")
    }

    // MARK: Wiring

    /// The spec's rules reach the binary, and they never go below Apple's limits.
    func testSpecRulesAreSafe() {
        XCTAssertGreaterThanOrEqual(RatingPolicy.Rules.spec.minDaysBetween, 60)
        XCTAssertLessThanOrEqual(RatingPolicy.Rules.spec.maxPerYear, 3)
    }

    /// Never inside onboarding: no onboarding source asks for a review; the main app does.
    func testNoRatingRequestInOnboarding() throws {
        let files = FileManager.default.enumerator(at: TestPaths.sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" } ?? []
        var asked = false
        for url in files {
            let text = try String(contentsOf: url, encoding: .utf8)
            if url.path.contains("/Onboarding/") {
                XCTAssertFalse(text.contains("requestReview"), "\(url.lastPathComponent) asks for a rating in onboarding")
            } else if text.contains(".ratingRequest(") {
                asked = true
            }
        }
        XCTAssertTrue(asked, "a success moment must call .ratingRequest(…)")
    }
}
