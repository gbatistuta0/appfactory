import Foundation
import HealthKit
import SwiftUI
import UIKit

// OPTIONAL MODULE (spec `health.enabled`). The scaffold deletes Sources/Health, the HealthKit
// entitlement and the usage strings when the spec leaves it off.
//
// Rules: nothing is read, written or even requested before the user's consent
// (`OnboardingAnswers.consentAt`, spec `consent.health`); every write carries
// HKMetadataKeySyncIdentifier + HKMetadataKeySyncVersion so a re-sync replaces instead of
// duplicating.

/// What the permission UI shows. HealthKit never reveals READ grants, so the state is derived
/// from the request status and the WRITE (share) statuses.
enum HealthAuthorization: Equatable {
    case unavailable
    case notDetermined
    case denied
    /// Some write types allowed, some not.
    case partial
    case authorized

    static func evaluate(available: Bool, requestNeeded: Bool, shareAllowed: [Bool]) -> HealthAuthorization {
        guard available else { return .unavailable }
        if requestNeeded { return .notDetermined }
        if shareAllowed.isEmpty || shareAllowed.allSatisfy({ $0 }) { return .authorized }
        if shareAllowed.allSatisfy({ !$0 }) { return .denied }
        return .partial
    }
}

enum HealthError: Error, Equatable {
    case consentRequired
    case unavailable
    case notAllowed(String)
}

/// One nutrition entry written to Apple Health (kcal + macros in grams).
struct NutritionEntry: Equatable {
    /// Stable id of the entry in the app (e.g. the meal row id); becomes the HK sync identifier.
    let id: String
    /// Bump when the entry is edited: HealthKit replaces the older version.
    let version: Int
    let date: Date
    var kcal: Double?
    var proteinG: Double?
    var carbsG: Double?
    var fatG: Double?
}

protocol HealthStore: AnyObject {
    var isAvailable: Bool { get }
    func authorization() async -> HealthAuthorization
    func requestAuthorization() async throws -> HealthAuthorization
    /// Active energy burned on the calendar day of `day`, in kcal.
    func activeEnergyBurned(on day: Date) async throws -> Double
    /// Latest body mass in kg.
    func latestBodyMass() async throws -> Double?
    func saveNutrition(_ entry: NutritionEntry) async throws
    func saveBodyMass(kg: Double, at date: Date, syncID: String, version: Int) async throws
}

/// The spec's HealthKit type lists (`health.read` / `health.write`), as quantity types.
enum HealthTypes {
    static func quantityTypes(_ identifiers: [String]) -> Set<HKQuantityType> {
        Set(identifiers.compactMap { HKQuantityType.quantityType(forIdentifier: HKQuantityTypeIdentifier(rawValue: "HKQuantityTypeIdentifier" + $0.prefix(1).uppercased() + $0.dropFirst())) })
    }
    static var read: Set<HKQuantityType> { quantityTypes(AppSpec.healthRead) }
    static var write: Set<HKQuantityType> { quantityTypes(AppSpec.healthWrite) }

    static func syncMetadata(id: String, version: Int) -> [String: Any] {
        [HKMetadataKeySyncIdentifier: id, HKMetadataKeySyncVersion: NSNumber(value: version)]
    }
}

/// Wraps any HealthStore and refuses every call until consent exists.
final class ConsentGatedHealthStore: HealthStore {
    private let base: HealthStore
    private let hasConsent: () -> Bool

    init(base: HealthStore, hasConsent: @escaping () -> Bool) {
        self.base = base
        self.hasConsent = hasConsent
    }

    var isAvailable: Bool { base.isAvailable }

    private func check() throws { guard hasConsent() else { throw HealthError.consentRequired } }

