// db_test.ts — schema, RLS, grants, triggers and the revoke-views rule of supabase/migrations,
// run on PGlite (Postgres in WASM) with a Supabase stand-in (db_harness.ts).
import { assert, assertEquals } from "jsr:@std/assert@1";
import { asAnon, asUser, createUser, freshDb, pgErrorCode } from "./db_harness.ts";

// PGlite keeps a WASM instance alive between ops; the test sanitizers would flag it.
const opts = { sanitizeOps: false, sanitizeResources: false };
type Db = Awaited<ReturnType<typeof freshDb>>;

async function insertUsage(db: Db, userId: string, tier: "free" | "premium", status = "ok", extra = ""): Promise<number> {
  const { rows } = await db.query<{ id: number }>(
    `insert into public.ai_usage (user_id, mode, tier, status, model, cost_usd${extra ? ", created_at" : ""})
     values ($1, 'photo', $2, $3, 'gemini-test', 0.003${extra ? ", $4" : ""}) returning id`,
    extra ? [userId, tier, status, extra] : [userId, tier, status],
  );
  return rows[0].id;
}

Deno.test("profiles: owner reads and writes, others and anon see nothing", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const b = await createUser(db);
  await asUser(db, a, () =>
    db.query(`insert into public.profiles (id, locale, answers) values ($1, 'tr', '{"goal":"palette"}')`, [a]));
  const own = await asUser(db, a, () => db.query("select locale, answers from public.profiles"));
  assertEquals(own.rows, [{ locale: "tr", answers: { goal: "palette" } }]);
  assertEquals((await asUser(db, b, () => db.query("select * from public.profiles"))).rows.length, 0);
  assertEquals(
    await pgErrorCode(asUser(db, b, () => db.query(`insert into public.profiles (id) values ($1)`, [a]))),
    "42501",
  );
  assertEquals(await pgErrorCode(asAnon(db, () => db.query("select * from public.profiles"))), "42501");
  // answers must be an object; locale must look like a tag.
  assertEquals(
    await pgErrorCode(asUser(db, b, () => db.query(`insert into public.profiles (id, answers) values ($1, '[1]')`, [b]))),
    "23514",
  );
  assertEquals(
    await pgErrorCode(asUser(db, b, () => db.query(`insert into public.profiles (id, locale) values ($1, 'x')`, [b]))),
    "23514",
  );
});

Deno.test("profiles: the app's PostgREST upsert works; cap columns are server-only", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const upsert = (tz: string) =>
    asUser(db, a, () =>
      db.query(
        `insert into public.profiles (id, locale, timezone, consent_health_at) values ($1, 'tr', $2, now())
         on conflict (id) do update set id = excluded.id, locale = excluded.locale, timezone = excluded.timezone,
           consent_health_at = excluded.consent_health_at`,
        [a, tz],
      ));
  assertEquals(await pgErrorCode(upsert("Europe/Istanbul")), null);
  assertEquals(await pgErrorCode(upsert("Europe/Berlin")), null);
  for (const col of ["cap_timezone = 'Asia/Tokyo'", "cap_timezone_changed_at = now()"]) {
    assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`update public.profiles set ${col}`))), "42501", col);
  }
});

Deno.test("profiles: consent is stamped with server time and can be withdrawn", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const consent = () =>
    asUser(db, a, async () =>
      (await db.query<{ c: string | null }>(`select consent_health_at::text as c from public.profiles`)).rows[0].c);
  await asUser(db, a, () => db.query(`insert into public.profiles (id, consent_health_at) values ($1, '2001-01-01')`, [a]));
  const first = await consent();
  assert(first !== null && !first.startsWith("2001"));
  await asUser(db, a, () => db.query(`update public.profiles set consent_health_at = '2030-01-01'`));
  assertEquals(await consent(), first);
  await asUser(db, a, () => db.query(`update public.profiles set consent_health_at = null`));
  assertEquals(await consent(), null);
  await asUser(db, a, () => db.query(`update public.profiles set consent_health_at = now()`));
  assert((await consent()) !== null);
});

