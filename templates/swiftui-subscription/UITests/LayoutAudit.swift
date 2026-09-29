import CoreText
import UIKit
import Vision
import XCTest

/// Layout and language audit of whatever is on screen (the audit that caught
/// every truncation, overflow and English leftover of a 30-language, 3-device store pass):
///
/// - Overflow: every element outside a scroll container lies inside the window horizontally; buttons
///   lie inside it vertically too; text is not cut by the screen edge.
/// - Pinned CTA: a wide bottom button keeps 12 pt from the bottom edge (34 pt with a home indicator).
/// - Truncation: SwiftUI keeps the full string in the accessibility label even when it draws "…", so
///   the screenshot is read with Vision OCR; an ellipsis that no label contains is a cut.
/// - Language: a visible label equal to an English source string whose translation in this language
///   differs is an English leftover (read from Localizable.xcstrings; simulator only).
/// - Glyphs: every character of a visible label has a glyph in some system font (no "tofu" boxes).
/// - Sheets: a `sheet_*` element fits its content (at most 24 pt plus the covered safe area below
///   it) and has no band of plain background over 120 pt.
/// - Occlusion: no text under the tab bar, a pinned bottom button or an `overlay_*` element; the main
///   scroll view is scrolled to its end so the last row must be able to scroll clear.
///
/// Call `LayoutAudit.assertClean(app, lang:)` on every screen of a capture or UI-test walk.
enum LayoutAudit {
    struct Finding: CustomStringConvertible {
        var kind: String
        var detail: String
        var description: String { "\(kind): \(detail)" }
    }

    /// Fails the test with every finding (and prints `LAYOUT` lines a capture script can grep).
    static func assertClean(_ app: XCUIApplication, lang: String, screen: String, scrolls: Bool = true,
                            file: StaticString = #filePath, line: UInt = #line) {
        let findings = run(app, lang: lang, scrolls: scrolls).findings
        for f in findings { print("LAYOUT FAIL \(lang) \(screen) \(f)") }
        XCTAssertTrue(findings.isEmpty, "\(screen) [\(lang)]: \(findings.map(\.description).joined(separator: "; "))",
                      file: file, line: line)
    }

    /// The findings plus every visible accessibility label. `scrolls: false` audits the screen as it is.
    static func run(_ app: XCUIApplication, lang: String, scrolls: Bool = true) -> (findings: [Finding], labels: [String]) {
        guard let root = try? app.snapshot() else { return ([Finding(kind: "audit", detail: "no snapshot")], []) }
        let window = root.frame
        var findings: [Finding] = []
        var labels: [String] = []
        var pinned: [(String, CGRect)] = []

        func walk(_ node: XCUIElementSnapshot, inScroll: Bool, inKeyboard: Bool = false) {
            let type = node.elementType
            let inKeyboard = inKeyboard || type == .keyboard
            // Scroll containers, system UI and horizontal rulers may extend past the window by design.
            let scroll = inScroll || [.scrollView, .collectionView, .table, .keyboard, .pickerWheel, .alert, .sheet].contains(type)
                || node.identifier.contains("ruler") || node.identifier == "PopoverDismissRegion"
            let f = node.frame
            // The system keyboard follows the keyboard language, not the app's.
            if !node.label.isEmpty, !inKeyboard { labels.append(node.label) }
            // Anonymous containers are layout plumbing; the content inside them is still checked.
            let anonymous = type == .other && node.label.isEmpty && node.identifier.isEmpty
            if f.width > 0, f.height > 0, type != .application, type != .window, !scroll, !anonymous {
                if type == .button, f.width >= window.width * 0.6 { pinned.append((describe(node), f)) }
                if f.minX < window.minX - 1 || f.maxX > window.maxX + 1 {
                    findings.append(Finding(kind: "overflow-x", detail: describe(node)))
                }
                let visible = f.intersection(window)
                if type == .button, visible.isNull || visible.height < f.height - 1 {
                    findings.append(Finding(kind: "button-offscreen", detail: describe(node) + " y \(Int(f.minY))…\(Int(f.maxY))"))
                }
                if type == .staticText, !node.label.isEmpty, f.maxY > window.maxY + 1 || f.minY < window.minY - 1 {
                    findings.append(Finding(kind: "clipped-y", detail: describe(node) + " y \(Int(f.minY))…\(Int(f.maxY))"))
                }
            }
            for child in node.children { walk(child, inScroll: scroll, inKeyboard: inKeyboard) }
        }
        walk(root, inScroll: false)
        findings += ctaEdge(pinned, window: window)
        findings += glyphs(labels)
        findings += sheets(root, window: window)
        findings += occlusions(root, window: window, atEnd: false)
        // The screen as it was, before any scrolling.
        let shot = app.screenshot().image
        // Under a sheet the screen behind is not the one being judged.
        let sheetUp = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'sheet_'")).firstMatch.exists
        if scrolls, !sheetUp, let end = scrolledToEnd(app) {
            findings += occlusions(end, window: window, atEnd: true)
        }
        findings += truncations(in: shot, labels: labels, lang: lang)
        if lang != "en", let index = StringsIndex.shared {
            for label in Set(labels) where index.isEnglishLeftover(label, lang: lang) {
                findings.append(Finding(kind: "english", detail: "“\(label)”"))
            }
        }
        var seen = Set<String>()
        return (findings, labels.filter { seen.insert($0).inserted })
    }

