// delete-account entry point: real dependencies → handler.ts.
import { createClient } from "jsr:@supabase/supabase-js@2";
import { createHandler } from "./handler.ts";

const supa = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false, autoRefreshToken: false },
});

Deno.serve(createHandler({
  userIdFromJwt: async (jwt) => {
    const { data, error } = await supa.auth.getUser(jwt);
    return error ? null : data.user?.id ?? null;
  },
  deleteUser: async (userId) => {
    const { error } = await supa.auth.admin.deleteUser(userId);
    if (error) throw new Error(error.message);
  },
}));
