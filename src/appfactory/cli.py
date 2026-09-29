"""AppFactory setup CLI — stdlib only.

    appfactory setup [--offline]              interactive wizard (re-runnable)
    appfactory doctor                         non-interactive status
    appfactory services enable|disable NAME   toggle one service
    appfactory approve ID                     approve a pending irreversible action (y/N, terminal only)
    appfactory-mcp                            run the MCP server over stdio

Secrets are read with getpass and never printed; config is written through
config.save_config (0600).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from . import config as cfg

AGENTS = ("claude", "codex", "gemini", "cursor")
FIRST_PROMPT = "Find 3 underserved iOS app niches in Health & Fitness and validate the best one"


# ---------------------------------------------------------------- helpers
def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _ask(prompt: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    ans = input(f"{prompt}{shown}: ").strip()
    return ans or default


def _yes(prompt: str, default: bool) -> bool:
    ans = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not ans else ans.startswith("y")


def _ask_secret(prompt: str, current: str) -> str:
    shown = " [set, Enter keeps]" if current else ""
    ans = getpass.getpass(f"{prompt}{shown}: ").strip()
    return ans or current


def missing_binaries(services: set[str]) -> dict[str, str]:
    """Required binaries (name -> install hint) that are not on PATH for the chosen services."""
    out: dict[str, str] = {}
    for name in sorted(services):
        for binary, hint in cfg.SERVICES[name]["binaries"].items():
            found = shutil.which(binary)
            if binary == "asc":  # reuse the server's resolution (custom paths)
                from . import asc_cli
                found = asc_cli.binary()
            if not found:
                out[binary] = hint
    return out


def mcp_command() -> list[str]:
    """How an agent should launch the server: repo checkout → uv run; installed → script/uvx."""
    repo = Path(__file__).resolve().parents[2]
    if (repo / "pyproject.toml").exists() and (repo / "src" / "appfactory").is_dir():
        return ["uv", "run", "--directory", str(repo), "appfactory-mcp"]
    if exe := shutil.which("appfactory-mcp"):
        return [exe]
    return ["uvx", "--from", "appfactory", "appfactory-mcp"]


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    bak = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(path, bak)
    return bak


# ---------------------------------------------------------------- agent configs
def agent_config_path(agent: str) -> Path | None:
    return {"codex": _home() / ".codex" / "config.toml",
            "gemini": _home() / ".gemini" / "settings.json",
            "cursor": _home() / ".cursor" / "mcp.json"}.get(agent)


def _merge_json(path: Path, command: list[str]) -> str:
    data: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        data = json.loads(path.read_text(encoding="utf-8"))
    bak = _backup(path)
    data.setdefault("mcpServers", {})["appfactory"] = {"command": command[0], "args": command[1:]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote {path}" + (f" (backup {bak.name})" if bak else "")


def _merge_codex(path: Path, command: list[str]) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    tomllib.loads(text)  # refuse to touch a file we cannot parse
    bak = _backup(path)
    # drop an existing [mcp_servers.appfactory] (and its sub-tables) up to the next unrelated header
    kept, skipping = [], False
    for line in text.splitlines():
        header = re.match(r"\s*\[+\s*([^\]]+?)\s*\]+", line)
        if header:
            skipping = header.group(1).startswith("mcp_servers.appfactory")
        if not skipping:
            kept.append(line)
    body = "\n".join(kept).rstrip()
    block = ("[mcp_servers.appfactory]\n"
             f"command = {json.dumps(command[0])}\n"
             f"args = [{', '.join(json.dumps(a) for a in command[1:])}]\n")
    new = (body + "\n\n" if body else "") + block
    tomllib.loads(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return f"wrote {path}" + (f" (backup {bak.name})" if bak else "")


def install_agent(agent: str, command: list[str]) -> str:
    if agent == "claude":
        argv = ["claude", "mcp", "add", "--scope", "user", "appfactory", "--", *command]
        if shutil.which("claude"):
            subprocess.run(["claude", "mcp", "remove", "--scope", "user", "appfactory"],
                           capture_output=True)
            r = subprocess.run(argv, capture_output=True, text=True)
            if r.returncode == 0:
                return "registered with Claude Code (user scope)"
            return f"`claude mcp add` failed: {r.stderr.strip()} — run: {' '.join(argv)}"
        return f"claude CLI not found — run: {' '.join(argv)}"
    path = agent_config_path(agent)
    assert path is not None
    return _merge_codex(path, command) if agent == "codex" else _merge_json(path, command)


def agent_status() -> dict[str, str]:
    out = {}
    for agent in AGENTS:
        if agent == "claude":
            p = _home() / ".claude.json"
            found = p.exists() and '"appfactory"' in p.read_text(encoding="utf-8", errors="ignore")
            out[agent] = "configured" if found else ("claude CLI present" if shutil.which("claude") else "not found")
            continue
        p = agent_config_path(agent)
        if not p or not p.exists():
            out[agent] = "not found"
        else:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            out[agent] = "configured" if ("mcp_servers.appfactory" in txt or '"appfactory"' in txt) else "no appfactory entry"
    return out


# ---------------------------------------------------------------- setup
def _validate_asc(c: dict[str, Any], offline: bool) -> None:
    p8 = c.get("asc_key_filepath")
    if p8 and not Path(os.path.expanduser(p8)).is_file():
        print(f"  ! .p8 not found at {p8}")
    if offline:
        return
    from . import asc_cli
    if not asc_cli.binary():
        print("  (skipping live ASC check: asc CLI missing)")
        return
    r = asc_cli.run(["apps", "list", "--limit=1"], timeout=60)
    print("  ASC live check: " + ("OK" if r.get("ok") else f"FAILED ({r.get('error', 'unknown')})"))


def setup(offline: bool = False) -> int:
    c = cfg.load_config()
    current = cfg.enabled_services(c) if "services" in c else {"research"}
    print(f"AppFactory setup — config: {cfg.CONFIG_PATH}\n")
    print("1) Choose services (Enter keeps the current choice)")
    chosen: list[str] = []
    for name, spec in cfg.SERVICES.items():
        if spec.get("always_on"):
            print(f"  - {name}: {spec['description']} (always on)")
            chosen.append(name)
        elif _yes(f"  - {name}: {spec['description']}?", name in current):
            chosen.append(name)
    c["services"] = chosen

    print("\n2) Credentials")
    for name in chosen:
        spec = cfg.SERVICES[name]
        keys = spec["keys"] + spec.get("optional_keys", [])
        if not keys:
            continue
        print(f" [{name}]")
        for key in keys:
            label = cfg.KNOWN_KEYS.get(key, key) + (" (optional)" if key in spec.get("optional_keys", []) else "")
            cur = str(c.get(key, "") or "")
            val = _ask_secret(f"  {label}", cur) if key in cfg.SECRET_KEYS else _ask(f"  {label}", cur)
            if val:
                c[key] = os.path.expanduser(val) if key.endswith("filepath") else val
    print("\n   Human approvals: live writes (App Store, Supabase, RevenueCat, GitHub, uploads) wait for you to run")
    print("   `appfactory approve <id>` in a terminal. WARNING: turning this off lets an agent reading untrusted")
    print("   web data make irreversible changes on its own. App Store submission and destructive SQL always ask.")
    keep = c.get("approvals", "required") != "off"
    c["approvals"] = "required" if _yes("   Require human approval for live writes? (strongly recommended)", keep) else "off"
    cfg.save_config(c)
    print(f"  saved {cfg.CONFIG_PATH} (0600)")
    if "apple" in chosen:
        _validate_asc(c, offline)

    missing = missing_binaries(set(chosen))
    if missing:
        print("\n  Missing tools:")
        for b, hint in missing.items():
            print(f"   - {b}: {hint}")

    print("\n3) Connect agents")
    command = mcp_command()
    print(f"  server command: {' '.join(command)}")
    connected = []
    for agent in AGENTS:
        if _yes(f"  - {agent}?", agent == "claude"):
            try:
                print("   " + install_agent(agent, command))
                connected.append(agent)
            except Exception as e:  # noqa: BLE001 — keep the wizard going
                print(f"   ! {agent}: {e}")

    print("\nDone.")
    print(f"  services: {', '.join(chosen)}")
    print(f"  agents:   {', '.join(connected) or 'none'}")
    print("  Restart your agent, then try this first prompt (no accounts needed):")
    print(f'    "{FIRST_PROMPT}"')
    return 0


# ---------------------------------------------------------------- doctor / services
def doctor() -> int:
    c = cfg.load_config()
    enabled = cfg.enabled_services(c)
    print(f"config: {cfg.CONFIG_PATH} ({'found' if cfg.CONFIG_PATH.exists() else 'missing'})")
    print("services:")
    for name, spec in cfg.SERVICES.items():
        if name not in enabled:
            print(f"  {name:<11} disabled")
            continue
        missing = [k for k in spec["keys"] if not c.get(k)]
        keys = ", ".join(f"{k}={'set' if c.get(k) else 'missing'}"
                         for k in spec["keys"] + spec.get("optional_keys", []))
        state = "configured" if not missing else "missing keys"
        print(f"  {name:<11} enabled, {state}" + (f" ({keys})" if keys else ""))
    missing_bins = missing_binaries(enabled)
    print("binaries:")
    for name in sorted(enabled):
        for b in cfg.SERVICES[name]["binaries"]:
            print(f"  {b:<11} {'MISSING — ' + missing_bins[b] if b in missing_bins else 'ok'}")
    print("agents:")
    for agent, state in agent_status().items():
        print(f"  {agent:<11} {state}")
    for note in cfg.doctor_notes(c):
        print(f"note: {note}")
    return 0


def toggle_service(action: str, name: str) -> int:
    if name not in cfg.SERVICES:
        print(f"unknown service {name!r}; choose from: {', '.join(cfg.SERVICES)}", file=sys.stderr)
        return 2
    if cfg.SERVICES[name].get("always_on") and action == "disable":
        print(f"{name} is always on", file=sys.stderr)
        return 2
    c = cfg.load_config()
    enabled = cfg.enabled_services(c)
    enabled = enabled | {name} if action == "enable" else enabled - {name}
    c["services"] = [s for s in cfg.SERVICES if s in enabled]
    cfg.save_config(c)
    print(f"{name} {action}d")
    return 0


def approve(approval_id: str) -> int:
    """Show a pending approval and ask the human y/N. Refuses without an interactive terminal."""
    from . import approvals
    rec = approvals.load(approval_id)
    if rec is None:
        print(f"no pending approval {approval_id!r}", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("approve needs an interactive terminal (a human must answer)", file=sys.stderr)
        return 2
    left = int(float(rec["expires"]) - time.time())
    if left <= 0:
        print("this approval has expired; ask the agent to request a new one", file=sys.stderr)
        return 2
    print(f"action:  {rec['action']}")
    if rec.get("reason"):
        print(f"reason:  {rec['reason']}")
    print("args:")
    for k, v in rec.get("args", {}).items():
        print(f"  {k}: {v if isinstance(v, str) else json.dumps(v, default=str)}")
    print(f"expires in {left // 60} min")
    if not _yes("Approve this action?", False):
        print("not approved")
        return 1
    r = approvals.approve(approval_id)
    print("approved — the agent can now re-run the tool once" if r["ok"] else r["error"])
    return 0 if r["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv and not sys.stdin.isatty():
        return mcp_main()  # launched by an MCP client (e.g. `uvx appfactory`)
    p = argparse.ArgumentParser(prog="appfactory", description="AppFactory setup and diagnostics")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="interactive setup wizard")
    s.add_argument("--offline", action="store_true", help="skip network validation")
    sub.add_parser("doctor", help="show configuration status")
    sub.add_parser("serve", help="run the MCP server over stdio")
    sv = sub.add_parser("services", help="enable or disable a service")
    sv.add_argument("action", choices=["enable", "disable"])
    sv.add_argument("name")
    ap = sub.add_parser("approve", help="approve a pending irreversible action")
    ap.add_argument("id")
    a = p.parse_args(argv)
    if a.cmd == "serve":
        return mcp_main()
    if a.cmd == "approve":
        try:
            return approve(a.id)
        except (KeyboardInterrupt, EOFError):
            print("\nnot approved")
            return 1
    if a.cmd == "setup":
        try:
            return setup(offline=a.offline)
        except (KeyboardInterrupt, EOFError):
            print("\naborted")
            return 130
    if a.cmd == "doctor":
        return doctor()
    return toggle_service(a.action, a.name)


def mcp_main() -> None:
    """Entry point for `appfactory-mcp`: run the MCP server over stdio."""
    from .server import main as server_main
    server_main()


if __name__ == "__main__":
    sys.exit(main())
