"""ai_* / backend_deploy — AI backend deploy + configuration.

AI keys (fal.ai etc.) only go to Supabase secrets; they never enter the app.

Subscription mode (default stack): backend_deploy renders the spec-driven files, applies the
migrations (tracked in supabase_migrations.schema_migrations, so `supabase db push` agrees), writes
the secrets from app.spec.json + ~/.appfactory/config.toml + per-app outputs, turns on anonymous
sign-ins + Sign in with Apple + manual linking, builds the legal pages and deploys the function set.
Credits mode (legacy credits model): deploy_proxy (ai-proxy + FAL_KEY + legal).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from . import config as cfg
from . import supabase as supa
from .proc import run


def deploy_proxy(app_dir: str | Path, project_ref: str, daily_limit: int = 20) -> dict[str, Any]:
    """Deploy ai-proxy: migration + secrets + supabase functions deploy."""
    app_dir = Path(app_dir).expanduser()
    fn_dir = app_dir / "supabase" / "functions" / "ai-proxy"
    if not fn_dir.exists():
        return {"ok": False, "error": f"ai-proxy function not found: {fn_dir}"}

    c = cfg.load_config()
    fal_key = c.get("fal_key")
    access_token = c.get("supabase_access_token")
    if not fal_key:
        return {"ok": False, "error": "fal_key missing (config_set)"}
    if not access_token:
        return {"ok": False, "error": "supabase_access_token missing"}

    steps: dict[str, Any] = {}

    # 1) ai_usage migration
    try:
        client = supa.SupabaseClient()
    except supa.SupabaseError as e:
        return {"ok": False, "error": str(e)}
    mig = app_dir / "supabase" / "migrations" / "0001_ai_usage.sql"
    if not mig.exists():  # scaffold before apply_backend_mode(credits)
        mig = app_dir / "supabase" / "migrations_credits" / "0001_ai_usage.sql"
    if mig.exists():
        steps["migration"] = client.run_sql(project_ref, mig.read_text(encoding="utf-8"))

    # 2) secrets (FAL_KEY + daily limit) — server-side, never enters the app
    steps["secrets"] = client.set_secrets(project_ref, {
        "FAL_KEY": fal_key,
        "AI_DAILY_LIMIT": str(daily_limit),
    })

    # 2b) enable anonymous auth (the app JWT calls ai-proxy with this) — automatic
    steps["anonymous_auth"] = client.enable_anonymous_auth(project_ref)

    # 3) deploy function via supabase CLI (SUPABASE_ACCESS_TOKEN env)
    env_run = os.environ.copy()
    env_run["SUPABASE_ACCESS_TOKEN"] = access_token
    import subprocess
    try:
        p = subprocess.run(
            ["supabase", "functions", "deploy", "ai-proxy", "--project-ref", project_ref],
            cwd=str(app_dir), capture_output=True, text=True, timeout=300, env=env_run,
        )
        steps["deploy"] = {"ok": p.returncode == 0, "stdout": p.stdout.strip()[-800:], "stderr": p.stderr.strip()[-800:]}
    except FileNotFoundError:
        return {"ok": False, "error": "supabase CLI not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "deploy timed out"}

    # 4) legal (privacy/terms/support) edge function — REQUIRED for every app, public.
    legal_dir = app_dir / "supabase" / "functions" / "legal"
    if legal_dir.exists():
        app_name = c.get("app_display_name") or "This App"
        steps["legal_secrets"] = client.set_secrets(project_ref, {
            "LEGAL_APP_NAME": app_name,
            # RULE: support/contact email is support_email (not apple_id, which is only the login).
            "LEGAL_SUPPORT_EMAIL": c.get("support_email") or c.get("apple_id") or "support@example.com",
            "LEGAL_COMPANY": app_name,
        })
        try:
            pl = subprocess.run(
                ["supabase", "functions", "deploy", "legal", "--project-ref", project_ref, "--no-verify-jwt"],
                cwd=str(app_dir), capture_output=True, text=True, timeout=300, env=env_run,
            )
            steps["legal_deploy"] = {"ok": pl.returncode == 0, "stderr": pl.stderr.strip()[-400:]}
        except Exception as e:  # noqa: BLE001
            steps["legal_deploy"] = {"ok": False, "error": str(e)}

    ok = steps["deploy"]["ok"]
    base = f"https://{project_ref}.supabase.co/functions/v1"
    return {
        "ok": ok,
        "function_url": f"{base}/ai-proxy",
        "legal_urls": {"privacy": f"{base}/legal/privacy", "terms": f"{base}/legal/terms", "support": f"{base}/legal/support"},
        "steps": steps,
    }


def configure(providers: list[str] | None = None, models: dict[str, str] | None = None) -> dict[str, Any]:
    """Report AI provider/model selection (currently fal.ai/Flux). Extensible later."""
    return {
        "ok": True,
        "providers": providers or ["fal.ai"],
        "models": models or {"image": "fal-ai/flux/schnell"},
        "note": "Keys are written to server-side secrets via ai_deploy_proxy.",
    }


# ---------------------------------------------------------------------------------------------
# Subscription-mode backend deploy (backend_deploy)
# ---------------------------------------------------------------------------------------------
import json as _json  # noqa: E402
import re as _re  # noqa: E402

from . import legal as legal_mod  # noqa: E402
from . import spec as spec_mod  # noqa: E402

_MIGRATION_TRACKING = (
    "create schema if not exists supabase_migrations;\n"
    "create table if not exists supabase_migrations.schema_migrations "
    "(version text primary key, statements text[], name text);\n"
)


def _migrations(app_dir: Path) -> list[Path]:
    return sorted((app_dir / "supabase" / "migrations").glob("*.sql"))


def _version(p: Path) -> str:
    return p.name.split("_", 1)[0]


def _applied_versions(client: Any, ref: str) -> tuple[set[str] | None, str | None]:
    r = client.run_sql(ref, _MIGRATION_TRACKING + "select version from supabase_migrations.schema_migrations;")
    if not r.get("ok"):
        return None, str(r.get("error"))[:300]
    data = r.get("data")
    rows = data if isinstance(data, list) else []
    return {str(x.get("version")) for x in rows if isinstance(x, dict)}, None


def _record_sql(p: Path) -> str:
    name = p.stem.split("_", 1)[1] if "_" in p.stem else p.stem
    return (f"insert into supabase_migrations.schema_migrations (version, name) "
            f"values ('{_version(p)}', '{name}') on conflict (version) do nothing;")


def plan_backend(app_dir: str | Path, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Offline: what backend_deploy would do (functions, migrations, secret NAMES, auth config)."""
    app = Path(app_dir).expanduser()
    sp = spec or spec_mod.load(app)
    mode = supa.mode_of(sp)
    c = cfg.load_config()
    outs = cfg.app_outputs(app)
    secrets, missing = supa.backend_secrets(sp, c, outs) if mode == "subscription" else ({}, [])
    return {
        "ok": True, "mode": mode,
        "ai_enabled": spec_mod.ai_enabled(sp),
        "functions": supa.functions_for(sp),
        "public_functions": sorted(supa.PUBLIC_FUNCTIONS & set(supa.functions_for(sp))),
        "migrations": [p.name for p in _migrations(app)],
        "secret_names": sorted(secrets),
        "missing_secrets": missing,
        "auth_config": supa.auth_config(sp) if mode == "subscription" else {"external_anonymous_users_enabled": True},
    }