    func authorization() async -> HealthAuthorization { await base.authorization() }
    func requestAuthorization() async throws -> HealthAuthorization { try check(); return try await base.requestAuthorization() }
    func activeEnergyBurned(on day: Date) async throws -> Double { try check(); return try await base.activeEnergyBurned(on: day) }
    func latestBodyMass() async throws -> Double? { try check(); return try await base.latestBodyMass() }
    func saveNutrition(_ entry: NutritionEntry) async throws { try check(); try await base.saveNutrition(entry) }
    func saveBodyMass(kg: Double, at date: Date, syncID: String, version: Int) async throws {
        try check(); try await base.saveBodyMass(kg: kg, at: date, syncID: syncID, version: version)
    }
}

/// HealthKit-backed implementation.
final class LiveHealthStore: HealthStore {
    private let store = HKHealthStore()

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func authorization() async -> HealthAuthorization {
        guard isAvailable else { return .unavailable }
        let needed = (try? await store.statusForAuthorizationRequest(toShare: HealthTypes.write, read: HealthTypes.read)) == .shouldRequest
        let allowed = HealthTypes.write.map { store.authorizationStatus(for: $0) == .sharingAuthorized }
        return HealthAuthorization.evaluate(available: true, requestNeeded: needed, shareAllowed: allowed)
    }

    func requestAuthorization() async throws -> HealthAuthorization {
        guard isAvailable else { throw HealthError.unavailable }
        try await store.requestAuthorization(toShare: HealthTypes.write, read: HealthTypes.read)
        return await authorization()
    }

    func activeEnergyBurned(on day: Date) async throws -> Double {
        guard let type = HKQuantityType.quantityType(forIdentifier: .activeEnergyBurned) else { return 0 }
        let start = Calendar.current.startOfDay(for: day)
        let end = Calendar.current.date(byAdding: .day, value: 1, to: start) ?? day
        let predicate = HKQuery.predicateForSamples(withStart: start, end: end)
        let descriptor = HKStatisticsQueryDescriptor(predicate: .quantitySample(type: type, predicate: predicate), options: .cumulativeSum)
        return try await descriptor.result(for: store)?.sumQuantity()?.doubleValue(for: .kilocalorie()) ?? 0
    }

    func latestBodyMass() async throws -> Double? {
        guard let type = HKQuantityType.quantityType(forIdentifier: .bodyMass) else { return nil }
        let descriptor = HKSampleQueryDescriptor(predicates: [.quantitySample(type: type)],
                                                 sortDescriptors: [SortDescriptor(\.endDate, order: .reverse)], limit: 1)
        return try await descriptor.result(for: store).first?.quantity.doubleValue(for: .gramUnit(with: .kilo))
    }

    func saveNutrition(_ entry: NutritionEntry) async throws {
        let pairs: [(HKQuantityTypeIdentifier, Double?, HKUnit)] = [
            (.dietaryEnergyConsumed, entry.kcal, .kilocalorie()),
            (.dietaryProtein, entry.proteinG, .gram()),
            (.dietaryCarbohydrates, entry.carbsG, .gram()),
            (.dietaryFatTotal, entry.fatG, .gram()),
        ]
        var samples: [HKQuantitySample] = []
        for (id, value, unit) in pairs {
            guard let value, let type = HKQuantityType.quantityType(forIdentifier: id), HealthTypes.write.contains(type) else { continue }
            samples.append(HKQuantitySample(type: type, quantity: HKQuantity(unit: unit, doubleValue: value),
                                            start: entry.date, end: entry.date,
                                            metadata: HealthTypes.syncMetadata(id: "\(entry.id).\(id.rawValue)", version: entry.version)))
        }
        guard !samples.isEmpty else { throw HealthError.notAllowed("nutrition") }
        try await store.save(samples)
    }

    func saveBodyMass(kg: Double, at date: Date, syncID: String, version: Int) async throws {
        guard let type = HKQuantityType.quantityType(forIdentifier: .bodyMass), HealthTypes.write.contains(type) else {
            throw HealthError.notAllowed("bodyMass")
        }
        let sample = HKQuantitySample(type: type, quantity: HKQuantity(unit: .gramUnit(with: .kilo), doubleValue: kg),
                                      start: date, end: date, metadata: HealthTypes.syncMetadata(id: syncID, version: version))
        try await store.save(sample)
    }
}

