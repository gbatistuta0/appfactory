// Credit ledger: EVERYTHING is app-scoped (every query filters on `app`). Verification lives in RevenueCat:
// subscription/consumable state is PULLed from the RC v2 API (rc.ts), no Apple JWS.
// Balance = periodic_remaining (subscription cycle) + bonus_remaining (purchased packs).
// Money-critical: server clock (refill), decrement only after success, idempotent consumable redeem.
import type { SupabaseClient } from "jsr:@supabase/supabase-js@2";
import { rcActiveSubscription, rcConsumablePurchases } from "./credits_rc.ts";

export interface Balance {
  plan: string;
  periodic_remaining: number;
  bonus_remaining: number;
  periodic_reset_at: string | null;
}

// Per plan: how many credits + period length in days (refill cadence is a BUSINESS rule, NOT the RC billing period).
// subscriptions/packs are keyed by store_identifier (rc.ts resolves UUID -> store_identifier).
export interface PlanConfig {
  freeCredits: number;
  subscriptions: Record<string, { plan: string; allowance: number; periodDays: number }>;
  packs: Record<string, number>; // store_identifier → credit count
}

const ZERO: Balance = { plan: "none", periodic_remaining: 0, bonus_remaining: 0, periodic_reset_at: null };

// ── Reads ──────────────────────────────────────────────────────────────────
export async function getBalance(supa: SupabaseClient, app: string, userId: string): Promise<Balance> {
  const { data } = await supa
    .from("user_credits")
    .select("plan, periodic_remaining, bonus_remaining, periodic_reset_at")
    .eq("app", app)
    .eq("user_id", userId)
    .maybeSingle();
  return data ? (data as Balance) : { ...ZERO };
}

// Pre-check: is there a balance BEFORE generation (server-authoritative 402 decision).
export async function hasCredit(supa: SupabaseClient, app: string, userId: string): Promise<boolean> {
  const b = await getBalance(supa, app, userId);
  return b.periodic_remaining > 0 || b.bonus_remaining > 0;
}

// ── Free credits (one-time, anti-farm) ───────────────────────────────────────
// Granted only when plan==none and free_granted==false. Thanks to the persistent user.id in the Keychain
// (==RC app_user_id), it is not granted again on reinstall.
export async function grantFreeIfEligible(
  supa: SupabaseClient, app: string, userId: string, freeCredits: number,
): Promise<Balance> {
  if (freeCredits <= 0) return await getBalance(supa, app, userId);
  await supa.from("user_credits").upsert(
    { app, user_id: userId },
    { onConflict: "app,user_id", ignoreDuplicates: true },
  );
  // Conditional update (… WHERE free_granted=false AND plan=none): does not run again on reinstall.
  await supa
    .from("user_credits")
    .update({ periodic_remaining: freeCredits, free_granted: true, updated_at: new Date().toISOString() })
    .eq("app", app)
    .eq("user_id", userId)
    .eq("free_granted", false)
    .eq("plan", "none");
  return await getBalance(supa, app, userId);
}

