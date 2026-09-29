// usage-status — the caller's tier and remaining analyses, for the home-screen counter and for
// deciding up front whether the capture button opens the camera or the paywall. No model call.
import type { Config } from "../_shared/config.ts";
import { resolveEntitlement } from "../_shared/entitlement.ts";
import { bearer, json } from "../_shared/http.ts";
import type { RcLookup } from "../_shared/rc.ts";
import type { Store } from "../_shared/store.ts";
import { usageSummary } from "../_shared/usage.ts";

export interface Deps {
  cfg: Config;
  store: Store;
  rc: RcLookup;
  userIdFromJwt: (jwt: string) => Promise<string | null>;
  now: () => number;
}

export function createHandler(deps: Deps): (req: Request) => Promise<Response> {
  const { cfg, store, rc, now } = deps;
  return async (req) => {
    if (req.method !== "POST" && req.method !== "GET") return json({ error: "method_not_allowed" }, 405);
    const jwt = bearer(req);
    const userId = jwt ? await deps.userIdFromJwt(jwt) : null;
    if (!userId) return json({ error: "unauthorized" }, 401);
    try {
      const ent = await resolveEntitlement(store, rc, userId, now(), cfg.entitlementGraceMs);
      if (ent.tier === "unknown") return json({ error: "entitlement_unavailable", retryable: true }, 503);
      return json(await usageSummary(store, cfg, userId, ent.tier === "premium"));
    } catch (e) {
      console.log(JSON.stringify({ fn: "usage-status", msg: "internal_error", userId, error: (e as Error).message }));
      return json({ error: "internal_error", retryable: true }, 500);
    }
  };
}
