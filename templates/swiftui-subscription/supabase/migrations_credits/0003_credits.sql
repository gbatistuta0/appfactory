-- Server-side credit ledger. Money-critical.
-- Identity = the EXISTING anonymous Supabase user (auth.users.id); there is NO separate UUID.
-- Only the edge function (service role) reads/writes. RLS deny-all: anon/authenticated have no access.
-- the app column namespaces apps sharing one Supabase project.

-- Credit balance: periodic (subscription refill) + bonus (purchased packs, persistent).
create table if not exists public.user_credits (
  app                 text not null,                                   -- bundle id (namespace)
  user_id             uuid not null references auth.users(id) on delete cascade,
  plan                text not null default 'none',                    -- none | weekly | yearly
  periodic_remaining  int  not null default 0,                         -- subscription-cycle credits
  periodic_reset_at   timestamptz,                                     -- next refill boundary (server clock)
  bonus_remaining     int  not null default 0,                         -- pack credits (survive renewal/lapse)
  free_granted        bool not null default false,                     -- free credits granted once (anti-farm)
  updated_at          timestamptz not null default now(),
  primary key (app, user_id)
);

-- CONSUMABLE pack idempotency: each Apple transactionId grants credits only once (replay-safe).
create table if not exists public.redeemed_transactions (
  transaction_id  text primary key,                                    -- Apple transactionId (globally unique)
  app             text not null,
  user_id         uuid not null,
  credits         int  not null,
  created_at      timestamptz not null default now()
);

-- RLS: deny-all. NO public policy → anon/authenticated roles can see/write NOTHING.
-- The edge function bypasses RLS with service-role (the only authorized writer/reader).
alter table public.user_credits          enable row level security;
alter table public.redeemed_transactions enable row level security;

-- ── Money-critical atomic operations (Postgres RPC) ─────────────────────────
-- These must run inside a SINGLE transaction; they cannot be emulated in the application layer.

-- redeem_consumable: adds pack credits idempotently + atomically (premortem #2).
-- If the transactionId has not been used before: bonus_remaining += credits AND the idempotency
-- row are written in the SAME transaction. It does not write the idempotency row BEFORE the credits.
-- Replay (same transactionId) → no-op, returns the current balance.
create or replace function public.redeem_consumable(
  p_app text, p_user uuid, p_txn text, p_credits int
) returns table(periodic_remaining int, bonus_remaining int)
language plpgsql security definer set search_path = public as $$
begin
  -- Idempotency: if the row already exists, add nothing (replay-safe).
  insert into redeemed_transactions(transaction_id, app, user_id, credits)
    values (p_txn, p_app, p_user, p_credits)
    on conflict (transaction_id) do nothing;

  if found then
    -- Seen for the first time → add the credits in the SAME transaction.
    insert into user_credits(app, user_id, bonus_remaining, updated_at)
      values (p_app, p_user, p_credits, now())
      on conflict (app, user_id) do update
        set bonus_remaining = user_credits.bonus_remaining + excluded.bonus_remaining,
            updated_at = now();
  end if;

  return query
    select uc.periodic_remaining, uc.bonus_remaining
    from user_credits uc where uc.app = p_app and uc.user_id = p_user;
end; $$;

-- decrement_credit: called AFTER a SUCCESSFUL generation (NO reserve/refund, premortem #5).
-- Deducts 1 from periodic first, otherwise from bonus; atomic and conditional (… WHERE > 0).
-- Returns false if there are no credits at all (but the pre-check should have passed by this point).
create or replace function public.decrement_credit(
  p_app text, p_user uuid
) returns boolean
language plpgsql security definer set search_path = public as $$
declare ok boolean := false;
begin
  update user_credits set periodic_remaining = periodic_remaining - 1, updated_at = now()
    where app = p_app and user_id = p_user and periodic_remaining > 0;
  if found then return true; end if;

  update user_credits set bonus_remaining = bonus_remaining - 1, updated_at = now()
    where app = p_app and user_id = p_user and bonus_remaining > 0;
  return found;
end; $$;

-- The RPCs are called only by service-role; anon/authenticated cannot EXECUTE them.
revoke all on function public.redeem_consumable(text, uuid, text, int) from public, anon, authenticated;
revoke all on function public.decrement_credit(text, uuid) from public, anon, authenticated;
