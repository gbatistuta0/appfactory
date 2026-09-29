"""maestro_* — Maestro end-to-end flows on the iOS Simulator.

Every app ships a `.maestro/` workspace (config.yaml + flows/). Flows tagged `smoke` must pass
before TestFlight: `run_flows` runs them against the booted simulator and writes
`.appfactory/verify/maestro.json`, which the features gate and `testflight_ship` read.

Rule: every test run is watched live in the Maestro Viewer (http://localhost:7777).
`maestro test` never starts the Viewer; only `maestro mcp` does. So `run_flows` goes through
`appfactory/bin/maestro-live` (shipped inside the package; `tools/maestro-live` links to it), which
starts `maestro mcp`, opens the Viewer in the browser and runs each flow with the MCP `run` tool.
The Viewer is optional: `headless=True`, APPFACTORY_MAESTRO_VIEWER=0, or a missing runner fall back to
plain `maestro test` (no Viewer).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .proc import run

WORKSPACE_REL = ".maestro"
REPORT_REL = Path("build") / "maestro" / "report.xml"
DEBUG_REL = Path("build") / "maestro" / "debug"
MARKER_REL = Path(".appfactory") / "verify" / "maestro.json"
SMOKE_TAG = "smoke"
# Maestro's default XCTest driver port is 22087. Two sessions driving two simulators on the same
# port talk to each other's driver (seen live: a flow for one app read another app's screen), so
# the factory uses its own port.
DEFAULT_DRIVER_PORT = 22187
MIN_JAVA = 17
# The canonical Viewer runner, shipped as package data and called by path so it does not depend on PATH.
LIVE_RUNNER = Path(__file__).resolve().parent / "bin" / "maestro-live"
LIVE_JSON_REL = Path("build") / "maestro" / "results.json"
LIVE_HINT = "ln -s <site-packages>/appfactory/bin/maestro-live ~/.local/bin/maestro-live"
INSTALL_HINT = "curl -fsSL https://get.maestro.mobile.dev | bash  (needs Java 17+: brew install openjdk@17)"
_JAVA_CANDIDATES = (
    "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
    "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home",
    "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
)
# Quiet, non-interactive CLI: no analytics, no "analyze" nag, no update check.
QUIET_ENV = {
    "MAESTRO_CLI_NO_ANALYTICS": "true",
    "MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED": "true",
    "MAESTRO_DISABLE_UPDATE_CHECK": "true",
}


def binary() -> str | None:
    """The maestro CLI: PATH first, then the installer's default ~/.maestro/bin."""
    found = shutil.which("maestro")
    if found:
        return found
    default = Path.home() / ".maestro" / "bin" / "maestro"
    return str(default) if default.exists() else None


def _java_version(home: str | None) -> int | None:
    java = str(Path(home) / "bin" / "java") if home else (shutil.which("java") or "java")
    r = run([java, "-version"], timeout=30)
    text = (r.get("stderr", "") + "\n" + r.get("stdout", "")) if "error" not in r else ""
    m = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major  # "1.8.0" → 8


def java_home() -> str | None:
    """JAVA_HOME if it is Java 17+, else the first Homebrew/`java_home -v 17+` JDK that is."""
    env = os.environ.get("JAVA_HOME")
    if env and (_java_version(env) or 0) >= MIN_JAVA:
        return env
    for cand in _JAVA_CANDIDATES:
        if Path(cand).exists() and (_java_version(cand) or 0) >= MIN_JAVA:
            return cand
    r = run(["/usr/libexec/java_home", "-v", f"{MIN_JAVA}+"], timeout=15)
    if r.get("ok") and r.get("stdout"):
        return r["stdout"].splitlines()[0].strip()
    return None


def env() -> dict[str, str]:
    """The environment maestro runs in: quiet flags + a Java 17+ JAVA_HOME + ~/.maestro/bin on PATH."""
    e = dict(os.environ)
    e.update(QUIET_ENV)
    home = java_home()
    if home:
        e["JAVA_HOME"] = home
    e["PATH"] = e.get("PATH", "") + os.pathsep + str(Path.home() / ".maestro" / "bin")
    return e


def doctor() -> dict[str, Any]:
    """maestro + Java 17+ presence and versions (no device needed)."""
    out: dict[str, Any] = {"ok": True, "notes": []}
    b = binary()
    if b:
        lines = (run([b, "--version"], timeout=60, env=env()).get("stdout") or "").splitlines()
        out["maestro"] = {"path": b, "version": lines[-1].strip() if lines else None}
    else:
        out["ok"] = False
        out["maestro"] = None
        out["notes"].append(f"maestro not installed: {INSTALL_HINT}")
    live = live_runner()
    out["maestro_live"] = {"path": live, "on_path": shutil.which("maestro-live")}
    if not live:
        out["ok"] = False
        out["notes"].append("maestro-live missing (appfactory/bin/maestro-live): test runs fall back to plain `maestro test`")
    elif not out["maestro_live"]["on_path"]:
        out["notes"].append(f"maestro-live not on PATH (app scripts call it): {LIVE_HINT}")
    home = java_home()
    jv = _java_version(home) if home else None
    out["java"] = {"home": home, "version": jv, "ok": bool(jv and jv >= MIN_JAVA)}
    if not out["java"]["ok"]:
        out["ok"] = False
        out["notes"].append(f"Java {MIN_JAVA}+ not found (brew install openjdk@{MIN_JAVA}; set JAVA_HOME)")
    return out