Deno.test("ai_usage: app reads whitelisted columns of its own rows only, never writes", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const b = await createUser(db);
  const id = await insertUsage(db, a, "premium");
  await insertUsage(db, b, "premium");
  const own = await asUser(db, a, () => db.query(`select id, status from public.ai_usage`));
  assertEquals(own.rows, [{ id, status: "ok" }]);
  assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`select cost_usd from public.ai_usage`))), "42501");
  assertEquals(
    await pgErrorCode(asUser(db, a, () =>
      db.query(`insert into public.ai_usage (user_id, mode, tier, status) values ($1, 'photo', 'premium', 'ok')`, [a]))),
    "42501",
  );
  assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`delete from public.ai_usage`))), "42501");
});

Deno.test("ai_usage: exactly one successful free analysis per user (partial unique index)", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  await insertUsage(db, a, "free", "not_applicable");     // failed attempts do not use the free analysis
  await insertUsage(db, a, "free", "invalid_output");
  await insertUsage(db, a, "free", "ok");
  assertEquals(await pgErrorCode(insertUsage(db, a, "free", "ok")), "23505");
  await insertUsage(db, a, "premium", "ok");
  await insertUsage(db, a, "premium", "ok");
  assertEquals(await pgErrorCode(insertUsage(db, a, "free", "not_food")), "23514");   // status is an enum
});

Deno.test("revoke-views rule: every view, the service tables and server functions are hidden from app roles", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  await db.query(`insert into public.entitlements (user_id, plan) values ($1, 'premium')`, [a]);
  const { rows: views } = await db.query<{ name: string }>(
    `select table_name as name from information_schema.views where table_schema = 'public' order by 1`,
  );
  assertEquals(views.map((v) => v.name), ["ai_cost_daily", "ai_denials_daily", "analytics_daily", "analytics_free_funnel"]);
  const hidden = [
    ...views.map((v) => `select * from public.${v.name}`),
    "select * from public.entitlements", "select * from public.ai_denials",
    "select * from public.revenue_events", "select * from public.attribution",
  ];
  for (const sql of hidden) {
    assertEquals(await pgErrorCode(asUser(db, a, () => db.query(sql))), "42501", sql);
    assertEquals(await pgErrorCode(asAnon(db, () => db.query(sql))), "42501", sql);
  }
  assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`select public.cap_day($1)`, [a]))), "42501");
  // Every view in public must have been revoked (a new view without its revoke fails here).
  const { rows: grants } = await db.query<{ table_name: string; grantee: string }>(
    `select table_name, grantee from information_schema.role_table_grants
     where table_schema = 'public' and grantee in ('anon', 'authenticated')
       and table_name in (select table_name from information_schema.views where table_schema = 'public')`,
  );
  assertEquals(grants, []);
});

