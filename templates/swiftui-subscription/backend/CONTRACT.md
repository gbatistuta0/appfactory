# __DISPLAY_NAME__ API contract (v1)

Owner: backend. Consumer: the iOS app. Source of truth for behaviour: `supabase/functions/` and
`supabase/migrations/`; values (quotas, models, placements, languages) come from `app.spec.json`
and are written into the Supabase secrets by `backend_deploy`. Changes to this file are announced
to the lead before they ship.

- Base URL: `__SUPABASE_URL__` (`https://<project-ref>.supabase.co`)
- Public client key: the project's **anon** key (a public key; it ships in `AppConfig`). It is sent
  as the `apikey` header on every request.

## 1. Identity: anonymous first, then Sign in with Apple

1. On first launch the app signs in **anonymously** (`supabase.auth.signInAnonymously()`) and keeps
   the session in the Keychain. That `user.id` is the identity for everything: rows in every table,
   quotas, and the RevenueCat `app_user_id` (`Purchases.configure(withAPIKey:appUserID: user.id)`).
2. Every request sends `apikey: <anon key>` and `Authorization: Bearer <access_token>`. Access
   tokens live 1 hour; refresh them through the Supabase client, never cache one forever.
3. Only discard the session when the server rejects the refresh (400/401/403). A network error is
   not a reason to drop the identity: a new identity loses the free analysis, the history and the
   subscription link (production incident).
4. **Sign in with Apple** ("Save your progress", optional, never before the first value moment):
   - Apple provider: native ID-token flow, client id = the bundle id (`supabase/config.toml`
     `[auth.external.apple]`). Anonymous sign-ins and manual identity linking are on.
   - Request `ASAuthorizationAppleIDProvider` with scopes `[.email]` and `nonce = sha256(rawNonce)`.
   - **Link** the Apple identity to the *current anonymous user* with the ID-token link call
     (supabase-swift: `auth.linkIdentityWithIdToken(credentials: OpenIDConnectCredentials(provider:
     .apple, idToken:, nonce: rawNonce))`; check the SDK version you pin exposes it). The user id does
     not change, so RevenueCat, quotas and history stay attached. No `Purchases.logIn` is needed.
   - If the Apple identity already belongs to another user (the link fails with
     `identity_already_exists`), this is a **restore on a new device**: sign in with the ID token
     (`auth.signInWithIdToken`), then `Purchases.logIn(newUser.id)`, then reload usage-status. The
     abandoned anonymous user keeps nothing of value (its free analysis stays used server-side only
     for that id).
   - The email may be an Apple private-relay address. The backend never requires it.
5. If spec `consent.health` is on (see `usage-status`/section 2), upsert `profiles.consent_health_at`
   before the first analysis; without it `analyze` answers 403 `consent_required`.

## 2. `POST /functions/v1/analyze`

Runs the app's AI analysis on a photo or a short text. The prompt and the result shape are
app-specific (`supabase/functions/_shared/analysis.ts`); everything else below is fixed.

### Request

```jsonc
// Photo
{
  "mode": "photo",
  "image": { "data": "<base64 JPEG>" },   // also accepted: a "data:image/jpeg;base64,…" prefix
  "note": "optional, ≤ 280 chars",
  "locale": "tr-TR"                       // any tag; mapped to an app language, default en
  // + app-specific fields validated by analysis.ts validateOptions()
}
// Text
{ "mode": "text", "text": "1–500 characters", "locale": "en-US" }
```

Image rules: JPEG (PNG/WebP accepted, HEIC is not), long edge ≤ 1024 px, quality ~0.7, at most
`MAX_IMAGE_BYTES` (1.5 MB) decoded. Re-encode on device (`UIImage.jpegData`) so EXIF location data
never leaves the phone.

### 200 OK

```jsonc
{
  "analysis_id": 1234,
  "mode": "photo",
  "locale": "tr",                 // the result's language
  "result": { /* app-specific, see analysis.ts AnalysisResult */ },
  "usage": { /* same shape as usage-status, after this analysis */ }
}
```

### Errors

Every error body is JSON with an `error` code. The app branches on `error`, never on the message.
Order of checks: auth → validation → consent → subscription check → quota → model.

| HTTP | `error` | Exact extra fields | What the app does |
|---|---|---|---|
| 400 | `invalid_request` | `message` | Bug: log it. |
| 401 | `unauthorized` | – | Refresh the session and retry once. |
| 403 | `consent_required` | – | Only when consent is required: show the consent step, upsert `consent_health_at`, retry. Costs nothing. |
| 402 | `paywall_required` | `reason`: `free_scan_used` \| `subscription_required`; `placement` (`free_scan_used`) | Open the paywall with `placement`. |
| 413 | `image_too_large` | `message` | Bug: re-encode smaller. |
| 415 | `unsupported_image` | `message` | Bug: send JPEG. |
| 422 | `not_applicable` | `usage` | "This photo is not something we can analyse" + retake. Does not use a scan. |
| 429 | `daily_cap_reached` | `placement: "daily_cap"`, `mode`, `limit`, `resets_at` | Daily-limit sheet with the reset time. |
| 429 | `too_many_attempts` | `resets_at` | Same sheet, generic copy (abuse backstop, rare). |
| 500 | `internal_error` | `retryable: true` | Retry button. |
| 502 | `analysis_failed` | `retryable: true` | Retry button. Does not use a scan. |
| 503 | `entitlement_unavailable` | `retryable: true` | "Couldn't verify your subscription", retry. **Never** show the paywall for this. |

