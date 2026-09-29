# App Review notes

`store_setup` (target asc) syncs the block below into App Store Connect → App Review Information → Notes, together
with `demoAccountRequired: false` (these apps create an anonymous account, so no demo account is needed). It sends the
block as plain text: `<!-- … -->` comments are dropped, and the run refuses a text over 4000 characters, one with an
unfilled `{{PLACEHOLDER}}`, or anything that looks like a phone number. The review phone lives only in
`review_contact_phone` in `~/.appfactory/config.toml` and is never written in the repository.

Write every sentence from the code, not from the plan: App Review 2.3.1 rejects notes or store copy that promise
something the build does not do (e.g. drop a "weekly progress insights" claim the build cannot back). Name the AI
providers (5.1.2), the account deletion path (5.1.1(v)) and the auto-renewal terms (3.1.2).

<!-- review-notes:start -->
```text
<!-- @if siwa -->
{{DISPLAY_NAME}} is {{ONE_LINE_PURPOSE}}. No login or demo account is needed: the app creates an anonymous account on first launch. Sign in with Apple (Settings) is optional and only links that account so it can be restored on a new iPhone.
<!-- @endif -->
<!-- @if !siwa -->
{{DISPLAY_NAME}} is {{ONE_LINE_PURPOSE}}. No login or demo account is needed: the app creates an anonymous account on first launch.
<!-- @endif -->

HOW TO TEST
<!-- @if quiz -->
1. Tap Get started and answer the onboarding questions (any values work).
<!-- @endif -->
<!-- @if !quiz -->
1. Tap Get started and go through the short onboarding.
<!-- @endif -->
<!-- @if offer_paywall -->
2. The paywall appears at the end. Close it with the X and continue with the free use, or subscribe in the sandbox. A one-time discounted offer may appear after the paywall is closed.
<!-- @endif -->
<!-- @if !offer_paywall -->
<!-- @if hard_paywall -->
2. The paywall appears at the end. Close it with the X and continue with the free use, or subscribe in the sandbox.
<!-- @endif -->
<!-- @if !hard_paywall -->
2. There is no paywall in onboarding: the app opens right after it. Subscribe from Settings > Upgrade or when the free use is spent.
<!-- @endif -->
<!-- @endif -->
3. {{CORE_ACTION_STEPS}}

{{DISPLAY_NAME}} PREMIUM (auto-renewable subscriptions: {{PLANS_AND_TRIALS}})
<!-- @if hard_paywall -->
Where to subscribe: the onboarding paywall; Settings > Upgrade; the paywall after the free use. Restore purchases is on every paywall and in Settings; Manage subscription in Settings opens Apple's subscription sheet.
<!-- @endif -->
<!-- @if !hard_paywall -->
Where to subscribe: Settings > Upgrade; the paywall after the free use. Restore purchases is on every paywall and in Settings; Manage subscription in Settings opens Apple's subscription sheet.
<!-- @endif -->
Premium unlocks: {{PREMIUM_FEATURES}}. Premium has fair daily limits on AI analyses.

AI AND DATA
{{WHAT_IS_SENT_TO_THE_AI_PROVIDERS_AND_WHAT_IS_STORED}}

OTHER
- Delete account: Settings > Delete account removes all data on our servers.
- No ads and no tracking (no advertising identifier, no ATT prompt).
- Contact: {{SUPPORT_EMAIL}} (other contact details are in the fields above).
```
<!-- review-notes:end -->
