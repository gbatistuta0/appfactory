import Foundation
import StoreKit

/// The single switch for sending analytics: ONLY production App Store builds send events to
/// Firebase. DEBUG builds, the simulator, unit/UI tests and TestFlight/sandbox installs log events
/// to the console instead — sandbox data once passed for real revenue.
struct AnalyticsGate: Equatable {
    enum StoreEnvironment: Equatable {
        /// App Store download.
        case production
        /// TestFlight or sandbox.
        case sandbox
        /// Xcode / local StoreKit.
        case xcode
        /// No receipt or AppTransaction yet: treated as not production.
        case unknown
    }

    var isDebugBuild: Bool
    var isSimulator: Bool
    var isUnderTest: Bool
    var storeEnvironment: StoreEnvironment

    /// Every condition must be production; anything else keeps events on this device.
    var allowsSending: Bool {
        !isDebugBuild && !isSimulator && !isUnderTest && storeEnvironment == .production
    }

    /// Why sending is blocked (for the console line), nil when allowed.
    var blockReason: String? {
        if isDebugBuild { return "debug_build" }
        if isSimulator { return "simulator" }
        if isUnderTest { return "test_run" }
        if storeEnvironment != .production { return "store_\(storeEnvironment)" }
        return nil
    }

    /// Decided synchronously at launch from the build, the process and the receipt name
    /// (`sandboxReceipt` for TestFlight/sandbox, `receipt` for the App Store).
    static func launch(processInfo: ProcessInfo = .processInfo, bundle: Bundle = .main) -> AnalyticsGate {
        #if DEBUG
        let debug = true
        #else
        let debug = false
        #endif
        #if targetEnvironment(simulator)
        let simulator = true
        #else
        let simulator = processInfo.environment["SIMULATOR_UDID"] != nil
        #endif
        let underTest = processInfo.arguments.contains("-uiTest")
            || processInfo.environment["XCTestConfigurationFilePath"] != nil
        return AnalyticsGate(isDebugBuild: debug, isSimulator: simulator, isUnderTest: underTest,
                             storeEnvironment: receiptEnvironment(bundle.appStoreReceiptURL))
    }

    static func receiptEnvironment(_ url: URL?) -> StoreEnvironment {
        guard let url else { return .unknown }
        switch url.lastPathComponent {
        case "sandboxReceipt": return .sandbox
        case "receipt": return FileManager.default.fileExists(atPath: url.path) ? .production : .unknown
        default: return .unknown
        }
    }

    /// Confirms the environment with the signed AppTransaction (iOS 16+). Can only close the
    /// gate further, never open it past what `launch()` decided for the build and process.
    static func verifiedStoreEnvironment() async -> StoreEnvironment? {
        guard let result = try? await AppTransaction.shared, case .verified(let tx) = result else { return nil }
        switch tx.environment {
        case .production: return .production
        case .sandbox: return .sandbox
        case .xcode: return .xcode
        default: return .unknown
        }
    }
}
