import XCTest

/// Walks the whole onboarding (to the hard paywall) and audits every screen with LayoutAudit:
/// overflow, truncation (Vision OCR), English leftovers, missing glyphs, sheets and occlusion.
///
/// Languages: `TEST_RUNNER_AUDIT_LANGS` = "all" (every spec.locales.app language), a comma list
/// ("de,tr,ar"), or unset = English only for the everyday test run. Run "all" on the smallest
/// (SE) and the largest (Pro Max) simulator before store captures: German and Turkish run longest,
/// CJK has no spaces to break at, Arabic and Hebrew mirror the layout.
final class LayoutAuditUITests: XCTestCase {
    override func setUp() { continueAfterFailure = true }

    private var languages: [String] {
        let raw = ProcessInfo.processInfo.environment["AUDIT_LANGS"] ?? ""
        guard raw == "all" else { return raw.isEmpty ? ["en"] : raw.split(separator: ",").map(String.init) }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let spec = (try? JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("app.spec.json")))) as? [String: Any]
        return ((spec?["locales"] as? [String: Any])?["app"] as? [String]) ?? ["en"]
    }

    func testOnboardingLayoutInEveryLanguage() {
        for lang in languages {
            let app = XCUIApplication()
            let region = lang.contains("-") ? lang.replacingOccurrences(of: "-", with: "_") : "\(lang)_\(lang.uppercased())"
            app.launchArguments = ["-uiTest", "-resetOnboarding", "-trialEligible", "NO", "-AppleLanguages", "(\(lang))",
                                   "-AppleLocale", lang == "en" ? "en_US" : region]
            app.launch()
            let cta = app.buttons["onb_cta"]
            // @if hard_paywall
            let paywall = app.buttons["paywall_cta"]
            // @endif
            // @if !hard_paywall
            let paywall = app.staticTexts["create_intro"] // the funnel ends in the main app
            // @endif
            var screen = 0
            while !paywall.exists && screen < 60 {
                screen += 1
                if app.buttons["account_skip"].exists { app.buttons["account_skip"].tap(); continue }
                if app.staticTexts["loading_percent"].exists { _ = paywall.waitForExistence(timeout: 0.5); continue }
                guard cta.waitForExistence(timeout: 5) else { break }
                let consent = app.switches["consent_switch"].exists ? app.switches["consent_switch"] : app.buttons["consent_switch"]
                if consent.exists, !cta.isEnabled { consent.tap() }
                if !cta.isEnabled {
                    app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'option_'")).firstMatch.tap()
                }
                LayoutAudit.assertClean(app, lang: lang, screen: "onboarding_\(screen)")
                cta.tap()
            }
            // @if hard_paywall
            if paywall.waitForExistence(timeout: 10) {
                LayoutAudit.assertClean(app, lang: lang, screen: "paywall_hard")
            } else {
                XCTFail("\(lang): the hard paywall never appeared")
            }
            // @endif
            // @if !hard_paywall
            if paywall.waitForExistence(timeout: 10) {
                LayoutAudit.assertClean(app, lang: lang, screen: "main_create")
            } else {
                XCTFail("\(lang): onboarding never reached the main app")
            }
            // @endif
            app.terminate()
        }
    }
}
