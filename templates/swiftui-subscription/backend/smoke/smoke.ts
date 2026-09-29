// smoke.ts — end-to-end check of the deployed functions as a brand-new anonymous user.
// PAID: exactly one model call (the free photo analysis). Everything else must be refused before
// the model is called, which this script also verifies through ai_usage. Run it only with the
// lead's go, after backend_deploy.
//
//   APP_URL=https://<ref>.supabase.co APP_ANON_KEY=… APP_SERVICE_KEY=… [REQUIRE_CONSENT=true] \
//     deno run --allow-net --allow-env --allow-read backend/smoke/smoke.ts <image.jpg>
import { encodeBase64 } from "jsr:@std/encoding@1/base64";

const URL_ = Deno.env.get("APP_URL")!;
const ANON = Deno.env.get("APP_ANON_KEY")!;
const SERVICE = Deno.env.get("APP_SERVICE_KEY")!;
const CONSENT = (Deno.env.get("REQUIRE_CONSENT") ?? "").toLowerCase() === "true";
const image = Deno.args[0];
if (!URL_ || !ANON || !SERVICE || !image) throw new Error("set APP_URL, APP_ANON_KEY, APP_SERVICE_KEY and pass an image");

let failures = 0;
function check(name: string, ok: boolean, detail: unknown = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : " → " + JSON.stringify(detail).slice(0, 400)}`);
  if (!ok) failures++;
}

async function fn(name: string, token: string | null, body?: unknown) {
  const res = await fetch(`${URL_}/functions/v1/${name}`, {
    method: "POST",
    headers: { apikey: ANON, "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json: any = null;
  try {
    json = JSON.parse(text);
  } catch { /* gateway errors may be plain text */ }
  return { status: res.status, json, text };
}

// 1. Anonymous sign-in, as the app does on first launch.
const signup = await fetch(`${URL_}/auth/v1/signup`, {
  method: "POST", headers: { apikey: ANON, "Content-Type": "application/json" }, body: "{}",
});
const session = await signup.json();
check("anonymous sign-in", signup.ok && !!session.access_token, session.error ?? signup.status);
const token: string = session.access_token;
const userId: string = session.user?.id;

// 2. Consent (only when the app requires it), then the profile with a timezone.
if (CONSENT) {
  const noConsent = await fn("analyze", token, { mode: "text", text: "hello" });
  check("no consent → 403 consent_required", noConsent.status === 403 && noConsent.json?.error === "consent_required", noConsent.text);
}
const prof = await fetch(`${URL_}/rest/v1/profiles`, {
  method: "POST",
  headers: {
    apikey: ANON, Authorization: `Bearer ${token}`, "Content-Type": "application/json",
    Prefer: "resolution=merge-duplicates",
  },
  body: JSON.stringify({ id: userId, locale: "tr", timezone: "Europe/Istanbul", consent_health_at: new Date().toISOString() }),
});
check("profile upsert", prof.ok, prof.status);
await prof.body?.cancel();

// 3. No token → 401.
check("no JWT → 401", (await fn("analyze", null, { mode: "text", text: "hello" })).status === 401);

// 4. usage-status. RevenueCat not configured → 503 entitlement_unavailable is expected.
const status = await fn("usage-status", token);
console.log(`     usage-status → ${status.status} ${status.text.slice(0, 200)}`);
const rcConfigured = status.status !== 503;

// 5. The free photo analysis (the one paid call).
const photo = { mode: "photo", image: { data: encodeBase64(await Deno.readFile(image)) }, locale: "tr-TR" };
const t0 = Date.now();
const first = await fn("analyze", token, photo);
check("free photo analysis → 200 (or 422 not_applicable)", first.status === 200 || first.status === 422, first.text);
if (first.status === 200) {
  check("result shape", typeof first.json.analysis_id === "number" && typeof first.json.result === "object", first.json);
  check("locale honoured (tr)", first.json.locale === "tr", first.json.locale);
  check("free analysis consumed", first.json.usage?.tier === "free" && first.json.usage?.free_scan_available === false, first.json.usage);
  console.log(`     ${Date.now() - t0} ms · ${JSON.stringify(first.json.result).slice(0, 200)}`);
}

// 6. Second photo and a text → refused before the model.
const second = await fn("analyze", token, photo);
const text = await fn("analyze", token, { mode: "text", text: "a red door" });
if (rcConfigured) {
  check("second photo → 402 free_scan_used", second.status === 402 && second.json?.reason === "free_scan_used", second.text);
  check("text as free user → 402 subscription_required", text.status === 402 && text.json?.reason === "subscription_required", text.text);
} else {
  check("second photo → 503 entitlement_unavailable", second.status === 503, second.text);
  check("text → 503 entitlement_unavailable", text.status === 503, text.text);
}

// 7. Server-side record: exactly one billed call, with the real fal charge.
const rows = await (await fetch(
  `${URL_}/rest/v1/ai_usage?user_id=eq.${userId}&select=status,tier,mode,model,input_tokens,output_tokens,cost_usd,latency_ms`,
  { headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}` } },
)).json();
check("one ai_usage row", Array.isArray(rows) && rows.length === 1, rows);
if (Array.isArray(rows)) for (const r of rows) console.log(`     ai_usage: ${JSON.stringify(r)}`);

// 8. The cap day follows the profile timezone (Istanbul midnight in UTC is 21:00); unknown zone → 400.
const day = await (await fetch(`${URL_}/rest/v1/rpc/cap_day`, {
  method: "POST",
  headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, "Content-Type": "application/json" },
  body: JSON.stringify({ p_user: userId }),
})).json();
check("cap_day in Europe/Istanbul", day?.[0]?.timezone === "Europe/Istanbul" && String(day?.[0]?.resets_at).includes("T21:00:00"), day);
const badTz = await fetch(`${URL_}/rest/v1/profiles?id=eq.${userId}`, {
  method: "PATCH",
  headers: { apikey: ANON, Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({ timezone: "Mars/Olympus" }),
});
check("unknown timezone → 400", badTz.status === 400, badTz.status);
await badTz.body?.cancel();

// 9. RLS from the app's side: own row visible, cost hidden.
const own = await fetch(`${URL_}/rest/v1/ai_usage?select=id,status`, { headers: { apikey: ANON, Authorization: `Bearer ${token}` } });
check("app reads own ai_usage", own.ok && (await own.json()).length === 1);
const cost = await fetch(`${URL_}/rest/v1/ai_usage?select=cost_usd`, { headers: { apikey: ANON, Authorization: `Bearer ${token}` } });
check("app cannot read cost_usd", !cost.ok, cost.status);
await cost.body?.cancel();

// 10. Legal pages are public.
for (const doc of ["privacy", "terms"]) {
  const r = await fetch(`${URL_}/functions/v1/legal/${doc}?lang=en`);
  check(`legal/${doc} → 200 text/plain`, r.status === 200 && (r.headers.get("Content-Type") ?? "").startsWith("text/plain"), r.status);
  await r.body?.cancel();
}

// 11. Delete the account through the app's own endpoint (cascades to every table).
check("delete-account without confirm → 400", (await fn("delete-account", token, {})).status === 400);
const del = await fn("delete-account", token, { confirm: "DELETE" });
check("delete-account → 200", del.status === 200 && del.json?.deleted === true, del.text);

console.log(failures === 0 ? "SMOKE OK" : `SMOKE FAILED (${failures})`);
Deno.exit(failures === 0 ? 0 : 1);
