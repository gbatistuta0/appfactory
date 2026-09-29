# {{display_name}} — Team Brief

{{display_name}}: SwiftUI iOS subscription app built with AppFactory. Bundle id `{{bundle_id}}`.
{{mascot_line}}
Source of truth for every product value: `app.spec.json` (products, prices, locales, placements,
caps, AI model, consent, analytics prefix, design tokens). Change the spec, then regenerate; never
hand-edit a generated file.

## Roles

| Session | Role | Owns (write access) |
|---|---|---|
| `{{lead_session}}` | **Team lead** — product decisions, design, reviews, merges, the only contact with the founder | `docs/`, `design/`, `app.spec.json` |
| `{{ios_session}}` | **iOS** — SwiftUI app, onboarding, main tabs, paywalls, mascot motion, tests | `Sources/`, `Resources/`, `Tests/`, `project.yml` |
| `{{backend_session}}` | **Backend / AI** — Supabase, edge functions (`ai-proxy`, webhooks, legal), usage caps, AI eval | `supabase/`, `backend/` |
| `{{store_session}}` | **Growth / Store** — ASO, StoreKit/RevenueCat parity, paywall copy, localization review, metadata, screenshots | `store/`, `marketing/` |

Write only inside the paths you own. Anything outside (a shared contract, another role's file, a
new top-level folder) → ask the lead first. Role briefs: `docs/team/<role>.md`.

## How to work with the lead

- Ask the lead (`SendMessage` to `{{lead_session}}`) for every product, design, pricing, scope or
  cross-role decision. **Only the lead talks to the founder**; the lead escalates when needed.
- Questions: one message, short, with the options you see and your recommendation.
- When a milestone is done: send the lead a short report (what, where, how verified).
- Do not wait idle: if blocked on an answer, continue with non-blocked work.

## Sources of truth

- Spec → `app.spec.json` (regenerate with the factory tools after every change).
- Onboarding flow, data use and analytics → `docs/onboarding-plan.md`.
- Design → Claude Design project "{{display_name}} Design" (`design/project/claude_design.json` has the
  project id and the founder link). It is the only design source, and the look comes from
  `design/research/brief.md` (competitor research, cited). Every screen (incl. paywalls) is specified
  individually in `design/screens.json`; `design/scaffold/` holds structure only and the boards in
  `design/project/*.dc.html` are authored from the brief, plus the app icon master and the App Store slides. SwiftUI matches the boards 1:1 (layout, sizes,
  colors, copy, motion).
- Mascot → approved poses in `design/mascot/<state>.png` (+ `-blink.png`), imported into
  `Resources/Assets.xcassets/Mascot/`. Animate the approved poses; never rig from a parts sheet.
<!-- @if github_issues -->
- Work tracking → GitHub Issues on the private repo https://github.com/{{repo}}/issues
  (labels: ios, backend, store, lead, founder, next, later, other-project). Tell the lead when you
  postpone something; the lead opens the issue (imperative title, labels, body: what/why/done-when).
  Never run `gh auth switch`. If `github_user` is set in ~/.appfactory/config.toml, run gh per command as
  `GH_TOKEN=$(gh auth token --user <github_user>) gh issue list -R {{repo}}`; otherwise plain `gh issue list -R {{repo}}`.
<!-- @endif -->
<!-- @if !github_issues -->
- Work tracking → no issue tracker (turned off). Tell the lead when you postpone something; the lead keeps the
  short backlog in `docs/CHECKLIST.md`.
<!-- @endif -->

## Design tokens

| Token | Value |
|---|---|
{{tokens_table}}
| Display font | {{display_font}} — body: {{body_font}} |

## Stack

- Native SwiftUI (XcodeGen `project.yml`, iOS 17.5+, iPhone only, portrait) + Supabase + RevenueCat.
- AI keys never ship in the app; every model call goes through the Supabase `ai-proxy` edge function.
  Model: `{{ai_model}}` (fallback `{{ai_fallback}}`), chosen by eval.
- Languages in the app: {{app_locales}} (`en` is source + fallback). Store locales: {{store_locales}}.
  Every user-facing string goes through the String Catalog from day one.
- Analytics: event prefix `{{event_prefix}}`; only production App Store builds send events.

## Product decisions (from the spec)

{{products_table}}

- Paywall placements (analytics `from` == RevenueCat placement id): {{placements}}.
<!-- @if offer_paywall -->
  Offer placements: {{offer_placements}}.
<!-- @endif -->
- Free usage and caps: {{usage}}.
<!-- @if offer_paywall -->
- Offer paywall price anchor: {{offer_anchor}}.
- Funnel: onboarding ({{onboarding_screens}} screens) → hard paywall → offer paywall → app. No rating
  prompt in onboarding, no notification permission, no fake stats or review counts, no spin wheel.
<!-- @endif -->
<!-- @if !offer_paywall -->
<!-- @if hard_paywall -->
- Funnel: onboarding ({{onboarding_screens}} screens) → hard paywall → app (no offer paywall). No rating
  prompt in onboarding, no notification permission, no fake stats or review counts, no spin wheel.
<!-- @endif -->
<!-- @if !hard_paywall -->
- Funnel: onboarding ({{onboarding_screens}} screens) → app (no paywall in onboarding: it opens from the
  placements only). No rating prompt in onboarding, no notification permission, no fake stats or review counts.
<!-- @endif -->
<!-- @endif -->
<!-- @if ratings -->
- Rating requests at success moments are mandatory; never in onboarding, rate-limited by RatingPolicy.
<!-- @endif -->
<!-- @if !ratings -->
- Rating prompts are turned off: no RatingPolicy, no review request anywhere.
<!-- @endif -->
- Health-data consent required: {{consent}}.
- StoreKit + RevenueCat + ASC: every product, intro offer and offering exists identically in all three.

## Rules

- **Never use Claude in Chrome / any `mcp__claude-in-chrome` tool.** Use APIs, CLIs and MCP servers.
- No secrets in code, logs, commits or test fixtures (keys live in `~/.appfactory/config.toml` and
  Supabase secrets only).
- All docs and code comments in English.
- Tests for every feature (unit + UI where it applies); never report "done" with a red suite.
<!-- @if github_issues -->
- Git: commit only your own paths (`git add <your dir>`), clear messages, mention the issue (`#12`).
<!-- @endif -->
<!-- @if !github_issues -->
- Git: commit only your own paths (`git add <your dir>`), clear messages.
<!-- @endif -->
  **Only the lead pushes**, always as the repo owner account.
- No App Store Connect write actions without the lead's go. No paid API calls (AI, ads, generation)
  that spend the founder's balance without asking.
- Work output goes into the repo, never only into a scratchpad.
