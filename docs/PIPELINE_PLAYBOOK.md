# AppFactory Pipeline Playbook (battle-tested flow)

The reasoning and the gotchas behind every pipeline step, learned end to end on apps shipped with the
factory. Every step is built into the MCP tools and gates;
this document is the "why / order / trap" reference. The per-stage instructions Claude follows live in
`src/appfactory/pipeline.py` (`STAGE_INSTRUCTIONS`), the run discipline in
`.claude/skills/appfactory-run/SKILL.md`.

## App Store Connect backend: the asc CLI
- Every App Store Connect call goes through [`asc`](https://github.com/rorkai/App-Store-Connect-CLI)
  (`brew install asc`), wrapped by `src/appfactory/asc_cli.py`: `--output json`, a timeout, and the repo's
  `{ok, error}` result shape. There is no hand-written HTTP/JWT client any more.
- Credentials: the `asc_key_id` / `asc_issuer_id` / `.p8` from `~/.appfactory/config.toml` are passed as
  `ASC_KEY_ID` / `ASC_ISSUER_ID` / `ASC_PRIVATE_KEY_PATH` (headless). Without them asc uses its keychain
  profile (`asc auth login`). `config_doctor` / `env_doctor` / `asc_token_check` report the binary, version and
  auth source.
- First-class asc commands wherever one exists (apps, versions, bundle ids, subscriptions and groups,
  availability, price points + equalizations + `prices import`, intro offers, review details and submissions,
  age rating, content rights, price schedule, localizations, categories, screenshots, previews, subscription
  review screenshots, certificates, profiles, builds, custom product pages, sales reports).
- `asc api` raw passthrough (`ASCClient.request`) only where asc has no command: `store_setup`'s generic
  JSON:API reconciler, the `gates` IAP read, legacy subscription (group) localizations, screenshot reorder, a new
  app-info locale, reads in `deliver` / `preview` (sets, assets), and a secondary-only category change.
- Read-only safety: `ASC_READ_ONLY=1` in the MCP server's environment makes asc refuse every mutating
  request before it is sent (exit code 6, surfaced as `read_only: true`). Use it for audits and dry runs.
- App creation is the exception: Apple's public API cannot create an app record and `asc web apps create`
  needs an interactive 2FA web session, so `asc_create_app` keeps `fastlane produce` (FASTLANE_SESSION from
  `fastlane spaceauth`).

## Order (pipeline.STAGES)
`scaffold → repo → design_research → design → features → backend → ai_proxy → icon → asc_app → iap →
localize → analytics → aso → metadata → screenshots → app_preview → deliver → custom_product_pages →
testflight → submission_prep`

A stage is never "done" until its gate passes (`pipeline_mark`). Metadata and deliver do not run before
ASO is complete. App Store submission is human-only, in the ASC web UI.

## Idea phase (Phase 0) — any category, AI optional
- Ideas are **not limited to AI or photo→AI apps**. Any iOS subscription
  idea qualifies when its market is rising, revenue-proven, open to newcomers and fits a solo SwiftUI
  subscription build. AI is an optional edge (`spec.ai.enabled`), never a requirement.
- `idea_harvest` sweeps the legacy top-grossing + top-free RSS per genre (all 24 charted App Store
  categories, `aso.GENRES`) × storefront (us, gb, de, br, tr, jp, fr), dedupes, enriches via iTunes lookup
  and returns chart-proven apps, rising newcomers (≤ 12 months, ratings/day) and per-genre "open niche"
  clusters. `idea_evaluate(term, country, genre)` returns the ranking evidence: autocomplete count, niche
  score/verdict, 12- and 6-month newcomer traction, leaders' price ladders, `ai_needed`, build complexity,
  review risk, name availability. Present the top 5.
- GOTCHA: the legacy RSS silently IGNORES an unknown genre id and serves the overall chart; the chart
  fetcher rejects a chart whose entries are not in the requested genre. Kids has no RSS genre (it is an
  age band), Stickers (6025) is empty and Magazines & Newspapers (6021) serves mostly News apps — all three
  are listed in `aso.UNCHARTED_GENRES`. A full default sweep takes ~1.5 minutes.
- GOTCHA: a failed feed is `ok:false` in `failed_feeds`, never "no apps"; unlooked-up ratings are `null`,
  never 0. The genre's AI density in `aso_niche_score` is informational only (not scored).
- Review risk flags: medical and kids high; finance, health, social, music medium.

## Spec-driven decisions (every app)
- **`app.spec.json` is the single source of truth**: monetization (`subscription` by default, `credits`
  for the legacy credit economy), products + intro offers + group levels + price overrides + grace period,
  locales (6 in-app, 8 store by default), the 8 paywall placements, usage caps, AI models, consent/HealthKit,
  analytics prefix, offer anchor, design tokens, onboarding count, mascot. Edit the spec, then regenerate
  (`app_sync_spec`, `storekit_generate`, `backend_render`, `metadata_render_listing`); never hand-edit a
  generated file. `storekit_parity` + `store_setup check` prove ASC == RevenueCat == `Configuration.storekit`.
- **Tab bar is mandatory** (single-page apps are an App Review risk).
- **Funnel:** onboarding → hard personalized paywall (close after ~2.5 s, restore + legal) → dismiss →
  offer paywall with a price anchor → app. Intro offers come only from the spec; never embed extra offers
  (`asc_finalize_subscription(period=…)` must not be used for trial products).
- **Credits mode only (GOTCHA — the renewal period is the PAYMENT period):** yearly credits are granted per
  month, weekly credits per week; otherwise "pay weekly, get monthly credits" contradicts itself. The yearly
  allowance must beat the weekly plan's monthly equivalent (weekly x 4.33); `aso_unit_economics` warns on an
  inverted ladder. No "unlimited" claims.
- **Photo input — images only (GOTCHA):** PhotosPicker always `matching: .images`; on change, check
  `supportedContentTypes` + decode with `UIImage(data:)`, otherwise reset the selection and show the
  "Photos only" alert. Already in the template (`GenerationFlow.swift`); the alert strings are in the generic
  localizations.
- **Rating requests at success moments are mandatory; never in onboarding, rate-limited by RatingPolicy**
  (see the "Submission, store assets, release" section).

## AI backend (only when `spec.ai.enabled`, the default)
- `spec.ai.enabled=false` (non-AI app): the `analyze` edge function is not deployed, `_shared/analysis.ts`
  is not required, `FAL_KEY` is not required, and the `ai_proxy` stage's AI part is n/a — its gate still
  requires the non-AI backend deploy (usage-status, delete-account, legal, rc-webhook) and the published
  legal pages. `AppSpec.aiEnabled` tells the app; the analyze sources stay in the repo, inert.
- AI only through the Supabase edge function (fal OpenRouter router, strict JSON schema, provider data
  collection denied, primary → fallback once); keys never enter the app binary. Every billed call is logged
  with its measured cost → `pricing_unit_economics` → `store/pricing.md`.
- Choose the model by eval (`backend/eval`, dry-run estimate and `--max-cost` first — spending needs approval).
- Image edits that must preserve a face need an edit model that keeps identity; text-to-image models ignore
  the user's photo. The app sends the photo to the proxy as a data URI.

## Analytics (mandatory in every app)
- **Firebase** + **Supabase events** (backup, free). Only production App Store builds send (AnalyticsGate:
  not DEBUG / simulator / tests). Full per-screen instrumentation happens at the end of development.
- `firebase_setup` is fully automatic: gcloud project + Firebase API enable + service account
  (roles/owner — GOTCHA: `serviceusage.services.enable` needs owner) + firebase-tools (the raw addFirebase
  API returns 404) + apps:create + **addGoogleAnalytics** + sdkconfig → `GoogleService-Info.plist`.
- GOTCHA (critical): apps:create does NOT link the project to GA4. Without the link the plist has
  `IS_ANALYTICS_ENABLED=false` and GA4 never sees the app. `_link_google_analytics` calls
  `projects/{pid}:addGoogleAnalytics`, polls the operation, waits ~15 s, THEN fetches sdkconfig. The plist is
  baked into the build: linking GA later needs a NEW build.
- Users are anonymous (anonymous auth): track what happened, not who.

## Legal (mandatory in every app)
- Privacy, terms and support are served by the Supabase **`legal` function**
  (`<functions>/legal/{privacy,terms,support}?lang=`), built from `store/privacy/*.md` in every app
  language (`legal_render` → `legal_check` → deploy → `legal_verify`). The same URLs are used in-app
  (AppConfig, paywall, Settings) and in ASC. Every URL must return 200; empty placeholder domains are rejected.
- Changing the in-app URLs needs a new build.

## IAP / subscriptions (GOTCHA — MISSING_METADATA and 409)
`store_setup` (plan → check → approval → apply via `appfactory approve <id>`) enforces the order; see
`templates/swiftui-subscription/store/CHECKLIST.md` for the full step list. The traps it handles:
- Availability must exist before any price, or ASC answers 409 `RELATIONSHIP.INVALID`.
- Intro offers are per territory (a "global" trial is one offer per territory); a weekly pay-as-you-go offer
  must be `PAY_AS_YOU_GO/ONE_WEEK` (pay-up-front answers 409).
- Price points: `/v1/subscriptions/{id}/pricePoints?filter[territory]=USA`, matched by customerPrice (paged).
- Product ids can never be reused, even after deletion.

## Localization (GOTCHA)
- Default: 6 in-app languages (en, es, pt-BR, de, fr, tr) and 8 store locales (en-US, en-GB, es-MX, es-ES,
  pt-BR, de-DE, fr-FR, tr), from the spec.
- App Store/IAP codes vs in-app codes: some store locales need a region suffix (bn-BD, sl-SI, ta-IN, de-DE,
  es-ES, fr-FR, ...; a bare code answers 409 "not a valid locale"), while the in-app String Catalog uses the
  BARE code (de, fr, ta) — `config.IN_APP_TO_ASC` maps them. Norwegian: in-app "nb", App Store "no".
- `build_catalog` is **additive** (keeps existing strings) and merges `data/generic_localizations.json`
  (Continue, Settings, Restore, Privacy, Terms, Manage Subscription, Photos only, ...), so each app only
  translates its own strings. A new generic string = one key in that JSON.
- **Restart gotcha:** after changing `localize.py` or `generic_localizations.json`, RESTART the MCP server,
  otherwise `localize_apply` runs the old code.
- **Completeness:** a missing string falls back to English and the screen shows mixed languages. Parameter
  strings (`Text(value: String)`, `SettingsRow(title:)`, option arrays) escape Xcode's auto-extraction — add
  them by hand. Dynamic display strings need `Text(LocalizedStringKey(value))`.
  `LocalizationCompletenessTests`, `LocalizationUITests` and `LayoutAuditUITests` (OCR truncation, English
  leftovers, glyphs, overflow) must be clean.

## Metadata (GOTCHA)
- fastlane deliver's metadata upload had a "No data" bug → metadata goes through the asc CLI
  (`upload_metadata_api`): name/subtitle/privacy URL → `asc localizations update --type app-info`,
  description/keywords/promo/support → `asc localizations update|create` on the version, categories →
  `asc categories set`. A brand-new app-info locale is created through `asc api` (asc has no create command
  for it).
- Keywords: comma-separated, no space after the comma (spaces inside a phrase are fine). Arabic commas and
  CJK list marks are errors; a language's own name in its keywords is filler.
- **Privacy Policy URL is a submission blocker** in every locale (appInfoLocalizations.privacyPolicyUrl).
- Categories are app-level (spec.store primary/secondary), not per locale.

## Screenshots (mandatory)
- The layout comes from the brief's screenshot concept (competitors' sets studied: frame-1 hook, caption
  style, framing, backgrounds, sequencing, badges; research refreshed when older than 45 days), authored as
  Claude Design `ST` boards with the real captions + captures, uploaded and recorded.
  `screenshot_build_all` applies `store_layout.json`, captures the concept's shots per store locale
  (ScreenshotMode launch args reach every screen without the PhotosPicker), brands and syncs.
  Same number of screenshots in every language.
