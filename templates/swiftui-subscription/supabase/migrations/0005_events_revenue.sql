-- 0005_events_revenue.sql — app event backup (Supabase analytics) and the RevenueCat revenue feed
-- for Ad Ops (functions/rc-webhook → revenue_events; adops/pull.py reads it with the adops_ro role).

-- ── events: client analytics backup (Firebase is primary) ──────────────────
create table public.events (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name        text not null check (char_length(name) between 1 and 80),
  props       jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index events_name_created_idx on public.events (name, created_at desc);
alter table public.events enable row level security;
create policy "events own insert" on public.events for insert to authenticated
  with check (user_id = auth.uid());
revoke all on public.events from anon;
revoke all on public.events from authenticated;
grant insert (user_id, name, props) on public.events to authenticated;

-- ── revenue_events: RevenueCat webhook (idempotent on the RC event id) ──────
create table public.revenue_events (
  id            text primary key,            -- RC event id (idempotent)
  app           text not null,
  user_id       text not null,
  type          text not null,               -- INITIAL_PURCHASE / RENEWAL / CANCELLATION / REFUND / ...
  price_usd     numeric,                     -- RC gross USD `price`
  price_local   numeric,
  currency      text,
  is_trial      boolean not null default false,
  sign          smallint not null default 1, -- refund/cancel → -1
  country       text,
  store         text,
  ts            timestamptz not null
);
create index revenue_events_app_country_ts on public.revenue_events (app, country, ts);
create index revenue_events_app_user on public.revenue_events (app, user_id);

create table public.attribution (            -- filled by Ad Ops M2; schema ready
  app text not null, user_id text not null,
  org_id bigint, campaign_id bigint, adgroup_id bigint, keyword_id bigint,
  country text, claim_type text, ts timestamptz not null default now(),
  primary key (app, user_id)
);
alter table public.revenue_events enable row level security;   -- no policies: deny-all
alter table public.attribution enable row level security;
revoke all on public.revenue_events from anon, authenticated;
revoke all on public.attribution from anon, authenticated;

-- Read-only role for the Ad Ops reporter (never the service-role god key). The password is set at
-- deploy time (`alter role adops_ro password …` from a secret), never in this file.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'adops_ro') then
    create role adops_ro nologin;
  end if;
end $$;
grant usage on schema public to adops_ro;
grant select on public.revenue_events, public.attribution to adops_ro;
-- RLS is on and adops_ro does not bypass it: without these policies the reporter reads 0 rows
-- (the credits-mode 0004_adops.sql had exactly that bug).
create policy "adops_ro read revenue" on public.revenue_events for select to adops_ro using (true);
create policy "adops_ro read attribution" on public.attribution for select to adops_ro using (true);
