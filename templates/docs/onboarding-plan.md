# {{display_name}} — Onboarding Plan

Status: draft ({{date}}). Generated from `design/screens.json` by `team_brief`; the lead keeps it
in sync with the design. Source of truth for the onboarding design pass.

## Goals

- Cal AI style conversion funnel: no login friction → personalization questions (tap-to-select,
  modern pickers) → attribution → emotional "glaze" → loading → custom plan result → hard paywall
  → offer paywall.
- Every answer feeds the plan and the paywall copy (see "Data collected → used for").
- Feel: modern, cute, animated. Every screen has one motion moment (see "Motion").
- Not taken from Cal AI: fake review counts or stats, spin-wheel discounts, "tried other apps",
  a rating prompt in onboarding (Apple rejects it; the app asks at success moments through
  RatingPolicy instead, which is mandatory), notification permission.
- Every weight picker shows a kg/lb toggle.

## Visual direction

- Tokens and fonts: `app.spec.json → design` (see `docs/TEAM.md`). Primary CTA pill pinned at the
  bottom, thin progress bar + back chevron at the top, large bold titles, soft cards.
- Mascot: {{mascot_line}}
- Haptics: selection tick on every option and picker detent, success haptic on plan ready.

## Flow

| # | Screen | Kind | Content | Input | Motion |
|---|---|---|---|---|---|
{{screen_table}}

## Main app screens

| # | Screen | Kind | Content | Motion |
|---|---|---|---|---|
{{main_table}}

## Data collected → used for

| Screen | Answer | Used for |
|---|---|---|
{{data_table}}

## Analytics

Prefix `{{event_prefix}}` (production App Store builds only). Standard factory catalog:

| Event | Props | When |
|---|---|---|
{{analytics_table}}

## Open questions

- (lead) …
