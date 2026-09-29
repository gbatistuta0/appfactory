// RC webhook → revenue_events (idempotent). Protected by a shared-secret header.
import { createClient } from "jsr:@supabase/supabase-js@2";
import { mapEvent } from "./map.ts";

const APP = Deno.env.get("APP_SLUG")!; // filled in by inject_config
const SECRET = Deno.env.get("RC_WEBHOOK_SECRET")!; // RC dashboard Authorization header

Deno.serve(async (req) => {
  if (req.headers.get("authorization") !== SECRET) return new Response("unauthorized", { status: 401 });
  const body = await req.json();
  const ev = body.event;
  if (!ev?.id) return new Response("no event", { status: 400 });
  const row = mapEvent(ev, APP);
  const supa = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { error } = await supa.from("revenue_events").upsert(row, { onConflict: "id", ignoreDuplicates: true });
  if (error) return new Response(error.message, { status: 500 });
  return new Response("ok");
});