    // MARK: Pinned CTAs

    /// A pinned primary button keeps clear of the bottom edge (on SE, Continue once sat flush on it):
    /// at least 12 pt without a home indicator, above the indicator's 34 pt with one.
    static func ctaEdge(_ buttons: [(String, CGRect)], window: CGRect) -> [Finding] {
        let limit = window.maxY - (window.height >= 812 ? 34 : 12)
        return buttons.filter { $0.1.maxY > limit + 0.5 }.map {
            Finding(kind: "cta-edge", detail: "\($0.0) ends \(Int(window.maxY - $0.1.maxY)) pt above the screen's bottom edge")
        }
    }

    // MARK: Sheets

    private static func sheets(_ root: XCUIElementSnapshot, window: CGRect) -> [Finding] {
        let leaves: Set<XCUIElement.ElementType> = [.staticText, .button, .image, .textField, .secureTextField, .switch,
                                                    .toggle, .slider, .picker, .pickerWheel, .link, .icon]
        var out: [Finding] = []
        func check(_ sheet: XCUIElementSnapshot) {
            var frames: [CGRect] = []
            func collect(_ n: XCUIElementSnapshot) {
                for c in n.children {
                    let f = c.frame
                    let named = !c.identifier.isEmpty && c.elementType != .scrollView && f.height < sheet.frame.height * 0.8
                    if leaves.contains(c.elementType) || named, f.width > 0, f.height > 0 { frames.append(f) }
                    collect(c)
                }
            }
            collect(sheet)
            out += sheetFit(sheet.identifier, sheet: sheet.frame, content: frames, window: window)
        }
        func visit(_ n: XCUIElementSnapshot) {
            if n.identifier.hasPrefix("sheet_") { check(n) } else { n.children.forEach(visit) }
        }
        visit(root)
        return out
    }

