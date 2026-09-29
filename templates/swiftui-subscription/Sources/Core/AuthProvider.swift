import AuthenticationServices
import CryptoKit
import Foundation

/// Account linking on the "Save your progress" onboarding step and in Settings.
///
/// The identity is ALWAYS the anonymous Supabase user first (backend CONTRACT §1). Linking adds
/// the Apple identity to that same user (`linkIdentity` with the Apple id_token), so the user id —
/// and with it the RevenueCat subscription and server quotas — never changes. If the Apple ID
/// already belongs to another account (a returning user on a new device), we sign in as that
/// account instead and RevenueCat follows with `logIn`.
enum AuthProviderKind: String, CaseIterable {
    case apple
}

enum AuthResult: Equatable {
    /// The anonymous user is now linked to the provider identity (same user id).
    case linked
    /// Signed in as the existing account that owns this identity (user id changed).
    case switchedAccount(userID: String)
    /// Backend not configured (fresh scaffold, tests): the flow continues as if skipped.
    case unavailable
    /// The user closed the provider sheet.
    case cancelled
    case failed

    var isSignedIn: Bool {
        switch self {
        case .linked, .switchedAccount: return true
        default: return false
        }
    }
}

/// One interface for every identity provider, so wiring another one is a one-file change.
protocol AuthProvider {
    var kind: AuthProviderKind { get }
    /// Link the provider credential to the current anonymous user.
    func link(_ credential: ProviderCredential) async -> AuthResult
}

/// What a provider sheet hands back: an OpenID Connect id_token plus the raw nonce whose SHA-256
/// was sent to the provider.
struct ProviderCredential: Equatable {
    let provider: AuthProviderKind
    let idToken: String
    let rawNonce: String
}

/// Links through Supabase Auth (`POST /auth/v1/token?grant_type=id_token`, `link_identity: true`).
struct SupabaseAuthProvider: AuthProvider {
    let kind: AuthProviderKind

    func link(_ credential: ProviderCredential) async -> AuthResult {
        guard AppConfig.isSupabaseConfigured else { return .unavailable }
        do {
            _ = try await SupabaseAuth.shared.linkIdentity(provider: kind.rawValue, idToken: credential.idToken,
                                                           nonce: credential.rawNonce)
            return .linked
        } catch SupabaseAuth.AuthError.identityAlreadyExists {
            // Returning user: the Apple ID owns another account. Sign in as that account.
            guard let uid = try? await SupabaseAuth.shared.signInWithIdToken(
                provider: kind.rawValue, idToken: credential.idToken, nonce: credential.rawNonce) else { return .failed }
            return .switchedAccount(userID: uid)
        } catch {
            return .failed
        }
    }
}

enum AuthProviders {
    static func provider(for kind: AuthProviderKind) -> AuthProvider {
        SupabaseAuthProvider(kind: kind)
    }

    /// Providers shown on the save-progress screen.
    static var visible: [AuthProviderKind] { [.apple] }
}

/// Sign in with Apple helpers: nonce generation and credential extraction for
/// `SignInWithAppleButton`'s request/completion closures.
enum AppleSignIn {
    /// A random nonce; its SHA-256 goes to Apple, the raw value to Supabase.
    static func randomNonce(length: Int = 32) -> String {
        let charset = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
        var generator = SystemRandomNumberGenerator()
        return String((0..<length).map { _ in charset[Int.random(in: 0..<charset.count, using: &generator)] })
    }

    static func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func configure(_ request: ASAuthorizationAppleIDRequest, rawNonce: String) {
        request.requestedScopes = [.email]  // CONTRACT §1.4; may be a private-relay address
        request.nonce = sha256(rawNonce)
    }

    enum Outcome: Equatable {
        case credential(ProviderCredential)
        /// No credential: report this result (cancelled / failed).
        case finished(AuthResult)
    }

    /// Completion → credential, or the result to report when there is none.
    static func outcome(from result: Result<ASAuthorization, Error>, rawNonce: String) -> Outcome {
        switch result {
        case .success(let auth):
            guard let apple = auth.credential as? ASAuthorizationAppleIDCredential,
                  let data = apple.identityToken, let token = String(data: data, encoding: .utf8)
            else { return .finished(.failed) }
            return .credential(ProviderCredential(provider: .apple, idToken: token, rawNonce: rawNonce))
        case .failure(let error):
            let cancelled = (error as? ASAuthorizationError)?.code == .canceled
            return .finished(cancelled ? .cancelled : .failed)
        }
    }
}
