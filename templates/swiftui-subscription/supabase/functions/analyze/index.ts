// analyze entry point: wires the real dependencies (service-role Supabase client, fal.ai,
// RevenueCat) into the handler. All logic and tests live in handler.ts.
import { createClient } from "jsr:@supabase/supabase-js@2";
import { loadConfig } from "../_shared/config.ts";
import { falClient } from "../_shared/llm.ts";
import { revenueCatLookup } from "../_shared/rc.ts";
import { supabaseStore } from "../_shared/store.ts";
import { createHandler } from "./handler.ts";

const cfg = loadConfig();
const supa = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false, autoRefreshToken: false },
});

Deno.serve(createHandler({
  cfg,
  store: supabaseStore(supa),
  llm: falClient(cfg.falKey),
  rc: revenueCatLookup(cfg.rcProjectId, cfg.rcSecretKey),
  userIdFromJwt: async (jwt) => {
    const { data, error } = await supa.auth.getUser(jwt);
    return error ? null : data.user?.id ?? null;
  },
  now: () => Date.now(),
}));
