// rc.ts: RevenueCat v2 REST client (SERVER-side PULL).
// There is NO Apple JWS verification anymore: RevenueCat verifies purchases itself
// (the cert-chain signature verification / Deno-crypto hassle is gone entirely). This module pulls the user's
// subscription + consumable state from RC. Identity: Supabase user.id == RC app_user_id.
const RC_BASE = "https://api.revenuecat.com/v2";
const PROJECT = Deno.env.get("RC_PROJECT_ID") ?? "";
const SECRET = Deno.env.get("RC_SECRET_KEY") ?? "";

async function rcGet(path: string): Promise<Record<string, unknown> | null> {
  const r = await fetch(`${RC_BASE}/projects/${PROJECT}${path}`, {
    headers: { Authorization: `Bearer ${SECRET}` },
  });
  if (r.status === 404) return null; // customer/resource does not exist yet
  if (!r.ok) throw new Error(`RC ${path} → ${r.status} ${await r.text()}`);
  return await r.json();
}

// RC product UUID → store_identifier (e.g. com.example.app.weekly).
// Fetched once on cold start; cached for the isolate's lifetime (warm requests are free).
let productMap: Record<string, string> | null = null;
async function storeIdMap(): Promise<Record<string, string>> {
  if (productMap) return productMap;
  const data = await rcGet(`/products?limit=100`);
  const m: Record<string, string> = {};
  for (const p of ((data?.items as Array<Record<string, unknown>>) ?? [])) {
    m[String(p.id)] = String(p.store_identifier);
  }
  productMap = m;
  return m;
}

export interface RcSubscription { storeId: string; startsMs: number; expiresMs: number; }

// The user's access-granting subscription that expires LATEST (null if none). product_id → store_identifier.
export async function rcActiveSubscription(userId: string): Promise<RcSubscription | null> {
  const data = await rcGet(`/customers/${encodeURIComponent(userId)}/subscriptions`);
  const items = (data?.items as Array<Record<string, unknown>>) ?? [];
  if (items.length === 0) return null;
  const map = await storeIdMap();
  let best: RcSubscription | null = null;
  for (const s of items) {
    if (s.gives_access !== true) continue; // grants no access (expired/cancelled/outside billing retry)
    const storeId = map[String(s.product_id)];
    if (!storeId) continue;
    const expires = Number(s.current_period_ends_at ?? s.ends_at ?? 0);
    if (!best || expires > best.expiresMs) {
      best = { storeId, startsMs: Number(s.starts_at ?? 0), expiresMs: expires };
    }
  }
  return best;
}

export interface RcPurchase { id: string; storeId: string; }

// The user's non-subscription (consumable) purchases. id = idempotency key (RC purchase id).
export async function rcConsumablePurchases(userId: string): Promise<RcPurchase[]> {
  const data = await rcGet(`/customers/${encodeURIComponent(userId)}/purchases`);
  const items = (data?.items as Array<Record<string, unknown>>) ?? [];
  if (items.length === 0) return [];
  const map = await storeIdMap();
  return items
    .map((p) => ({ id: String(p.id), storeId: map[String(p.product_id)] }))
    .filter((p) => !!p.storeId);
}
