-- 0004_adops.sql — Ad Ops: revenue events + attribution (for M2) + a read-only reporter role.
create table if not exists revenue_events (
  id            text primary key,            -- RC event id (idempotent)
  app           text not null,
  user_id       text not null,
  type          text not null,               -- INITIAL_PURCHASE / RENEWAL / CANCELLATION / REFUND / ...
  price_usd     numeric,                      -- RC gross USD `price`
  price_local   numeric, currency text,       -- price_in_purchased_currency + currency (audit)
  is_trial      boolean not null default false,
  sign          smallint not null default 1,  -- refund/cancel → -1
  country       text, store text,
  ts            timestamptz not null
);
create index if not exists revenue_events_app_country_ts on revenue_events (app, country, ts);
create index if not exists revenue_events_app_user on revenue_events (app, user_id);

create table if not exists attribution (          -- filled in M2; the schema is ready now
  app text not null, user_id text not null,
  org_id bigint, campaign_id bigint, adgroup_id bigint, keyword_id bigint,
  country text, claim_type text, ts timestamptz not null default now(),
  primary key (app, user_id)
);

alter table revenue_events enable row level security;  -- no anon/auth access (service_role + the role below)
alter table attribution    enable row level security;

-- READ-ONLY role for the reporter (premortem F: do not use the service_role god-key).
-- NOTE: the password is set at deploy time via set_secret; this is a placeholder.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'adops_ro') then
    create role adops_ro login password 'CHANGE_ME_AT_DEPLOY';
  end if;
end $$;
grant usage on schema public to adops_ro;
grant select on revenue_events, attribution to adops_ro;

-- RLS is on and adops_ro does not bypass it: without these policies the reporter reads 0 rows.
do $$ begin
  create policy "adops_ro read revenue" on revenue_events for select to adops_ro using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "adops_ro read attribution" on attribution for select to adops_ro using (true);
exception when duplicate_object then null; end $$;
