import XCTest
@testable import __APP_NAME__

/// Every String Catalog key is translated in every shipped language (spec `locales.app`), no key
/// is stale, format specifiers match the English source, and every literal UI key in Sources/ is
/// in the catalog. Fails the build's test run before a half-English screen can ship.
final class LocalizationCompletenessTests: XCTestCase {
    private var targets: [String] { AppSpec.appLocales.filter { $0 != "en" } }

    private func strings(_ url: URL) throws -> [String: [String: Any]] {
        try XCTUnwrap(TestPaths.json(url)["strings"] as? [String: [String: Any]])
    }

    func testEveryKeyIsTranslatedInEveryLanguage() throws {
        for url in [TestPaths.catalog, TestPaths.infoPlistCatalog] {
            var problems: [String] = []
            for (key, entry) in try strings(url) {
                if entry["shouldTranslate"] as? Bool == false || key.trimmingCharacters(in: .whitespaces).isEmpty { continue }
                if entry["extractionState"] as? String == "stale" { problems.append("stale: \(key)"); continue }
                let locs = entry["localizations"] as? [String: Any] ?? [:]
                for lang in targets {
                    let values = Self.values(locs[lang])
                    if values.isEmpty { problems.append("\(lang) missing: \(key)"); continue }
                    for (state, value) in values {
                        if state != "translated" || value.isEmpty { problems.append("\(lang) \(state): \(key)") }
                        let source = Self.values(locs["en"]).first?.1 ?? key
                        if Self.specifiers(value) != Self.specifiers(source) {
                            problems.append("\(lang) specifiers \(Self.specifiers(value)) ≠ \(Self.specifiers(source)): \(key)")
                        }
                    }
                }
                for lang in locs.keys where lang != "en" && !targets.contains(lang) {
                    problems.append("unshipped language \(lang): \(key)")
                }
            }
            XCTAssertTrue(problems.isEmpty, "\(url.lastPathComponent):\n" + problems.sorted().prefix(40).joined(separator: "\n"))
        }
    }

    func testEveryLiteralUIKeyIsInTheCatalog() throws {
        let catalog = try strings(TestPaths.catalog)
        var missing: Set<String> = []
        let files = FileManager.default.enumerator(at: TestPaths.sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" } ?? []
        XCTAssertFalse(files.isEmpty)
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for key in Self.literalKeys(in: text) where catalog[key] == nil { missing.insert("\(file.lastPathComponent): \(key)") }
        }
        XCTAssertTrue(missing.isEmpty, "keys missing from Localizable.xcstrings:\n" + missing.sorted().joined(separator: "\n"))
    }

    // @if offer_paywall
    func testOfferAnchorKeyIsTranslated() throws {
        let entry = try XCTUnwrap(try strings(TestPaths.catalog)[AppSpec.offerAnchorKey], AppSpec.offerAnchorKey)
        let locs = entry["localizations"] as? [String: Any] ?? [:]
        XCTAssertFalse(Self.values(locs["en"]).isEmpty, "semantic key needs an English value")
    }
    // @endif

    // MARK: - Helpers

    /// (state, value) of a localization, including plural/device variations.
    static func values(_ loc: Any?) -> [(String, String)] {
        guard let loc = loc as? [String: Any] else { return [] }
        var out: [(String, String)] = []
        if let unit = loc["stringUnit"] as? [String: Any] {
            out.append((unit["state"] as? String ?? "new", unit["value"] as? String ?? ""))
        }
        for kind in (loc["variations"] as? [String: [String: Any]] ?? [:]).values {
            for variant in kind.values { out += values(variant) }
        }
        return out
    }

    /// Format specifiers as a sorted list, positional forms normalized (%1$@ → %@).
    static func specifiers(_ s: String) -> [String] {
        let regex = try! NSRegularExpression(pattern: #"%(?:\d+\$)?(?:ll|l)?[@dDuUxXoOfeEgGcCsSaAp]"#)
        let ns = s as NSString
        return regex.matches(in: s, range: NSRange(location: 0, length: ns.length)).map {
            ns.substring(with: $0.range).replacingOccurrences(of: #"\d+\$"#, with: "", options: .regularExpression)
        }.sorted()
    }

    /// Literal keys passed to localizing APIs (no interpolation): Text("…"), Button("…"),
    /// Label("…"), title:/subtitle:/cta:/unit: "…", String(localized: "…"), bullets arrays.
    static func literalKeys(in text: String) -> Set<String> {
        let patterns = [
            #"\bText\(\s*"([^"\\]+)"\s*\)"#,
            #"\bButton\(\s*"([^"\\]+)""#,
            #"\bLabel\(\s*"([^"\\]+)""#,
            #"\b(?:title|subtitle|cta|unit|label):\s*"([^"\\]+)""#,
            #"String\(localized:\s*"([^"\\]+)""#,
            #"\.alert\(\s*"([^"\\]+)""#,
            #"confirmationDialog\(\s*"([^"\\]+)""#,
            #"segment\(\.\w+,\s*"([^"\\]+)""#,
        ]
        var keys: Set<String> = []
        let ns = text as NSString
        for p in patterns {
            let regex = try! NSRegularExpression(pattern: p)
            for m in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
                keys.insert(ns.substring(with: m.range(at: 1)))
            }
        }
        // bullets: ["…", "…"]
        let bullets = try! NSRegularExpression(pattern: #"bullets:\s*\[([^\]]+)\]"#)
        let item = try! NSRegularExpression(pattern: #""([^"\\]+)""#)
        for m in bullets.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            let inner = ns.substring(with: m.range(at: 1)) as NSString
            for i in item.matches(in: inner as String, range: NSRange(location: 0, length: inner.length)) {
                keys.insert(inner.substring(with: i.range(at: 1)))
            }
        }
        // Not UI copy: identifiers, SF Symbols, fonts, JSON keys.
        return keys.filter { key in
            !key.isEmpty && !key.hasPrefix("appfactory") && key.rangeOfCharacter(from: .letters) != nil
                && !(key.contains(".") && !key.contains(" ")) && key != "Default"
        }
    }
}
