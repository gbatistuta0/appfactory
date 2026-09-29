"""orchestrator — the DECISION brain of the autonomous driver loop (pure Python).

Stage→subagent routing, persistent retry budget, NEEDS_HUMAN, pre-flight and
'next action'. The actual subagent dispatch + creative work belong to the
/appfactory-run skill in Plan 4. Leaf module: lazily imports pipeline/config.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Stage → subagent role (the Plan 4 skill spawns an Agent based on this role).
STAGE_AGENT: dict[str, str] = {
    "scaffold": "scaffold-agent",
    "repo": "scaffold-agent",
    "design_research": "design-agent",
    "design": "design-agent",
    "features": "feature-agent",
    "backend": "backend-agent",
    "ai_proxy": "backend-agent",
    "icon": "design-agent",
    "asc_app": "asc-agent",
    "iap": "asc-agent",
    "localize": "localize-agent",
    "analytics": "feature-agent",
    "aso": "aso-agent",
    "metadata": "delivery-agent",
    "screenshots": "delivery-agent",
    "app_preview": "delivery-agent",
    "deliver": "delivery-agent",
    "custom_product_pages": "delivery-agent",
    "testflight": "delivery-agent",
    "submission_prep": "asc-agent",
}

MAX_ATTEMPTS = 5
CAFFEINATE_CMD = "caffeinate -dimsu"
REQUIRED_CONFIG_KEYS = [
    "asc_key_id", "asc_issuer_id", "apple_id", "apple_app_specific_password",
    "team_id", "supabase_access_token", "fal_key",
]


def route(stage: str) -> str:
    """Subagent role for a stage. Unknown stage → general-purpose."""
    return STAGE_AGENT.get(stage, "general-purpose")


def _attempts_path(app_dir: str | Path) -> Path:
    return Path(app_dir).expanduser() / ".appfactory" / "attempts.json"


def _load_attempts(app_dir: str | Path) -> dict[str, int]:
    p = _attempts_path(app_dir)
    if not p.exists():
        return {}
    try:
        return {k: int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
    except Exception:  # noqa: BLE001
        return {}


def attempts(app_dir: str | Path, stage: str) -> int:
    return _load_attempts(app_dir).get(stage, 0)


def record_attempt(app_dir: str | Path, stage: str) -> int:
    """Count a failed attempt for a stage (after a gate fail). Return the new count."""
    data = _load_attempts(app_dir)
    data[stage] = data.get(stage, 0) + 1
    p = _attempts_path(app_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data[stage]


def should_retry(app_dir: str | Path, stage: str) -> bool:
    """Whether retry budget remains for a stage (attempts < MAX_ATTEMPTS)."""
    return attempts(app_dir, stage) < MAX_ATTEMPTS


def write_needs_human(app_dir: str | Path, stage: str, reason: str,
                      how_to_resolve: str) -> str:
    """Self-correct exhausted: write NEEDS_HUMAN.md to the app root, return its path."""
    app = Path(app_dir).expanduser()
    app.mkdir(parents=True, exist_ok=True)
    p = app / "NEEDS_HUMAN.md"
    p.write_text(
        f"# NEEDS HUMAN — `{stage}`\n\n"
        f"**Problem:** {reason}\n\n"
        f"**How to resolve:** {how_to_resolve}\n\n"
        f"Once resolved: delete this file and tell the orchestrator **continue**. "
        f"Completed stages will not re-run (idempotent resume).\n",
        encoding="utf-8")
    return str(p)


def preflight(app_dir: str | Path | None = None) -> dict[str, Any]:
    """Pre-run readiness: config keys + the asc CLI (every ASC call) + maestro (end-to-end smoke
    flows) + fastlane session freshness (app creation only).
    Ready if blockers is empty. Also returns the caffeinate command (the skill runs it in the background)."""
    from . import config as cfg
    c = cfg.load_config()
    missing = [k for k in REQUIRED_CONFIG_KEYS if not c.get(k)]
    sess = cfg.session_status()
    blockers: list[str] = []
    if missing:
        blockers.append(f"Missing config key: {', '.join(missing)} (set via config_set)")
    p8 = cfg.resolve_asc_key_filepath(c)
    if c.get("asc_key_id") and p8 is None:
        blockers.append("ASC .p8 not found (asc_key_id set but AuthKey_<id>.p8 missing) → put it in ~/.appfactory or Desktop")
    from . import asc_cli
    if not asc_cli.binary():
        blockers.append(asc_cli.INSTALL_HINT)
    from . import maestro
    if not maestro.binary():  # the features gate and testflight_ship need green smoke flows
        blockers.append(f"maestro missing: {maestro.INSTALL_HINT}")
    if not maestro.live_runner():  # every test run goes through the Viewer runner
        blockers.append(f"maestro-live missing: {maestro.LIVE_HINT}")
    if sess.get("stale"):
        blockers.append("fastlane session stale/missing → in Phase 0 run `fastlane spaceauth -u <apple_id>` (2FA from phone)")
    return {"ok": not blockers, "missing_config": missing, "session": sess,
            "asc_p8": str(p8) if p8 else None,
            "caffeinate_cmd": CAFFEINATE_CMD, "blockers": blockers}


def next_action(app_dir: str | Path) -> dict[str, Any]:
    """Next action for the driver. done=True → pipeline finished (submit requires human approval)."""
    from . import pipeline as pipe
    st = pipe.status(app_dir)
    if not st.get("ok"):
        return {"ok": False, "error": st.get("error", "could not read pipeline status")}
    nxt = st.get("next")
    if nxt is None:
        return {"ok": True, "done": True,
                "message": "All stages complete. App Store submit only with human approval."}
    return {
        "ok": True, "done": False, "stage": nxt, "agent": route(nxt),
        "attempts": attempts(app_dir, nxt), "max_attempts": MAX_ATTEMPTS,
        "should_retry": should_retry(app_dir, nxt),
        "instruction": pipe.stage_instruction(app_dir, nxt),
    }
