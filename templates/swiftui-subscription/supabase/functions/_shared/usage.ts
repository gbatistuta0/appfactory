// usage.ts — quota state and the allow/deny decision for one analysis request.
//
//   Non-subscriber: freeLifetimeScans (0 or 1) successful analysis per identity, lifetime, in the
//                   free modes (default: photo). Anything else needs a subscription.
//   Subscriber:     photoDailyLimit photo + textDailyLimit text analyses (successful ones only) per
//                   local calendar day; the day follows the cap timezone (cap_day() in SQL, which
//                   honours a timezone change at most once per 24 h).
//   Everyone:       a rolling-24 h cap on billed model calls (failed ones included) against abuse.
import { PLACEMENTS } from "./app.gen.ts";
import type { Config } from "./config.ts";
import type { Mode, Store } from "./store.ts";

export const WINDOW_MS = 24 * 3_600_000;
export const MODES: Mode[] = ["photo", "text"];

export interface Allowance {
  limit: number;
  used: number;
  remaining: number;
  resets_at: string | null;   // UTC instant of the next local midnight (null for lifetime allowances)
}

export interface UsageSummary {
  tier: "free" | "premium";
  free_scan_available: boolean;
  timezone: string | null;       // the cap day's timezone (premium)
  photo: Allowance;
  text: Allowance;
}

export function freeModes(cfg: Config): Set<Mode> {
  return new Set(cfg.freeModes);
}

function allowance(limit: number, used: number, resetsAt: string | null): Allowance {
  return { limit, used, remaining: Math.max(0, limit - used), resets_at: resetsAt };
}

export async function usageSummary(
  store: Store,
  cfg: Config,
  userId: string,
  premium: boolean,
): Promise<UsageSummary> {
  const freeUsed = await store.freeScanUsed(userId);
  if (!premium) {
    const free = freeModes(cfg);
    const lifetime = (mode: Mode) => {
      const limit = free.has(mode) ? cfg.freeLifetimeScans : 0;
      return allowance(limit, freeUsed ? limit : 0, null);
    };
    return {
      tier: "free",
      free_scan_available: cfg.freeLifetimeScans > 0 && !freeUsed,
      timezone: null,
      photo: lifetime("photo"),
      text: lifetime("text"),
    };
  }
  const day = await store.capDay(userId);
  const [photo, text] = await Promise.all([
    store.usageSince(userId, day.day_start, { mode: "photo", okOnly: true }),
    store.usageSince(userId, day.day_start, { mode: "text", okOnly: true }),
  ]);
  return {
    tier: "premium",
    free_scan_available: cfg.freeLifetimeScans > 0 && !freeUsed,
    timezone: day.timezone,
    photo: allowance(cfg.photoDailyLimit, photo.count, day.resets_at),
    text: allowance(cfg.textDailyLimit, text.count, day.resets_at),
  };
}

/** Summary after one more successful analysis in `mode` (avoids re-querying). */
export function consumeOne(s: UsageSummary, mode: Mode): UsageSummary {
  const next = structuredClone(s);
  if (s.tier === "free") {
    next.free_scan_available = false;
    for (const m of MODES) next[m] = { ...next[m], used: next[m].limit, remaining: 0 };
    return next;
  }
  const a = next[mode];
  a.used += 1;
  a.remaining = Math.max(0, a.limit - a.used);
  return next;
}

export type Gate =
  | { allow: true }
  | { allow: false; status: number; body: Record<string, unknown> };

/** Pure decision: may this request call the model? Error bodies follow backend/CONTRACT.md. */
export function gate(
  s: UsageSummary,
  mode: Mode,
  attempts: { count: number; oldest: string | null },
  cfg: Config,
): Gate {
  if (s.tier === "free") {
    if (!freeModes(cfg).has(mode) || cfg.freeLifetimeScans === 0) {
      return {
        allow: false, status: 402,
        body: { error: "paywall_required", reason: "subscription_required", placement: PLACEMENTS.freeUsed },
      };
    }
    if (!s.free_scan_available) {
      return {
        allow: false, status: 402,
        body: { error: "paywall_required", reason: "free_scan_used", placement: PLACEMENTS.freeUsed },
      };
    }
  } else if (s[mode].remaining <= 0) {
    return {
      allow: false, status: 429,
      body: {
        error: "daily_cap_reached", placement: PLACEMENTS.dailyCap, mode,
        limit: s[mode].limit, resets_at: s[mode].resets_at,
      },
    };
  }
  const attemptLimit = s.tier === "free" ? cfg.freeAttemptLimit : cfg.hardAttemptLimit;
  if (attempts.count >= attemptLimit) {
    return {
      allow: false, status: 429,
      body: {
        error: "too_many_attempts",
        resets_at: attempts.oldest ? new Date(Date.parse(attempts.oldest) + WINDOW_MS).toISOString() : null,
      },
    };
  }
  return { allow: true };
}