def live_runner() -> str | None:
    """The packaged maestro-live runner, else `maestro-live` on PATH."""
    if LIVE_RUNNER.is_file():
        return str(LIVE_RUNNER)
    return shutil.which("maestro-live")


def booted_simulator() -> str | None:
    """UDID of the first booted iPhone simulator (any booted simulator as a fallback)."""
    r = run(["xcrun", "simctl", "list", "devices", "booted", "--json"], timeout=30)
    if not r.get("ok"):
        return None
    try:
        data = json.loads(r["stdout"])
    except Exception:  # noqa: BLE001
        return None
    booted = [d for devs in data.get("devices", {}).values() for d in devs if d.get("state") == "Booted"]
    booted.sort(key=lambda d: "iPhone" not in (d.get("name") or ""))
    return booted[0]["udid"] if booted else None


def parse_junit(xml_text: str) -> list[dict[str, Any]]:
    """Maestro's JUnit report → [{name, file, passed, status, tags, failure, time}] per flow."""
    root = ET.fromstring(xml_text)
    flows = []
    for tc in root.iter("testcase"):
        failure = tc.find("failure")
        error = tc.find("error")
        bad = failure if failure is not None else error
        status = (tc.get("status") or "").upper()
        tags: list[str] = []
        for prop in tc.iter("property"):
            if prop.get("name") == "tags":
                tags = [t.strip() for t in (prop.get("value") or "").split(",") if t.strip()]
        passed = bad is None and status in ("", "SUCCESS")
        flows.append({
            "name": tc.get("name") or tc.get("id"),
            "file": tc.get("file"),
            "passed": passed,
            "status": "passed" if passed else "failed",
            "tags": tags,
            "failure": None if bad is None else ((bad.text or bad.get("message") or "").strip() or status),
            "time": float(tc.get("time") or 0),
        })
    return flows


def _latest_flow_mtime(app: Path) -> float:
    ws = app / WORKSPACE_REL
    return max((p.stat().st_mtime for p in ws.rglob("*.yaml")), default=0.0) if ws.exists() else 0.0


