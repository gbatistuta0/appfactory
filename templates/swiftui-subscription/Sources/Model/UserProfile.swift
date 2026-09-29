import Foundation

/// Everything the user answered during onboarding. Persisted (ProfileStore), so the paywall, the
/// finale and the main app read the same answers — never view-local @State.
///
/// Keys are the stable step ids of `OnboardingCatalog` and the option ids of each step (snake_case,
/// never localized copy), so they double as analytics values and backend enum keys.
struct OnboardingAnswers: Codable, Equatable {
    /// Question steps: step id → selected option ids (one for single choice).
    var choices: [String: [String]] = [:]
    /// Picker steps: step id → value (weights in kg, heights in cm, years, minutes …).
    var numbers: [String: Double] = [:]
    var unitSystem: UnitSystem = .metric
    /// Explicit consent on the permission step (GDPR Art. 9 / KVKK when the spec needs it).
    var consentAt: Date?
    // @if siwa
    /// Provider the anonymous account was linked to on the account step (nil = skipped).
    var linkedProvider: String?
    // @endif
    var completedAt: Date?

    func selected(_ stepID: String) -> [String] { choices[stepID] ?? [] }
    func first(_ stepID: String) -> String? { choices[stepID]?.first }
    func number(_ stepID: String) -> Double? { numbers[stepID] }

    var answeredCount: Int { choices.values.filter { !$0.isEmpty }.count + numbers.count }
}

/// Local persistence of the onboarding answers (UserDefaults JSON).
@MainActor
final class ProfileStore: ObservableObject {
    nonisolated static let answersKey = "profile.onboarding_answers"

    @Published private(set) var answers: OnboardingAnswers?
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        answers = Self.storedAnswers(defaults)
    }

    /// Thread-safe read of the persisted answers (UserDefaults is thread-safe).
    nonisolated static func storedAnswers(_ defaults: UserDefaults = .standard) -> OnboardingAnswers? {
        defaults.data(forKey: answersKey).flatMap { try? JSONDecoder().decode(OnboardingAnswers.self, from: $0) }
    }

    func save(_ answers: OnboardingAnswers) {
        self.answers = answers
        if let data = try? JSONEncoder().encode(answers) { defaults.set(data, forKey: Self.answersKey) }
    }

    /// Consent given (or withdrawn with nil) outside onboarding, e.g. after a 403 consent_required.
    func recordConsent(_ date: Date?) {
        var a = answers ?? OnboardingAnswers()
        a.consentAt = date
        save(a)
    }

    func reset() {
        answers = nil
        defaults.removeObject(forKey: Self.answersKey)
    }
}

/// Writes the profile row (locale, timezone, attribution, answers jsonb, consent) — CONTRACT §5.
/// Fire-and-forget: a failure never blocks the UI; the next launch or consent retry sends again.
enum ProfileSync {
    static func upsert(_ answers: OnboardingAnswers) async {
        var row: [String: Any] = [
            "locale": AppConfig.appLanguage,
            "timezone": TimeZone.current.identifier,
        ]
        if let source = answers.first("source") { row["attribution"] = String(source.prefix(40)) }
        var json: [String: Any] = ["units": answers.unitSystem.rawValue]
        for (k, v) in answers.choices { json[k] = v }
        for (k, v) in answers.numbers { json[k] = v }
        row["answers"] = json
        row[AppSpec.consentColumn] = answers.consentAt.map { ISO8601DateFormatter().string(from: $0) } ?? NSNull()
        await send(row)
    }

    static func upsertConsent(_ date: Date?) async {
        await send([AppSpec.consentColumn: date.map { ISO8601DateFormatter().string(from: $0) } ?? NSNull()])
    }

    private static func send(_ fields: [String: Any]) async {
        guard AppConfig.isSupabaseConfigured,
              let uid = try? await SupabaseAuth.shared.userID(),
              let token = try? await SupabaseAuth.shared.accessToken(),
              let url = URL(string: AppConfig.supabaseURL + "/rest/v1/profiles?on_conflict=id") else { return }
        var row = fields
        row["id"] = uid
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("resolution=merge-duplicates,return=minimal", forHTTPHeaderField: "Prefer")
        req.httpBody = try? JSONSerialization.data(withJSONObject: row)
        _ = try? await URLSession.shared.data(for: req)
    }
}

/// Settings → Delete account (backend CONTRACT §4; App Review requires it once accounts exist).
enum AccountService {
    enum DeleteResult: Equatable { case deleted, failed }

    static func deleteAccount() async -> DeleteResult {
        do {
            let obj = try await Proxy.post("delete-account", body: ["confirm": "DELETE"])
            guard obj["deleted"] as? Bool == true else { return .failed }
        } catch {
            return .failed
        }
        await SupabaseAuth.shared.signOut()
        return .deleted
    }
}
