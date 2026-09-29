"""Thin wrapper around the `asc` CLI (github.com/rorkai/App-Store-Connect-CLI, MIT).

Every App Store Connect call this MCP makes goes through here. Two entry points:

- `run(args)` runs a first-class asc command with `--output json` and returns
  `{"ok", "returncode", "status", "data" | "error"}`.
- `api(method, path, params=, body=)` runs the `asc api` raw passthrough and returns the exact
  shape the old httpx client returned: `{"ok", "status", "data"}` on success,
  `{"ok": False, "status", "error": [{"status", "detail"}]}` on failure. Use it only where asc has
  no first-class command.

Credentials: when config.toml holds asc_key_id + asc_issuer_id + a resolvable .p8, they are passed
as ASC_KEY_ID / ASC_ISSUER_ID / ASC_PRIVATE_KEY_PATH (headless, no keychain prompt). Otherwise asc
falls back to its own keychain profile (`asc auth login`). `ASC_READ_ONLY=1` in the environment is
passed through untouched: asc then refuses every mutating request (exit code 6).

Flag values are passed as `--flag=value`; a value starting with "@" is escaped as "@@" because asc
reads `@env:` / `@file:` prefixes. Telemetry is never touched here (it stays however the user set it).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Iterable

from . import config as cfg

INSTALL_HINT = ("asc CLI not found — install it with `brew install asc` "
                "(github.com/rorkai/App-Store-Connect-CLI), then `asc auth login` or set the asc_* config keys")
DEFAULT_TIMEOUT = 180
UPLOAD_TIMEOUT = 1800
READ_ONLY_EXIT = 6
_FALLBACK_PATHS = ("/opt/homebrew/bin/asc", "/usr/local/bin/asc")
_STATUS_RE = re.compile(r'HTTP Response"?\s+status=(\d{3})')


def binary() -> str | None:
    """Path of the asc binary: $ASC_BIN, then PATH, then the Homebrew locations."""
    explicit = os.environ.get("ASC_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    found = shutil.which("asc")
    if found:
        return found
    return next((p for p in _FALLBACK_PATHS if os.path.exists(p)), None)


def credentials_env(c: dict[str, Any] | None = None) -> dict[str, str]:
    """ASC_KEY_ID / ASC_ISSUER_ID / ASC_PRIVATE_KEY_PATH from config.toml — only when all three are
    present; otherwise {} and asc uses its keychain profile."""
    c = cfg.load_config() if c is None else c
    key_id, issuer = c.get("asc_key_id"), c.get("asc_issuer_id")
    p8 = cfg.resolve_asc_key_filepath(c)
    if key_id and issuer and p8:
        return {"ASC_KEY_ID": str(key_id), "ASC_ISSUER_ID": str(issuer), "ASC_PRIVATE_KEY_PATH": str(p8)}
    return {}


def auth_source(c: dict[str, Any] | None = None) -> str:
    return "config.toml (env credentials)" if credentials_env(c) else "asc keychain profile"


def build_env(creds: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["ASC_SPINNER_DISABLED"] = "1"
    env["ASC_SKILLS_AUTO_CHECK"] = "0"
    env["NO_COLOR"] = "1"
    env.update(credentials_env() if creds is None else creds)
    return env


def escape(value: Any) -> str:
    """A flag value as asc must see it: bools lower-case, a leading "@" doubled."""
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value)
    return "@" + s if s.startswith("@") else s


def flag(name: str, value: Any) -> str:
    return f"--{name}={escape(value)}"


def flags(**values: Any) -> list[str]:
    """--kebab-name=value for every value that is not None (underscores become dashes)."""
    return [flag(k.replace("_", "-"), v) for k, v in values.items() if v is not None]


def _exec(argv: list[str], *, timeout: float, env: dict[str, str], stdin: str | None) -> subprocess.CompletedProcess:
    """The one subprocess call (tests replace this)."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, input=stdin)


def _error_text(stderr: str, stdout: str) -> str:
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip() and not ln.startswith("level=")]
    errs = [ln[len("Error:"):].strip() for ln in lines if ln.startswith("Error:")]
    if errs:
        return " | ".join(errs)[:1500]
    return ("\n".join(lines[-5:]) or (stdout or "").strip()[-600:] or "asc failed without output")[:1500]


def _status(stderr: str) -> int | None:
    found = _STATUS_RE.findall(stderr or "")
    return int(found[-1]) if found else None


