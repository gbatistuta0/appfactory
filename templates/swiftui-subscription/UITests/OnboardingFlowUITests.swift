import XCTest

/// Walks the whole onboarding generically (whatever the features stage puts in it): answers every
/// question with its first option, passes pickers / consent / account, reaches the hard paywall,
/// closes it, dismisses the one-time offer and lands in the main app.
final class OnboardingFlowUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTest", "-resetOnboarding", "-trialEligible", "NO"] + extra
        app.launch()
        return app
    }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    // @if hard_paywall
    func testFullFunnelToMainApp() {
        let app = launch()
        let cta = app.buttons["onb_cta"]
        let paywall = app.buttons["paywall_cta"]
        var screens = 0
        while !paywall.exists && screens < 60 {
            screens += 1
            if app.buttons["account_skip"].exists { app.buttons["account_skip"].tap(); continue }
            if app.staticTexts["loading_percent"].exists { _ = paywall.waitForExistence(timeout: 0.5); continue }
            guard cta.waitForExistence(timeout: 5) else { break }
            let consent = app.switches["consent_switch"].exists ? app.switches["consent_switch"] : app.buttons["consent_switch"]
            if consent.exists, !cta.isEnabled { consent.tap() }
            if !cta.isEnabled {
                let option = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'option_'")).firstMatch
                XCTAssertTrue(option.exists, "a disabled CTA must be unlocked by an answer")
                XCTAssertFalse(option.isSelected, "nothing is preselected")
                option.tap()
            }
            if screens <= 3 { snap(app, "onboarding_\(screens)") }
            cta.tap()
        }
        XCTAssertTrue(paywall.waitForExistence(timeout: 10), "reached the hard paywall after \(screens) screens")
        XCTAssertTrue(app.staticTexts["paywall_title"].exists)
        XCTAssertEqual(paywall.label, "Continue", "no trial copy when not eligible")
        XCTAssertTrue(app.buttons["paywall_restore"].exists)
        snap(app, "paywall_hard")

        // The close button fades in after a delay (hit-testing off until then).
        let close = app.buttons["paywall_close"]
        let hittable = expectation(for: NSPredicate(format: "isHittable == true"), evaluatedWith: close)
        wait(for: [hittable], timeout: 8)
        close.tap()
        // @if offer_paywall
        let noThanks = app.buttons["offer_no_thanks"]
        if !noThanks.waitForExistence(timeout: 5) {
            snap(app, "after_close")
            XCTFail(app.staticTexts["create_intro"].exists
                    ? "the offer was skipped (offer_paywall_seen already set?) — went straight to the main app"
                    : "offer did not appear after dismissing the hard paywall:\n\(app.debugDescription.prefix(3000))")
            return
        }
        XCTAssertTrue(app.buttons["offer_cta"].exists)
        snap(app, "paywall_offer")
        // Leave through the offer's X: the overlaid close buttons once swallowed taps.
        XCTAssertTrue(noThanks.isHittable)
        let offerClose = app.buttons["paywall_close"]
        wait(for: [expectation(for: NSPredicate(format: "isHittable == true"), evaluatedWith: offerClose)], timeout: 8)
        offerClose.tap()
        // @endif
        XCTAssertTrue(app.staticTexts["create_intro"].waitForExistence(timeout: 5), "main app after the funnel")
    }
    // @endif
    // @if !hard_paywall
    /// No hard paywall: the last onboarding step lands in the main app.
    func testOnboardingEndsInTheMainApp() {
        let app = launch()
        let cta = app.buttons["onb_cta"]
        let main = app.staticTexts["create_intro"]
        var screens = 0
        while !main.exists && screens < 60 {
            screens += 1
            if app.buttons["account_skip"].exists { app.buttons["account_skip"].tap(); continue }
            if app.staticTexts["loading_percent"].exists { _ = main.waitForExistence(timeout: 0.5); continue }
            guard cta.waitForExistence(timeout: 5) else { break }
            let consent = app.switches["consent_switch"].exists ? app.switches["consent_switch"] : app.buttons["consent_switch"]
            if consent.exists, !cta.isEnabled { consent.tap() }
            if !cta.isEnabled {
                let option = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'option_'")).firstMatch
                XCTAssertTrue(option.exists, "a disabled CTA must be unlocked by an answer")
                option.tap()
            }
            if screens <= 3 { snap(app, "onboarding_\(screens)") }
            cta.tap()
        }
        XCTAssertTrue(main.waitForExistence(timeout: 10), "onboarding ends in the main app after \(screens) screens")
        XCTAssertFalse(app.buttons["paywall_cta"].exists, "no paywall in the funnel")
    }
    // @endif

    func testTrialCopyOnlyWhenEligible() {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTest", "-uiPaywall", "-trialEligible", "YES"]
        app.launch()
        let cta = app.buttons["paywall_cta"]
        XCTAssertTrue(cta.waitForExistence(timeout: 5))
        XCTAssertEqual(cta.label, "Start my free trial")
        XCTAssertEqual(cta.value as? String, "demo", "automated runs use the spec's demo prices")
        let badge = app.staticTexts.matching(NSPredicate(format: "identifier ENDSWITH '_badge'")).firstMatch
        XCTAssertTrue(badge.exists, "SAVE x% badge on the best-value plan")
        snap(app, "paywall_trial")
    }
}
