"""github_* — a private GitHub repo per project + regular push (gh CLI).

Each app starts as a local git repo (app_scaffold), then github_create_repo
opens a PRIVATE repo under the configured GitHub account (see issues.py) and pushes; improvements are pushed regularly via github_push.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .proc import run

_SWIFT_GITIGNORE = """# Xcode / Swift
build/
DerivedData/
*.xcuserstate
*.xcuserdatad/
.DS_Store
# node (screenshots)
node_modules/
marketing/screenshots/raw/
marketing/screenshots/branded/
# AppFactory runtime
.appfactory/
# Supabase
supabase/.temp/
# secrets
*.p8
.env
"""


def init_local(app_dir: str | Path, app_name: str) -> dict[str, Any]:
    """Local git repo + .gitignore + first commit (secrets excluded)."""
    d = Path(app_dir).expanduser()
    if (d / ".git").exists():
        return {"ok": True, "note": "already a git repo"}
    init = run(["git", "init", "-q"], cwd=str(d))
    if not init.get("ok"):
        return {"ok": False, "step": "git init", "detail": init}
    (d / ".gitignore").write_text(_SWIFT_GITIGNORE, encoding="utf-8")
    run(["git", "add", "-A"], cwd=str(d))
    commit = run(["git", "commit", "-q", "-m", f"init: {app_name} (AppFactory scaffold)"], cwd=str(d))
    return {"ok": commit.get("ok", False), "detail": commit}


def create_private_repo(app_dir: str | Path, repo_name: str, dry_run: bool = True) -> dict[str, Any]:
    """Open a PRIVATE repo under the configured GitHub account + push (never `gh auth switch`)."""
    from . import issues

    d = Path(app_dir).expanduser()
    if not (d / ".git").exists():
        return {"ok": False, "error": "a local git repo is required first (app_scaffold inits it)"}
    full = repo_name if "/" in repo_name else f"{issues.repo_owner()}/{repo_name}"
    cmd = ["gh", "repo", "create", full, "--private", "--source", str(d), "--remote", "origin", "--push"]
    r = issues.run_as_user([cmd], dry_run, timeout=180, cwd=str(d))
    if r.get("ok"):
        r["repo"] = full
    return r


def push(app_dir: str | Path, message: str) -> dict[str, Any]:
    """Commit + push changes (regular tracking)."""
    d = Path(app_dir).expanduser()
    run(["git", "add", "-A"], cwd=str(d))
    commit = run(["git", "commit", "-m", message], cwd=str(d))
    pushed = run(["git", "push"], cwd=str(d), timeout=120)
    return {"ok": pushed.get("ok", False), "commit": commit, "push": pushed}
