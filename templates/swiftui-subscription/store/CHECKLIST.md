# Store setup checklist: App Store Connect + RevenueCat

Desired state: `app.spec.json` (products, periods, levels, prices, intro offers, price overrides, grace
period, locales, placements, consent) + `store/metadata/listing.json` (name, subtitle, keywords, promo,
description, legal URLs, IAP display copy). The `store_setup` MCP tool makes the live stores match them.
It reads first and writes only what is missing or different, so every step can be re-run safely. State
that contradicts the spec is reported as `CONFLICT` and left untouched for a human to decide.

Nothing here submits anything for review.

## Commands (appfactory MCP)

```text
store_setup(app_dir, mode="plan")                                   # offline preview, no credentials
store_setup(app_dir, mode="check", target="capabilities|asc|rc|all") # live reads, simulated writes
store_setup(app_dir, mode="apply", target="…", confirm="<bundle id>") # live writes (lead's go)
metadata_listing_check(app_dir)                                     # listing rules before any apply
pricing_unit_economics(app_dir)                                     # pricing.md from the measured cost
asc_sbp_check()                                                     # Small Business Program proof (after sales)
```

ASC uses the factory key (`asc_key_id`, `asc_issuer_id`, `asc_key_filepath`); RevenueCat uses the global
`rc_secret_key`. Per-app ids (ASC app id, RC project/app ids, RC public key, the RevenueCat Apple
notification URL) are written to `.appfactory/outputs.json`, never to the global config. The review
phone comes only from `review_contact_phone` in `~/.appfactory/config.toml` and is never printed.

## Order (store_setup enforces it)

| # | Step | How |
|---|---|---|
| 0 | Bundle id registered | `asc_create_bundle_id` |
| 1 | **App ID capabilities FIRST**: IN_APP_PURCHASE, APPLE_ID_AUTH (PRIMARY_APP_CONSENT), HEALTHKIT if `spec.health.enabled`, PUSH only if `spec.push.enabled` | `store_setup target=capabilities` (keys, profiles and `testflight_ship` refuse to run while pending) |
| 2 | App record (name, SKU = `spec.sku`, en-US primary) | `asc_create_app` (Apple ID session); store_setup checks the SKU |
| 3 | App Store Server Notifications V2 (production + sandbox) → RevenueCat | `rc_apple_notification_url=` (RevenueCat dashboard → app → Apple Server-to-Server notification URL). Without it: one MANUAL line |
| 4 | Billing Grace Period (`spec.subscription.grace_period`) | PATCH `subscriptionGracePeriods` (weekly gets 6 days for the 16/28-day options) |
| 5 | Subscription group + group name in every store locale | listing.json `iap.group_name` |
| 6 | Products (ids `<bundle>.<suffix>`, periods, group levels) + display name/description per store locale | spec + listing.json `iap.products` |
| 7 | Availability: every territory except `spec.store.excluded_territories` (CHN), new territories on — **before any price** | automatic |
| 8 | Prices: USA price point + Apple's equalizations, one POST per territory — **the unsold ones (CHN) too** | automatic |
| 9 | Local price overrides (`spec.subscription.price_overrides`, per currency: EUR storefronts, BRA, TUR) | automatic (live territory currencies) |
| 10 | Intro offers exactly as the spec: trial products one free trial **per territory**; offer products **none** | automatic; anything else is a CONFLICT |
| 11 | Age rating (health/wellness = `spec.consent.health`, everything else none/no) | automatic |
| 11a | App availability (v2): every territory but the excluded ones, new territories on | automatic; an existing setting is never overwritten (CONFLICT if it sells in an excluded one) |
| 11b | Primary/secondary category (`spec.store.primary_category` / `secondary_category`) | automatic; MANUAL until the spec sets them |
| 11c | Content rights (`spec.store.content_rights`: third-party data such as a product database says so) | automatic |
| 11d | App price: FREE at the USA price point | automatic when no schedule exists |
| 11e | Copyright `© <year> <display name>` — the brand, never a personal name | automatic (`spec.store.copyright` overrides) |
| 12 | App info (name, subtitle, privacy URL) + version (keywords, promo, description, support URL) per locale | listing.json; legal URLs = Supabase `legal` function with `?lang=` |
| 13 | App Review contact (`legal_controller`, `support_email`, `review_contact_phone`), `demoAccountRequired: false`, notes from `store/review-notes.md` | automatic; MANUAL until the phone is set / the notes have no placeholders |
| 14 | RevenueCat: project, App Store app, products, entitlement `premium`, offerings `default` (current) + `offer`, packages, targeting rule with every placement | automatic; MANUAL: upload the In-App Purchase key + ASC API key in the RC dashboard; MCP plan when the REST write is refused |
| 15 | App Privacy labels | ASC web UI (no API) from `backend/PRIVACY.md`; keep them equal to `Privacy/PrivacyInfo.xcprivacy` |
| 16 | Review screenshot per subscription: `store/review-screenshots/<product key>.png` (hard paywall with REAL sandbox prices for the default offering, the offer paywall for offer products) | `deliver_subscription_review_screenshots` after an iOS build; without it a subscription stays MISSING_METADATA |
| 17 | **Submission: first subscriptions go with the version.** ASC web UI → the version page → "In-App Purchases and Subscriptions" → select every subscription → Add for Review → Submit | founder, web UI. `asc_submit_for_review` refuses while subscriptions are READY_TO_SUBMIT or MISSING_METADATA |

