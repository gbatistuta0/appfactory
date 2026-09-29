"""revenuecat_setup — RevenueCat v2 REST setup client (live, httpx). LEGACY (credits mode).

Subscription-mode apps use store_setup (spec-driven: products, entitlement, offerings, packages,
targeting-rule placements; per-app ids recorded in <app>/.appfactory/outputs.json, never in the
global config — only rc_secret_key is global).

Automates the RC API setup done manually in this session:
create/find entitlement (premium) → attach 4 subscriptions → read SDK key →
write Supabase secret. The human only opens the RC project + links ASC + provides the v2 key.

The v2 key is PROJECT-SCOPED (v1 endpoints return 403, v2 only).
Recipe (proven): GET /v2/projects → apps → public_api_keys → products
→ entitlements (idempotent) → actions/attach_products (NOT /products = 405).
Docs: https://www.revenuecat.com/docs/api-v2
"""

from __future__ import annotations

from typing import Any

import httpx

from . import supabase as supa_mod

RC_BASE = "https://api.revenuecat.com/v2"

# The 4 expected subscription store_identifier suffixes for a bundle.
_SUB_SUFFIXES = ("weekly", "yearly", "weekly.offer", "yearly.offer")


def _request(
    method: str,
    path: str,
    v2_key: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """RC v2 call; structured result ({ok, status, data|error})."""
    url = path if path.startswith("http") else f"{RC_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {v2_key}",
        "Content-Type": "application/json",
    }
    try:
        r = httpx.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
    except httpx.HTTPError as e:
        return {"ok": False, "status": 0, "error": f"network error: {e}"}
    out: dict[str, Any] = {"ok": r.is_success, "status": r.status_code}
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"raw": r.text[:500]}
    out["data" if r.is_success else "error"] = body
    return out


def revenuecat_setup(
    v2_key: str,
    bundle_id: str,
    supabase_ref: str,
    env_suffix: str = "",
    set_secrets: bool = True,
    suffixes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Set up the RC project idempotently and (optionally) write the Supabase secret.

    On success: {ok:True, project_id, app_id, sdk_key, entitlement_id,
    attached_products:[...], secrets_set:[...]}. On error: {ok:False, step, detail}.
    Preflight (no project / 401): step="preflight", detail="NEEDS_HUMAN: ...".
    """
    # --- Step 1: project_id (preflight) ---
    r = _request("GET", "/projects", v2_key)
    items = (r.get("data") or {}).get("items") if r.get("ok") else None
    if r.get("status") in (401, 403) or not items:
        return {"ok": False, "step": "preflight",
                "detail": "NEEDS_HUMAN: open RC project + link ASC + v2 key"}
    project_id = items[0].get("id")
    if not project_id:
        return {"ok": False, "step": "preflight",
                "detail": "NEEDS_HUMAN: open RC project + link ASC + v2 key"}

    # --- Step 2: app_store app (verify the bundle match) ---
    r = _request("GET", f"/projects/{project_id}/apps", v2_key)
    if not r.get("ok"):
        return {"ok": False, "step": "apps", "detail": r.get("error")}
    app_id = None
    for app in (r.get("data") or {}).get("items", []):
        if app.get("type") == "app_store":
            app_id = app.get("id")
            app_bundle = (app.get("app_store") or {}).get("bundle_id")
            if app_bundle and app_bundle != bundle_id:
                return {"ok": False, "step": "apps",
                        "detail": f"bundle mismatch: RC={app_bundle} != arg={bundle_id}"}
            break
    if not app_id:
        return {"ok": False, "step": "apps", "detail": "no app of type app_store"}

    # --- Step 3: SDK key (appl_…) ---
    r = _request("GET", f"/projects/{project_id}/apps/{app_id}/public_api_keys", v2_key)
    if not r.get("ok"):
        return {"ok": False, "step": "sdk_key", "detail": r.get("error")}
    keys = (r.get("data") or {}).get("items", [])
    if not keys:
        return {"ok": False, "step": "sdk_key", "detail": "public_api_keys is empty"}
    sdk_key = keys[0].get("key")

    # --- Step 4: collect the uuids of the 4 subscriptions ---
    r = _request("GET", f"/projects/{project_id}/products", v2_key, params={"limit": 100})
    if not r.get("ok"):
        return {"ok": False, "step": "products", "detail": r.get("error")}
    sufs = tuple(suffixes) if suffixes else _SUB_SUFFIXES  # spec: tuple(p["suffix"] for p in spec products)
    wanted = {f"{bundle_id}.{suf}": None for suf in sufs}
    for prod in (r.get("data") or {}).get("items", []):
        sid = prod.get("store_identifier")
        if sid in wanted:
            wanted[sid] = prod.get("id")
    sub_uuids = [uid for uid in wanted.values() if uid]
    if len(sub_uuids) != len(sufs):
        missing = [sid for sid, uid in wanted.items() if not uid]
        return {"ok": False, "step": "products", "detail": f"missing subscription(s): {missing}"}

    # --- Step 5: entitlement (premium) — idempotent ---
    r = _request("GET", f"/projects/{project_id}/entitlements", v2_key)
    if not r.get("ok"):
        return {"ok": False, "step": "entitlements", "detail": r.get("error")}
    entitlement_id = None
    for ent in (r.get("data") or {}).get("items", []):
        if ent.get("lookup_key") == "premium":
            entitlement_id = ent.get("id")
            break
    if not entitlement_id:
        r = _request("POST", f"/projects/{project_id}/entitlements", v2_key,
                     json={"lookup_key": "premium", "display_name": "Premium"})
        if not r.get("ok"):
            return {"ok": False, "step": "entitlements", "detail": r.get("error")}
        entitlement_id = (r.get("data") or {}).get("id")
    if not entitlement_id:
        return {"ok": False, "step": "entitlements", "detail": "could not get entitlement id"}

    # --- Step 6: attach (idempotent, actions/attach_products — /products 405 verir) ---
    r = _request("POST",
                 f"/projects/{project_id}/entitlements/{entitlement_id}/actions/attach_products",
                 v2_key, json={"product_ids": sub_uuids})
    if not r.get("ok"):
        return {"ok": False, "step": "attach", "detail": r.get("error")}

    # --- Step 7: Supabase secret (opsiyonel) ---
    secrets_set: list[str] = []
    if set_secrets:
        pid_name = f"RC_PROJECT_ID{env_suffix}"
        key_name = f"RC_SECRET_KEY{env_suffix}"
        try:
            cl = supa_mod.SupabaseClient()
            sr = cl.set_secrets(supabase_ref, {pid_name: project_id, key_name: v2_key})
        except supa_mod.SupabaseError as e:
            return {"ok": False, "step": "secrets", "detail": str(e)}
        if not sr.get("ok"):
            return {"ok": False, "step": "secrets", "detail": sr.get("error")}
        secrets_set = [pid_name, key_name]

    return {
        "ok": True,
        "project_id": project_id,
        "app_id": app_id,
        "sdk_key": sdk_key,
        "entitlement_id": entitlement_id,
        "attached_products": sub_uuids,
        "secrets_set": secrets_set,
    }
