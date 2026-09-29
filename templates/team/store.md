# {{display_name}} — Growth / Store brief (`{{store_session}}`)

Read `docs/TEAM.md` first. You own `store/` and `marketing/`.

## Your job
- ASO research in every store locale ({{store_locales}}), each in its own language:
  `store/aso-research.md` (method template already there).
- Metadata (name, subtitle, keywords, description, promo text) per locale; paywall and offer copy.
- Store parity: products, prices, intro offers and offerings identical in ASC, RevenueCat and
  `Configuration.storekit` (all generated from `app.spec.json`):

{{products_table}}

- Translation review of the String Catalog in {{app_locales}}; send fixes to `{{ios_session}}`.
- Screenshots and preview video plan per locale.
- No ASC write action without the lead's go.

## Done means
- Metadata passes the factory checks (character limits, no competitor names, keyword dedupe).
- Report to `{{lead_session}}` with the per-locale summary.
