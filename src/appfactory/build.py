"""build_* — Xcode/simulator/console tools (xcodebuild, xcrun simctl).

Most tools require an Xcode project (Phase 3 comes from the template). simctl
list/screenshot do not require a project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .proc import run


def list_simulators() -> dict[str, Any]:
    """Return the available iOS simulators (iPhones are surfaced first)."""
    r = run(["xcrun", "simctl", "list", "devices", "available", "--json"], timeout=30)
    if not r.get("ok"):
        return r
    try:
        data = json.loads(r["stdout"])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"json parse: {e}"}
    sims = []
    for runtime, devices in data.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for d in devices:
            if d.get("isAvailable", True):
                sims.append({
                    "name": d.get("name"),
                    "udid": d.get("udid"),
                    "state": d.get("state"),
                    "runtime": runtime.split(".")[-1],
                })
    sims.sort(key=lambda s: ("iPhone" not in (s["name"] or ""), s["name"] or ""))
    return {"ok": True, "count": len(sims), "simulators": sims}


def _resolve_sim_udid(device_name: str) -> str | None:
    """Resolve device_name to an existing simulator udid; if no exact name, use the newest iPhone sim.
    (If the default 'iPhone 16' isn't on this machine, fall back to a suitable sim automatically — live-run finding.)"""
    sims = list_simulators().get("simulators", [])
    if not sims:
        return None
    for s in sims:
        if (s.get("name") or "").lower() == device_name.lower():
            return s.get("udid")
    iphones = [s for s in sims if "iPhone" in (s.get("name") or "")]
    pool = sorted(iphones or sims, key=lambda s: s.get("runtime", ""), reverse=True)
    return pool[0].get("udid") if pool else None


def _sim_destination(device_name: str) -> str:
    """xcodebuild destination — by udid (avoids the name+OS:latest mismatch)."""
    udid = _resolve_sim_udid(device_name)
    return f"platform=iOS Simulator,id={udid}" if udid else f"platform=iOS Simulator,name={device_name}"


def boot_sim(udid: str) -> dict[str, Any]:
    """Boot the simulator (fine if already running) and open Simulator.app."""
    r = run(["xcrun", "simctl", "boot", udid], timeout=60)
    run(["open", "-a", "Simulator"], timeout=15)
    # an "already booted" error counts as success
    if not r.get("ok") and "Booted" in (r.get("stderr", "") + r.get("error", "")):
        return {"ok": True, "note": "already booted"}
    return r


def screenshot(udid: str, out_path: str) -> dict[str, Any]:
    """Capture a screenshot from the booted simulator → out_path (PNG)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    r = run(["xcrun", "simctl", "io", udid, "screenshot", out_path], timeout=30)
    if r.get("ok"):
        r["path"] = out_path
    return r


def archive(project: str, scheme: str, archive_path: str, configuration: str = "Release") -> dict[str, Any]:
    """xcodebuild archive (generic iOS device) → .xcarchive."""
    proj_flag = "-workspace" if project.endswith(".xcworkspace") else "-project"
    return run([
        "xcodebuild", proj_flag, project, "-scheme", scheme,
        "-configuration", configuration, "-destination", "generic/platform=iOS",
        "-archivePath", archive_path, "archive",
    ], timeout=900)


def export_ipa(archive_path: str, export_dir: str, export_options_plist: str) -> dict[str, Any]:
    """xcodebuild -exportArchive → .ipa."""
    return run([
        "xcodebuild", "-exportArchive", "-archivePath", archive_path,
        "-exportPath", export_dir, "-exportOptionsPlist", export_options_plist,
    ], timeout=600)


def build_for_sim(project: str, scheme: str, device_name: str = "iPhone 16") -> dict[str, Any]:
    """Build for the simulator (for verification; running is separate)."""
    proj_flag = "-workspace" if project.endswith(".xcworkspace") else "-project"
    return run([
        "xcodebuild", proj_flag, project, "-scheme", scheme,
        "-destination", _sim_destination(device_name),
        "-derivedDataPath", "build", "build",
    ], timeout=900)


def run_tests(project: str, scheme: str, device_name: str = "iPhone 16") -> dict[str, Any]:
    """xcodebuild test (on the simulator)."""
    proj_flag = "-workspace" if project.endswith(".xcworkspace") else "-project"
    return run([
        "xcodebuild", proj_flag, project, "-scheme", scheme,
        "-destination", _sim_destination(device_name), "test",
    ], timeout=900)
