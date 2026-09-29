import Foundation

/// Authed calls to the app's Edge Functions (backend CONTRACT: identity §1, error table §2).
/// Headers: `apikey: <anon key>` + `Authorization: Bearer <access token>`. No user id in the
/// body — the server takes it from the JWT.
enum Proxy {
    /// Every error the contract defines, decided on the `error` code, never on the message.
    enum APIError: Error, Equatable {
        /// 402 `paywall_required` → open the paywall at the server's `placement`.
        case paywallRequired(PaywallSource)
        /// 429 `daily_cap_reached` → paywall `daily_cap` for free users, limit message for subscribers.
        case dailyCap(resetsAt: Date?)
        /// 429 `too_many_attempts` → message only (abuse backstop), never a paywall.
        case tooManyAttempts(resetsAt: Date?)
        /// 422 `not_applicable` → "not something we can analyze" + retake. Does not use a scan.
        case notApplicable
        /// 403 `consent_required` → show the consent screen, record consent, retry.
        case consentRequired
        /// 503 `entitlement_unavailable`, 500, 502 → retry message. NEVER a paywall.
        case retryable(code: String)
        /// 400 / 413 / 415 / 422 → a client bug or unusable input; logged.
        case invalidRequest(code: String)
        case unauthorized
        // @if credits
        /// 402 `out_of_credits` (credits monetization): top-up for subscribers, paywall otherwise.
        case outOfCredits
        // @endif
        case notConfigured
        case transport(status: Int)
    }

    /// Where the UI goes for an error. Pure, so it is unit-tested against the contract table.
    enum Route: Equatable {
        case paywall(PaywallSource)
        case consent
        case message(Message)
        // @if credits
        case topUp
        // @endif
    }

    enum Message: Equatable {
        case notApplicable
        case dailyLimit(resetsAt: Date?)
        case tooManyAttempts
        case retry
        case generic
    }

    static func route(for error: APIError, isSubscribed: Bool) -> Route {
        switch error {
        case .paywallRequired(let source):
            return .paywall(source)
        case .dailyCap(let resets):
            return isSubscribed ? .message(.dailyLimit(resetsAt: resets)) : .paywall(.dailyCap)
        case .tooManyAttempts:
            return .message(.tooManyAttempts)
        case .consentRequired:
            return .consent
        case .notApplicable:
            return .message(.notApplicable)
        case .retryable:
            return .message(.retry)
        // @if credits
        case .outOfCredits:
            return isSubscribed ? .topUp : .paywall(.onboarding)
        // @endif
        case .invalidRequest, .unauthorized, .notConfigured, .transport:
            return .message(.generic)
        }
    }

    /// POST a JSON body to `/functions/v1/<function>`. A 401 refreshes the session and retries
    /// once, as the contract requires (the server rejects before doing any work).
    @discardableResult
    static func post(_ function: String, body: [String: Any] = [:], timeout: TimeInterval = 60) async throws -> [String: Any] {
        do {
            return try await send(function, body: body, timeout: timeout)
        } catch APIError.unauthorized {
            await SupabaseAuth.shared.invalidateCachedToken()
            return try await send(function, body: body, timeout: timeout)
        }
    }

    private static func send(_ function: String, body: [String: Any], timeout: TimeInterval) async throws -> [String: Any] {
        guard AppConfig.isSupabaseConfigured, let url = URL(string: AppConfig.functionsURL + "/" + function) else {
            throw APIError.notConfigured
        }
        let token = try await SupabaseAuth.shared.accessToken()
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if let error = error(status: status, body: obj) { throw error }
        return obj
    }

    /// Maps a response to the contract's error table (nil for 2xx).
    static func error(status: Int, body: [String: Any]) -> APIError? {
        if (200..<300).contains(status) { return nil }
        let code = body["error"] as? String ?? ""
        let resets = (body["resets_at"] as? String).flatMap(parseDate)
        switch code {
        case "paywall_required":
            // An unknown placement still opens the paywall: a user who must pay needs a way to pay.
            let placement = body["placement"] as? String ?? ""
            return .paywallRequired(PaywallSource(rawValue: placement) ?? .onboarding)
        case "daily_cap_reached", "daily_cap":
            return .dailyCap(resetsAt: resets)
        case "too_many_attempts":
            return .tooManyAttempts(resetsAt: resets)
        case "consent_required":
            return .consentRequired
        case "entitlement_unavailable", "internal_error", "analysis_failed", "generation_failed":
            return .retryable(code: code)
        case "not_applicable", "not_food":
            return .notApplicable
        case "invalid_request", "image_too_large", "unsupported_image":
            return .invalidRequest(code: code)
        case "unauthorized":
            return .unauthorized
        // @if credits
        case "out_of_credits":
            return .outOfCredits
        // @endif
        default:
            if status == 401 { return .unauthorized }
            if status == 402 { return .paywallRequired(PaywallSource(rawValue: body["placement"] as? String ?? "") ?? .onboarding) }
            if status == 429 { return .tooManyAttempts(resetsAt: resets) }
            if status >= 500 { return .retryable(code: code.isEmpty ? "http_\(status)" : code) }
            return .transport(status: status)
        }
    }

    static func parseDate(_ s: String) -> Date? {
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return withFraction.date(from: s) ?? ISO8601DateFormatter().date(from: s)
    }
}
