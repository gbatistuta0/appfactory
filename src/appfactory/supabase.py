"""supabase_* — Supabase Management API client (live).

Backend: list/create projects, get anon url+key, run SQL/schema, write secrets
(for ai-proxy), deploy edge functions. AI keys only go to secrets.
Docs: https://supabase.com/docs/reference/api
"""

from __future__ import annotations

from typing import Any

import httpx

from . import config as cfg

MGMT_BASE = "https://api.supabase.com"


class SupabaseError(Exception):
    pass


class SupabaseClient:
    def __init__(self, timeout: float = 40.0):
        c = cfg.load_config()
        self.token = c.get("supabase_access_token")
        if not self.token:
            raise SupabaseError("supabase_access_token missing (set it via config_set)")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def request(self, method: str, path: str, *, json: Any = None) -> dict[str, Any]:
        url = f"{MGMT_BASE}{path}"
        try:
            r = httpx.request(method, url, headers=self._headers(), json=json, timeout=self._timeout)
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"network error: {e}"}
        out: dict[str, Any] = {"ok": r.is_success, "status": r.status_code}
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = {"raw": r.text[:500]}
        out["data" if r.is_success else "error"] = body
        return out

    # ---- reads ----
    def list_projects(self) -> dict[str, Any]:
        return self.request("GET", "/v1/projects")

    def list_organizations(self) -> dict[str, Any]:
        return self.request("GET", "/v1/organizations")

    def get_keys(self, ref: str) -> dict[str, Any]:
        """Get anon + service_role keys (reveal=true). anon → app; service → server."""
        r = self.request("GET", f"/v1/projects/{ref}/api-keys?reveal=true")
        if not r.get("ok"):
            return r
        data = r.get("data", [])
        keys = {k.get("name"): (k.get("api_key") or k.get("secret")) for k in data if isinstance(k, dict)}
        return {
            "ok": True,
            "project_url": f"https://{ref}.supabase.co",
            "anon_key": keys.get("anon") or keys.get("publishable"),
            "service_role_key": keys.get("service_role") or keys.get("secret"),
            "raw_key_names": [k.get("name") for k in data if isinstance(k, dict)],
        }

    # ---- writes ----
    def create_project(self, name: str, org_id: str, region: str, db_pass: str) -> dict[str, Any]:
        return self.request("POST", "/v1/projects", json={
            "name": name, "organization_id": org_id, "region": region,
            "db_pass": db_pass, "plan": "free",
        })

    def run_sql(self, ref: str, sql: str) -> dict[str, Any]:
        """Run SQL on the project (schema/migration)."""
        return self.request("POST", f"/v1/projects/{ref}/database/query", json={"query": sql})

    def set_secrets(self, ref: str, secrets: dict[str, str]) -> dict[str, Any]:
        """Write edge function secrets (FAL_KEY etc. — server-side, never enters the app)."""
        payload = [{"name": k, "value": v} for k, v in secrets.items()]
        return self.request("POST", f"/v1/projects/{ref}/secrets", json=payload)

    def enable_anonymous_auth(self, ref: str) -> dict[str, Any]:
        """Enable anonymous sign-in (the ai-proxy app JWT relies on this). Automatic."""
        return self.request("PATCH", f"/v1/projects/{ref}/config/auth",
                            json={"external_anonymous_users_enabled": True})

    def get_auth_config(self, ref: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/projects/{ref}/config/auth")

    def update_auth_config(self, ref: str, body: dict[str, Any]) -> dict[str, Any]:
        """PATCH the project's auth config (anonymous sign-ins, Apple provider, manual linking)."""
        return self.request("PATCH", f"/v1/projects/{ref}/config/auth", json=body)

    def list_secrets(self, ref: str) -> dict[str, Any]:
        """Secret NAMES (the API returns digests, not values)."""
        return self.request("GET", f"/v1/projects/{ref}/secrets")


# ---------------------------------------------------------------------------------------------
# Backend template: mode selection, rendering from app.spec.json, secrets and auth config.
# ---------------------------------------------------------------------------------------------
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

# Edge functions per monetization mode. `public` ones deploy with --no-verify-jwt.
FUNCTION_SETS: dict[str, list[str]] = {
    "subscription": ["analyze", "usage-status", "delete-account", "legal", "rc-webhook"],
    "credits": ["ai-proxy", "legal", "rc-webhook"],
}
PUBLIC_FUNCTIONS = {"legal", "rc-webhook"}
# Functions that exist only for the AI edge (spec.ai.enabled=false drops them from deploy + gates).
AI_FUNCTIONS = {"analyze", "ai-proxy"}
# Template paths that exist only for one mode (relative to supabase/).
_MODE_ONLY: dict[str, list[str]] = {
    "subscription": ["functions/analyze", "functions/usage-status", "functions/delete-account",
                     "functions/_shared/analysis.ts", "functions/_shared/config.ts",
                     "functions/_shared/entitlement.ts", "functions/_shared/usage.ts",
                     "functions/_shared/store.ts", "functions/_shared/rc.ts", "functions/_shared/llm.ts",
                     "tests/analyze_test.ts", "tests/db_test.ts", "tests/calendar_caps_db_test.ts",
                     "tests/shared_test.ts", "tests/delete_account_test.ts", "tests/fakes.ts"],
    "credits": ["functions/ai-proxy", "functions/_shared/credits.ts", "functions/_shared/credits_rc.ts"],
}


def mode_of(spec: dict[str, Any]) -> str:
    return spec.get("monetization") or "subscription"


def apply_backend_mode(app_dir: str | _Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Prune the scaffolded supabase/ tree to the spec's monetization mode (idempotent).

    subscription: drop the credits-only functions and migrations_credits/.
    credits:      drop the subscription-only functions/tests; migrations_credits/ becomes migrations/.
    Call once right after app_scaffold (the scaffold copies both modes).
    """
    sb = _Path(app_dir).expanduser() / "supabase"
    if not sb.exists():
        return {"ok": False, "error": f"supabase/ not found in {app_dir}"}
    mode = mode_of(spec)
    other = "credits" if mode == "subscription" else "subscription"
    removed = []
    for rel in _MODE_ONLY[other]:
        p = sb / rel
        if p.is_dir():
            _shutil.rmtree(p)
            removed.append(rel)
        elif p.exists():
            p.unlink()
            removed.append(rel)
    creds = sb / "migrations_credits"
    if creds.exists():
        if mode == "credits":
            _shutil.rmtree(sb / "migrations", ignore_errors=True)
            creds.rename(sb / "migrations")
            removed.append("migrations (subscription) → replaced by migrations_credits")
        else:
            _shutil.rmtree(creds)
            removed.append("migrations_credits")
    return {"ok": True, "mode": mode, "functions": FUNCTION_SETS[mode], "removed": removed}


def functions_for(spec: dict[str, Any] | None) -> list[str]:
    """The edge functions this app deploys: the mode's set, minus the AI ones when spec.ai.enabled is false.
    The analyze sources stay in the repo (inert, still unit-tested) — only deploy and gates skip them."""
    from . import spec as spec_mod
    fns = FUNCTION_SETS[mode_of(spec or {})]
    if spec_mod.ai_enabled(spec):
        return list(fns)
    return [f for f in fns if f not in AI_FUNCTIONS]


def _ts_list(values: list[str]) -> str:
    return "[" + ", ".join(_json.dumps(v) for v in values) + "]"


def render_app_gen(spec: dict[str, Any]) -> str:
    placements = spec.get("placements") or []
    free_used = "free_scan_used" if "free_scan_used" in placements else (placements[0] if placements else "free_scan_used")
    daily = "daily_cap" if "daily_cap" in placements else free_used
    return (
        "// GENERATED from app.spec.json by appfactory (supabase.render_backend). Do not edit by hand:\n"
        "// change app.spec.json and re-render.\n\n"
        "/** App display name (legal page titles, logs). */\n"
        f"export const APP_NAME = {_json.dumps(spec.get('display_name') or spec.get('name') or 'App', ensure_ascii=False)};\n\n"
        "/** In-app languages (spec.locales.app). The first one is the fallback. */\n"
        f"export const SUPPORTED_LOCALES = {_ts_list(spec['locales']['app'])} as const;\n\n"
        "/** RevenueCat placement ids (spec.placements); the backend returns them in 402/429 bodies. */\n"
        "export const PLACEMENTS = {\n"
        f"  freeUsed: {_json.dumps(free_used)},\n"
        f"  dailyCap: {_json.dumps(daily)},\n"
        "} as const;\n"
    )


def render_quota_block(spec: dict[str, Any]) -> str:
    u = spec.get("usage", {})
    caps = u.get("daily_caps", {})
    free = u.get("free_lifetime_scans", 1)
    abuse = u.get("abuse_limits", {})
    consent = bool(spec.get("consent", {}).get("health"))
    free_photo = f"{free} successful analysis, lifetime (free modes: photo)" if free else "needs a subscription (402 `subscription_required`)"
    return "\n".join([
        "| Who | Photo analyses | Text analyses |",
        "|---|---|---|",
        f"| Not subscribed | {free_photo} | needs a subscription (402 `subscription_required`) |",
        f"| Subscribed (incl. free trial, billing grace period, sandbox/TestFlight) | {caps.get('photo', 0)} per local calendar day | {caps.get('text', 0)} per local calendar day |",
        "",
        f"Abuse backstop: {abuse.get('free_attempts', 5)} billed calls per rolling 24 h for non-subscribers, "
        f"{abuse.get('hard_attempts', 60)} for subscribers.",
        f"Consent required before the first analysis: {'yes (403 `consent_required`)' if consent else 'no'}.",
    ])


def _replace_block(text: str, name: str, body: str) -> str:
    pat = _re.compile(rf"(<!-- {name}:begin -->\n)(.*?)(\n<!-- {name}:end -->)", _re.S)
    if not pat.search(text):
        return text
    return pat.sub(lambda m: m.group(1) + body + m.group(3), text)


def render_backend(app_dir: str | _Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Write the spec-driven parts of the backend: functions/_shared/app.gen.ts, config.toml
    (project id, Apple client id = bundle id) and the CONTRACT.md quota block. Idempotent."""
    app = _Path(app_dir).expanduser()
    written = []
    gen = app / "supabase" / "functions" / "_shared" / "app.gen.ts"
    if gen.parent.exists():
        gen.write_text(render_app_gen(spec), encoding="utf-8")
        written.append(str(gen.relative_to(app)))
    toml = app / "supabase" / "config.toml"
    if toml.exists():
        t = toml.read_text(encoding="utf-8")
        t = _re.sub(r'^project_id = ".*"$', f'project_id = "{_re.sub(r"[^a-z0-9-]", "", (spec.get("name") or "app").lower()) or "app"}"', t, flags=_re.M)
        t = _re.sub(r'(\[auth\.external\.apple\][^\[]*?client_id = )".*?"', rf'\1"{spec["bundle_id"]}"', t, flags=_re.S)
        toml.write_text(t, encoding="utf-8")
        written.append(str(toml.relative_to(app)))
    contract = app / "backend" / "CONTRACT.md"
    if contract.exists():
        contract.write_text(_replace_block(contract.read_text(encoding="utf-8"), "quotas", render_quota_block(spec)),
                            encoding="utf-8")
        written.append(str(contract.relative_to(app)))
    return {"ok": True, "written": written}


REQUIRED_SECRETS = ("FAL_KEY", "RC_SECRET_KEY", "RC_PROJECT_ID")
AI_SECRETS = ("FAL_KEY",)


def required_secrets(spec: dict[str, Any] | None) -> tuple[str, ...]:
    """REQUIRED_SECRETS minus the AI provider key when spec.ai.enabled is false."""
    from . import spec as spec_mod
    if spec_mod.ai_enabled(spec):
        return REQUIRED_SECRETS
    return tuple(s for s in REQUIRED_SECRETS if s not in AI_SECRETS)


def backend_secrets(spec: dict[str, Any], cfg: dict[str, Any], outputs: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """(secrets, missing) for the subscription backend. Values include keys: never log them —
    report sorted(secrets) (the names) only. Per-app RC project id comes from outputs, never cfg.
    RC_WEBHOOK_SECRET (rc-webhook) is optional: without it the webhook answers 401."""
    ai = spec.get("ai", {})
    u = spec.get("usage", {})
    caps = u.get("daily_caps", {})
    abuse = u.get("abuse_limits", {})
    secrets: dict[str, str] = {
        "AI_MODEL": str(ai.get("model", "")),
        # "none" disables the fallback (Supabase secrets cannot be empty strings).
        "AI_FALLBACK_MODEL": str(ai.get("fallback_model") or "none"),
        "AI_REASONING": str(ai.get("reasoning", "minimal")),
        "AI_TIMEOUT_MS": str(ai.get("timeout_ms", 25000)),
        "FREE_LIFETIME_SCANS": str(u.get("free_lifetime_scans", 1)),
        "FREE_MODES": "photo",
        "PHOTO_DAILY_LIMIT": str(caps.get("photo", 0)),
        "TEXT_DAILY_LIMIT": str(caps.get("text", 0)),
        "FREE_ATTEMPT_LIMIT": str(abuse.get("free_attempts", 5)),
        "HARD_ATTEMPT_LIMIT": str(abuse.get("hard_attempts", 60)),
        "ENTITLEMENT_GRACE_HOURS": str(u.get("entitlement_grace_hours", 72)),
        "REQUIRE_CONSENT": "true" if spec.get("consent", {}).get("health") else "false",
        "APP_SLUG": spec.get("bundle_id", ""),
    }
    missing = []
    from . import spec as spec_mod
    ai_on = spec_mod.ai_enabled(spec)
    for name, value in (("FAL_KEY", cfg.get("fal_key") if ai_on else None), ("RC_SECRET_KEY", cfg.get("rc_secret_key")),
                        ("RC_PROJECT_ID", outputs.get("rc_project_id")),
                        ("RC_WEBHOOK_SECRET", outputs.get("rc_webhook_secret"))):
        if value:
            secrets[name] = str(value)
        elif name in AI_SECRETS and not ai_on:
            continue  # non-AI app: the AI key is neither pushed nor reported missing
        else:
            missing.append(name)
    return secrets, missing


def auth_config(spec: dict[str, Any]) -> dict[str, Any]:
    """Management API auth config: anonymous sign-ins + native Sign in with Apple (client id = the
    bundle id) + manual linking, so an anonymous user can link Apple without changing its id."""
    return {
        "external_anonymous_users_enabled": True,
        "external_apple_enabled": True,
        "external_apple_client_id": spec["bundle_id"],
        "security_manual_linking_enabled": True,
    }
