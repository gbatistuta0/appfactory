# Setup

`appfactory setup` walks through all of this interactively (secrets are read with a hidden prompt and stored in
`~/.appfactory/config.toml`, mode 0600). `appfactory doctor` shows what is configured and what is missing.
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
