-- 0001_core.sql — core schema of a factory subscription app (monetization = "subscription").
--
-- Identity: every row hangs off auth.users(id). The app signs in anonymously on first launch (and
-- may later link Sign in with Apple to the same user); that user id is also the RevenueCat
-- app_user_id, so "what happened to this user" is one key everywhere.
--
-- Access model:
--   profiles      → the app reads/writes its own row through PostgREST (RLS + column grants).
--   ai_usage      → written only by the `analyze` edge function (service role); the app may read a
--                   whitelisted subset of its own rows.
--   entitlements  → service role only (RevenueCat cache, deny-all RLS).
-- RULE (revoke views): every view/function added later must be revoked from anon/authenticated in
-- its own migration: views run with the owner's rights and bypass RLS (a production
-- incident). App-specific tables (the features stage) go in new migrations with the same rules.

-- ── Helpers ──────────────────────────────────────────────────────────────────
create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at = now();
  return new;
end; $$;
revoke all on function public.set_updated_at() from public, anon, authenticated;

-- ── profiles: one row per user ───────────────────────────────────────────────
-- Generic columns only. Onboarding answers go in `answers` (jsonb, app-defined keys) or in typed
-- columns added by the app's own migration (add them to the column grants in that migration).
create table public.profiles (
  id                       uuid primary key references auth.users(id) on delete cascade,
  locale                   text not null default 'en' check (char_length(locale) between 2 and 10),
  timezone                 text check (char_length(timezone) <= 64),   -- IANA, e.g. Europe/Istanbul
  attribution              text check (char_length(attribution) <= 40),
  answers                  jsonb not null default '{}'::jsonb check (jsonb_typeof(answers) = 'object'),
  consent_health_at        timestamptz,        -- explicit consent (0003); server-stamped
  cap_timezone             text,               -- server-managed (0004)
  cap_timezone_changed_at  timestamptz,        -- server-managed (0004)
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);
create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
create policy "profiles own select" on public.profiles for select to authenticated
  using (id = auth.uid());
create policy "profiles own insert" on public.profiles for insert to authenticated
  with check (id = auth.uid());
create policy "profiles own update" on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
revoke all on public.profiles from anon;
revoke all on public.profiles from authenticated;
grant select on public.profiles to authenticated;
-- The app may write every column except the server-managed cap_* ones. `id` is in the update grant
-- because a PostgREST upsert (Prefer: resolution=merge-duplicates) runs ON CONFLICT (id) DO UPDATE
-- SET <every sent column>, id included; RLS still pins id to auth.uid().
grant insert (id, locale, timezone, attribution, answers, consent_health_at) on public.profiles to authenticated;
grant update (id, locale, timezone, attribution, answers, consent_health_at) on public.profiles to authenticated;

-- ── ai_usage: one row per billed model call ─────────────────────────────────
-- Written by `analyze` after every provider call (success or not) so cost is reconcilable.
-- Only status = 'ok' rows count toward the user's quota (a failed analysis costs the user nothing).
-- tier = 'free' + status = 'ok' is the lifetime free analysis; the partial unique index below makes
-- it impossible to hand out two, even under concurrent requests.
create table public.ai_usage (
  id              bigint generated always as identity primary key,
  user_id         uuid not null references auth.users(id) on delete cascade,
  mode            text not null check (mode in ('photo', 'text')),
  tier            text not null check (tier in ('free', 'premium')),
  status          text not null check (status in ('ok', 'not_applicable', 'invalid_output', 'provider_error')),
  model           text,
  locale          text,
  input_tokens    int,
  output_tokens   int,
  thinking_tokens int,
  cost_usd        numeric(10,6),
  latency_ms      int,
  result          jsonb,          -- normalized result returned to the app (no image, no raw prompt)
  created_at      timestamptz not null default now()
);
create index ai_usage_user_created on public.ai_usage (user_id, created_at desc);
create unique index ai_usage_one_free_scan on public.ai_usage (user_id)
  where tier = 'free' and status = 'ok';

alter table public.ai_usage enable row level security;
create policy "ai_usage own select" on public.ai_usage for select to authenticated
  using (user_id = auth.uid());
revoke all on public.ai_usage from anon;
revoke all on public.ai_usage from authenticated;
-- Column whitelist: cost/tokens/model stay server-side.
grant select (id, user_id, mode, tier, status, result, created_at) on public.ai_usage to authenticated;

-- ── entitlements: RevenueCat cache (service role only) ──────────────────────
-- plan = 'premium' is trusted until valid_until (period end + grace); after that the edge
-- function pulls RevenueCat again. Sandbox subscriptions count (App Review must work).
create table public.entitlements (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  plan         text not null default 'none' check (plan in ('none', 'premium')),
  environment  text check (environment in ('production', 'sandbox')),
  product_id   text,
  valid_until  timestamptz,
  checked_at   timestamptz not null default now()
);
alter table public.entitlements enable row level security;   -- no policies: deny-all
revoke all on public.entitlements from anon;
revoke all on public.entitlements from authenticated;

-- ── Ops view: AI cost per day and model (service role / dashboard only) ─────
create view public.ai_cost_daily as
  select (created_at at time zone 'utc')::date as day, model, mode,
         count(*)                                  as calls,
         count(*) filter (where status = 'ok')     as ok_calls,
         count(distinct user_id)                   as users,
         coalesce(sum(cost_usd), 0)::numeric(12,4) as cost_usd,
         (coalesce(sum(cost_usd), 0) / nullif(count(*) filter (where status = 'ok'), 0))::numeric(12,6)
                                                   as cost_per_ok_call_usd
  from public.ai_usage
  group by 1, 2, 3;
revoke all on public.ai_cost_daily from public, anon, authenticated;
