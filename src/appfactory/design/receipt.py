"""Claude Design upload receipt — proof that the local project is what lives in Claude Design.

`design_generate` writes the board files and `upload_plan.json`; the orchestrating agent uploads
them with the claude-design MCP and then calls `record()` (MCP tool `design_record_upload`) with the
project id and the founder-facing `open_url` from `render_preview`. The receipt stores a SHA-256 per
uploaded file, so every design gate can tell "uploaded and current" from "generated locally only" or
"changed after the upload" (stdlib only).
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_REL = "design/project"
PLAN_REL = f"{PROJECT_REL}/upload_plan.json"
RECEIPT_REL = f"{PROJECT_REL}/claude_design.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(app: Path) -> dict[str, Any] | None:
    p = app / PLAN_REL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def plan_files(app: Path) -> list[str]:
    plan = _plan(app) or {}
    return sorted(set(plan.get("files") or []) | set(plan.get("binary_files") or []))


def load(app_dir: str | Path) -> dict[str, Any] | None:
    p = Path(app_dir).expanduser() / RECEIPT_REL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def record(app_dir: str | Path, project_id: str, open_url: str) -> dict[str, Any]:
    """Record a finished upload of every file in upload_plan.json (run after the MCP calls succeed)."""
    app = Path(app_dir).expanduser()
    if not str(project_id or "").strip():
        return {"ok": False, "error": "project_id missing (from mcp__claude-design__create_project)"}
    if not str(open_url or "").startswith("https://"):
        return {"ok": False, "error": "open_url must be the https claude.ai/design link from render_preview "
                "(never the serve_url)"}
    if "claudeusercontent" in open_url:
        return {"ok": False, "error": "that is the short-lived serve_url — record the open_url instead"}
    plan = _plan(app)
    if plan is None:
        return {"ok": False, "error": f"{PLAN_REL} missing — run design_generate first"}
    root = app / PROJECT_REL
    files = plan_files(app)
    missing = [f for f in files if not (root / f).exists()]
    if missing:
        return {"ok": False, "error": f"planned files missing locally: {', '.join(missing[:5])} — re-run design_generate"}
    from . import research
    receipt = {"project_id": project_id, "open_url": open_url, "brief_sha256": research.brief_sha(app),
               "uploaded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "files": {f: sha256(root / f) for f in files}}
    (app / RECEIPT_REL).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    plan["project_id"] = project_id
    (app / PLAN_REL).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "receipt": str(app / RECEIPT_REL), "files": len(files), "project_id": project_id}


def check(app_dir: str | Path, required: list[str] | None = None) -> dict[str, Any]:
    """Every planned file (plus `required`) was uploaded to Claude Design and is unchanged since."""
    app = Path(app_dir).expanduser()
    rec = load(app)
    if rec is None:
        return {"ok": False, "reason": f"no Claude Design upload recorded ({RECEIPT_REL}) — run the upload_plan "
                "calls with the claude-design MCP, then design_record_upload(project_id, open_url)"}
    if not rec.get("project_id") or not str(rec.get("open_url", "")).startswith("https://"):
        return {"ok": False, "reason": f"{RECEIPT_REL} has no project_id/open_url — re-record the upload"}
    uploaded = rec.get("files") or {}
    root = app / PROJECT_REL
    files = sorted(set(plan_files(app)) | set(required or []))
    if not files:
        return {"ok": False, "reason": f"{PLAN_REL} lists no files — run design_generate"}
    not_uploaded = [f for f in files if f not in uploaded]
    if not_uploaded:
        return {"ok": False, "reason": f"not uploaded to Claude Design: {', '.join(not_uploaded[:5])}"
                + (f" (+{len(not_uploaded) - 5} more)" if len(not_uploaded) > 5 else "")
                + " — upload them and re-run design_record_upload"}
    changed = [f for f in files if not (root / f).exists() or sha256(root / f) != uploaded[f]]
    if changed:
        return {"ok": False, "reason": f"changed since the Claude Design upload: {', '.join(changed[:5])} — "
                "re-upload (write_files) and re-run design_record_upload"}
    return {"ok": True, "project_id": rec["project_id"], "open_url": rec["open_url"], "files": len(files),
            "brief_sha256": rec.get("brief_sha256")}


def check_after_brief(app_dir: str | Path, required: list[str] | None = None) -> dict[str, Any]:
    """check() + the recorded upload was made against the CURRENT design brief."""
    from . import research
    up = check(app_dir, required)
    if not up["ok"]:
        return up
    if up.get("brief_sha256") != research.brief_sha(app_dir):
        return {"ok": False, "reason": "the Claude Design upload was recorded before the current design brief — "
                "re-author from the brief, upload and re-run design_record_upload"}
    return up
