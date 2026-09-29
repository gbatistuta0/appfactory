"""github_issue* — the issue convention for every factory app.

Postponed work lives in GitHub Issues on the app's private repo, with one fixed label set:
role labels (ios, backend, store, lead, founder, other-project) + timing (next, later).
Titles are short imperative phrases ("Add kg/lb toggle to S09"), bodies say what and why.

`gh` runs as the active account, or — when `github_user` is set in ~/.appfactory/config.toml —
as that account with the token injected per command via `GH_TOKEN=$(gh auth token --user <user>)`,
never with `gh auth switch`. Tools default to `dry_run=True` and return the exact commands.
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any

from . import config
from .proc import run


def gh_user() -> str:
    """Configured GitHub account (`github_user`), or "" for the active gh account."""
    return str(config.load_config().get("github_user") or "").strip()


def repo_owner() -> str:
    """Owner for new repos: the configured account, else the active gh login."""
    user = gh_user()
    if user:
        return user
    r = run(["gh", "api", "user", "--jq", ".login"], timeout=30)
    return (r.get("stdout") or "").strip()

LABELS: dict[str, tuple[str, str]] = {
    "ios": ("1D76DB", "iOS app (Sources/, Resources/, project.yml)"),
    "backend": ("5319E7", "Supabase, edge functions, AI proxy"),
    "store": ("FBCA04", "ASO, metadata, pricing, screenshots, localization"),
    "lead": ("0E8A16", "Team lead: product, design, review, merge"),
    "founder": ("D93F0B", "Needs the founder (decision, account, payment)"),
    "next": ("B60205", "Do next"),
    "later": ("C5DEF5", "Postponed on purpose"),
    "other-project": ("BFD4F2", "Belongs to another app/repo"),
}
ROLE_LABELS = {"ios", "backend", "store", "lead", "founder", "other-project"}
TIMING_LABELS = {"next", "later"}

_NOT_IMPERATIVE = re.compile(r"^(added|adding|fixed|fixing|updated|updating|implemented|implementing|"
                             r"created|creating|removed|removing|changed|changing|refactored|refactoring)\b", re.I)


def gh_user_env() -> dict[str, Any]:
    """Environment for gh: GH_TOKEN of `github_user` when set (never returned or logged), else inherited."""
    user = gh_user()
    if not user:
        return {"ok": True, "env": dict(os.environ)}
    r = run(["gh", "auth", "token", "--user", user], timeout=30)
    token = (r.get("stdout") or "").strip()
    if not r.get("ok") or not token:
        return {"ok": False, "error": f"no gh token for {user} — run `gh auth login` for that account "
                "(do not `gh auth switch`)", "detail": r.get("stderr") or r.get("error")}
    return {"ok": True, "env": {**os.environ, "GH_TOKEN": token}}


def shown(cmd: list[str]) -> str:
    """The command as a copy-pasteable shell line, with the per-command token prefix when a user is set."""
    user = gh_user()
    prefix = f"GH_TOKEN=$(gh auth token --user {user}) " if user else ""
    return prefix + " ".join(shlex.quote(c) for c in cmd)


def run_as_user(cmds: list[list[str]], dry_run: bool, timeout: int = 60, cwd: str | None = None) -> dict[str, Any]:
    """Run gh commands as the configured account, or (dry run) just return them."""
    lines = [shown(c) for c in cmds]
    if dry_run:
        return {"ok": True, "dry_run": True, "commands": lines}
    env = gh_user_env()
    if not env["ok"]:
        return {**env, "commands": lines}
    results = []
    for c, line in zip(cmds, lines):
        r = run(c, timeout=timeout, cwd=cwd, env=env["env"])
        results.append({"command": line, "ok": r.get("ok", False), "stdout": r.get("stdout", ""),
                        "stderr": r.get("stderr", "") or r.get("error", "")})
    return {"ok": all(x["ok"] for x in results), "dry_run": False, "results": results}


def _repo(repo: str) -> str:
    return repo if "/" in repo else f"{repo_owner()}/{repo}"


def bootstrap_commands(repo: str) -> list[list[str]]:
    return [["gh", "label", "create", name, "--repo", _repo(repo), "--color", color, "--description", desc, "--force"]
            for name, (color, desc) in LABELS.items()]


def bootstrap_labels(repo: str, dry_run: bool = True) -> dict[str, Any]:
    """Create/refresh the factory label set (idempotent: `--force` updates existing labels)."""
    return {**run_as_user(bootstrap_commands(repo), dry_run), "repo": _repo(repo), "labels": list(LABELS)}


def check_issue(title: str, labels: list[str], body: str) -> list[str]:
    errs: list[str] = []
    t = title.strip()
    if not t:
        errs.append("title is required")
    elif len(t) > 80:
        errs.append("title longer than 80 characters")
    elif t.endswith("."):
        errs.append("title has no trailing period")
    elif _NOT_IMPERATIVE.match(t):
        errs.append(f"title must be imperative ('Add …', 'Fix …'), not {t.split()[0]!r}")
    unknown = sorted(set(labels) - set(LABELS))
    if unknown:
        errs.append(f"unknown labels {unknown} (use {sorted(LABELS)}; run github_issues_bootstrap first)")
    if not set(labels) & ROLE_LABELS:
        errs.append(f"needs a role label: one of {sorted(ROLE_LABELS)}")
    if len(set(labels) & TIMING_LABELS) > 1:
        errs.append("use next OR later, not both")
    if not body.strip():
        errs.append("body is required (what, why, where, done-when)")
    return errs


def create_issue(repo: str, title: str, labels: list[str], body: str, dry_run: bool = True) -> dict[str, Any]:
    errs = check_issue(title, labels, body)
    if errs:
        return {"ok": False, "error": "; ".join(errs)}
    cmd = ["gh", "issue", "create", "--repo", _repo(repo), "--title", title.strip(), "--body", body.strip()]
    for label in labels:
        cmd += ["--label", label]
    res = run_as_user([cmd], dry_run)
    if not dry_run and res.get("ok"):
        res["url"] = res["results"][0]["stdout"].splitlines()[-1] if res["results"][0]["stdout"] else None
    return {**res, "repo": _repo(repo)}
