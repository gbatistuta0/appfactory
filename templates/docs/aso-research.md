# ASO research: {{display_name}}

Status: template ({{date}}). Owner: growth/store (`{{store_session}}`). Storefronts: {{store_locales}},
each researched in its own language. Fill every section with real data; no invented numbers.

## 1. Summary

Five to seven numbered findings: which head terms are closed, which locales are open, the single
strongest market, the differentiator, and the growth plan beyond metadata.

## 2. Method and data

| Step | Tool | Output (`store/research/data/`) |
|---|---|---|
| Competitor lists per storefront and query | iTunes Search API (`aso.fetch_competitors`, country pinned) | `competitors_by_storefront.json` |
| Localized title, subtitle, top IAP prices | App Store product page per language (`aso.competitor_iap`) | `competitor_pages.json` |
| Real search demand | App Store autocomplete (`aso.search_hints`, storefront header; a–z expansion of seeds + short prefixes) | `search_hints_raw.json` |
| Keyword universe and popularity proxy | hint rank per sighting (weight 3 for prefixes ≤ 4 chars, 2 for the bare seed, 1 for expansions) | `keyword_universe.json` |
| Niche score (demand + competitor weakness + newcomer traction) | `aso.niche_score(term, country, genre)` | `niche_scores.json` |
| Pricing and margins | `aso.unit_economics` | `unit_economics.json` |

Popularity proxy: Apple returns autocomplete hints in popularity order with no numbers. It is a
ranking signal, not a volume. Record the collection date; rating counts are per storefront.

## 3. Competitors

Leaders by storefront (ratings in that storefront), and how the direct competitors title
themselves (title | subtitle). Note which competitors are NOT localized.

## 4. Niche scores

| Storefront | Term | Score | Verdict | Median ratings of top 50 | Newcomers |
|---|---|---:|---|---:|---|

How to read: REJECT means "do not start a new app here"; for an existing app it marks where
ranking is unrealistic. The newcomer test shows whether apps launched in the last 6–12 months
gathered ratings.

## 5. Keyword universe

Top relevant autocomplete terms per storefront (popularity proxy in brackets).

## 6. Metadata per locale

| Locale | Name (30) | Subtitle (30) | Keywords (100) |
|---|---|---|---|

Reserve keywords: swap in after 4–8 weeks if a keyword does not move.

## 7. Beyond metadata

Custom product pages, in-app events, promoted in-app purchase, ratings (`requestReview()` only
after a success moment, never in onboarding), featuring nomination, capped Apple Ads discovery
test, icon/screenshot A/B tests.

## 8. Measure and iterate

Every 2–4 weeks: ranks per locale, impressions, tap-through, conversion (organic = App Store search
installs minus Apple Ads installs). Replace keywords that do not move after 2 cycles; re-run the
hint harvest and niche scores monthly.
