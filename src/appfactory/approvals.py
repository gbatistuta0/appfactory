"""Out-of-band human approval for irreversible or outward actions.

A gated tool called without a valid approval does not execute: it writes a pending record to
~/.appfactory/approvals/<id>.json (action, argument summary, argument hash, a 6-digit code, 30-minute
expiry) and tells the agent to ask the human to run `appfactory approve <id>` in a terminal. The code
never reaches the agent; approving stores a signature derived from it, which the tool checks on the
re-call (approval_id=<id>) together with the expiry and the argument hash, then consumes the record.

Config `approvals = "required" | "off"` (default required). Forced actions (App Store submission,
destructive SQL) need approval even when approvals are off.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from . import config as cfg

TTL_S = 30 * 60
_REDACT_ARGS = {"value", "db_pass", "v2_key", "password", "token", "secret"}
_ID_RE = re.compile(r"^[a-f0-9]{12}$")


def approvals_dir() -> Path:
    return cfg.CONFIG_DIR / "approvals"


def mode() -> str:
    return "off" if str(cfg.load_config().get("approvals", "required")).lower() == "off" else "required"


def _hash(action: str, args: dict[str, Any]) -> str:
    blob = json.dumps({"action": action, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _sig(code: str, rec: dict[str, Any]) -> str:
    return hashlib.sha256(f"{code}:{rec['id']}:{rec['args_hash']}".encode()).hexdigest()


def summarize(args: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in args.items():
        if k in _REDACT_ARGS:
            out[k] = "***"
        elif isinstance(v, str) and len(v) > 4000:
            out[k] = v[:4000] + f"… ({len(v)} chars)"
        else:
            out[k] = v
    return out


def _path(approval_id: str) -> Path | None:
    return approvals_dir() / f"{approval_id}.json" if _ID_RE.match(approval_id or "") else None


def _write(rec: dict[str, Any]) -> None:
    d = approvals_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd = os.open(d / f"{rec['id']}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, default=str)


def load(approval_id: str) -> dict[str, Any] | None:
    p = _path(approval_id)
    if not p or not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def request(action: str, args: dict[str, Any], reason: str = "") -> dict[str, Any]:
    """Create a pending approval and return the agent-facing refusal (no code inside)."""
    rec = {"id": secrets.token_hex(6), "action": action, "args": summarize(args), "args_hash": _hash(action, args),
           "reason": reason, "code": f"{secrets.randbelow(10**6):06d}", "created": time.time(),
           "expires": time.time() + TTL_S, "approved_sig": None}
    _write(rec)
    return {"ok": False, "approval_required": rec["id"], "action": action, "reason": reason or None,
            "how": (f"Ask the human to run `appfactory approve {rec['id']}` in a terminal (it prints the details "
                    f"and asks y/N), then call the tool again with the same arguments and approval_id={rec['id']}")}


def check(action: str, args: dict[str, Any], approval_id: str | None, *, force: bool = False,
          reason: str = "") -> dict[str, Any] | None:
    """None = go ahead. Otherwise the refusal dict to return from the tool (a new pending approval, or why
    the given approval_id is not valid)."""
    if not force and mode() == "off":
        return None
    if not approval_id:
        return request(action, args, reason)
    rec = load(approval_id)
    if rec is None:
        return {"ok": False, "error": f"unknown approval id {approval_id!r}; call the tool without approval_id "
                                      "to request a new one"}
    if rec.get("action") != action or rec.get("args_hash") != _hash(action, args):
        return {"ok": False, "error": "approval does not match this action and these exact arguments; call "
                                      "without approval_id to request a new one"}
    if time.time() > float(rec.get("expires", 0)):
        _path(approval_id).unlink(missing_ok=True)
        return {"ok": False, "error": "approval expired (30 min); request a new one"}
    if not rec.get("approved_sig") or rec["approved_sig"] != _sig(rec["code"], rec):
        return {"ok": False, "approval_pending": approval_id,
                "error": f"not approved yet: the human must run `appfactory approve {approval_id}`"}
    _path(approval_id).unlink(missing_ok=True)  # single use
    return None


def approve(approval_id: str) -> dict[str, Any]:
    """Mark a pending approval approved (called by the CLI after the human said yes)."""
    rec = load(approval_id)
    if rec is None:
        return {"ok": False, "error": f"no pending approval {approval_id!r}"}
    if time.time() > float(rec.get("expires", 0)):
        return {"ok": False, "error": "approval expired"}
    rec["approved_sig"] = _sig(rec["code"], rec)
    _write(rec)
    return {"ok": True}


# ---- destructive SQL (always needs approval, even with approvals off) ----
_DESTRUCTIVE = [
    re.compile(r"\bdrop\s+", re.I),
    re.compile(r"\btruncate\b", re.I),
    re.compile(r"\balter\b[^;]*\bdrop\b", re.I),
    re.compile(r"\b(grant|revoke)\b[^;]*\bauth\b", re.I),
]
_NO_WHERE = re.compile(r"^\s*(delete\s+from|update)\b(?![^;]*\bwhere\b)", re.I)


def destructive_sql(sql: str) -> list[str]:
    """The statements in sql that are destructive (DROP, TRUNCATE, ALTER … DROP, GRANT/REVOKE on auth,
    DELETE/UPDATE without WHERE)."""
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    hits = []
    for stmt in (s.strip() for s in stripped.split(";")):
        if stmt and (any(r.search(stmt) for r in _DESTRUCTIVE) or _NO_WHERE.search(stmt)):
            hits.append(stmt[:200])
    return hits
