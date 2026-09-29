// ai-proxy: AI provider proxy + server-side credit ledger (Deno edge function).
// Security: AI keys live only here (Supabase secret). The app holds no keys.
// Identity: derived from the anonymous Supabase JWT (getUser); == RevenueCat app_user_id.
// Verification lives in RevenueCat (NO Apple JWS); state is PULLed from the RC v2 API.
// Flow (action routing):
//   sync    → consumable reconcile from RC + subscription refill + free grant → balance
//   image   → pre-check hasCredit → if none, 402 → fal.ai → decrement ON SUCCESS → result + balance
// Money-critical premortem mitigations: server clock (refill), success-decrement, app-scoped, idempotent redeem, NO trust-bypass.
import { createClient } from "jsr:@supabase/supabase-js@2";
import {
  getBalance, hasCredit, syncCredits, refillFromLedger, decrementOnSuccess,
  type PlanConfig,
} from "../_shared/credits.ts";

const FAL_KEY = Deno.env.get("FAL_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const DAILY_LIMIT = Number(Deno.env.get("AI_DAILY_LIMIT") ?? "20");
// Usage table (billing-protection backstop). Separate from the app-scoped credit tables in a shared project.
const USAGE_TABLE = "ai_usage";

// app = this deployment's bundle id. Namespaces the credit tables in a shared project (premortem #6).
// Injected via the __APP_BUNDLE__ token or the APP_BUNDLE env. NO trust-bypass header (premortem #7).
const APP = Deno.env.get("APP_BUNDLE") ?? "__APP_BUNDLE__";
const FREE_CREDITS = Number(Deno.env.get("FREE_CREDITS") ?? "1");

// Subscription + consumable → credit mapping (app-scoped, keyed by store_identifier).
// rc.ts resolves RC product UUIDs to these store_identifiers. productId bases are injected.
// weekly 10/7d, yearly 15/30d (yearly sub refills monthly). Offer products map to the same plan.
const PRODUCT_WEEKLY = Deno.env.get("PRODUCT_WEEKLY") ?? "__PRODUCT_WEEKLY__";
const PRODUCT_YEARLY = Deno.env.get("PRODUCT_YEARLY") ?? "__PRODUCT_YEARLY__";
const PLAN_CONFIG: PlanConfig = {
  freeCredits: FREE_CREDITS,
  subscriptions: {
    [PRODUCT_WEEKLY]: { plan: "weekly", allowance: 10, periodDays: 7 },
    [PRODUCT_WEEKLY + ".offer"]: { plan: "weekly", allowance: 10, periodDays: 7 },
    [PRODUCT_YEARLY]: { plan: "yearly", allowance: 15, periodDays: 30 },
    [PRODUCT_YEARLY + ".offer"]: { plan: "yearly", allowance: 15, periodDays: 30 },
  },
  packs: {
    [`${APP}.credits.small`]: 10,
    [`${APP}.credits.medium`]: 30,
    [`${APP}.credits.large`]: 60,
  },
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  // Auth client: forwards the user's JWT (for getUser).
  const authHeader = req.headers.get("Authorization") ?? "";
  const auth = createClient(SUPABASE_URL, SERVICE_KEY, {
    global: { headers: { Authorization: authHeader } },
  });

  // Identity = anonymous Supabase user. user.id is the ledger key (NOT sent by the app).
  const { data: { user } } = await auth.auth.getUser();
  if (!user) return json({ error: "unauthorized" }, 401);
  const userId = user.id;

  // Data client: service-role ONLY (user JWT is NOT forwarded) → bypasses RLS.
  // Credit/usage tables are deny-all RLS; only this client reads/writes them (money-critical, premortem #3).
  const supa = createClient(SUPABASE_URL, SERVICE_KEY);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid json" }, 400);
  }
  const action = (body.action as string) ?? "image";

  // ── Credit sync (pull from RC) ─────────────────────────────────────────────
  // Single action: consumable reconcile + subscription refill + free grant. The app calls this on cold open,
  // foreground and after every purchase.
  if (action === "sync") {
    const balance = await syncCredits(supa, APP, userId, PLAN_CONFIG);
    return json({ ok: true, balance });
  }

  // ── AI generation (credit-gated) ───────────────────────────────────────────
  if (action === "image") {
    const prompt = (body.prompt as string) ?? "";
    if (!prompt) return json({ error: "prompt required" }, 400);

    // 0) If the period has rolled over, refill credits BEFORE generation (ledger-only, no RC call) →
    //    guarantees "every period is always refilled" without waiting for sync.
    await refillFromLedger(supa, APP, userId, PLAN_CONFIG);

    // 1) Pre-check: with no credits, do NOT CALL fal.ai; return 402 → the app routes to paywall/top-up.
    if (!(await hasCredit(supa, APP, userId))) {
      return json({ error: "out_of_credits" }, 402);
    }

    // 2) Daily quota (billing protection: a backstop independent of the credit ledger).
    const since = new Date();
    since.setHours(0, 0, 0, 0);
    const { count } = await supa
      .from(USAGE_TABLE)
      .select("*", { count: "exact", head: true })
      .eq("user_id", userId)
      .gte("created_at", since.toISOString());
    if ((count ?? 0) >= DAILY_LIMIT) {
      return json({ error: "daily quota exceeded", limit: DAILY_LIMIT }, 429);
    }

    // 3) Generation.
    const imageUrl = body.image_url as string | undefined;
    let usedModel: string;
    let falBody: Record<string, unknown>;
    if (imageUrl) {
      // Face-preserving: Nano Banana PRO (Gemini 3 Pro Image edit), keeps identity MOST faithfully ($0.15).
      usedModel = (body.model as string) ?? "fal-ai/nano-banana-pro/edit";
      falBody = { prompt, image_urls: [imageUrl] };
    } else {
      usedModel = (body.model as string) ?? "fal-ai/flux/schnell";
      falBody = { prompt, image_size: body.image_size ?? "portrait_4_3" };
    }
    const r = await fetch(`https://fal.run/${usedModel}`, {
      method: "POST",
      headers: { "Authorization": `Key ${FAL_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(falBody),
    });
    const result = await r.json();
    if (!r.ok) {
      // Generation FAILED → credit is NOT deducted (decrement-on-success; no refund needed).
      return json({ error: "provider error", detail: result }, 502);
    }

    // 4) SUCCESS → deduct the credit (atomic, conditional). Log to the usage table for reconciliation.
    await decrementOnSuccess(supa, APP, userId);
    await supa.from(USAGE_TABLE).insert({ user_id: userId, action, model: usedModel });

    const balance = await getBalance(supa, APP, userId);
    return json({ ok: true, result, balance });
  }

  return json({ error: "unsupported action: " + action }, 400);
});
