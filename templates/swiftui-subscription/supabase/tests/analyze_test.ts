// End-to-end behaviour of the analyze handler with in-memory DB, model and RevenueCat.
// Error bodies are asserted exactly: they are the contract with the iOS app (backend/CONTRACT.md).
import { assert, assertEquals } from "jsr:@std/assert@1";
import { createHandler, type Deps } from "../functions/analyze/handler.ts";
import { createHandler as createStatusHandler } from "../functions/usage-status/handler.ts";
import type { LlmResult } from "../functions/_shared/llm.ts";
import type { RcSubscription } from "../functions/_shared/rc.ts";
import {
  ACTIVE_SUB, errorResult, GOOD_OUTPUT, JPEG_B64, MemoryStore, NOT_APPLICABLE_OUTPUT, okResult,
  rcReturning, scriptedLlm, T0, testConfig,
} from "./fakes.ts";

const USER = "11111111-1111-1111-1111-111111111111";

function setup(opts: {
  results?: LlmResult[];
  sub?: RcSubscription | null | Error;
  env?: Record<string, string>;
  store?: MemoryStore;
} = {}) {
  const store = opts.store ?? new MemoryStore();
  const llm = scriptedLlm(opts.results ?? [okResult(GOOD_OUTPUT)]);
  const rc = rcReturning(opts.sub === undefined ? ACTIVE_SUB : opts.sub);
  const logs: string[] = [];
  const deps: Deps = {
    cfg: testConfig(opts.env),
    store, llm, rc,
    userIdFromJwt: (jwt) => Promise.resolve(jwt === "good" ? USER : null),
    now: () => T0,
    log: (msg) => logs.push(msg),
  };
  return { handler: createHandler(deps), store, llm, rc, logs };
}

