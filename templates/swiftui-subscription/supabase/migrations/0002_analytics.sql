-- 0002_analytics.sql — read-only analytics for the lead (dashboard / service role only).
--
-- ai_denials records every request `analyze` refused before calling the model (paywall, caps,
-- consent, RevenueCat outage). Without it the free→paywall step of the funnel is invisible: a
-- refused request costs nothing, so it never reaches ai_usage. All days are UTC calendar days.

create table public.ai_denials (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  mode        text not null check (mode in ('photo', 'text')),
  tier        text check (tier in ('free', 'premium')),
  reason      text not null check (reason in (
                'free_scan_used', 'subscription_required', 'daily_cap_reached',
                'too_many_attempts', 'entitlement_unavailable', 'consent_required')),
  created_at  timestamptz not null default now()
);
create index ai_denials_created on public.ai_denials (created_at);
create index ai_denials_user on public.ai_denials (user_id, created_at);
alter table public.ai_denials enable row level security;   -- no policies: deny-all
revoke all on public.ai_denials from anon;
revoke all on public.ai_denials from authenticated;

-- One row per UTC day with any activity.
--   active_users   distinct users with a model call or a refused request
--   paywall_402*   refused with 402 (free analysis used, or subscription required)
create view public.analytics_daily as
with usage as (
  select (created_at at time zone 'utc')::date as day,
         count(*) filter (where status = 'ok' and mode = 'photo')                  as photo_analyses,
         count(*) filter (where status = 'ok' and mode = 'text')                   as text_analyses,
         count(*) filter (where status = 'ok' and tier = 'free')                   as free_analyses,
         count(*) filter (where status = 'ok' and tier = 'premium')                as premium_analyses,
         count(*) filter (where status = 'not_applicable')                         as not_applicable,
         count(*) filter (where status in ('invalid_output', 'provider_error'))    as failed_calls,
         coalesce(sum(cost_usd), 0)                                                as cost_usd
  from public.ai_usage group by 1
), denials as (
  select (created_at at time zone 'utc')::date as day,
         count(*) filter (where reason in ('free_scan_used', 'subscription_required'))            as paywall_402,
         count(distinct user_id) filter (where reason in ('free_scan_used', 'subscription_required')) as paywall_402_users,
         count(*) filter (where reason = 'daily_cap_reached')                                     as daily_cap_429,
         count(*) filter (where reason = 'entitlement_unavailable')                               as entitlement_503,
         count(*) filter (where reason = 'consent_required')                                      as consent_403
  from public.ai_denials group by 1
), active as (
  select day, count(distinct user_id) as active_users
  from (
    select (created_at at time zone 'utc')::date as day, user_id from public.ai_usage
    union select (created_at at time zone 'utc')::date, user_id from public.ai_denials
  ) a
  group by 1
)
select a.day,
       a.active_users,
       coalesce(u.photo_analyses, 0)    as photo_analyses,
       coalesce(u.text_analyses, 0)     as text_analyses,
       coalesce(u.free_analyses, 0)     as free_analyses,
       coalesce(u.premium_analyses, 0)  as premium_analyses,
       coalesce(u.not_applicable, 0)    as not_applicable,
       coalesce(u.failed_calls, 0)      as failed_calls,
       coalesce(d.paywall_402, 0)       as paywall_402,
       coalesce(d.paywall_402_users, 0) as paywall_402_users,
       coalesce(d.daily_cap_429, 0)     as daily_cap_429,
       coalesce(d.entitlement_503, 0)   as entitlement_503,
       coalesce(d.consent_403, 0)       as consent_403,
       coalesce(u.cost_usd, 0)::numeric(12,4)                                   as cost_usd,
       (coalesce(u.cost_usd, 0) / nullif(a.active_users, 0))::numeric(12,5)     as cost_per_active_user_usd
from active a
left join usage u using (day)
left join denials d using (day);

-- Free-analysis funnel by the UTC day each user took their free analysis:
--   hit_paywall_users   later refused with 402 (tried again after the free analysis)
--   subscribed_users    later analysed as a subscriber, or currently cached as premium
create view public.analytics_free_funnel as
with free as (
  select user_id, min(created_at) as free_at
  from public.ai_usage where tier = 'free' and status = 'ok'
  group by user_id
)
select (f.free_at at time zone 'utc')::date as cohort_day,
       count(*) as free_users,
       count(*) filter (where exists (
         select 1 from public.ai_denials d
         where d.user_id = f.user_id and d.created_at >= f.free_at
           and d.reason in ('free_scan_used', 'subscription_required'))) as hit_paywall_users,
       count(*) filter (where exists (
         select 1 from public.ai_usage u
         where u.user_id = f.user_id and u.tier = 'premium' and u.status = 'ok')
         or exists (select 1 from public.entitlements e where e.user_id = f.user_id and e.plan = 'premium'))
         as subscribed_users
from free f
group by 1;

-- Refused requests per UTC day and reason (what the paywall/caps/consent actually cost in users).
create view public.ai_denials_daily as
  select (created_at at time zone 'utc')::date as day, reason, mode, tier,
         count(*) as denials, count(distinct user_id) as users
  from public.ai_denials
  group by 1, 2, 3, 4;

-- Views run with the owner's rights and bypass RLS: never readable by the app roles.
revoke all on public.analytics_daily from public, anon, authenticated;
revoke all on public.analytics_free_funnel from public, anon, authenticated;
revoke all on public.ai_denials_daily from public, anon, authenticated;
