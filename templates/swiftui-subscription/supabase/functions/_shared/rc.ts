// rc.ts — RevenueCat v2 REST client (server-side PULL). RevenueCat verifies purchases with Apple;
// we only ask it whether this user currently has access. Identity: Supabase user.id == RC app_user_id.
//
// Rules carried over from production incidents:
// - Sandbox vs production is decided by `environment`, never by `store` (sandbox also says app_store).
// - Sandbox subscriptions COUNT: App Review buys with sandbox accounts and must get the product.
// - A subscription in its free trial counts as active.

export interface RcSubscription {
  productId: string;
  environment: "production" | "sandbox";
  status: string;          // active | trialing | in_grace_period | in_billing_retry | …
  expiresMs: number;       // access end: grace expiry in grace/billing retry, else period end (0 = unknown)
}

export type RcLookup = (userId: string) => Promise<RcSubscription | null>;

export function isSandbox(x: Record<string, unknown>): boolean {
  return String(x.environment ?? "").toLowerCase() === "sandbox";
}

// Billing resilience: with the App Store Billing Grace Period on, a subscriber whose
// renewal failed keeps access while Apple retries the charge.
//   in_grace_period   → access (unless RevenueCat says gives_access: false)
//   in_billing_retry  → access only while RevenueCat says gives_access: true
const ACCESS_STATUSES = new Set(["active", "trialing", "in_grace_period"]);
const GRACE_EXPIRY_FIELDS = ["grace_period_expires_at", "grace_period_ends_at", "billing_issues_grace_period_ends_at"];

/** Does this RC v2 subscription object grant access right now? */
export function grantsAccess(s: Record<string, unknown>): boolean {
  const status = String(s.status ?? "").toLowerCase();
  if (s.gives_access === false) return false;
  if (status === "in_billing_retry") return s.gives_access === true;
  if (s.gives_access === true) return true;
  return ACCESS_STATUSES.has(status);
}

function ms(v: unknown): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
    const d = Date.parse(v);
    if (Number.isFinite(d)) return d;
  }
  return 0;
}

/**
 * When access ends: the grace expiry while in grace/billing retry (if RevenueCat reports one),
 * otherwise the current period end. 0 = unknown.
 */
export function accessEndsMs(s: Record<string, unknown>): number {
  const status = String(s.status ?? "").toLowerCase();
  if (status === "in_grace_period" || status === "in_billing_retry") {
    const grace = Math.max(0, ...GRACE_EXPIRY_FIELDS.map((f) => ms(s[f])));
    if (grace > 0) return grace;
  }
  return ms(s.current_period_ends_at) || ms(s.ends_at);
}

/** Of the subscriptions that grant access, the one whose access ends last. */
export function pickActiveSubscription(items: Array<Record<string, unknown>>): RcSubscription | null {
  let best: RcSubscription | null = null;
  for (const s of items) {
    if (!grantsAccess(s)) continue;
    const expires = accessEndsMs(s);
    if (!best || expires > best.expiresMs) {
      best = {
        productId: String(s.product_id ?? ""),
        environment: isSandbox(s) ? "sandbox" : "production",
        status: String(s.status ?? ""),
        expiresMs: expires,
      };
    }
  }
  return best;
}

export function revenueCatLookup(
  projectId: string,
  secretKey: string,
  fetchImpl: typeof fetch = fetch,
  base = "https://api.revenuecat.com/v2",
): RcLookup {
  return async (userId) => {
    // Never guess "not a subscriber" when the secret is missing: the caller turns this error into
    // a retryable 503, which is far cheaper than paywalling a paying user.
    if (!projectId || !secretKey) throw new Error("RevenueCat is not configured (RC_PROJECT_ID / RC_SECRET_KEY)");
    const url = `${base}/projects/${encodeURIComponent(projectId)}/customers/${encodeURIComponent(userId)}/subscriptions`;
    const r = await fetchImpl(url, { headers: { Authorization: `Bearer ${secretKey}` } });
    if (r.status === 404) {
      await r.body?.cancel();
      return null;          // customer not known to RevenueCat yet
    }
    if (!r.ok) throw new Error(`RevenueCat ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const data = await r.json() as { items?: Array<Record<string, unknown>> };
    return pickActiveSubscription(data.items ?? []);
  };
}
