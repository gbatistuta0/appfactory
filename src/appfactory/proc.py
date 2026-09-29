"""Console command runner helper — used by all shell-based tools."""

from __future__ import annotations

import subprocess
from typing import Any

from .config import scrub


def run(cmd: list[str], timeout: int = 120, cwd: str | None = None, env: dict | None = None) -> dict[str, Any]:
    """Run a command, return a structured result ({ok, exit_code, stdout, stderr}); secret values scrubbed."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return scrub({
            "ok": p.returncode == 0,
            "exit_code": p.returncode,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
        })
    except FileNotFoundError:
        return {"ok": False, "error": f"command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return scrub({"ok": False, "error": f"timeout ({timeout}s): {' '.join(cmd)}"})
