// legal entry point. Public (verify_jwt = false in config.toml).
import { LEGAL } from "./content.gen.ts";
import { createHandler } from "./handler.ts";

const base = `${Deno.env.get("SUPABASE_URL") ?? ""}/functions/v1/legal`;
Deno.serve(createHandler(LEGAL, base));
