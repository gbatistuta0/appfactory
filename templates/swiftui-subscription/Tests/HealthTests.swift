import XCTest
@testable import __APP_NAME__

/// Optional Health module (spec `health.enabled`); the scaffold deletes this file when it is off.
final class HealthTests: XCTestCase {
    func testNothingHappensBeforeConsent() async {
        let fake = FakeHealthStore()
        var consent = false
        let store = ConsentGatedHealthStore(base: fake) { consent }
        do {
            _ = try await store.requestAuthorization()
            XCTFail("request before consent must throw")
        } catch {
            XCTAssertEqual(error as? HealthError, .consentRequired)
        }
        await XCTAssertThrowsAsync { try await store.saveBodyMass(kg: 70, at: Date(), syncID: "w1", version: 1) }
        await XCTAssertThrowsAsync { _ = try await store.latestBodyMass() }
        XCTAssertEqual(fake.requestCount, 0)
        consent = true
        let granted = try? await store.requestAuthorization()
        XCTAssertEqual(granted, .authorized)
        XCTAssertEqual(fake.requestCount, 1)
    }

    func testSyncIdentifierVersionReplacesOlderWrites() async throws {
        let fake = FakeHealthStore()
        let store = ConsentGatedHealthStore(base: fake) { true }
        try await store.saveNutrition(NutritionEntry(id: "meal1", version: 1, date: Date(), kcal: 500, proteinG: 20))
        try await store.saveNutrition(NutritionEntry(id: "meal1", version: 2, date: Date(), kcal: 450, proteinG: 20))
        try await store.saveNutrition(NutritionEntry(id: "meal1", version: 1, date: Date(), kcal: 999))
        XCTAssertEqual(fake.saved["meal1.kcal"]?.value, 450)
        XCTAssertEqual(fake.saved["meal1.kcal"]?.version, 2)
        XCTAssertEqual(HealthTypes.syncMetadata(id: "x", version: 3).count, 2)
    }

    func testPermissionStates() {
        XCTAssertEqual(HealthAuthorization.evaluate(available: false, requestNeeded: true, shareAllowed: []), .unavailable)
        XCTAssertEqual(HealthAuthorization.evaluate(available: true, requestNeeded: true, shareAllowed: [false]), .notDetermined)
        XCTAssertEqual(HealthAuthorization.evaluate(available: true, requestNeeded: false, shareAllowed: [false, false]), .denied)
        XCTAssertEqual(HealthAuthorization.evaluate(available: true, requestNeeded: false, shareAllowed: [true, false]), .partial)
        XCTAssertEqual(HealthAuthorization.evaluate(available: true, requestNeeded: false, shareAllowed: [true]), .authorized)
    }

    func testSpecTypesResolve() {
        XCTAssertEqual(HealthTypes.read.count, AppSpec.healthRead.count)
        XCTAssertEqual(HealthTypes.write.count, AppSpec.healthWrite.count)
    }

    private func XCTAssertThrowsAsync(_ body: () async throws -> Void, line: UInt = #line) async {
        do { try await body(); XCTFail("expected a throw", line: line) } catch {}
    }
}