    /// The sheet rule on frames alone (LayoutAuditRuleTests proves it still fails real defects).
    /// Measured to the sheet's own bottom: iOS 26 floats a partial sheet 8 pt above the screen edge.
    static func sheetFit(_ id: String, sheet: CGRect, content frames: [CGRect], window: CGRect) -> [Finding] {
        guard !frames.isEmpty else { return [] }
        let safeBottom: CGFloat = window.height >= 812 ? 34 : 0
        var out: [Finding] = []
        var runs: [(minY: CGFloat, maxY: CGFloat)] = []
        for f in frames.sorted(by: { $0.minY < $1.minY }) {
            if let last = runs.last, f.minY <= last.maxY + 1 {
                runs[runs.count - 1].maxY = max(last.maxY, f.maxY)
            } else {
                runs.append((f.minY, f.maxY))
            }
        }
        for (a, b) in zip(runs, runs.dropFirst()) where b.minY - a.maxY > 120 {
            out.append(Finding(kind: "sheet-gap", detail: "\(id) \(Int(b.minY - a.maxY)) pt empty at y \(Int(a.maxY))…\(Int(b.minY))"))
        }
        let bottom = runs.last!.maxY
        let edge = min(window.maxY, sheet.maxY)
        let below = edge - bottom
        let allowed = 24 + (edge > window.maxY - safeBottom ? safeBottom : 0)
        if bottom < edge - 1, below > allowed + 1 {
            out.append(Finding(kind: "sheet-tall", detail: "\(id) \(Int(below)) pt below its content (max \(Int(allowed)))"))
        }
        return out
    }

    private static func describe(_ node: XCUIElementSnapshot) -> String {
        let name = !node.identifier.isEmpty ? node.identifier : String(node.label.prefix(40))
        return "\(node.elementType.rawValue) “\(name)” x \(Int(node.frame.minX))…\(Int(node.frame.maxX))"
    }

    // MARK: Glyphs

    private static func hasGlyphs(_ font: CTFont, _ s: String) -> Bool {
        let utf16 = Array(s.utf16)
        var glyphs = [CGGlyph](repeating: 0, count: utf16.count)
        return CTFontGetGlyphsForCharacters(font, utf16, &glyphs, utf16.count)
    }

    /// Characters no system font can draw (they render as a box). Brand fonts that lack a script must
    /// fall back to the system font for that language (e.g. Figtree has no Cyrillic, CJK or Arabic).
    static func glyphs(_ labels: [String]) -> [Finding] {
        let system = UIFont.systemFont(ofSize: 15) as CTFont
        var missing = Set<String>()
        for label in Set(labels) {
            for c in label where !c.isWhitespace && !c.isNewline && !isInvisibleFormat(c) {
                let s = String(c)
                let used = CTFontCreateForString(system, s as CFString, CFRange(location: 0, length: s.utf16.count))
                if (CTFontCopyPostScriptName(used) as String) == "LastResort" || !hasGlyphs(used, s) {
                    missing.insert("\(s) U+\(String(c.unicodeScalars.first!.value, radix: 16, uppercase: true))")
                }
            }
        }
        return missing.sorted().map { Finding(kind: "glyph", detail: $0) }
    }

    /// Format characters draw nothing (soft hyphen, zero-width spaces/joiners, the word joiner).
    static func isInvisibleFormat(_ c: Character) -> Bool {
        c.unicodeScalars.allSatisfy { $0.properties.generalCategory == .format }
    }

    // MARK: Occlusion

    /// Covers: the tab bar, full-width buttons pinned at the bottom (outside any scroll view) and
    /// `overlay_*` decorations. Text under one of them (and not part of it) is hidden.
    private static func occlusions(_ root: XCUIElementSnapshot, window: CGRect, atEnd: Bool) -> [Finding] {
        var covers: [(String, CGRect)] = []
        var texts: [(String, CGRect, CGRect?)] = []
        var purchase = false
        func walk(_ node: XCUIElementSnapshot, scrollFrame: CGRect?, inCover: Bool) {
            let type = node.elementType
            if [.alert, .sheet, .keyboard].contains(type) { return }
            let scroll = [.scrollView, .collectionView, .table].contains(type) ? node.frame : scrollFrame
            let f = node.frame
            if ["paywall_cta", "offer_cta"].contains(node.identifier) { purchase = true }
            var cover = false
            if type == .tabBar || node.identifier.hasPrefix("overlay_") {
                cover = true
            } else if type == .button, scroll == nil, f.width > window.width * 0.6, f.minY > window.height * 0.75 {
                cover = true
            }
            if cover { covers.append((node.identifier.isEmpty ? node.label : node.identifier, f)) }
            if type == .staticText, !inCover, !cover, !node.label.isEmpty, f.width > 0, f.height > 0 {
                texts.append((node.label, f, scroll))
            }
            for child in node.children {
                walk(child, scrollFrame: scroll, inCover: inCover || cover || type == .tabBar)
            }
        }
        walk(root, scrollFrame: nil, inCover: false)
        var out: [Finding] = []
        for (label, f, scrollFrame) in texts {
            let inScroll = scrollFrame != nil
            // After scrolling to the end the last rows must be fully visible; on a paywall nothing may
            // hide behind the price tiles even at rest.
            if let sf = scrollFrame, atEnd || purchase, f.maxY > sf.maxY + 1, f.minY < sf.maxY {
                out.append(Finding(kind: atEnd ? "clipped-at-end" : "under-purchase-block", detail: "“\(label.prefix(40))”"))
            }
            if inScroll && !atEnd { continue }
            if !inScroll && atEnd { continue }
            for (name, c) in covers where f.insetBy(dx: 2, dy: 2).intersects(c) {
                out.append(Finding(kind: atEnd ? "occluded-at-end" : "occluded", detail: "“\(label.prefix(40))” under \(name)"))
            }
        }
        return out
    }

