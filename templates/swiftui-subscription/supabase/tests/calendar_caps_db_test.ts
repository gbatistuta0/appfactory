// calendar_caps_db_test.ts — migration 0004: cap_day() and its timezone guard.
import { assert, assertEquals } from "jsr:@std/assert@1";
import { asUser, createUser, freshDb, pgErrorCode } from "./db_harness.ts";

const opts = { sanitizeOps: false, sanitizeResources: false };
type Db = Awaited<ReturnType<typeof freshDb>>;

async function capDay(db: Db, u: string) {
  const { rows } = await db.query<{ timezone: string; local_start: string; hours: number; contains_now: boolean }>(
    `select timezone,
            (day_start at time zone timezone)::text as local_start,
            extract(epoch from resets_at - day_start)::int / 3600 as hours,
            now() >= day_start and now() < resets_at as contains_now
     from public.cap_day($1)`,
    [u],
  );
  return rows[0];
}
const setTz = (db: Db, u: string, tz: string) =>
  asUser(db, u, () => db.query(`update public.profiles set timezone = $1`, [tz]));

Deno.test("cap_day: local midnight of the cap timezone; UTC without a profile", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  const none = await capDay(db, a);
  assertEquals(none.timezone, "UTC");
  assert(none.local_start.endsWith("00:00:00") && none.contains_now);

  await asUser(db, a, () => db.query(`insert into public.profiles (id, timezone) values ($1, 'Europe/Istanbul')`, [a]));
  const ist = await capDay(db, a);
  assertEquals(ist.timezone, "Europe/Istanbul");
  assert(ist.local_start.endsWith("00:00:00"), ist.local_start);   // midnight in Istanbul
  assert(ist.contains_now);
  assert(ist.hours >= 23 && ist.hours <= 25);                       // DST days are 23/25 h
});

Deno.test("cap_day: a timezone change is honoured at most once per 24 h", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  await asUser(db, a, () => db.query(`insert into public.profiles (id, timezone) values ($1, 'Europe/Istanbul')`, [a]));
  assertEquals((await capDay(db, a)).timezone, "Europe/Istanbul");   // first setting is not a change

  await setTz(db, a, "America/New_York");
  assertEquals((await capDay(db, a)).timezone, "America/New_York");  // first change: honoured

  await setTz(db, a, "Asia/Tokyo");
  assertEquals((await capDay(db, a)).timezone, "America/New_York");  // within 24 h: previous kept

  // 24 h later the pending change is adopted.
  await db.query(`update public.profiles set cap_timezone_changed_at = now() - interval '25 hours' where id = $1`, [a]);
  assertEquals((await capDay(db, a)).timezone, "Asia/Tokyo");
});

Deno.test("profiles: unknown timezones are rejected; cap columns are server-only", opts, async () => {
  const db = await freshDb();
  const a = await createUser(db);
  assertEquals(
    await pgErrorCode(asUser(db, a, () =>
      db.query(`insert into public.profiles (id, timezone) values ($1, 'Mars/Olympus')`, [a]))),
    "22023",
  );
  await asUser(db, a, () => db.query(`insert into public.profiles (id, timezone) values ($1, 'UTC')`, [a]));
  for (const col of ["cap_timezone = 'Asia/Tokyo'", "cap_timezone_changed_at = now()"]) {
    assertEquals(await pgErrorCode(asUser(db, a, () => db.query(`update public.profiles set ${col}`))), "42501", col);
  }
  assertEquals(
    await pgErrorCode(asUser(db, a, () => db.query(`select public.cap_day($1)`, [a]))),
    "42501",
  );
});

