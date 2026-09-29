# Setup

Setup happens inside your agent. After adding the MCP (see the [README](../README.md)), ask it to "Set up
AppFactory". It uses these tools, none of which need a config file:

- `setup_status()`: per service, whether it is enabled, which keys are set or missing (never the values), missing
  tools with install commands, the approvals mode, and what to do next.
- `setup_services(enable, disable)`: choose services (research is always on).
- `setup_set(key, value)`: non-secret keys only (Key ID, Issuer ID, Team ID, .p8 path, support email, ...).
- Keys, like any MCP: environment variables on the MCP entry, named `APPFACTORY_<KEY>` (e.g.
  `APPFACTORY_ASC_KEY_ID`, `APPFACTORY_SUPABASE_ACCESS_TOKEN`). `setup_status()` returns ready-to-edit `add_keys`
  commands for Claude Code, Codex, Gemini CLI and Cursor. Environment values override the file and are never
  written to it.
- `setup_credentials(services)` (optional alternative): opens a local page in your browser (127.0.0.1, random port, one-time token,
  stops after Save or 30 idle minutes) where you type the secrets and can test the App Store Connect connection.
  Secrets never pass through the chat or the model, and the page never shows saved values again.
- `setup_approvals("required")`: only you can turn human approvals off, with the toggle on that page.

Keys are stored in `~/.appfactory/config.toml` (mode 0600). `appfactory doctor` shows what is configured;
`appfactory setup` is an optional terminal wizard for the same thing (`appfactory setup --browser` opens the page).
Only set up the services you use: see "Choose what you use" in the [README](../README.md).