    /// Scrolls the main (largest visible) scroll view to its end and snapshots it, then scrolls back.
    /// The drag runs down the list's trailing margin: from its center it moved sliders instead, and
    /// the leading edge is the system back swipe.
    private static func scrolledToEnd(_ app: XCUIApplication) -> XCUIElementSnapshot? {
        let window = app.frame
        func visibleArea(_ e: XCUIElement) -> CGFloat {
            let r = e.frame.intersection(window)
            return r.isNull ? 0 : r.width * r.height
        }
        func mainList() -> XCUIElement? {
            app.scrollViews.allElementsBoundByIndex.filter { $0.exists && $0.isHittable }
                .reversed().max(by: { visibleArea($0) < visibleArea($1) })
        }
        guard mainList() != nil,
              app.tabBars.firstMatch.exists || app.buttons.matching(NSPredicate(format: "identifier ENDSWITH '_cta'")).count > 0
        else { return nil }
        func swipe(up: Bool) {
            guard let list = mainList() else { return }
            let low = list.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.85))
            let high = list.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.15))
            (up ? low : high).press(forDuration: 0.01, thenDragTo: up ? high : low, withVelocity: .fast, thenHoldForDuration: 0)
        }
        var before = mainList()?.debugDescription ?? ""
        var moved = false
        for _ in 0..<8 {
            swipe(up: true)
            Thread.sleep(forTimeInterval: 0.6)
            guard let now = mainList()?.debugDescription, now != before else { break }
            before = now
            moved = true
        }
        Thread.sleep(forTimeInterval: 1.5)   // let the momentum and the bounce finish
        let snap = try? app.snapshot()
        // Never drag down inside a sheet: that dismisses it.
        if moved, !app.otherElements["PopoverDismissRegion"].exists {
            for _ in 0..<6 { swipe(up: false) }
            Thread.sleep(forTimeInterval: 1.0)
        }
        return snap
    }

    // MARK: Truncation (Vision OCR)

    /// Vision's languages for an app language ("ja" → ja-JP, "zh-Hant" → zh-Hant), then English
    /// (digits, units, brand names); a language Vision cannot read is checked with English only.
    static func ocrLanguages(_ lang: String, supported: [String]) -> [String] {
        guard lang != "en" else { return ["en-US"] }
        if let exact = supported.first(where: { $0.caseInsensitiveCompare(lang) == .orderedSame }) { return [exact, "en-US"] }
        let base = lang.split(separator: "-").first.map(String.init) ?? lang
        let own = supported.filter { $0.split(separator: "-").first.map(String.init) == base && !$0.hasPrefix("zh") }
        return Array(own.prefix(1)) + ["en-US"]
    }

    private static func truncations(in image: UIImage, labels: [String], lang: String) -> [Finding] {
        guard let cg = image.cgImage else { return [] }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ocrLanguages(lang, supported: (try? request.supportedRecognitionLanguages()) ?? [])
        try? VNImageRequestHandler(cgImage: cg).perform([request])
        // A label may put a (no-break) space before its own ellipsis; Vision reads it without one.
        let joined = labels.joined(separator: "\n")
            .replacingOccurrences(of: "[\\s\u{00A0}\u{202F}]+…", with: "…", options: .regularExpression)
        // Labels whose own text ends in "…": OCR can misread a diacritic inside one ("posiłek" →
        // "positek"), so they are matched structurally — same word count, each word's length and its
        // first/last letter — since a real truncation drops whole words, not one glyph.
        let ellipsisLabelWords: [[Substring]] = labels.filter { $0.hasSuffix("…") }.map { $0.dropLast().split(separator: " ") }
        func looksLikeLabel(_ line: Substring) -> Bool {
            let lineWords = line.hasSuffix("…") ? line.dropLast().split(separator: " ") : line.split(separator: " ")
            return ellipsisLabelWords.contains { words in
                words.count == lineWords.count && zip(words, lineWords).allSatisfy { w, l in
                    w.count == l.count && w.first == l.first && w.last == l.last
                }
            }
        }
        var out: [Finding] = []
        for observation in request.results ?? [] {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let text = candidate.string
            // Photo texture read as text ("lurnonicuTIa", "& n..i....a"): 2+ periods inside a word
            // never occur in UI text or a real truncation.
            if text.range(of: "\\p{L}\\.\\.+\\p{L}", options: .regularExpression) != nil { continue }
            let line = text.replacingOccurrences(of: "...", with: "…")
            if looksLikeLabel(line[...]) { continue }
            // Vision often reads a row as one line, so an ellipsis can sit mid-line: check every one.
            var search = line.startIndex..<line.endIndex
            while let r = line.range(of: "…", range: search) {
                search = r.upperBound..<line.endIndex
                let before = line[..<r.lowerBound].split(separator: " ").suffix(3).joined(separator: " ")
                guard before.filter(\.isLetter).count >= 2 else { continue }   // wheel dots are not text
                if joined.contains(before + "…") { continue }                   // the label's own ellipsis
                if let label = labels.first(where: { $0.contains(before) }), !label.hasSuffix(before) {
                    out.append(Finding(kind: "truncated", detail: "“\(before)…” of “\(label.prefix(60))”"))
                } else if labels.allSatisfy({ !$0.contains(before) }) {
                    out.append(Finding(kind: "truncated", detail: "“\(line.prefix(60))”"))
                }
            }
        }
        return out
    }
}

