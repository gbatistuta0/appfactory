import XCTest

/// Launches the app in every shipped language (app.spec.json locales.app) and checks the welcome
/// title is the catalog's translation. Screenshots stay in the .xcresult for a visual review of
/// long German / Turkish lines.
final class LocalizationUITests: XCTestCase {
    private let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()

    private func json(_ rel: String) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent(rel))) as? [String: Any])
    }

    func testWelcomeIsTranslatedInEveryLanguage() throws {
        let spec = try json("app.spec.json")
        let languages = try XCTUnwrap((spec["locales"] as? [String: Any])?["app"] as? [String])
        let strings = try XCTUnwrap(try json("Resources/Localizable.xcstrings")["strings"] as? [String: [String: Any]])
        let key = "Your personal AI, ready in seconds"
        for lang in languages {
            let locs = strings[key]?["localizations"] as? [String: [String: Any]]
            let expected = (locs?[lang]?["stringUnit"] as? [String: Any])?["value"] as? String ?? key
            let app = XCUIApplication()
            let region = lang.contains("-") ? lang.replacingOccurrences(of: "-", with: "_") : "\(lang)_\(lang.uppercased())"
            app.launchArguments = ["-uiTest", "-resetOnboarding", "-AppleLanguages", "(\(lang))",
                                   "-AppleLocale", lang == "en" ? "en_US" : region]
            app.launch()
            let title = app.staticTexts.matching(identifier: "onb_title").firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 8), lang)
            XCTAssertEqual(title.label, expected, lang)
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.name = "welcome_\(lang)"
            shot.lifetime = .keepAlways
            add(shot)
            app.terminate()
        }
    }
}
