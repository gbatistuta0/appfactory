-- AI usage log (quota + billing protection). Written by ai-proxy; users can read their own rows.
create table if not exists public.ai_usage (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  action      text not null,
  model       text,
  created_at  timestamptz not null default now()
);
create index if not exists ai_usage_user_day on public.ai_usage(user_id, created_at);
alter table public.ai_usage enable row level security;
create policy "own usage read" on public.ai_usage for select using (auth.uid() = user_id);
