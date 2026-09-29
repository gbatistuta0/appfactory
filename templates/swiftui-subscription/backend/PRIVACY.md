# __DISPLAY_NAME__ data processing (backend facts for the privacy policy and App Privacy labels)

Owner: backend. States what the system does, as configured by the factory template; the legal
wording lives in `store/privacy/*.md`. Re-check after any provider change. Sections between
`<!-- if:… -->` markers are kept or dropped by `legal_render` from `app.spec.json`.

## What leaves the device

| Data | When | Where it goes | Stored by us |
|---|---|---|---|
| Photo (JPEG, re-encoded on device: no EXIF/GPS) | Each photo analysis | Supabase edge function → fal.ai → OpenRouter → model host | **No.** Never written to our database or storage. |
| Optional note / text description | Each analysis | Same path as the photo | No. The resulting analysis is stored. |
| Language | Each analysis | Same path (inside the prompt) | Yes, `profiles.locale` |
| Onboarding answers, timezone, attribution | Onboarding and settings | Supabase | Yes, `profiles` |
| Analysis records (mode, status, result, model, tokens, cost, latency) | Each analysis | Supabase | Yes, `ai_usage` |
| Refused requests (reason: free analysis used, subscription required, daily cap, too many attempts, subscription check unavailable, consent missing; time) | When `analyze` refuses a request | Supabase | Yes, `ai_denials`, service role only |
| App events (name + small props) | While using the app | Supabase (backup of Firebase) | Yes, `events` |
| Anonymous user id | Always | Supabase, RevenueCat | Yes |
| Email address (possibly an Apple private-relay address) and Apple user id, **only if the user chooses Sign in with Apple** | On sign-in | Supabase Auth (linked to the same user) | Yes, until account deletion |
| Consent timestamp | When given or withdrawn | Supabase | Yes, `profiles.consent_health_at` |
| Purchase status | Purchases, and each analysis by a non-subscriber | RevenueCat (server-to-server lookup by user id) | Cached in `entitlements` (never beyond the subscription's access end) |
<!-- if:consent.health -->
| Apple Health (HealthKit) data the app reads or writes | Only after the user grants each HealthKit permission | Stays on the device unless a row below says otherwise | See "Apple Health" |
<!-- endif -->

The account starts anonymous. The backend collects no name or phone number, and an email address
only when the user opts into Sign in with Apple. No advertising identifier is used by the backend.

<!-- if:consent.health -->
## Apple Health (HealthKit)

- **Read**: {{HEALTHKIT_READ_TYPES}} (e.g. active energy, body mass), only with the user's
  per-type permission, to {{HEALTHKIT_PURPOSE}}.
- **Written**: {{HEALTHKIT_WRITE_TYPES}} (or "nothing").
- HealthKit data is **never used for advertising or marketing**, never sold, never shared with
  data brokers, and never used to track the user (App Store Review Guideline 5.1.2 and 5.1.3).
- HealthKit data is **never sent to the AI model provider** unless the privacy policy says so for a
  named field; today: {{HEALTHKIT_TO_AI}} (default: never).
- Values synced to our backend: {{HEALTHKIT_SYNCED}} (default: none). Deleted with the account.
- Explicit consent (`profiles.consent_health_at`, GDPR Art. 9 / KVKK) is required before the first
  analysis (`REQUIRE_CONSENT=true`).
<!-- endif -->

## Processors

| Processor | Role | Region | Retention / training (as documented by the provider) |
|---|---|---|---|
| Supabase | Database, auth (anonymous accounts, Sign in with Apple), edge functions | project region | Until the user deletes the account. |
| fal.ai | Model gateway | US | We send `X-Fal-Store-IO: 0`, which disables fal's default 30-day storage of request/response payloads (the photo travels inside the payload). fal API terms: client content is not used to train fal's products. |
| OpenRouter | Routing to the model host (reached through fal) | US | Every request sets `provider.data_collection = "deny"`: only hosts that do not collect or train on prompts are used. |
| Model host (e.g. Google Gemini via OpenRouter) | The AI model (`AI_MODEL`, fallback `AI_FALLBACK_MODEL`) | – | Reached only through OpenRouter under "deny data collection" routing. |
| RevenueCat | Subscription status | US | Purchase history keyed by the anonymous user id. |

## Retention and deletion

- Photos: not retained by us; provider-side retention as above.
- Everything in Supabase is keyed to the user id and removed by one cascade when the auth user is
  deleted (tested in `supabase/tests/db_test.ts`). The in-app "Delete account" action calls
  `delete-account`, which deletes the auth user immediately. RevenueCat keeps its purchase history
  for the old id; the App Store subscription stays with the user's Apple ID until they cancel it.

## App Privacy label inputs (for the store stage to map)

- Photos: sent for analysis and not stored. App functionality, not linked over time.
- User content: notes and text descriptions. App functionality.
- Identifiers: the anonymous user id. App functionality.
- Contact info: email address, only with Sign in with Apple. Linked to the user. App functionality.
- Purchases: subscription status through RevenueCat. App functionality.
- Other data: onboarding answers. App functionality; attribution is also used for analytics.
<!-- if:consent.health -->
- Health & Fitness: the HealthKit types above and any health answers in onboarding. Linked to the
  user. App functionality only.
<!-- endif -->
- No tracking, and nothing is used for third-party advertising by the backend.
