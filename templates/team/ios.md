# {{display_name}} — iOS brief (`{{ios_session}}`)

Read `docs/TEAM.md` first. You own `Sources/`, `Resources/`, `Tests/`, `project.yml`.

## Your job
- Build the onboarding ({{onboarding_screens}} screens), paywalls and main tabs 1:1 from the Claude
  Design boards (`design/project/*.dc.html`): layout, sizes, token colors, copy keys (`data-l10n`),
  and the motion moment of every screen (`Sources/Design/Motion.swift`: rise/pop/fadeIn, bob, pulse,
  scanLine, blinkDot, floatUp, DrawOnAppear).
- Mascot: `MascotView(state:)` with the spec states ({{mascot_states}}); art comes from
  `Assets.xcassets/Mascot` (imported by the lead with `mascot_assets`).
- Every weight picker shows a kg/lb toggle; units follow the locale by default.
- Purchases through RevenueCat with the spec product ids; every paywall entry passes its placement
  ({{placements}}). Trial copy only when RevenueCat reports intro eligibility.
- Reduced motion: put `.motionReducedRoot()` on the root; `-uiTest` freezes all loops.

## Done means
- `xcodebuild test` green (unit + UI), String Catalog complete in {{app_locales}}.
- Screenshots of every screen compared with its board; differences fixed or agreed with the lead.
- Report to `{{lead_session}}`: what, where, how verified.