// ── Single sync: consumable reconcile + subscription refill + free grant ──
// The app calls a single {action:"sync"}. Order:
//   1) Idempotently redeem RC consumable purchases (bonus += pack).
//   2) Find the active RC subscription → time-based periodic refill (server clock).
//      No active subscription → grant the free credits (if any).
export async function syncCredits(
  supa: SupabaseClient, app: string, userId: string, cfg: PlanConfig,
): Promise<Balance> {
  // 1) Reconcile consumable packs (idempotent; RC purchase id = key).
  const purchases = await rcConsumablePurchases(userId);
  for (const p of purchases) {
    const credits = cfg.packs[p.storeId];
    if (!credits || credits <= 0) continue;
    // redeem_consumable: credits + idempotency row in the SAME tx (dup id → no-op).
    await supa.rpc("redeem_consumable", {
      p_app: app, p_user: userId, p_txn: p.id, p_credits: credits,
    });
  }

  // 2) Active subscription?
  const sub = await rcActiveSubscription(userId);
  const map = sub ? cfg.subscriptions[sub.storeId] : undefined;
  if (!sub || !map) {
    // No active subscription. For a FORMER SUBSCRIBER (plan != none) accumulated SUBSCRIPTION credits are RESET
    // (user decision: cancel → periodic 0, purchased bonus is kept). Do not touch FREE users.
    const cur = await getBalance(supa, app, userId);
    if (cur.plan !== "none") {
      await supa.from("user_credits")
        .update({ plan: "none", periodic_remaining: 0, periodic_reset_at: null, updated_at: new Date().toISOString() })
        .eq("app", app).eq("user_id", userId);
      return await getBalance(supa, app, userId);
    }
    return await grantFreeIfEligible(supa, app, userId, cfg.freeCredits);
  }

  // Time-based refill (server clock, anchor = the subscription's starts_at).
  // STANDARD model (use-it-or-lose-it): each period RESETS periodic to the allowance (NO rollover).
  const now = Date.now();
  const periodMs = map.periodDays * 86400_000;
  const cur = await getBalance(supa, app, userId);

  let resetMs: number;
  let periodic: number;
  if (!cur.periodic_reset_at || cur.plan !== map.plan) {
    // New subscriber / plan change (including upgrade) → set to allowance (e.g. 10→15 on upgrade).
    resetMs = sub.startsMs + periodMs;
    periodic = map.allowance;
  } else {
    // Same plan: continue from the current reset.
    resetMs = new Date(cur.periodic_reset_at).getTime();
    periodic = cur.periodic_remaining;
  }
  // When the period rolls over, RESET to the allowance (unused credits expire). while = missed windows yield one grant.
  while (now >= resetMs) {
    periodic = map.allowance;
    resetMs += periodMs;
  }

  await supa.from("user_credits").upsert(
    {
      app, user_id: userId,
      plan: map.plan,
      periodic_remaining: periodic,
      periodic_reset_at: new Date(resetMs).toISOString(),
      updated_at: new Date().toISOString(),
    },
    { onConflict: "app,user_id" },
  );
  return await getBalance(supa, app, userId);
}

// ── Ledger-based refill (NO RC call) ─────────────────────────────────────────
// Called at generation (image) time: if the period has rolled over, refreshes credits BEFORE generation →
// guarantees "every period is always refilled" (without waiting for sync). Uses only the ledger's
// plan + periodic_reset_at; allowance/periodDays are looked up in cfg by plan name.
export async function refillFromLedger(
  supa: SupabaseClient, app: string, userId: string, cfg: PlanConfig,
): Promise<Balance> {
  const cur = await getBalance(supa, app, userId);
  if (cur.plan === "none" || !cur.periodic_reset_at) return cur; // not a subscriber → no periodic refill
  const entry = Object.values(cfg.subscriptions).find((s) => s.plan === cur.plan);
  if (!entry) return cur;
  const periodMs = entry.periodDays * 86400_000;
  const now = Date.now();
  let resetMs = new Date(cur.periodic_reset_at).getTime();
  let periodic = cur.periodic_remaining;
  let changed = false;
  // STANDARD (use-it-or-lose-it): when the period rolls over, RESET to the allowance (no rollover).
  while (now >= resetMs) { periodic = entry.allowance; resetMs += periodMs; changed = true; }
  if (!changed) return cur;
  await supa.from("user_credits").upsert(
    {
      app, user_id: userId, plan: cur.plan,
      periodic_remaining: periodic,
      periodic_reset_at: new Date(resetMs).toISOString(),
      updated_at: new Date().toISOString(),
    },
    { onConflict: "app,user_id" },
  );
  return await getBalance(supa, app, userId);
}

// ── Decrement after success (NO reserve/refund) ──────────────────────────────
// Called AFTER a SUCCESSFUL generation. Atomic and conditional: periodic first, otherwise bonus.
export async function decrementOnSuccess(supa: SupabaseClient, app: string, userId: string): Promise<boolean> {
  const { data, error } = await supa.rpc("decrement_credit", { p_app: app, p_user: userId });
  if (error) throw new Error(`decrement_credit rpc: ${error.message}`);
  return data === true;
}
