// db_harness.ts — runs the real migrations on an in-process Postgres (PGlite, Postgres 17 WASM)
// with a minimal stand-in for what Supabase provides: the auth schema, auth.uid(), the
// anon/authenticated/service_role roles and Supabase's default grants on the public schema.
// That makes RLS, column grants, triggers and constraints testable without Docker or a project.
import { PGlite } from "npm:@electric-sql/pglite@0.3";

const MIGRATIONS_DIR = new URL("../migrations/", import.meta.url);

const SUPABASE_STUB = `
  create role anon nologin;
  create role authenticated nologin;
  create role service_role nologin bypassrls;
  create schema auth;
  create table auth.users (id uuid primary key);
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
  $$;
  grant usage on schema auth to anon, authenticated, service_role;
  grant execute on function auth.uid() to anon, authenticated, service_role;
  grant usage on schema public to anon, authenticated, service_role;
  -- Supabase grants everything in public to the API roles by default; RLS and the
  -- migrations' own revokes are what actually protect the tables.
  alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
  alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
  alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;
`;

export async function freshDb(): Promise<PGlite> {
  const db = new PGlite();
  await db.exec(SUPABASE_STUB);
  const files: string[] = [];
  for await (const e of Deno.readDir(MIGRATIONS_DIR)) {
    if (e.isFile && e.name.endsWith(".sql")) files.push(e.name);
  }
  files.sort();
  for (const f of files) {
    await db.exec(await Deno.readTextFile(new URL(f, MIGRATIONS_DIR)));
  }
  return db;
}

export async function createUser(db: PGlite): Promise<string> {
  const { rows } = await db.query<{ id: string }>(
    "insert into auth.users (id) values (gen_random_uuid()) returning id",
  );
  return rows[0].id;
}

/** Run `fn` as the PostgREST `authenticated` role with the given JWT subject. */
export async function asUser<T>(db: PGlite, userId: string, fn: () => Promise<T>): Promise<T> {
  await db.exec(`set role authenticated; select set_config('request.jwt.claim.sub', '${userId}', false);`);
  try {
    return await fn();
  } finally {
    await db.exec(`reset role; select set_config('request.jwt.claim.sub', '', false);`);
  }
}

export async function asAnon<T>(db: PGlite, fn: () => Promise<T>): Promise<T> {
  await db.exec(`set role anon;`);
  try {
    return await fn();
  } finally {
    await db.exec(`reset role;`);
  }
}

/** Resolves to the Postgres error code (e.g. 42501, 23505) or null if the query succeeded. */
export async function pgErrorCode(p: Promise<unknown>): Promise<string | null> {
  try {
    await p;
    return null;
  } catch (e) {
    return (e as { code?: string }).code ?? "unknown";
  }
}