## Gotchas (handled by store_setup; do not redo by hand)

- **Never** use `asc_finalize_subscription(period=…)` for trial products: the old embedded offers
  ($37.49 pay-up-front on every yearly, a trial on every weekly) contradict the spec. Intro offers
  follow `spec.subscription.products[].intro`.
- Product ids can never be reused, even after deletion. A wrong period on an existing id is a CONFLICT.
- Intro offers are per territory: `POST /v1/subscriptionIntroductoryOffers` without a territory fails
  with `ENTITY_ERROR.RELATIONSHIP.REQUIRED`.
- Availability must exist before any price is set, or ASC returns 409.
- ASC sometimes returns a 500 for one territory's price: reported as ERROR, a re-run fills the gap.
  GETs are retried 3 times on 5xx; writes are never retried in the same run.
- Grace period API values: `THREE_DAYS`, `SIXTEEN_DAYS`, `TWENTY_EIGHT_DAYS`; `renewalType`
  `ALL_RENEWALS` | `PAID_TO_PAID_ONLY`. The resource always exists per app; only PATCH.
- RevenueCat placements: REST v2 `targeting_rules` (GET verified); if the write is refused, run the
  emitted plan with the RevenueCat MCP `create-targeting-rule`.
- iOS must not depend on placements being configured: resolve the placement, then fall back to
  `offerings.all["offer"]`, then `offerings.current`.
- **CHN pricing:** `POST /v1/subscriptionSubmissions` answered
  `409 IAP_SUBMISSION_NOT_ALLOWED_MISSING_PRICING_DATA` for CHN although the app is unavailable there:
  ASC wants every territory priced. store_setup prices the excluded territories (unsold, availability
  untouched).
- **First subscription:** `subscriptionSubmissions` then fails with
  `FIRST_SUBSCRIPTION_MUST_BE_SUBMITTED_ON_VERSION`, and `reviewSubmissionItems` has no subscription
  relationship: an API-submitted version would be reviewed without its products (a paywall with nothing
  to buy is a rejection). The web UI's Submit puts the version and its subscriptions in one submission.
- The subscriptions stay `READY_TO_SUBMIT` until that submission; ASC's `sourceFileChecksum` is MD5.
- Store copy, review notes and screenshots claim only what the build does (App Review 2.3.1); the review
  notes name the AI providers (5.1.2), account deletion (5.1.1(v)) and the renewal terms (3.1.2).

## Run log

| Date | Run | Result |
|---|---|---|
| | | |
