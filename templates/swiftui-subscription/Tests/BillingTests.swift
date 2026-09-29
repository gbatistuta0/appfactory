import StoreKit
import StoreKitTest
import XCTest
@testable import __APP_NAME__

/// Billing resilience (grace period / billing retry / expiry). The banner state comes from
/// RevenueCat's entitlement in production; the same mapping is exercised here against real
/// StoreKit renewal states produced by an SKTestSession on the spec's Configuration.storekit.
final class BillingIssueTests: XCTestCase {
    func testRevenueCatEntitlementMapping() {
        let now = Date()
        XCTAssertNil(BillingIssue.evaluate(isActive: true, billingIssueDetectedAt: nil, expirationDate: now))
        XCTAssertEqual(BillingIssue.evaluate(isActive: true, billingIssueDetectedAt: now, expirationDate: now),
                       .gracePeriod(expires: now))
        XCTAssertEqual(BillingIssue.evaluate(isActive: false, billingIssueDetectedAt: now, expirationDate: now, now: now),
                       .billingRetry)
        let longAgo = now.addingTimeInterval(-(BillingIssue.retryWindow + 3600))
        XCTAssertNil(BillingIssue.evaluate(isActive: false, billingIssueDetectedAt: longAgo, expirationDate: longAgo, now: now),
                     "after Apple's 60-day retry window the banner stops")
        XCTAssertNil(BillingIssue.evaluate(isActive: false, billingIssueDetectedAt: nil, expirationDate: now), "plain expiry")
    }

    func testStoreKitRenewalStateMapping() {
        XCTAssertEqual(BillingIssue.evaluate(renewalState: .inGracePeriod, expirationDate: nil), .gracePeriod(expires: nil))
        XCTAssertEqual(BillingIssue.evaluate(renewalState: .inBillingRetryPeriod, expirationDate: nil), .billingRetry)
        XCTAssertNil(BillingIssue.evaluate(renewalState: .subscribed, expirationDate: nil))
        XCTAssertNil(BillingIssue.evaluate(renewalState: .expired, expirationDate: nil))
    }
}

@MainActor
final class StoreKitSessionTests: XCTestCase {
    private var session: SKTestSession!
    private let groupID = "21000001"

    private var weeklyID: String {
        AppSpec.products.first { $0.offering == "default" && $0.period.hasSuffix("W") }?.id
            ?? AppSpec.products[0].id
    }

    override func setUp() async throws {
        session = try SKTestSession(contentsOf: TestPaths.storekit)
        session.resetToDefaultState()
        session.disableDialogs = true
        session.clearTransactions()
    }

    /// StoreKit Test needs a signed test host; an unsigned CI build answers `notEntitled`.
    private func buy(_ id: String) async throws {
        do {
            _ = try await session.buyProduct(identifier: id, options: [])
        } catch {
            if "\(error)".contains("notEntitled") { throw XCTSkip("StoreKit Test unavailable (unsigned test host)") }
            throw error
        }
    }

    override func tearDown() async throws {
        session.clearTransactions()
        session = nil
    }

    private func state() async throws -> Product.SubscriptionInfo.RenewalState? {
        try await Product.SubscriptionInfo.status(for: groupID).first?.state
    }

    func testPurchaseThenExpire() async throws {
        try await buy(weeklyID)
        let subscribed = try await state()
        XCTAssertEqual(subscribed, .subscribed)
        let issueWhileActive = await BillingIssue.currentFromStoreKit(groupID: groupID)
        XCTAssertNil(issueWhileActive)
        try session.expireSubscription(productIdentifier: weeklyID)
        let expired = try await state()
        XCTAssertEqual(expired, .expired)
        let issueAfterExpiry = await BillingIssue.currentFromStoreKit(groupID: groupID)
        XCTAssertNil(issueAfterExpiry, "a plain expiry is not a billing issue")
    }

    func testBillingRetryShowsTheBanner() async throws {
        session.billingGracePeriodIsEnabled = false
        session.shouldEnterBillingRetryOnRenewal = true
        try await buy(weeklyID)
        try session.forceRenewalOfSubscription(productIdentifier: weeklyID)
        let retry = try await waitForState(.inBillingRetryPeriod)
        XCTAssertEqual(retry, .inBillingRetryPeriod)
        let issue = await BillingIssue.currentFromStoreKit(groupID: groupID)
        XCTAssertEqual(issue, .billingRetry)
    }

    func testGracePeriodKeepsAccessWithBanner() async throws {
        session.billingGracePeriodIsEnabled = true
        session.shouldEnterBillingRetryOnRenewal = true
        try await buy(weeklyID)
        try session.forceRenewalOfSubscription(productIdentifier: weeklyID)
        let grace = try await waitForState(.inGracePeriod)
        XCTAssertEqual(grace, .inGracePeriod)
        guard case .gracePeriod = await BillingIssue.currentFromStoreKit(groupID: groupID) else {
            return XCTFail("grace period must surface as a banner")
        }
    }

    /// StoreKit Test applies renewals asynchronously; poll briefly.
    private func waitForState(_ wanted: Product.SubscriptionInfo.RenewalState) async throws -> Product.SubscriptionInfo.RenewalState? {
        var last: Product.SubscriptionInfo.RenewalState?
        for _ in 0..<20 {
            last = try await state()
            if last == wanted { return last }
            try await Task.sleep(for: .milliseconds(250))
        }
        return last
    }
}
