import Foundation

/// THIN client for the SERVER-side credit ledger (ai-proxy).
/// MONEY-CRITICAL: credits are no longer held/deducted LOCALLY — the server
/// (Supabase) is the sole authority. This class only holds the last known balance
/// for the UI; the generation gate is on the SERVER, NOT the CLIENT (proxy returns
/// 402 `out_of_credits` — premortem #8).
///
/// Contract (proxy, Authorization = persistent anon JWT, NO user_id in body):
///   {action:"balance"}                 → {ok, balance}
///   {action:"sync", transactions:[jws]}→ {ok, balance}   (currentEntitlements JWS)
/// Returned balance: {plan, periodic_remaining, bonus_remaining, periodic_reset_at}
@MainActor
final class CreditManager: ObservableObject {
    /// UI display: periodic + bonus total credits (last known value from the server).
    /// Starts at the last known value on launch (no "0" flicker until sync arrives → looks correct).
    @Published private(set) var credits: Int = UserDefaults.standard.integer(forKey: "last_known_credits")
    /// Date the periodic credit will renew (if any) — TopUpSheet "credits renew on {date}".
    @Published private(set) var nextReset: Date?
    /// Plan reported by the server (none/weekly/yearly) — informational.
    @Published private(set) var plan: String = "none"

    /// Balance returned by the server. periodic + bonus = displayed credit.
    struct Balance {
        var plan: String
        var periodicRemaining: Int
        var bonusRemaining: Int
        var periodicResetAt: Date?

        var total: Int { periodicRemaining + bonusRemaining }

        /// Try ISO8601 both with AND without fractional seconds (whichever the server returns).
        static func parseDate(_ s: String) -> Date? {
            let withFraction = ISO8601DateFormatter()
            withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let d = withFraction.date(from: s) { return d }
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            return plain.date(from: s)
        }

        /// Decode from proxy JSON (snake_case, ISO8601 reset).
        init?(json: [String: Any]) {
            guard let plan = json["plan"] as? String else { return nil }
            self.plan = plan
            self.periodicRemaining = (json["periodic_remaining"] as? Int) ?? 0
            self.bonusRemaining = (json["bonus_remaining"] as? Int) ?? 0
            if let s = json["periodic_reset_at"] as? String {
                self.periodicResetAt = Balance.parseDate(s)
            } else {
                self.periodicResetAt = nil
            }
        }
    }

    /// Apply the server balance to the UI (used by refresh + purchase + generation responses).
    func applyBalance(_ b: Balance) {
        credits = b.total
        nextReset = b.periodicResetAt
        plan = b.plan
        // Persist the last known balance → next launch the pill shows the correct value immediately.
        UserDefaults.standard.set(b.total, forKey: "last_known_credits")
    }

    /// Called on launch + foreground. Single `sync`: server pulls state from RC
    /// (consumable reconcile + subscription refill + free grant) → balance. Money-critical:
    /// the client never hard-gates. If the server is unreachable, the last known balance is kept.
    func refresh() async {
        do {
            let obj = try await Proxy.post(AppConfig.aiFunction, body: ["action": "sync"])
            if let balanceJSON = obj["balance"] as? [String: Any], let b = Balance(json: balanceJSON) {
                applyBalance(b)
            }
        } catch {
            #if DEBUG
            print("[CreditManager] refresh failed: \(error.localizedDescription)")
            #endif
        }
    }
}