Deno.test("analytics views: daily metrics, free funnel, cost and denials", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);   // free analysis, then paywall, then subscribes
  const b = await createUser(db);   // free analysis only
  const ins = (u: string, tier: string, status: string, mode = "photo", cost = 0.002, at = "2026-09-24 10:00:00+00") =>
    db.query(
      `insert into public.ai_usage (user_id, mode, tier, status, cost_usd, model, created_at) values ($1, $2, $3, $4, $5, 'm', $6)`,
      [u, mode, tier, status, cost, at],
    );
  await ins(a, "free", "ok");
  await ins(b, "free", "ok");
  await ins(b, "free", "not_applicable");
  await ins(a, "premium", "provider_error", "photo", 0, "2026-09-25 09:00:00+00");
  await ins(a, "premium", "ok", "text", 0.001, "2026-09-25 09:01:00+00");
  await db.query(
    `insert into public.ai_denials (user_id, mode, tier, reason, created_at) values
       ($1, 'photo', 'free', 'free_scan_used', '2026-09-24 11:00:00+00'),
       ($1, 'text',  'free', 'subscription_required', '2026-09-24 11:05:00+00'),
       ($1, 'photo', null, 'consent_required', '2026-09-24 11:06:00+00')`,
    [a],
  );
  const { rows } = await db.query<Record<string, unknown>>(
    `select day::text, active_users, photo_analyses, text_analyses, free_analyses, not_applicable, failed_calls,
            paywall_402, paywall_402_users, consent_403, cost_usd::float, cost_per_active_user_usd::float
     from public.analytics_daily order by day`,
  );
  assertEquals(rows, [
    { day: "2026-09-24", active_users: 2, photo_analyses: 2, text_analyses: 0, free_analyses: 2, not_applicable: 1,
      failed_calls: 0, paywall_402: 2, paywall_402_users: 1, consent_403: 1, cost_usd: 0.006, cost_per_active_user_usd: 0.003 },
    { day: "2026-09-25", active_users: 1, photo_analyses: 0, text_analyses: 1, free_analyses: 0, not_applicable: 0,
      failed_calls: 1, paywall_402: 0, paywall_402_users: 0, consent_403: 0, cost_usd: 0.001, cost_per_active_user_usd: 0.001 },
  ]);
  const funnel = await db.query(`select cohort_day::text, free_users, hit_paywall_users, subscribed_users from public.analytics_free_funnel`);
  assertEquals(funnel.rows, [{ cohort_day: "2026-09-24", free_users: 2, hit_paywall_users: 1, subscribed_users: 1 }]);
  const cost = await db.query(
    `select day::text, mode, calls, ok_calls, cost_usd::float, cost_per_ok_call_usd::float from public.ai_cost_daily order by day, mode`,
  );
  assertEquals(cost.rows[0], { day: "2026-09-24", mode: "photo", calls: 3, ok_calls: 2, cost_usd: 0.006, cost_per_ok_call_usd: 0.003 });
  const denials = await db.query(`select reason, denials from public.ai_denials_daily order by reason`);
  assertEquals(denials.rows.map((r: any) => r.reason), ["consent_required", "free_scan_used", "subscription_required"]);
});

Deno.test("events: the app inserts its own events only; revenue feed is service/adops only", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const b = await createUser(db);
  await asUser(db, a, () => db.query(`insert into public.events (name, props) values ('paywall_view', '{"from":"onboarding"}')`));
  assertEquals(
    await pgErrorCode(asUser(db, a, () => db.query(`insert into public.events (user_id, name) values ($1, 'x')`, [b]))),
    "42501",
  );
  assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`select * from public.events`))), "42501");
  await db.query(
    `insert into public.revenue_events (id, app, user_id, type, ts) values ('e1', 'app', $1, 'INITIAL_PURCHASE', now())`,
    [a],
  );
  await db.exec(`set role adops_ro;`);
  try {
    const { rows } = await db.query(`select id from public.revenue_events`);
    assertEquals(rows, [{ id: "e1" }]);
  } finally {
    await db.exec(`reset role;`);
  }
});

Deno.test("deleting the auth user removes every row", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  await insertUsage(db, a, "free");
  await asUser(db, a, async () => {
    await db.query(`insert into public.profiles (id) values ($1)`, [a]);
    await db.query(`insert into public.events (name) values ('x')`);
  });
  await db.query(`insert into public.entitlements (user_id) values ($1)`, [a]);
  await db.query(`insert into public.ai_denials (user_id, mode, reason) values ($1, 'photo', 'free_scan_used')`, [a]);
  await db.query(`delete from auth.users where id = $1`, [a]);
  for (const t of ["profiles", "ai_usage", "entitlements", "ai_denials", "events"]) {
    const { rows } = await db.query<{ n: number }>(`select count(*)::int as n from public.${t}`);
    assertEquals(rows[0].n, 0, t);
  }
});