def parse_live_results(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """maestro-live's --json output → the same per-flow shape as parse_junit."""
    flows = []
    for d in data:
        passed = bool(d.get("passed"))
        flows.append({
            "name": d.get("name"),
            "file": d.get("file"),
            "passed": passed,
            "status": "passed" if passed else "failed",
            "tags": list(d.get("tags") or []),
            "failure": None if passed else (d.get("detail") or "failed"),
            "time": float(d.get("seconds") or 0),
        })
    return flows


def _run_live(app: Path, b: str, udid: str, tag_list: list[str], report: Path,
              timeout: int) -> tuple[list[dict[str, Any]] | None, dict[str, Any], dict[str, Any] | None]:
    """Run the flows through maestro-live (Maestro Viewer up). → (flows | None, run result, error)."""
    live = live_runner()
    if not live:
        return None, {}, {"ok": False, "error": f"maestro-live missing: {LIVE_HINT}"}
    out = app / LIVE_JSON_REL
    if out.exists():
        out.unlink()
    cmd = [live] if os.access(live, os.X_OK) else [sys.executable, live]
    cmd += ["--device", udid, "--junit", str(report), "--json", str(out)]
    if tag_list:
        cmd += ["--tags", ",".join(tag_list)]
    cmd.append(WORKSPACE_REL)
    e = env()
    e["MAESTRO_BIN"] = b
    r = run(cmd, timeout=timeout, cwd=str(app), env=e)
    if not out.exists():
        if "no flows matched" in (r.get("stderr") or ""):
            return [], r, None
        return None, r, {"ok": False, "error": "maestro-live wrote no results",
                         "detail": r.get("error") or (r.get("stderr") or r.get("stdout") or "")[-2000:]}
    try:
        return parse_live_results(json.loads(out.read_text(encoding="utf-8"))), r, None
    except (ValueError, AttributeError) as ex:
        return None, r, {"ok": False, "error": f"maestro-live results parse: {ex}", "results": str(out)}


def _run_headless(app: Path, b: str, udid: str, tag_list: list[str], report: Path, driver_port: int,
                  timeout: int) -> tuple[list[dict[str, Any]] | None, dict[str, Any], dict[str, Any] | None]:
    """Plain `maestro test` with a JUnit report, no Viewer (CI only)."""
    shutil.rmtree(app / DEBUG_REL, ignore_errors=True)  # only this run's screenshots/logs
    cmd = [b, "--device", udid, "test", "--driver-host-port", str(driver_port),
           "--format", "junit", "--output", str(report),
           "--debug-output", str(app / DEBUG_REL), "--flatten-debug-output"]
    if tag_list:
        cmd += ["--include-tags", ",".join(tag_list)]
    cmd.append(WORKSPACE_REL)
    r = run(cmd, timeout=timeout, cwd=str(app), env=env())
    if not report.exists():
        return None, r, {"ok": False, "error": "maestro wrote no JUnit report",
                         "detail": r.get("error") or (r.get("stderr") or r.get("stdout") or "")[-2000:]}
    try:
        return parse_junit(report.read_text(encoding="utf-8")), r, None
    except ET.ParseError as ex:
        return None, r, {"ok": False, "error": f"JUnit parse: {ex}", "report": str(report)}


def run_flows(app_dir: str | Path, tags: str | list[str] | None = None, device: str | None = None,
              driver_port: int = DEFAULT_DRIVER_PORT, timeout: int = 1800,
              headless: bool = False) -> dict[str, Any]:
    """Run the app's `.maestro/` flows against a booted simulator (the app must already be installed).

    Default: through maestro-live, so the Maestro Viewer opens and the user can watch the run.
    headless=True (or APPFACTORY_MAESTRO_VIEWER=0, or no runner): plain `maestro test`, no Viewer
    (driver_port applies only here).
    tags: include only flows with these tags ("smoke" or ["smoke", "paywall"]).
    Returns {ok, passed, failed, flows:[…], report, marker}; writes the verify marker."""
    app = Path(app_dir).expanduser()
    ws = app / WORKSPACE_REL
    if not ws.is_dir():
        return {"ok": False, "error": f"no {WORKSPACE_REL}/ in {app} (the template ships one: config.yaml + flows/)"}
    b = binary()
    if not b:
        return {"ok": False, "error": f"maestro not installed: {INSTALL_HINT}"}
    udid = device or booted_simulator()
    if not udid:
        return {"ok": False, "error": "no booted simulator — build_boot_sim first, then install the app"}
    tag_list = [tags] if isinstance(tags, str) else list(tags or [])
    report = app / REPORT_REL
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()
    if not headless and (os.environ.get("APPFACTORY_MAESTRO_VIEWER") == "0" or not live_runner()):
        headless = True  # the Viewer is optional: fall back to plain `maestro test`
    if headless:
        flows, r, err = _run_headless(app, b, udid, tag_list, report, driver_port, timeout)
    else:
        flows, r, err = _run_live(app, b, udid, tag_list, report, timeout)
    if err:
        return err
    assert flows is not None
    failed = [f for f in flows if not f["passed"]]
    smoke = [f for f in flows if SMOKE_TAG in f["tags"]]
    result = {
        "ok": bool(flows) and not failed and bool(r.get("ok")),
        "device": udid,
        "tags": tag_list,
        "runner": "maestro test (headless)" if headless else "maestro-live (Viewer)",
        "passed": len(flows) - len(failed),
        "failed": len(failed),
        "flows": flows,
        "smoke_ok": bool(smoke) and all(f["passed"] for f in smoke),
        "report": str(report),
        "debug": str(app / DEBUG_REL),
        "ran_at": time.time(),
    }
    if not headless:
        result["results"] = str(app / LIVE_JSON_REL)
    if not flows:
        result["error"] = "no flow ran (check the tags and .maestro/config.yaml `flows:`)"
    marker = app / MARKER_REL
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    result["marker"] = str(marker)
    return result


def smoke_check(app_dir: str | Path) -> dict[str, Any]:
    """Gate check: `.maestro/` exists, the last run's smoke flows all passed, and no flow file was
    edited after that run. {ok, reason}."""
    app = Path(app_dir).expanduser()
    if not (app / WORKSPACE_REL).is_dir():
        return {"ok": False, "reason": f"no {WORKSPACE_REL}/ — add Maestro flows (config.yaml + flows/, "
                "tag the launch → onboarding → paywall flow `smoke`)"}
    mk = app / MARKER_REL
    if not mk.exists():
        return {"ok": False, "reason": "Maestro smoke flows not run — install the app on a booted simulator, "
                "then maestro_test(app_dir, tags='smoke')"}
    try:
        data = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"maestro marker unreadable: {e}"}
    smoke = [f for f in data.get("flows", []) if SMOKE_TAG in f.get("tags", [])]
    if not smoke:
        return {"ok": False, "reason": "no flow tagged `smoke` ran — tag the launch → onboarding → paywall flow"}
    bad = [f["name"] for f in smoke if not f.get("passed")]
    if bad:
        return {"ok": False, "reason": f"Maestro smoke flow(s) failing: {', '.join(bad)}",
                "detail": {"failed": [f for f in smoke if not f.get("passed")]}}
    if _latest_flow_mtime(app) > float(data.get("ran_at") or 0):
        return {"ok": False, "reason": "a .maestro/ flow changed after the last run — re-run maestro_test"}
    return {"ok": True, "reason": f"Maestro: {len(smoke)} smoke flow(s) green"}