function post(body: unknown, jwt: string | null = "good"): Request {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (jwt) headers.Authorization = `Bearer ${jwt}`;
  return new Request("http://localhost/analyze", {
    method: "POST", headers, body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const MIDNIGHT = new Date(Date.parse("2026-09-25T00:00:00Z")).toISOString();   // next UTC midnight after T0
const PHOTO = { mode: "photo", image: { data: JPEG_B64 }, locale: "tr-TR", note: "golden hour" };
const TEXT = { mode: "text", text: "a red door in a white wall", locale: "en-US" };
const PAYWALL_FREE_USED = { error: "paywall_required", reason: "free_scan_used", placement: "free_scan_used" };
const PAYWALL_SUB_REQUIRED = { error: "paywall_required", reason: "subscription_required", placement: "free_scan_used" };

async function call(h: (r: Request) => Promise<Response>, req: Request) {
  const res = await h(req);
  return { status: res.status, body: await res.json() };
}

Deno.test("subscriber photo analysis: 200 with the normalized result and remaining quota", async () => {
  const { handler, store, llm } = setup();
  const { status, body } = await call(handler, post(PHOTO));
  assertEquals(status, 200);
  assertEquals(body.analysis_id, 1);
  assertEquals(body.locale, "tr");
  assertEquals(body.result, {
    title: "Sunset over the sea", summary: "A warm orange sunset over calm water.",
    tags: ["sunset", "sea", "orange", "calm", "evening"], confidence: 0.82,
  });
  assertEquals(body.usage.tier, "premium");
  assertEquals(body.usage.photo, { limit: 12, used: 1, remaining: 11, resets_at: MIDNIGHT });
  assertEquals(body.usage.timezone, "UTC");
  assertEquals(body.usage.text.remaining, 20);

  assertEquals(llm.calls.length, 1);
  assert(llm.calls[0].system.includes("in Turkish"));
  assert(llm.calls[0].userText.includes('User note: """golden hour"""'));
  assertEquals(llm.calls[0].image?.mime, "image/jpeg");
  assertEquals(llm.calls[0].schemaName, "analysis");
  assertEquals(llm.calls[0].reasoning, "minimal");

  assertEquals(store.usage.length, 1);
  assertEquals([store.usage[0].status, store.usage[0].tier, store.usage[0].cost_usd], ["ok", "premium", 0.0031]);
});

Deno.test("subscriber text analysis: 200, counted against the text quota", async () => {
  const { handler, llm } = setup();
  const { status, body } = await call(handler, post(TEXT));
  assertEquals(status, 200);
  assertEquals(body.mode, "text");
  assertEquals(body.usage.text.used, 1);
  assertEquals(body.usage.photo.used, 0);
  assertEquals(llm.calls[0].image, null);
  assert(llm.calls[0].userText.includes("a red door"));
});

Deno.test("auth: missing or invalid JWT → 401, no model call", async () => {
  for (const jwt of [null, "bad"]) {
    const { handler, llm } = setup();
    const r = await call(handler, post(PHOTO, jwt));
    assertEquals([r.status, r.body], [401, { error: "unauthorized" }]);
    assertEquals(llm.calls.length, 0);
  }
});

Deno.test("validation errors → 4xx, no model call", async () => {
  const cases: Array<[unknown, number, string]> = [
    ["{not json", 400, "invalid_request"],
    [{ mode: "video" }, 400, "invalid_request"],
    [{ mode: "photo" }, 400, "invalid_request"],
    [{ mode: "photo", image: { data: btoa("GIF89a" + "x".repeat(40)) } }, 415, "unsupported_image"],
    [{ ...PHOTO, note: "x".repeat(281) }, 400, "invalid_request"],
    [{ mode: "text", text: "   " }, 400, "invalid_request"],
    [{ mode: "text", text: "y".repeat(501) }, 400, "invalid_request"],
  ];
  for (const [body, status, error] of cases) {
    const { handler, llm } = setup();
    const r = await call(handler, post(body));
    assertEquals([r.status, r.body.error], [status, error], JSON.stringify(body).slice(0, 60));
    assertEquals(llm.calls.length, 0);
  }
  const { handler } = setup({ env: { MAX_IMAGE_BYTES: "20" } });
  assertEquals((await call(handler, post(PHOTO))).status, 413);
  const get = await setup().handler(new Request("http://localhost/", { method: "GET" }));
  assertEquals(get.status, 405);
});

Deno.test("consent: REQUIRE_CONSENT → 403 consent_required before RevenueCat or the model", async () => {
  const store = new MemoryStore();
  store.noConsent.add(USER);
  const { handler, llm, rc } = setup({ store, env: { REQUIRE_CONSENT: "true" } });
  const r = await call(handler, post(PHOTO));
  assertEquals([r.status, r.body], [403, { error: "consent_required" }]);
  assertEquals([llm.calls.length, rc.calls, store.usage.length], [0, 0, 0]);
  assertEquals(store.denials.map((d) => d.reason), ["consent_required"]);

  // Without REQUIRE_CONSENT (spec.consent.health = false) the column is not checked.
  const open = new MemoryStore();
  open.noConsent.add(USER);
  assertEquals((await setup({ store: open }).handler(post(PHOTO))).status, 200);
});

Deno.test("validation runs before consent: a bad body is 400 even without consent", async () => {
  const store = new MemoryStore();
  store.noConsent.add(USER);
  const r = await call(setup({ store, env: { REQUIRE_CONSENT: "1" } }).handler, post({ mode: "video" }));
  assertEquals(r.status, 400);
});

Deno.test("free user: first photo analysis is free, second → 402 free_scan_used", async () => {
  const { handler, store, llm } = setup({ sub: null, results: [okResult(GOOD_OUTPUT), okResult(GOOD_OUTPUT)] });
  const first = await call(handler, post(PHOTO));
  assertEquals(first.status, 200);
  assertEquals(first.body.usage.tier, "free");
  assertEquals(first.body.usage.free_scan_available, false);
  assertEquals(store.usage[0].tier, "free");

  const second = await call(handler, post(PHOTO));
  assertEquals([second.status, second.body], [402, PAYWALL_FREE_USED]);
  assertEquals(llm.calls.length, 1);
});

Deno.test("free user: text needs a subscription unless FREE_MODES includes it; 0 free scans → always 402", async () => {
  const { handler, llm } = setup({ sub: null });
  const r = await call(handler, post(TEXT));
  assertEquals([r.status, r.body], [402, PAYWALL_SUB_REQUIRED]);
  assertEquals(llm.calls.length, 0);

  assertEquals((await setup({ sub: null, env: { FREE_MODES: "photo,text" } }).handler(post(TEXT))).status, 200);

  const none = await call(setup({ sub: null, env: { FREE_LIFETIME_SCANS: "0" } }).handler, post(PHOTO));
  assertEquals([none.status, none.body], [402, PAYWALL_SUB_REQUIRED]);
});

Deno.test("free analysis is not consumed by failures or not-applicable input", async () => {
  const { handler, store } = setup({
    sub: null,
    results: [okResult(NOT_APPLICABLE_OUTPUT), errorResult("a"), errorResult("b"), okResult(GOOD_OUTPUT)],
  });
  const na = await call(handler, post(PHOTO));
  assertEquals(na.status, 422);
  assertEquals(na.body.error, "not_applicable");
  assertEquals(na.body.usage.free_scan_available, true);

  const failed = await call(handler, post(PHOTO));          // primary and fallback both fail
  assertEquals([failed.status, failed.body], [502, { error: "analysis_failed", retryable: true }]);

  const ok = await call(handler, post(PHOTO));
  assertEquals(ok.status, 200);
  assertEquals(store.usage.map((u) => u.status), ["not_applicable", "provider_error", "provider_error", "ok"]);
});

Deno.test("concurrent free analyses: the loser gets 402 and no result", async () => {
  const store = new MemoryStore();
  const { handler } = setup({ sub: null, store });
  const origInsert = store.insertUsage.bind(store);
  store.insertUsage = (row) => {
    if (row.status === "ok") store.seed(USER, 1, { tier: "free", atMs: T0 });
    return origInsert(row);
  };
  const r = await call(handler, post(PHOTO));
  assertEquals([r.status, r.body], [402, PAYWALL_FREE_USED]);
});

Deno.test("fallback model: used once after a provider error or unusable output", async () => {
  const { handler, llm, store } = setup({ results: [errorResult("x", 429), okResult(GOOD_OUTPUT)] });
  assertEquals((await handler(post(PHOTO))).status, 200);
  assertEquals(llm.calls.map((c) => c.model), ["google/gemini-3.6-flash", "google/gemini-3.8-flash"]);
  assertEquals(store.usage.map((u) => [u.status, u.model]), [
    ["provider_error", "google/gemini-3.6-flash"],
    ["ok", "google/gemini-3.8-flash"],
  ]);

  const bad = setup({ results: [okResult("sorry, I can't"), okResult(GOOD_OUTPUT)] });
  assertEquals((await bad.handler(post(PHOTO))).status, 200);
  assertEquals(bad.store.usage.map((u) => u.status), ["invalid_output", "ok"]);

  const noFallback = setup({ env: { AI_FALLBACK_MODEL: "" }, results: [errorResult("x")] });
  assertEquals((await noFallback.handler(post(PHOTO))).status, 502);
  assertEquals(noFallback.llm.calls.length, 1);

  const same = setup({ env: { AI_FALLBACK_MODEL: "google/gemini-3.6-flash" }, results: [errorResult("x")] });
  assertEquals((await same.handler(post(PHOTO))).status, 502);
  assertEquals(same.llm.calls.length, 1);   // the same model is never tried twice
});

Deno.test("not_applicable is final: no fallback call, not counted", async () => {
  const { handler, llm, store } = setup({ results: [okResult(NOT_APPLICABLE_OUTPUT)] });
  const r = await call(handler, post(PHOTO));
  assertEquals(r.status, 422);
  assertEquals(r.body.usage.photo.used, 0);
  assertEquals(llm.calls.length, 1);
  assertEquals(store.usage[0].status, "not_applicable");
});

Deno.test("subscriber daily caps per local calendar day (env-configurable)", async () => {
  const store = new MemoryStore();
  store.seed(USER, 12, { mode: "photo", atMs: T0 - 3 * 3_600_000 });   // earlier today (UTC)
  const { handler, llm } = setup({ store });
  const r = await call(handler, post(PHOTO));
  assertEquals([r.status, r.body], [429, {
    error: "daily_cap_reached", placement: "daily_cap", mode: "photo", limit: 12, resets_at: MIDNIGHT,
  }]);
  assertEquals(llm.calls.length, 0);
  assertEquals((await handler(post(TEXT))).status, 200);   // text has its own quota

  // Analyses from yesterday (13 h ago, before midnight) no longer count.
  const old = new MemoryStore();
  old.seed(USER, 12, { mode: "photo", atMs: T0 - 13 * 3_600_000 });
  assertEquals((await setup({ store: old }).handler(post(PHOTO))).status, 200);

  // The day follows the cap timezone: in Istanbul (UTC+3) the day began at 21:00 UTC yesterday.
  const tz = new MemoryStore();
  tz.day = { timezone: "Europe/Istanbul", day_start: "2026-09-23T21:00:00.000Z", resets_at: "2026-09-24T21:00:00.000Z" };
  tz.seed(USER, 12, { mode: "photo", atMs: Date.parse("2026-09-23T22:00:00Z") });
  const r2 = await call(setup({ store: tz }).handler, post(PHOTO));
  assertEquals([r2.status, r2.body.resets_at], [429, "2026-09-24T21:00:00.000Z"]);

  const custom = new MemoryStore();
  custom.seed(USER, 3, { mode: "photo" });
  assertEquals((await call(setup({ store: custom, env: { PHOTO_DAILY_LIMIT: "3" } }).handler, post(PHOTO))).status, 429);
});

Deno.test("attempt backstop: too many billed calls in 24 h → 429 too_many_attempts", async () => {
  const store = new MemoryStore();
  store.seed(USER, 5, { tier: "free", status: "not_applicable" });
  const r = await call(setup({ sub: null, store }).handler, post(PHOTO));
  assertEquals(r.status, 429);
  assertEquals(r.body, {
    error: "too_many_attempts", resets_at: new Date(T0 - 3_600_000 + 86_400_000).toISOString(),
  });

  const premium = new MemoryStore();
  premium.seed(USER, 60, { status: "invalid_output" });
  assertEquals((await call(setup({ store: premium }).handler, post(PHOTO))).body.error, "too_many_attempts");
});

Deno.test("trial and sandbox subscriptions unlock analysis", async () => {
  for (const sub of [{ ...ACTIVE_SUB, status: "trialing" }, { ...ACTIVE_SUB, environment: "sandbox" as const }]) {
    const { handler, store } = setup({ sub });
    assertEquals((await handler(post(TEXT))).status, 200);
    assertEquals(store.usage[0].tier, "premium");
  }
});

Deno.test("RevenueCat outage: free analysis still works, others get 503 (never a paywall)", async () => {
  const outage = new Error("RC 503");
  const r1 = await call(setup({ sub: outage }).handler, post(PHOTO));
  assertEquals([r1.status, r1.body.usage.tier], [200, "free"]);

  const store = new MemoryStore();
  store.seed(USER, 1, { tier: "free" });
  const r2 = await call(setup({ sub: outage, store }).handler, post(PHOTO));
  assertEquals([r2.status, r2.body], [503, { error: "entitlement_unavailable", retryable: true }]);

  // Text is not a free mode: 503, not 402, during an outage.
  assertEquals((await call(setup({ sub: outage }).handler, post(TEXT))).status, 503);

  // Missing RC secrets behave like an outage (the lookup throws "not configured").
  const cached = new MemoryStore();
  cached.entitlements.set(USER, {
    plan: "premium", environment: "production", product_id: "p",
    valid_until: new Date(T0 + 86_400_000).toISOString(),
  });
  const r3 = setup({ sub: outage, store: cached });
  assertEquals((await r3.handler(post(PHOTO))).status, 200);
  assertEquals(r3.rc.calls, 0);
});

Deno.test("refused requests are recorded; a failing record does not change the answer", async () => {
  const { handler, store } = setup({ sub: null, results: [okResult(GOOD_OUTPUT)] });
  await handler(post(PHOTO));
  await handler(post(PHOTO));
  await handler(post(TEXT));
  assertEquals(store.denials.map((d) => [d.mode, d.tier, d.reason]), [
    ["photo", "free", "free_scan_used"],
    ["text", "free", "subscription_required"],
  ]);

  const capped = new MemoryStore();
  capped.seed(USER, 12, { mode: "photo" });
  await setup({ store: capped }).handler(post(PHOTO));
  assertEquals(capped.denials.map((d) => [d.tier, d.reason]), [["premium", "daily_cap_reached"]]);

  const outage = new MemoryStore();
  outage.seed(USER, 1, { tier: "free" });
  await setup({ sub: new Error("RC down"), store: outage }).handler(post(PHOTO));
  assertEquals(outage.denials.map((d) => [d.tier, d.reason]), [[null, "entitlement_unavailable"]]);

  const broken = new MemoryStore();
  broken.seed(USER, 1, { tier: "free" });
  broken.insertDenial = () => Promise.reject(new Error("db down"));
  const r = setup({ sub: null, store: broken });
  const res = await call(r.handler, post(PHOTO));
  assertEquals([res.status, res.body.reason], [402, "free_scan_used"]);
  assert(r.logs.includes("denial_log_failed"));
});

Deno.test("store failure → 500 internal_error, logged", async () => {
  const store = new MemoryStore();
  store.getEntitlement = () => Promise.reject(new Error("db down"));
  const { handler, logs } = setup({ store });
  const r = await call(handler, post(PHOTO));
  assertEquals([r.status, r.body], [500, { error: "internal_error", retryable: true }]);
  assert(logs.includes("internal_error"));
});

Deno.test("usage-status: tier and remaining quota without a model call", async () => {
  const store = new MemoryStore();
  store.seed(USER, 3, { mode: "photo" });
  store.seed(USER, 2, { mode: "text" });
  const h = createStatusHandler({
    cfg: testConfig(), store, rc: rcReturning(ACTIVE_SUB),
    userIdFromJwt: (j) => Promise.resolve(j === "good" ? USER : null), now: () => T0,
  });
  const req = (jwt: string, method = "POST") =>
    new Request("http://x/", { method, headers: { Authorization: `Bearer ${jwt}` } });
  const r = await call(h, req("good"));
  assertEquals(r.status, 200);
  assertEquals(r.body.tier, "premium");
  assertEquals(r.body.photo, { limit: 12, used: 3, remaining: 9, resets_at: MIDNIGHT });
  assertEquals(r.body.text.remaining, 18);
  assertEquals((await h(req("bad"))).status, 401);
  assertEquals((await h(req("good", "DELETE"))).status, 405);

  const free = createStatusHandler({
    cfg: testConfig(), store: new MemoryStore(), rc: rcReturning(null),
    userIdFromJwt: () => Promise.resolve(USER), now: () => T0,
  });
  assertEquals((await call(free, req("good"))).body, {
    tier: "free", free_scan_available: true, timezone: null,
    photo: { limit: 1, used: 0, remaining: 1, resets_at: null },
    text: { limit: 0, used: 0, remaining: 0, resets_at: null },
  });

  const outage = createStatusHandler({
    cfg: testConfig(), store: new MemoryStore(), rc: rcReturning(new Error("down")),
    userIdFromJwt: () => Promise.resolve(USER), now: () => T0,
  });
  assertEquals((await call(outage, req("good"))).body, { error: "entitlement_unavailable", retryable: true });
});