- Upload (solved): fastlane deliver is unreliable for screenshots (silently drops images, all-or-nothing
  overwrite, 10-per-device limit). `deliver_screenshots` uses `sync_screenshots_api`: MD5-incremental (skip
  when the local MD5 equals ASC's sourceFileChecksum, otherwise `asc screenshots delete` + `asc screenshots
  upload` one file at a time — asc reserves, uploads, commits with the MD5 and creates a missing set), then
  reorder by file name (`asc api` PATCH; asc has no reorder command). The display type comes from the PNG size.
- `deliver_screenshots_audit` (files, order, COMPLETE, MD5) must be clean before submission.

## End-to-end tests: Maestro (mandatory before TestFlight)
- iOS apps are tested on the Simulator with the `maestro` MCP. Open the Maestro Viewer
  (`open_maestro_viewer`, http://localhost:7777) so you can watch; drive the installed Debug build
  with `inspect_screen` / `run`; save every passing flow as YAML in the app's `.maestro/flows/`.
- The template ships `.maestro/config.yaml` + `flows/smoke_onboarding_paywall.yaml` (appId filled in at
  scaffold time from `__BUNDLE_ID__`). It walks any onboarding generically (consent, first option, continue,
  account skip) until `paywall_cta` shows, then asserts the title, a plan and Restore. It never taps a buy
  button. Expect ~3–4 minutes: Maestro waits for the animated steps to settle after every tap.
- Every test run opens the Viewer, not just interactive driving. `maestro test` never starts it (only
  `maestro mcp` does), so `maestro_test` and every app runner script go through `tools/maestro-live`: it
  starts `maestro mcp`, opens http://localhost:7777 (or the next free port) in the browser, and runs each
  flow with the MCP `run` tool, retrying when the device is not reachable yet. Plain `maestro test`
  (`headless=True`, `--headless` in app scripts) is for CI only.
- `maestro_test(app_dir, tags="smoke")` → per-flow results in `build/maestro/results.json`, JUnit in
  `build/maestro/report.xml`, marker `.appfactory/verify/maestro.json`. The features gate and `testflight_ship`
  refuse unless every `smoke` flow passed and no `.maestro/` YAML changed after the run.
- GOTCHAS: launch argument keys need the leading dash (`-uiTest: true`), Maestro
  passes them verbatim; `clearState` does not reset UserDefaults (use `-resetOnboarding`); a sheet presented
  on top of another sheet is missing from Maestro's hierarchy (keep it from appearing with a launch flag);
  two sessions on Maestro's default driver port 22087 read each other's simulator, so the headless runner
  uses 22187. `maestro mcp` hardcodes 22087 (no option), so maestro-live refuses to start (exit 3) while
  another simulator's driver holds that port, and stops the driver it started when it ends: one
  Viewer-backed run at a time per Mac.

## Signing + TestFlight (GOTCHA — headless)
- `testflight_ship`: distribution cert (CSR → `asc certificates create`) → **legacy p12** (PBE-SHA1-3DES,
  sha1 MAC: macOS keychain cannot read OpenSSL 3 p12s) → temporary keychain + **Apple WWDR intermediates**
  (otherwise "0 valid identities") → App Store profiles (`asc profiles create`) → manual-signing export →
  `asc builds upload --ipa` (replaces altool). No system keychain password needed.
- errSecInternalComponent at export: a reused keychain needs `set-key-partition-list` (+ a long
  `set-keychain-settings -t`). If the keychain password is lost, delete the unreachable DISTRIBUTION certs
  in ASC and let setup create a fresh one (revoking a cert does not affect shipped or TestFlight builds).
- Profile 409 "Multiple profiles found": profiles with the same name are deleted before creation.
- `asc builds upload` exits 0 once the IPA is committed and prints a JSON receipt; the build shows up in
  ASC after ~5–15 min of PROCESSING (poll with `asc builds list`).
- App names are globally unique: `aso_find_available_name` / `create_app_auto` pick a free one.
- Ruby 4.x breaks fastlane → app creation (`fastlane produce`, the only fastlane step left) falls back to
  the ruby@3.3 fastlane.
- Bump `CURRENT_PROJECT_VERSION` for every upload.

## App Privacy label
- Apple has no API for it (appDataUsages endpoints return 404) and Chrome automation is banned: the answers
  from `backend/PRIVACY.md` (== `PrivacyInfo.xcprivacy`) go into `NEEDS_HUMAN` for you (ASC web UI).

## Onboarding
- Onboarding visuals are authored as Claude Design boards from the brief; never reuse the same image.
  (Legacy hero-image onboarding via `screenshot_onboarding_heroes` is opt-in with `allow_external_generator`.)
- CRITICAL: after adding files under `Resources/`, run `xcodegen generate`, otherwise they never enter the
  bundle and every step shows the fallback image.
- Conversion funnel (Cal AI pattern): no sign-in wall → tap-to-select personalization questions (+ progress
  bar) → attribution → emotional payoff → loading + a custom result → paywall. Leave out what App Review
  rejects: fake review counts, spin wheels, "80% off forever" pressure, notification or rating prompts.

## Growth (post-launch — after the app is live)
- `growth_build_slideshows`: 1080x1920 TikTok/Reels slideshows (hook overlay) into
  `marketing/growth/<set>/NN.png`. Claude writes the hook + slide text; visuals are a given image (e.g. a
  sample in Resources) or generated with fal like the app's own AI (paid — needs approval). No scraped images.
  You post; volume finds the winners.
- Distribution order and rules: see the post-launch section of the `appfactory-run` skill.

## Design (red line — never skipped)
- **Research first, Claude Design only, no house look.** `design_research_collect` downloads the category
  leaders' App Store screenshots + icons (search + top charts, several storefronts); Claude studies them and
  writes `design/research/brief.md` + `brief.json` — a blended, differentiated direction per section, citing
  references, never copying brand/assets/trade dress. Spec tokens/fonts and the onboarding flow come from the
  brief. `design_generate` only writes STRUCTURAL scaffolds (`design/scaffold/`); every board — screens,
  paywall + offer, icon, App Store slides — is AUTHORED in Claude Design from the brief, synced to
  `design/project/`, uploaded and recorded (`design_record_upload`). Gates reject scaffolds uploaded as-is,
  uploads older than the brief, template-default palettes and palettes identical to another factory app.
  Recoloring a template instead of designing is forbidden.
- Stitch is retired: the gates no longer accept Stitch manifests.
- Structural rules: opaque iOS 26 sheets; system tab bar, main action = search-role tab
  (original-rendering brand image, minimizes on scroll); SF Symbols, never emoji; iPhone SE compact layouts,
  pinned buttons 16 pt from the bottom; WCAG AA text; paywall buttons sized per language.
- Native iOS 26: system Liquid Glass tab bar, navigation bars, sheets and
  controls, built with the iOS 26 SDK (iOS 17.5 fallback); no custom tab/top bars (features gate).
- App icon: authored in Claude Design from the brief (`B01-AppIcon`) → `design_export_png` → `design/icon.png`
  → `icon_install`. `icon_generate` is opt-in reference drafting only.

## Submission, store assets, release (lessons)
- **Rating requests are mandatory at success moments; never in onboarding, rate-limited by RatingPolicy**
  App Review rejects a rating step inside onboarding. Template
  `Sources/Core/RatingPolicy.swift` + `.ratingRequest($trigger)`: N successes on M days and milestones
  (spec.rating), ≥60 days apart, ≤3 per year, never in a launch with a failure, never in tests. The features
  gate fails without a success-moment hook or with any rating request under `Sources/Onboarding`.
- **CHN subscription prices:** the first subscription submission failed with
  `IAP_SUBMISSION_NOT_ALLOWED_MISSING_PRICING_DATA` for CHN although the app is unavailable there. store_setup
  prices every territory (unsold ones too); availability still excludes spec.store.excluded_territories.
- **Submission mechanics:** a first subscription cannot be submitted through the API
  (`FIRST_SUBSCRIPTION_MUST_BE_SUBMITTED_ON_VERSION`; reviewSubmissionItems has no subscription relationship).
  You submit in the ASC web UI: version page → In-App Purchases and Subscriptions → select all → Add
  for Review → Submit. `asc_submit_for_review` refuses while subscriptions are READY_TO_SUBMIT / MISSING_METADATA.
- **store_setup app level:** availability (v2), categories (spec.store), content rights, FREE price schedule,
  copyright `© <year> <brand>` (never a personal name), review notes from `store/review-notes.md` (no phone,
  ≤4000 characters, no placeholders) with demoAccountRequired false. Age rating: the 2025 questionnaire needs
  every field (enums NONE, booleans false).
- **Subscription review screenshots:** `deliver_subscription_review_screenshots` from
  `store/review-screenshots/<product key>.png` (real sandbox prices).
- **Screenshots:** status bar 9:41 on a fixed date, NOT charging (App Review flagged the bolt), AppleLocale with
  AppleLanguages; `Scripts/sim_store_prep.sh` for widgets/SpringBoard/Watch (system language + region, reboot,
  uninstall before install); per-script fonts, RTL and CJK/Thai wrapping in build.mjs; Watch sets are
  APP_WATCH_ULTRA (422x514).
- **App Preview:** authored by Claude from real simulator recordings (HyperFrames brief, destination
  app-store-preview; the Remotion template was removed): 886x1920, ≤30 fps, H.264, 15–30 s, stereo AAC or
  silent, one per locale or a documented share (spec.preview.shared). Self-review sheets + scored log (all 8+
  on the MD5-matched final file), deterministic composition, `preview_upload(dry_run=False)` after `appfactory approve <id>`.
- **Signing:** ASC's bundleIds identifier filter is a substring match → exact match; a profile per extension;
  profiles created right before -exportArchive (Xcode sweeps earlier ones).
- **iOS template:** RevenueCat follows the Supabase user (syncIdentity before load/purchase/restore — otherwise a
  paying user can end up on the paywall after an identity change); Gregorian BirthYears (Thai Buddhist calendar bug); locale digits
  (Units.plainNumber); the device-run scheme has no StoreKit configuration (Billing Problem loop); generated
  PrivacyInfo.xcprivacy; LayoutAudit (OCR truncation, English leftovers, glyphs, overflow, sheets, occlusion).
- **Backend:** locale aliases (zh-TW → zh-Hant, no → nb, iw → he, in → id) and a language rule that asks
  non-Latin languages for their own script and names things in the user's language.
- **Listing:** Latin-only diacritic folding; Arabic comma / CJK list marks split words and are errors in the
  keyword field; a language's own name in its keywords is filler.
