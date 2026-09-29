// delete-account — in-app "Delete account" (App Review guideline 5.1.1(v)).
// Deletes the caller's auth user; every app table cascades from auth.users, so one call removes
// profile, app data, usage and the entitlement cache. The App Store subscription itself is
// managed by Apple: the app must tell the user to cancel it in Settings (we cannot).
import { bearer, json } from "../_shared/http.ts";

export interface Deps {
  userIdFromJwt: (jwt: string) => Promise<string | null>;
  deleteUser: (userId: string) => Promise<void>;
}

export function createHandler(deps: Deps): (req: Request) => Promise<Response> {
  return async (req) => {
    if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    const jwt = bearer(req);
    const userId = jwt ? await deps.userIdFromJwt(jwt) : null;
    if (!userId) return json({ error: "unauthorized" }, 401);

    // Explicit confirmation in the body so a stray request cannot wipe an account.
    let body: Record<string, unknown> = {};
    try {
      body = await req.json();
    } catch { /* handled below */ }
    if (body?.confirm !== "DELETE") {
      return json({ error: "invalid_request", message: 'send {"confirm":"DELETE"}' }, 400);
    }

    try {
      await deps.deleteUser(userId);
    } catch (e) {
      console.log(JSON.stringify({ fn: "delete-account", msg: "delete_failed", userId, error: (e as Error).message }));
      return json({ error: "internal_error", retryable: true }, 500);
    }
    console.log(JSON.stringify({ fn: "delete-account", msg: "deleted", userId }));
    return json({ deleted: true });
  };
}