Exact bodies:

```jsonc
{ "error": "paywall_required", "reason": "free_scan_used", "placement": "free_scan_used" }
{ "error": "paywall_required", "reason": "subscription_required", "placement": "free_scan_used" }
{ "error": "daily_cap_reached", "placement": "daily_cap", "mode": "photo", "limit": 12, "resets_at": "2026-09-24T21:00:00.000Z" }
{ "error": "too_many_attempts", "resets_at": "2026-09-25T10:00:00.000Z" }
{ "error": "consent_required" }
{ "error": "entitlement_unavailable", "retryable": true }
```

### Quotas (server-enforced, from `app.spec.json` `usage`)

<!-- quotas:begin -->
| Who | Photo analyses | Text analyses |
|---|---|---|
| Not subscribed | 1 successful analysis, lifetime (free modes: photo) | needs a subscription (402 `subscription_required`) |
| Subscribed (incl. free trial, billing grace period, sandbox/TestFlight) | 12 per local calendar day | 20 per local calendar day |

Abuse backstop: 5 billed calls per rolling 24 h for non-subscribers, 60 for subscribers.
Consent required before the first analysis: no.
<!-- quotas:end -->

- Only successful analyses count. `not_applicable` and failures (`502`) never use a scan.
- Caps reset at **local midnight** of `profiles.timezone` (send the device's IANA zone,
  `TimeZone.current.identifier`, on onboarding and whenever it changes). `resets_at` is that
  midnight as a UTC instant. A timezone change is honoured for the caps at most once per 24 h.
  No profile/timezone → UTC. `usage.timezone` says which zone the caps currently use.
- Subscription status comes from RevenueCat on the server. A user who just purchased is recognised
  on the very next request. The app never sends its entitlement. A subscriber in Apple's billing
  grace period keeps access until the grace expiry.

## 3. `POST /functions/v1/usage-status`

No body, no model call. Use it for the home-screen counter and to decide whether the capture
button opens the camera or the paywall.

```jsonc
{
  "tier": "premium",                 // "free" | "premium"
  "free_scan_available": false,
  "timezone": "Europe/Istanbul",     // zone of the cap day (premium), null for free
  "photo": { "limit": 12, "used": 3, "remaining": 9, "resets_at": "2026-09-24T21:00:00.000Z" },
  "text":  { "limit": 20, "used": 0, "remaining": 20, "resets_at": "2026-09-24T21:00:00.000Z" }
}
```

For `tier: "free"` the limits are lifetime allowances (`resets_at: null`); a mode that is not free
has `limit: 0`. Errors: 401 `unauthorized`, 503 `entitlement_unavailable`, 500 `internal_error`.

## 4. `POST /functions/v1/delete-account`

Settings → "Delete account". Body must be exactly `{"confirm": "DELETE"}`. Deletes the auth user;
every table cascades, so all profile, usage and app data is gone.

- 200 `{"deleted": true}` → sign out locally, clear the Keychain session, `Purchases.logOut()`,
  return to onboarding. The next launch creates a new anonymous user.
- 400 `invalid_request` (missing confirmation), 401 `unauthorized`, 500 `internal_error` (retryable).
- The App Store subscription is not cancelled by this. Before deleting, tell the user to cancel it
  in Settings → Apple ID → Subscriptions (App Review expects that notice).

## 5. Tables (PostgREST, `/rest/v1/<table>`)

Row Level Security restricts every query to `auth.uid()`.

### `profiles` — one row per user, `id` = `auth.uid()`

Write with `upsert` (`Prefer: resolution=merge-duplicates`) after onboarding and whenever settings change.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | = user id (required) |
| `locale` | text | app language tag, e.g. `tr`, `pt-BR` |
| `timezone` | text | IANA, e.g. `Europe/Istanbul`; unknown names → 400. Drives the daily caps. |
| `attribution` | text | onboarding "how did you hear about us" key, ≤ 40 chars |
| `answers` | jsonb object | onboarding answers, app-defined keys (typed columns may be added by the app's own migration) |
| `consent_health_at` | timestamptz | Send any timestamp to give consent; the server stamps its own time and keeps the first one. `null` withdraws. |

`cap_timezone` / `cap_timezone_changed_at` are server-managed and not writable.

### `ai_usage` — read-only, own rows

The app may read `id, mode, tier, status, result, created_at` (e.g. to restore the last result
after a crash). Cost, tokens and model are server-only; selecting them fails.

### `events` — insert only

`POST /rest/v1/events {"name": "paywall_view", "props": {"from": "onboarding"}}` (backup of the
Firebase event stream; the app cannot read events back).

## 6. Legal pages (public, no auth)

- Privacy Policy: `__SUPABASE_URL__/functions/v1/legal/privacy`
- Terms of Use: `__SUPABASE_URL__/functions/v1/legal/terms`
- Support: `__SUPABASE_URL__/functions/v1/legal/support`

Plain text. Append `?lang=<app language>` when opening them from the app so the page matches the UI
language; without it the browser's Accept-Language decides, then English. Open them in
`SFSafariViewController`. The same URLs (with the listing locale's `?lang=`) go into App Store
Connect. Until a document is published the URL answers 404 "not been published yet".

## 7. Things the server never does

- It never stores the photo. The image goes to the model provider and is discarded (see
  `backend/PRIVACY.md`).
- It never trusts client claims about the subscription, the free analysis or quotas.
- It never returns a paywall because RevenueCat was unreachable (503 instead).
