// entitlement.ts — is this user a subscriber right now?
//
// The cache row is trusted while plan = premium and now < valid_until, so a subscriber's request
// costs one row read, not a RevenueCat round trip. valid_until is the access end reported by
// RevenueCat (period end, or grace expiry during the billing grace period / billing retry) capped
// at now + maxCacheMs (ENTITLEMENT_GRACE_HOURS, a periodic re-check that also catches refunds). It
// NEVER goes beyond the access end once access has ended we ask RevenueCat again.
// Anything else — no row, plan none, or an expired row — asks RevenueCat. Non-subscribers therefore
// always get a fresh answer: a user who just paid is recognised on their very next request.
import type { RcLookup } from "./rc.ts";
import type { Store } from "./store.ts";

export type Entitlement =
  | { tier: "premium" | "none"; source: "cache" | "revenuecat" }
  | { tier: "unknown"; error: string };   // RevenueCat unreachable and no valid cache

/** Unknown access end (RevenueCat did not say): re-check within a day at most. */
export const UNKNOWN_END_RECHECK_MS = 86_400_000;

export function cacheValidUntil(accessEndsMs: number, nowMs: number, maxCacheMs: number): number {
  const end = accessEndsMs > 0 ? accessEndsMs : nowMs + Math.min(maxCacheMs, UNKNOWN_END_RECHECK_MS);
  return Math.min(end, nowMs + maxCacheMs);
}

export async function resolveEntitlement(
  store: Store,
  rc: RcLookup,
  userId: string,
  nowMs: number,
  maxCacheMs: number,
): Promise<Entitlement> {
  const cached = await store.getEntitlement(userId);
  if (cached?.plan === "premium" && cached.valid_until && Date.parse(cached.valid_until) > nowMs) {
    return { tier: "premium", source: "cache" };
  }

  let sub;
  try {
    sub = await rc(userId);
  } catch (e) {
    return { tier: "unknown", error: (e as Error).message };
  }

  if (sub) {
    await store.putEntitlement(userId, {
      plan: "premium",
      environment: sub.environment,
      product_id: sub.productId || null,
      valid_until: new Date(cacheValidUntil(sub.expiresMs, nowMs, maxCacheMs)).toISOString(),
    });
    return { tier: "premium", source: "revenuecat" };
  }

  if (cached?.plan !== "none" || cached === null) {
    await store.putEntitlement(userId, { plan: "none", environment: null, product_id: null, valid_until: null });
  }
  return { tier: "none", source: "revenuecat" };
}