/// In-memory implementation for unit tests and previews.
final class FakeHealthStore: HealthStore {
    var isAvailable = true
    var state: HealthAuthorization = .notDetermined
    var grantOnRequest: HealthAuthorization = .authorized
    var energyKcal: Double = 0
    var bodyMassKg: Double?
    /// Saved samples keyed by sync identifier → (version, value): a newer version replaces.
    private(set) var saved: [String: (version: Int, value: Double)] = [:]
    private(set) var requestCount = 0

    func authorization() async -> HealthAuthorization { isAvailable ? state : .unavailable }

    func requestAuthorization() async throws -> HealthAuthorization {
        guard isAvailable else { throw HealthError.unavailable }
        requestCount += 1
        state = grantOnRequest
        return state
    }

    func activeEnergyBurned(on day: Date) async throws -> Double { energyKcal }
    func latestBodyMass() async throws -> Double? { bodyMassKg }

    func saveNutrition(_ entry: NutritionEntry) async throws {
        for (suffix, value) in [("kcal", entry.kcal), ("protein", entry.proteinG), ("carbs", entry.carbsG), ("fat", entry.fatG)] {
            if let value { upsert("\(entry.id).\(suffix)", entry.version, value) }
        }
    }

    func saveBodyMass(kg: Double, at date: Date, syncID: String, version: Int) async throws {
        upsert(syncID, version, kg)
    }

    private func upsert(_ id: String, _ version: Int, _ value: Double) {
        if let existing = saved[id], existing.version >= version { return }
        saved[id] = (version, value)
    }
}

/// The app's shared, consent-gated Health store.
@MainActor
enum Health {
    static var store: HealthStore = ConsentGatedHealthStore(base: LiveHealthStore()) {
        ProfileStore.storedAnswers()?.consentAt != nil || !AppSpec.consentRequired
    }
}

// MARK: - Permission UX

/// Onboarding / Settings card: connect, denied (→ Settings), partial, connected.
struct HealthPermissionCard: View {
    let hasConsent: Bool
    @State private var state: HealthAuthorization = .notDetermined
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(spacing: 12) {
            switch state {
            case .unavailable:
                Text("Apple Health isn't available on this device.")
                    .foregroundStyle(DS.Palette.secondaryText)
            case .notDetermined:
                Button { Task { await request() } } label: { Text("Connect Apple Health") }
                    .buttonStyle(.primary)
                    .disabled(!hasConsent)
                    .accessibilityIdentifier("health_connect")
                if !hasConsent {
                    Text("Give consent first to connect Apple Health.")
                        .font(.system(size: 13)).foregroundStyle(DS.Palette.secondaryText)
                }
            case .denied, .partial:
                Text(state == .denied ? "Apple Health access is off." : "Some Apple Health permissions are off.")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(DS.Palette.foreground)
                Button { if let u = URL(string: UIApplication.openSettingsURLString) { openURL(u) } } label: {
                    Text("Open Settings")
                }
                .accessibilityIdentifier("health_open_settings")
            case .authorized:
                Label("Apple Health connected", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(DS.Palette.primary)
            }
        }
        .multilineTextAlignment(.center)
        .task { state = await Health.store.authorization() }
    }

    private func request() async {
        let result = (try? await Health.store.requestAuthorization()) ?? state
        state = result
        Tracker.log(custom: "health_permission", ["result": "\(result)"])
    }
}

/// Settings row for the Health connection.
struct HealthSettingsRow: View {
    @EnvironmentObject private var profiles: ProfileStore

    var body: some View {
        NavigationLink {
            HealthPermissionCard(hasConsent: profiles.answers?.consentAt != nil || !AppSpec.consentRequired)
                .padding(DS.Spacing.lg)
                .navigationTitle(Text("Apple Health"))
        } label: {
            Label("Apple Health", systemImage: "heart.text.square")
        }
    }
}