def run(args: Iterable[str], *, timeout: float = DEFAULT_TIMEOUT, json_output: bool = True,
        stdin: str | None = None, creds: dict[str, str] | None = None, debug: bool = True) -> dict[str, Any]:
    """Run `asc <args>`. json_output adds `--output json` and parses stdout; debug adds the global
    `--api-debug` flag so the final HTTP status can be read from stderr (headers are redacted)."""
    b = binary()
    if not b:
        return {"ok": False, "error": INSTALL_HINT, "missing_binary": True}
    args = list(args)
    argv = [b, *(["--api-debug"] if debug else []), *args]
    if json_output and not any(a == "--output" or a.startswith("--output=") for a in args):
        argv += ["--output", "json"]
    try:
        p = _exec(argv, timeout=timeout, env=build_env(creds), stdin=stdin)
    except FileNotFoundError:
        return {"ok": False, "error": INSTALL_HINT, "missing_binary": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"asc timed out after {int(timeout)}s: asc {' '.join(args[:3])}"}
    out = (p.stdout or "").strip()
    data: Any = out
    if out and json_output:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = out
    res: dict[str, Any] = {"ok": p.returncode == 0, "returncode": p.returncode, "status": _status(p.stderr)}
    if p.returncode == 0:
        res["data"] = data if out else {}
        return res
    res["error"] = _error_text(p.stderr, out)
    if p.returncode == READ_ONLY_EXIT:
        res["read_only"] = True
    return res


def api(method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None,
        paginate: bool = False, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """`asc api` raw passthrough with the old httpx client's result shape."""
    method = method.upper()
    args = ["api", method, path, "--allow-unknown-path"]
    for k, v in (params or {}).items():
        args.append(flag("query", f"{k}={v}"))
    if paginate and method == "GET":
        args.append("--paginate")
    stdin = None
    if method != "GET":
        args.append("--confirm")
        if body is not None:
            args += ["--body-file", "-"]
            stdin = json.dumps(body)
    r = run(args, timeout=timeout, json_output=False, stdin=stdin)
    if r.get("missing_binary"):
        return {"ok": False, "status": None, "error": r["error"]}
    status = r.get("status")
    if r["ok"]:
        raw = r.get("data")
        if isinstance(raw, str) and raw:
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {"raw": raw[:500]}
        return {"ok": True, "status": status or (204 if not raw else 200), "data": raw or {}}
    out: dict[str, Any] = {"ok": False, "status": status,
                           "error": [{"status": str(status) if status else None, "detail": r.get("error")}]}
    if r.get("read_only"):
        out["read_only"] = True
    return out


def version() -> dict[str, Any]:
    b = binary()
    if not b:
        return {"ok": False, "error": INSTALL_HINT}
    r = run(["--version"], json_output=False, debug=False, timeout=20)
    return {"ok": r["ok"], "path": b, "version": (r.get("data") or r.get("error") or "").strip()}


def doctor() -> dict[str, Any]:
    """Binary, version and auth source (no network)."""
    v = version()
    if not v["ok"]:
        return {"ok": False, "error": v["error"]}
    st = run(["auth", "status"], debug=False, timeout=30)
    creds = (st.get("data") or {}).get("credentials") if isinstance(st.get("data"), dict) else None
    return {"ok": True, "path": v["path"], "version": v["version"], "auth_source": auth_source(),
            "keychain_profiles": [x.get("name") for x in creds or []],
            "read_only": os.environ.get("ASC_READ_ONLY") in ("1", "true", "yes")}


def envelope(data: Any) -> dict[str, Any]:
    """First-class commands print Apple's JSON:API envelope; wrap anything else so callers can
    always read `["data"]`."""
    if isinstance(data, dict) and "data" in data:
        return data
    return {"data": data}


def cli(args: Iterable[str], *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """First-class command in the ASCClient.request result shape: {ok, status, data=<envelope>} or
    {ok: False, status, error}."""
    r = run(args, timeout=timeout)
    if r.get("ok"):
        return {"ok": True, "status": r.get("status") or 200, "data": envelope(r.get("data"))}
    out = {"ok": False, "status": r.get("status"), "error": r.get("error")}
    if r.get("read_only"):
        out["read_only"] = True
    return out


def items(r: dict[str, Any]) -> list[dict[str, Any]]:
    """`data.data` of a list result as a list ([] on error)."""
    d = (r.get("data") or {}).get("data") if isinstance(r.get("data"), dict) else None
    return d if isinstance(d, list) else ([] if d is None else [d])
