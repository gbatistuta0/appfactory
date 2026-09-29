import Foundation

/// Free-usage gate kept on the device (the Supabase service is off, so there is no server quota).
/// Free users get `freeUses` core actions for the lifetime of the install, then the paywall;
/// subscribers are never gated. A reinstall resets the count: acceptable without a backend.
enum LocalUsageGate {
    /// From app.spec.json `usage.free_lifetime_scans` at scaffold time.
    static let freeUses = __FREE_USES__
    static let key = "local_usage_count"

    static var used: Int { UserDefaults.standard.integer(forKey: key) }

    static func allows(isSubscribed: Bool) -> Bool {
        isSubscribed || used < freeUses
    }

    /// Call after a successful core action.
    static func recordUse() {
        UserDefaults.standard.set(used + 1, forKey: key)
    }
}