/// English source values of Localizable.xcstrings whose translation differs, per language.
final class StringsIndex {
    static let shared: StringsIndex? = StringsIndex()

    private var english: [String: [String: String]] = [:]   // English value → lang → translation
    private var translated: [String: Set<String>] = [:]    // lang → every translated value

    private init?() {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Resources/Localizable.xcstrings")
        guard let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let strings = json["strings"] as? [String: Any] else { return nil }
        for (key, value) in strings {
            guard let entry = value as? [String: Any], let locs = entry["localizations"] as? [String: Any] else { continue }
            let en = Self.value(locs["en"]) ?? key
            guard !en.contains("%") else { continue }   // formats never match a rendered label exactly
            var map: [String: String] = [:]
            for (lang, loc) in locs where lang != "en" {
                if let v = Self.value(loc) {
                    map[lang] = v
                    translated[lang, default: []].insert(v)
                }
            }
            english[en] = map
        }
    }

    private static func value(_ loc: Any?) -> String? {
        ((loc as? [String: Any])?["stringUnit"] as? [String: Any])?["value"] as? String
    }

    func isEnglishLeftover(_ label: String, lang: String) -> Bool {
        guard let translations = english[label], let value = translations[lang] else { return false }
        // The same word can be right in this language for another key.
        return value != label && !(translated[lang]?.contains(label) ?? false)
    }
}
