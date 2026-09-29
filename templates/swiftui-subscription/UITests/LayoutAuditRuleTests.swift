import XCTest

/// The audit's pure rules still fail real defects (frames measured on real SE and Pro Max runs;
/// no app launch).
final class LayoutAuditRuleTests: XCTestCase {
    private let se = CGRect(x: 0, y: 0, width: 375, height: 667)
    private let proMax = CGRect(x: 0, y: 0, width: 440, height: 956)

    private func kinds(_ findings: [LayoutAudit.Finding]) -> [String] { findings.map(\.kind) }

    func testFloatingSheetFitsAndAnOversizedOneFails() {
        let sheet = CGRect(x: 8, y: 228, width: 359, height: 431)
        let fits = [CGRect(x: 31, y: 260, width: 313, height: 300), CGRect(x: 31, y: 582, width: 313, height: 54)]
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: fits, window: se)), [])
        let tall = [CGRect(x: 31, y: 240, width: 313, height: 119)]
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: tall, window: se)), ["sheet-tall"])
    }

    func testDoubleSafeAreaInsetFails() {
        let sheet = CGRect(x: 0, y: 600, width: 440, height: 356)
        let fits = [CGRect(x: 24, y: 640, width: 392, height: 258)]      // ends 34 + 24 above the edge
        let doubled = [CGRect(x: 24, y: 640, width: 392, height: 224)]   // 92 pt below
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: fits, window: proMax)), [])
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: doubled, window: proMax)), ["sheet-tall"])
    }

    func testEmptyBandFailsAndANamedControlFillsIt() {
        let sheet = CGRect(x: 8, y: 200, width: 359, height: 459)
        let title = CGRect(x: 31, y: 230, width: 313, height: 40)
        let cta = CGRect(x: 31, y: 580, width: 313, height: 56)
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: [title, cta], window: se)), ["sheet-gap"])
        let ruler = CGRect(x: 8, y: 290, width: 359, height: 270)
        XCTAssertEqual(kinds(LayoutAudit.sheetFit("sheet_x", sheet: sheet, content: [title, ruler, cta], window: se)), [])
    }

    func testPinnedCTAKeepsClearOfTheBottomEdge() {
        XCTAssertEqual(kinds(LayoutAudit.ctaEdge([("onb_cta", CGRect(x: 24, y: 611, width: 327, height: 56))], window: se)), ["cta-edge"])
        XCTAssertEqual(kinds(LayoutAudit.ctaEdge([("onb_cta", CGRect(x: 24, y: 595, width: 327, height: 56))], window: se)), [])
        XCTAssertEqual(kinds(LayoutAudit.ctaEdge([("onb_cta", CGRect(x: 24, y: 866, width: 392, height: 56))], window: proMax)), [])
        XCTAssertEqual(kinds(LayoutAudit.ctaEdge([("onb_cta", CGRect(x: 24, y: 880, width: 392, height: 56))], window: proMax)), ["cta-edge"])
    }

    func testGlyphProbe() {
        XCTAssertEqual(kinds(LayoutAudit.glyphs(["Калории", "今日のカロリー", "السعرات", "1.249,99\u{00A0}₺"])), [])
        XCTAssertEqual(kinds(LayoutAudit.glyphs(["price \u{E000}"])), ["glyph"], "a private-use character has no glyph")
    }

    func testOCRLanguagesMapToVision() {
        let vision = ["en-US", "fr-FR", "de-DE", "pt-BR", "zh-Hans", "zh-Hant", "ja-JP", "ko-KR", "ru-RU", "ar-SA"]
        XCTAssertEqual(LayoutAudit.ocrLanguages("ja", supported: vision), ["ja-JP", "en-US"])
        XCTAssertEqual(LayoutAudit.ocrLanguages("zh-Hant", supported: vision), ["zh-Hant", "en-US"])
        XCTAssertEqual(LayoutAudit.ocrLanguages("pt-BR", supported: vision), ["pt-BR", "en-US"])
        XCTAssertEqual(LayoutAudit.ocrLanguages("en", supported: vision), ["en-US"])
        XCTAssertEqual(LayoutAudit.ocrLanguages("hi", supported: vision), ["en-US"], "Vision has no Hindi")
    }
}
