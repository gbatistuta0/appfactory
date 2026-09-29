import XCTest
@testable import __APP_NAME__

/// Rule: only production App Store builds send analytics. Each non-production
/// condition alone must block sending.
final class AnalyticsGateTests: XCTestCase {
    private let production = AnalyticsGate(isDebugBuild: false, isSimulator: false, isUnderTest: false,
                                           storeEnvironment: .production)

    func testProductionAppStoreBuildSends() {
        XCTAssertTrue(production.allowsSending)
        XCTAssertNil(production.blockReason)
    }

    func testEachNonProductionConditionBlocks() {
        var debug = production; debug.isDebugBuild = true
        var simulator = production; simulator.isSimulator = true
        var test = production; test.isUnderTest = true
        var testFlight = production; testFlight.storeEnvironment = .sandbox
        var xcode = production; xcode.storeEnvironment = .xcode
        var unknown = production; unknown.storeEnvironment = .unknown
        let cases: [(AnalyticsGate, String)] = [
            (debug, "debug_build"), (simulator, "simulator"), (test, "test_run"),
            (testFlight, "store_sandbox"), (xcode, "store_xcode"), (unknown, "store_unknown"),
        ]
        for (gate, reason) in cases {
            XCTAssertFalse(gate.allowsSending, reason)
            XCTAssertEqual(gate.blockReason, reason)
        }
    }

    func testReceiptNameMapsToEnvironment() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let prod = dir.appendingPathComponent("receipt")
        XCTAssertEqual(AnalyticsGate.receiptEnvironment(prod), .unknown, "no receipt file yet → not production")
        try Data([1]).write(to: prod)
        XCTAssertEqual(AnalyticsGate.receiptEnvironment(prod), .production)
        XCTAssertEqual(AnalyticsGate.receiptEnvironment(dir.appendingPathComponent("sandboxReceipt")), .sandbox)
        XCTAssertEqual(AnalyticsGate.receiptEnvironment(nil), .unknown)
    }

    /// This test process itself (DEBUG, simulator, XCTest) must never send.
    func testThisRunIsBlocked() {
        let gate = AnalyticsGate.launch()
        XCTAssertFalse(gate.allowsSending)
        XCTAssertTrue(gate.isDebugBuild)
        XCTAssertTrue(gate.isSimulator)
        XCTAssertTrue(gate.isUnderTest)
        XCTAssertFalse(Tracker.isSending)
    }
}
