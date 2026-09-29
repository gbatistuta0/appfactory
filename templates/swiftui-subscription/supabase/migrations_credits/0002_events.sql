-- Live event tracking (Supabase Analytics). Required for every app.
create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid default auth.uid(),
  name text not null,
  props jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);
alter table public.events enable row level security;
do $$ begin
  create policy "insert own events" on public.events
    for insert to authenticated with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;
create index if not exists events_name_created_idx on public.events (name, created_at desc);