AppFactory runs locally on a Mac against your own accounts. Toolchain per service: Xcode + `xcodegen`
(xcode), the [`asc` CLI](https://github.com/rorkai/App-Store-Connect-CLI) (apple), `supabase` + `deno`
(supabase), `firebase` (firebase), `gh` (github), Maestro + Java 17+ (maestro), `node` (lottie).

## Apple Developer (service `apple`)
1. [App Store Connect > Users and Access > Integrations](https://appstoreconnect.apple.com/access/integrations/api):
   create an API key (App Manager or Admin) and download the `.p8` (downloadable once).
2. Note the Key ID, the Issuer ID and the `.p8` path; the Team ID is on the
   [Membership](https://developer.apple.com/account/#/membership) page.
3. `brew install asc`. Every App Store Connect call goes through it. AppFactory passes the configured key as
   `ASC_KEY_ID` / `ASC_ISSUER_ID` / `ASC_PRIVATE_KEY_PATH`. Fallback: store the key in the keychain with
   `asc auth login --name appfactory --key-id ... --issuer-id ... --private-key /path/to/AuthKey.p8`.
   `ASC_READ_ONLY=1` turns every asc write into a refusal (audits, dry runs).
4. Creating the app record also needs an Apple ID (Apple's public API cannot create apps, so `fastlane produce`
   is used for that one step): `apple_id`, `apple_app_specific_password` and a `fastlane spaceauth` session.
5. Sales reports and Small Business Program proof (`asc_sbp_check`) need a Finance-capable key
   (`asc_finance_key_id`, `asc_finance_key_filepath`) and `asc_vendor_number`.

## Supabase (service `supabase`)
A personal access token from [Account > Access Tokens](https://supabase.com/dashboard/account/tokens)
(`supabase_access_token`). One project per app.

## RevenueCat (service `revenuecat`)
`rc_secret_key`: a RevenueCat v2 secret key. Server-side only, never in an app.

## AI features (service `ai`)
Optional keys `fal_key`, `openai_api_key`, `anthropic_api_key`. They go only to server-side Supabase secrets and
never into the app binary.

## Store and legal identity
`support_email` (legal pages, review contact, listing), `legal_controller` (legal name in the privacy policy and
terms), `review_contact_phone` (App Review contact; never logged or committed). The App Store copyright is
per app (`spec.store.copyright`, default `(c) <year> <app name>`).

## Per-app choices
Everything app-specific lives in `<app>/app.spec.json`. A few values go through `app_inject_config`:

- `paywall_strategy`: `hard_only`, or `hard_and_offer` (default: hard paywall, then an offer paywall on dismiss).
- Credits mode (`monetization: credits`): `yearly_credits`, `weekly_credits`, `credit_pack_small/medium/large`.
- Onboarding length: `onboarding_plan(step_count=N)` returns guidance for the chosen count.
- Locales come from the spec (6 in-app, 8 store by default).

## Check
```
appfactory doctor     # services, keys, binaries
```
or, from the agent: `config_doctor`, `env_doctor`, `asc_token_check`, `orchestrator_preflight`.

## Environment variables

Every key can be passed on the MCP entry. Secrets are marked.

| Variable | What | Secret |
|---|---|---|
| `APPFACTORY_ASC_KEY_ID` | App Store Connect API Key ID (from the .p8 file name) |  |
| `APPFACTORY_ASC_ISSUER_ID` | App Store Connect Issuer ID |  |
| `APPFACTORY_ASC_KEY_FILEPATH` | Full path to the AuthKey_*.p8 file |  |
| `APPFACTORY_TEAM_ID` | Apple Developer Team ID |  |
| `APPFACTORY_APPLE_ID` | Apple ID email (ASC app creation via fastlane produce) |  |
| `APPFACTORY_APPLE_APP_SPECIFIC_PASSWORD` | Apple app-specific password (fastlane produce fallback for app creation) | yes |
| `APPFACTORY_APPLE_SESSION` | fastlane spaceauth FASTLANE_SESSION (app creation, 2FA, ~30 days) | yes |
| `APPFACTORY_SUPABASE_ACCESS_TOKEN` | Supabase account access token | yes |
| `APPFACTORY_FAL_KEY` | fal.ai (Flux) API key — server-side (ai-proxy secret) | yes |
| `APPFACTORY_REPLICATE_TOKEN` | Replicate API token — server-side (ai-proxy secret) | yes |
| `APPFACTORY_OPENAI_API_KEY` | OpenAI API key (optional) — server-side | yes |
| `APPFACTORY_ANTHROPIC_API_KEY` | Anthropic API key (optional) — server-side | yes |
| `APPFACTORY_COPYRIGHT` | ASC submission copyright text (e.g. '© 2026 Your Name') |  |
| `APPFACTORY_SUPPORT_EMAIL` | Public support/contact email (legal pages, App Review contact, listing) |  |
| `APPFACTORY_LEGAL_CONTROLLER` | Legal name of the developer / data controller in the privacy policy and terms |  |
| `APPFACTORY_RC_SECRET_KEY` | RevenueCat v2 secret key (GLOBAL, all apps) — server-side only, never in an app | yes |
| `APPFACTORY_REVIEW_CONTACT_PHONE` | App Review contact phone (store_setup reads it; never logged or committed) | yes |
| `APPFACTORY_ASC_FINANCE_KEY_ID` | ASC API key id with Finance access (sales reports / SBP proof; issuer shared) |  |
| `APPFACTORY_ASC_FINANCE_KEY_FILEPATH` | Full path to the Finance-capable AuthKey_*.p8 (e.g. ~/.appfactory/AuthKey_<id>.p8) |  |
| `APPFACTORY_ASC_VENDOR_NUMBER` | App Store Connect vendor number (Payments and Financial Reports; sales reports) |  |
| `APPFACTORY_GITHUB_USER` | GitHub account that owns app repos (optional; empty = the active `gh` account) |  |
| `APPFACTORY_SIGNING_IDENTITY` | Name on the Apple Distribution certificate (optional; empty = auto-detect) |  |
| `APPFACTORY_SERVICES` | Comma-separated services to enable (e.g. `apple,xcode,supabase`) | |
