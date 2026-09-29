# __DISPLAY_NAME__ pricing, trial and paywall funnel

Owner: store. Everything between `<!-- …:begin -->` / `<!-- …:end -->` markers is generated from
`app.spec.json` (and the measured AI cost) by the factory tool `pricing_unit_economics`; edit the spec,
not the generated blocks. The rest is written by the store stage.

## 1. Decisions

<!-- decisions:begin -->
_Not generated yet: run `pricing_unit_economics`._
<!-- decisions:end -->

## 2. Market check

Competitor price ladders per storefront (`aso_competitor_iap`), with the reading that justifies each
price. Durations are inferred from purchase names; mark unknowns with `?`.

| App | Ratings | Yearly | Yearly offer | Weekly | Monthly |
|---|---:|---|---|---|---|
| {{COMPETITOR}} | | | | | |

## 3. Unit economics (measured AI cost)

<!-- unit-economics:begin -->
_Not generated yet: run the eval (`backend/eval/run.ts`, needs the lead's go for the paid run), then
`pricing_unit_economics`._
<!-- unit-economics:end -->

## 4. App Store Connect layout

<!-- asc-layout:begin -->
_Not generated yet._
<!-- asc-layout:end -->

### Introductory-offer rules the app must respect

1. **Eligibility is per subscription group.** An Apple Account gets one introductory offer in the group,
   ever. A user who took the weekly trial gets no yearly trial later, and neither does a lapsed subscriber.
2. **The paywall checks eligibility before it shows any trial copy** (Guideline 3.1.2): RevenueCat
   `checkTrialOrIntroDiscountEligibility(product:)` or StoreKit 2
   `await product.subscription?.isEligibleForIntroOffer`. Show trial copy only when eligible.
3. The billed amount stays the most prominent price on the tile: "then $49.99/year" is never smaller
   than "3 days free".
4. **No reminder promise.** The app asks for no notification permission, so no copy may say "we'll
   remind you before the trial ends".
5. **Offer products carry no intro offer**: the offer paywall competes on price, not on a trial.

## 5. RevenueCat layout

<!-- rc-layout:begin -->
_Not generated yet._
<!-- rc-layout:end -->

iOS lookup, so a missing or wrong dashboard rule can never show the wrong prices:

1. `offerings.currentOffering(forPlacement: id)`. Without a rule, RevenueCat falls back to the current
   offering, which for an offer placement would be the hard-paywall products.
2. If the identifier is not the expected offering, use `offerings.all[expected]`, then `offerings.current`.
3. If StoreKit returns no products at all, the tiles still render fixed demo prices, never an endless
   spinner.

Entitlement check: `customerInfo.entitlements["premium"]?.isActive == true` (active during the free trial
and the billing grace period). The backend decides quotas from its own records; it never trusts the client.

## 6. Paywall price math (compute from StoreKit, never hard-code)

| Label | Formula |
|---|---|
| Yearly per week | `yearly.price / 52` (RevenueCat: `pricePerWeek`) |
| Saving badge | `floor((1 − yearly.price / (weekly.price × 52)) × 100)` |
| Offer per month | `offer.price / 12` (RevenueCat: `pricePerMonth`) |
| Offer discount | `floor((1 − offer.price / yearly.price) × 100)` |
| Struck-through price | `yearly.localizedPriceString` |

Percentages are **floored**, so a saving is never overstated. A local price override changes the numbers
per storefront, which is why they must be computed. If a product has not loaded, hide the badge.

## 7. Local prices

<!-- local-prices:begin -->
_Not generated yet._
<!-- local-prices:end -->

## 8. Offer anchor

The offer's monthly cost must stay below the anchor item's price in every storefront, or the line stops
being true. A burger works; a coffee failed (an espresso in FR/ES/TR costs less than the offer's
monthly price). Copy never names a brand.

<!-- offer-anchor:begin -->
_Not generated yet._
<!-- offer-anchor:end -->

## 9. Open items

1. Re-run the eval and `pricing_unit_economics` whenever the model or its list price changes.
