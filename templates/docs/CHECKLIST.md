# {{display_name}} — Factory checklist

<!-- @if github_issues -->
Tick each item with the commit or issue that proves it.
<!-- @endif -->
<!-- @if !github_issues -->
Tick each item with the commit that proves it.
<!-- @endif -->

## Spec and repo
- [ ] `app.spec.json` validated (products, intro offers, locales, placements, caps, AI, consent, design)
<!-- @if github_issues -->
- [ ] Private repo `{{repo}}` created; labels bootstrapped (`github_issues_bootstrap`)
<!-- @endif -->
<!-- @if !github_issues -->
- [ ] Private repo `{{repo}}` created (issue tracking is turned off)
<!-- @endif -->
- [ ] `docs/TEAM.md` + role briefs rendered (`team_brief`), sessions assigned

## Design research
- [ ] `design_research_collect`: category leaders' screenshots + icons downloaded (several storefronts, top charts)
- [ ] `design/research/brief.md` + `brief.json`: every direction cites references + what this app does differently; no copied brand/assets/trade dress
- [ ] Screenshot concept from the competitors' screenshot sets (hook, captions, framing, backgrounds, sequencing, badges)

## Design (Claude Design only — no Stitch, no image generators, no house look)
- [ ] Spec tokens/fonts = the brief (WCAG AA, not the template defaults or another app's)
<!-- @if offer_paywall -->
- [ ] `design/screens.json`: {{onboarding_screens}} onboarding (brief flow) + main screens + paywall + offer, each specified individually
<!-- @endif -->
<!-- @if !offer_paywall -->
<!-- @if hard_paywall -->
- [ ] `design/screens.json`: {{onboarding_screens}} onboarding (brief flow) + main screens + paywall (no offer), each specified individually
<!-- @endif -->
<!-- @if !hard_paywall -->
- [ ] `design/screens.json`: {{onboarding_screens}} onboarding (brief flow, no paywall) + main screens, each specified individually
<!-- @endif -->
<!-- @endif -->
- [ ] Every board authored in Claude Design from the brief (scaffolds are structure only)
- [ ] Cal AI funnel without dark patterns (no fake stats/reviews, spin wheel, notification prompt; no rating request inside onboarding)
- [ ] Every weight picker has the kg/lb toggle; SF Symbols (no emoji); opaque sheets; SE-compact layouts
- [ ] Native iOS 26 chrome on every board and screen: system Liquid Glass tab bar (main action = search-role tab), navigation bars/toolbars, sheets and glass controls; no custom tab/top bars (features gate)
- [ ] `design_generate` → upload plan run with the claude-design MCP → `design_record_upload`; founder approved via open_url
- [ ] App icon designed on `B01-AppIcon` → `design_export_png` → `icon_install` (`verify/icon.json`)
- [ ] App Store slides authored from the brief's screenshot concept with the real captions + captures, uploaded, approved
- [ ] Mascot poses approved → `mascot_blink` → `mascot_assets`; motion boards reviewed
- [ ] `.appfactory/verify/design_review.json` `{"fidelity_ok": true}` after screenshot-vs-board review

## Build
- [ ] Onboarding, paywalls, main tabs match the boards; motion moments implemented
<!-- @if ratings -->
- [ ] Rating requests at success moments are mandatory; never in onboarding, rate-limited by RatingPolicy
      (`RatingPolicy.shared.request(…)` at the real success moment + `.ratingRequest($trigger)`; spec.rating)
<!-- @endif -->
<!-- @if !ratings -->
- [ ] No rating request code (rating prompts are turned off)
<!-- @endif -->
- [ ] String Catalog complete in {{app_locales}}; `LayoutAuditUITests` clean with `TEST_RUNNER_AUDIT_LANGS=all`
      on the SE and the Pro Max (OCR truncation, English leftovers, glyphs, overflow, sheets, occlusion)
- [ ] Numbers in the user's digits (`Units.plainNumber`, Arabic-Indic in ar), ages and birth years Gregorian
      (`BirthYears`: Thailand's Buddhist calendar made ages ~543 years off), CJK day numbers without 日/일
- [ ] A system font for scripts the brand fonts lack; RTL (ar/he) checked on every screen
- [ ] RevenueCat follows the Supabase user (`StoreManager.syncIdentity` before load, purchase, restore)
- [ ] The device-run scheme has no StoreKit configuration (Billing Problem loop on a device)
- [ ] Extensions (widgets, Watch): no emoji (SF Symbols; emoji draw as "?" boxes on the Lock Screen), fonts by
      PostScript name + `UIAppFonts` in the extension's Info.plist (the widget renderer rejects descriptor-built
      fonts: blank widgets), a privacy manifest per bundle, give the first render ~20 s before a screenshot
- [ ] Device scripts: every background log capture filtered and time-bounded, killed by an EXIT trap;
      `${VAR:-}` for optional env vars under `set -u`
- [ ] Unit + UI tests green

## Backend and store
- [ ] Supabase + ai-proxy + webhook deployed; caps enforced server-side
- [ ] ASC == RevenueCat == Configuration.storekit (products, intro offers, offerings)
- [ ] ASO research + metadata in {{store_locales}}; no language names or foreign list separators in keywords
- [ ] Every claim in the listing, captions and review notes is backed by the build (App Review 2.3.1)
- [ ] Legal pages and a support page per language live (every privacy/support URL returns 200)
- [ ] `store_setup` check clean: prices in every territory incl. unsold CHN, availability, categories,
      content rights, FREE price, brand copyright (no personal name), review notes, demo account off
- [ ] Screenshots: store status bar (not charging), `deliver_screenshots_audit` clean in every locale
- [ ] App Preview: real footage, self-review 8+ on every criterion, `preview_check` clean
- [ ] Subscription review screenshots uploaded (`deliver_subscription_review_screenshots`)

## Release (lead + founder)
- [ ] TestFlight build; sandbox purchase smoke on a device
- [ ] App Review submission only with the founder's go, in the ASC web UI: version page → In-App Purchases and
      Subscriptions → select every subscription → Add for Review → Submit (a first subscription cannot go via the API)
