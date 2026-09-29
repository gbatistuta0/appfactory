import Foundation
import Security

/// Lightweight Supabase auth: an anonymous session first (backend CONTRACT §1), optionally
/// linked to Sign in with Apple later so the same user id survives a new device.
///
/// MONEY-CRITICAL (production incidents): the user id must survive everything, because
/// RevenueCat's `app_user_id` and every server-side quota hang off it.
/// - The refresh token is stored twice: an iCloud-synchronized Keychain item (moves with the
///   user to a new device) and a local item (always writable). `kSecAttrSynchronizable` and
///   `kSecAttrAccessible` cannot be combined — `SecItemAdd` rejects the pair.
/// - The session is only deleted when the server rejects the refresh token (400/401/403).
///   A network error must never throw the identity away.
/// - Access tokens live one hour; the cache honours the JWT `exp`.
/// - Token acquisition is single-flight: actors are reentrant, and two concurrent callers used
///   to create two anonymous users per launch.
actor SupabaseAuth {
    static let shared = SupabaseAuth()

    enum AuthError: LocalizedError, Equatable {
        case notConfigured
        case badResponse(Int)
        case malformedToken
        // @if siwa
        /// The Apple identity already belongs to another user (returning user on a new device).
        case identityAlreadyExists
        // @endif
        var errorDescription: String? {
            switch self {
            case .notConfigured: return "Supabase is not configured"
            case .badResponse(let s): return "Auth request failed (\(s))"
            case .malformedToken: return "Malformed access token"
            // @if siwa
            case .identityAlreadyExists: return "This Apple ID is already linked to another account"
            // @endif
            }
        }
    }

    struct RefreshError: LocalizedError {
        let status: Int
        let tokenRejected: Bool
        var errorDescription: String? { "Session refresh failed (\(status))" }
    }

    /// Only these statuses mean "the server rejected this refresh token" (CONTRACT §1.4).
    nonisolated static func isTokenRejection(status: Int) -> Bool { [400, 401, 403].contains(status) }

    private var cachedAccessToken: String?
    private var cachedExpiry: Date?
    private let expiryMargin: TimeInterval = 120
    private var inFlight: Task<String, Error>?

    private let kAccount = "supabase.anon.session"
    private var kService: String { (Bundle.main.bundleIdentifier ?? "app") + ".supabase.auth" }

    /// A valid access token: fresh cache → in-flight request → refresh → anonymous sign-up.
    func accessToken() async throws -> String {
        guard AppConfig.isSupabaseConfigured else { throw AuthError.notConfigured }
        if let cachedAccessToken, let cachedExpiry, cachedExpiry.timeIntervalSinceNow > expiryMargin {
            return cachedAccessToken
        }
        if let inFlight { return try await inFlight.value }
        let task = Task { try await self.fetchFreshToken() }
        inFlight = task
        defer { inFlight = nil }
        return try await task.value
    }

    /// Supabase user id (== RevenueCat app_user_id), decoded from the JWT `sub` claim.
    func userID() async throws -> String {
        let token = try await accessToken()
        guard let sub = Self.claims(of: token)?["sub"] as? String, !sub.isEmpty else {
            throw AuthError.malformedToken
        }
        return sub
    }

    /// Whether the current session is still anonymous (JWT `is_anonymous`).
    func isAnonymous() async -> Bool {
        guard let token = try? await accessToken() else { return true }
        return (Self.claims(of: token)?["is_anonymous"] as? Bool) ?? true
    }

    /// Account deleted on the server: forget the identity so the next launch signs up anew.
    func signOut() {
        deleteSession()
    }

    /// Callers that get a 401 drop the cache once and retry.
    func invalidateCachedToken() {
        cachedAccessToken = nil
        cachedExpiry = nil
    }

    // @if siwa
    // MARK: - Identity linking (Sign in with Apple)

    /// Links an OpenID Connect identity (Apple `identityToken`) to the CURRENT anonymous user:
    /// `POST /auth/v1/token?grant_type=id_token` with `link_identity: true` and the user's JWT
    /// (what supabase-js `linkIdentity({ provider, token, nonce })` sends). The user id — and with
    /// it the RevenueCat subscription — does not change.
    func linkIdentity(provider: String, idToken: String, nonce: String?) async throws -> String {
        let token = try await accessToken()
        let fresh = try await idTokenGrant(provider: provider, idToken: idToken, nonce: nonce, linkWith: token)
        cache(fresh)
        return try cachedUserID()
    }

    /// Signs in AS the user that already owns this identity (returning user on a new device).
    /// The anonymous session on this device is replaced; the caller must `Purchases.logIn` the
    /// returned user id so RevenueCat follows.
    func signInWithIdToken(provider: String, idToken: String, nonce: String?) async throws -> String {
        let fresh = try await idTokenGrant(provider: provider, idToken: idToken, nonce: nonce, linkWith: nil)
        cache(fresh)
        return try cachedUserID()
    }

    private func cachedUserID() throws -> String {
        guard let token = cachedAccessToken, let sub = Self.claims(of: token)?["sub"] as? String else {
            throw AuthError.malformedToken
        }
        return sub
    }

    private func idTokenGrant(provider: String, idToken: String, nonce: String?, linkWith jwt: String?) async throws -> String {
        guard let url = URL(string: "\(AppConfig.supabaseURL)/auth/v1/token?grant_type=id_token") else {
            throw AuthError.notConfigured
        }
        var body: [String: Any] = ["provider": provider, "id_token": idToken]
        if let nonce { body["nonce"] = nonce }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let jwt {
            body["link_identity"] = true
            req.setValue("Bearer \(jwt)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard (200..<300).contains(status), let token = obj["access_token"] as? String else {
            if Self.isIdentityConflict(status: status, body: obj) { throw AuthError.identityAlreadyExists }
            throw AuthError.badResponse(status)
        }
        if let refresh = obj["refresh_token"] as? String { saveRefreshToken(refresh) }
        return token
    }

    /// GoTrue answers 422 `identity_already_exists` when the identity belongs to another user.
    nonisolated static func isIdentityConflict(status: Int, body: [String: Any]) -> Bool {
        let code = (body["error_code"] as? String) ?? (body["code"] as? String) ?? ""
        return code == "identity_already_exists" || (status == 422 && code.isEmpty
            && ((body["msg"] as? String) ?? "").localizedCaseInsensitiveContains("already"))
    }
    // @endif

    // MARK: - Session

    private func fetchFreshToken() async throws -> String {
        invalidateCachedToken()
        if let refresh = loadRefreshToken() {
            do {
                let token = try await refreshSession(refresh)
                cache(token)
                return token
            } catch let e as RefreshError where e.tokenRejected {
                deleteSession()   // the server says this identity is dead
            }
            // Any other error propagates: opening a new identity would strand the user's purchases.
        }
        let token = try await anonymousSignUp()
        cache(token)
        return token
    }

    private func cache(_ token: String) {
        cachedAccessToken = token
        cachedExpiry = Self.expiry(of: token)
    }

    /// JWT `exp`; falls back to 50 minutes (Supabase default lifetime is one hour).
    nonisolated static func expiry(of token: String) -> Date {
        let fallback = Date().addingTimeInterval(50 * 60)
        guard let exp = claims(of: token)?["exp"] as? Double else { return fallback }
        return Date(timeIntervalSince1970: exp)
    }

    nonisolated static func claims(of token: String) -> [String: Any]? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        guard let data = Data(base64Encoded: b64) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    // MARK: - Network

    /// Anonymous sign-in (`supabase.auth.signInAnonymously()` = POST /auth/v1/signup with `{}`).
    private func anonymousSignUp() async throws -> String {
        guard let url = URL(string: "\(AppConfig.supabaseURL)/auth/v1/signup") else { throw AuthError.notConfigured }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
        guard (200..<300).contains(status),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = obj["access_token"] as? String
        else { throw AuthError.badResponse(status) }
        if let refresh = obj["refresh_token"] as? String { saveRefreshToken(refresh) }
        return token
    }

    private func refreshSession(_ refreshToken: String) async throws -> String {
        guard let url = URL(string: "\(AppConfig.supabaseURL)/auth/v1/token?grant_type=refresh_token") else {
            throw AuthError.notConfigured
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["refresh_token": refreshToken])
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw RefreshError(status: -1, tokenRejected: false) }
        guard (200..<300).contains(http.statusCode),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = obj["access_token"] as? String
        else {
            throw RefreshError(status: http.statusCode, tokenRejected: Self.isTokenRejection(status: http.statusCode))
        }
        // Supabase rotates refresh tokens: store the new one.
        if let refresh = obj["refresh_token"] as? String { saveRefreshToken(refresh) }
        return token
    }

    // MARK: - Keychain

    private func keychainQuery(sync: Bool) -> [String: Any] {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: kService,
            kSecAttrAccount as String: kAccount,
        ]
        if sync { q[kSecAttrSynchronizable as String] = kCFBooleanTrue! }
        return q
    }

    private func saveRefreshToken(_ refresh: String) {
        let value = Data(refresh.utf8)
        var syncAdd = keychainQuery(sync: true)
        SecItemDelete(syncAdd as CFDictionary)
        syncAdd[kSecValueData as String] = value
        let syncStatus = SecItemAdd(syncAdd as CFDictionary, nil)

        var localAdd = keychainQuery(sync: false)
        SecItemDelete(localAdd as CFDictionary)
        localAdd[kSecValueData as String] = value
        localAdd[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let localStatus = SecItemAdd(localAdd as CFDictionary, nil)

        if syncStatus != errSecSuccess && localStatus != errSecSuccess {
            Tracker.log(custom: "keychain_save_failed", ["reason": "sync_\(syncStatus)_local_\(localStatus)"])
        }
    }

    private func loadRefreshToken() -> String? {
        for sync in [true, false] {
            var q = keychainQuery(sync: sync)
            q[kSecReturnData as String] = kCFBooleanTrue!
            q[kSecMatchLimit as String] = kSecMatchLimitOne
            var item: CFTypeRef?
            if SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess,
               let data = item as? Data, let token = String(data: data, encoding: .utf8) {
                return token
            }
        }
        return nil
    }

    /// Removes BOTH copies; leaving the local one behind would resurrect a rejected token.
    private func deleteSession() {
        SecItemDelete(keychainQuery(sync: true) as CFDictionary)
        SecItemDelete(keychainQuery(sync: false) as CFDictionary)
        invalidateCachedToken()
    }
}
