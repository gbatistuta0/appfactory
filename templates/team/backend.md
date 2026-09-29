# {{display_name}} — Backend / AI brief (`{{backend_session}}`)

Read `docs/TEAM.md` first. You own `supabase/` and `backend/`.

## Your job
- Supabase project for {{display_name}}; migrations for usage, credits/entitlements, events, consent.
- `ai-proxy` edge function: model `{{ai_model}}` (fallback `{{ai_fallback}}`), timeout and reasoning
  from the spec; keys only as Supabase secrets, never in the app or the repo.
- Usage caps from the spec, counted server-side and never derived from RevenueCat: {{usage}}.
- RevenueCat webhook → entitlement state; grace period from the spec.
- Legal pages (privacy, terms) in {{app_locales}}.

## Done means
- Deno tests green; a smoke call through the proxy with a fake key in tests (no paid calls).
- Report to `{{lead_session}}` with the deployed function list and what you verified.