def deploy_backend(app_dir: str | Path, project_ref: str, *, client: Any = None,
                   runner: Callable[..., dict[str, Any]] | None = None,
                   config: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Deploy the spec's function set + migrations + secrets + auth config to one Supabase project.

    LIVE side effects unless dry_run. Secrets are reported by NAME only. Writes the per-app outputs
    (supabase_ref/url, legal_base, functions) and the verify marker .appfactory/verify/backend_deploy.json.
    """
    app = Path(app_dir).expanduser()
    if not spec_mod.path(app).exists():
        return {"ok": False, "error": f"{spec_mod.SPEC_FILE} not found in {app} (spec is required)"}
    sp = spec_mod.load(app)
    errs = spec_mod.validate(sp)
    if errs:
        return {"ok": False, "error": "invalid app.spec.json: " + "; ".join(errs)}
    mode = supa.mode_of(sp)
    if mode == "credits":
        return deploy_proxy(app, project_ref)
    plan = plan_backend(app, sp)
    if dry_run:
        return {**plan, "dry_run": True}
    c = config if config is not None else cfg.load_config()
    access_token = c.get("supabase_access_token")
    if client is None:
        try:
            client = supa.SupabaseClient()
        except supa.SupabaseError as e:
            return {"ok": False, "error": str(e)}
    runner = runner or run
    outs = cfg.app_outputs(app)
    secrets, missing = supa.backend_secrets(sp, c, outs)
    hard_missing = [m for m in missing if m in supa.required_secrets(sp)]
    steps: dict[str, Any] = {}

    # 1) spec-driven files + legal pages (build refuses placeholders; the rest still deploys)
    steps["render"] = supa.render_backend(app, sp)
    legal_chk = legal_mod.check(app, sp)
    lb = runner(["deno", "run", "--allow-read", "--allow-write", "backend/legal/build.ts"], cwd=str(app), timeout=120)
    steps["legal_build"] = {"ok": lb.get("ok", False), "publishable": legal_chk["publishable"],
                            "blocking": legal_chk["blocking"],
                            "detail": (lb.get("stderr") or lb.get("error") or "")[-400:]}

    # 2) migrations, in order, each once (tracked like the supabase CLI does)
    applied, err = _applied_versions(client, project_ref)
    mig_steps = []
    if applied is None:
        mig_steps.append({"ok": False, "error": f"could not read applied migrations: {err}"})
    else:
        for p in _migrations(app):
            if _version(p) in applied:
                mig_steps.append({"file": p.name, "ok": True, "skipped": "already applied"})
                continue
            r = client.run_sql(project_ref, p.read_text(encoding="utf-8") + "\n" + _record_sql(p))
            mig_steps.append({"file": p.name, "ok": bool(r.get("ok")),
                              **({} if r.get("ok") else {"error": str(r.get("error"))[:300]})})
            if not r.get("ok"):
                break  # later migrations depend on this one
    steps["migrations"] = mig_steps

    # 3) secrets (names only in the report)
    sr = client.set_secrets(project_ref, secrets)
    steps["secrets"] = {"ok": bool(sr.get("ok")), "names": sorted(secrets), "missing": missing,
                        **({} if sr.get("ok") else {"error": str(sr.get("error"))[:300]})}

    # 4) auth: anonymous sign-ins + Sign in with Apple (native, client id = bundle id) + manual linking
    ar = client.update_auth_config(project_ref, supa.auth_config(sp))
    steps["auth"] = {"ok": bool(ar.get("ok")), **({} if ar.get("ok") else {"error": str(ar.get("error"))[:300]})}

    # 5) functions via the supabase CLI (token only in the child env)
    env_run = os.environ.copy()
    if access_token:
        env_run["SUPABASE_ACCESS_TOKEN"] = access_token
    fn_steps = []
    for name in supa.functions_for(sp):
        cmd = ["supabase", "functions", "deploy", name, "--project-ref", project_ref, "--use-api"]
        if name in supa.PUBLIC_FUNCTIONS:
            cmd.append("--no-verify-jwt")
        r = runner(cmd, cwd=str(app), timeout=300, env=env_run)
        fn_steps.append({"function": name, "ok": bool(r.get("ok")),
                         **({} if r.get("ok") else {"error": (r.get("stderr") or r.get("error") or "")[-400:]})})
    steps["functions"] = fn_steps

    supabase_url = f"https://{project_ref}.supabase.co"
    ok = (all(m.get("ok") for m in mig_steps) and steps["secrets"]["ok"] and steps["auth"]["ok"]
          and all(f["ok"] for f in fn_steps) and not hard_missing)
    cfg.update_app_outputs(app, supabase_ref=project_ref, supabase_url=supabase_url,
                           legal_base=legal_mod.base_url(supabase_url),
                           functions=[f["function"] for f in fn_steps if f["ok"]])
    marker = app / ".appfactory" / "verify" / "backend_deploy.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_json.dumps({
        "ok": ok, "mode": mode, "project_ref": project_ref, "ai_enabled": spec_mod.ai_enabled(sp),
        "functions": [f["function"] for f in fn_steps if f["ok"]],
        "secret_names": sorted(secrets), "missing_secrets": missing,
        "legal_published": legal_chk["publishable"],
    }, indent=2) + "\n", encoding="utf-8")
    base = f"{supabase_url}/functions/v1"
    return {
        "ok": ok, "mode": mode, "steps": steps,
        "missing_required_secrets": hard_missing,
        "function_urls": {f: f"{base}/{f}" for f in supa.functions_for(sp)},
        "legal_urls": {d: legal_mod.url(supabase_url, d) for d in ("privacy", "terms", "support")},
    }
