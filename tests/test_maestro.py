"""maestro_test tool, the Maestro smoke gate (features + testflight_ship), the doctors and the
template's .maestro/ workspace. No simulator: every maestro/xcrun call is a fake subprocess."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from appfactory import app, gates, maestro

FIXTURE = Path(__file__).parent / "fixtures" / "maestro" / "junit_mixed.xml"
BOOTED = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-26-3": [
    {"name": "Apple Watch", "udid": "WATCH", "state": "Booted"},
    {"name": "iPhone 17 Pro", "udid": "SIM-UDID", "state": "Booted"},
]}}
ALL_GREEN = """<?xml version='1.0' encoding='UTF-8'?>
<testsuites><testsuite name="Test Suite" tests="2" failures="0">
  <testcase id="smoke_onboarding_paywall" name="smoke_onboarding_paywall" file=".maestro/flows/a.yaml"
            time="3.5" status="SUCCESS"><properties><property name="tags" value="smoke, paywall"/></properties></testcase>
  <testcase id="extra" name="extra" file=".maestro/flows/b.yaml" time="1.0" status="SUCCESS"/>
</testsuite></testsuites>"""


def _workspace(root: Path) -> Path:
    (root / ".maestro" / "flows").mkdir(parents=True, exist_ok=True)
    (root / ".maestro" / "config.yaml").write_text('flows:\n  - "flows/*"\n')
    (root / ".maestro" / "flows" / "a.yaml").write_text("appId: com.x\n---\n- launchApp\n")
    old = time.time() - 60  # flows written before the run
    for p in (root / ".maestro").rglob("*.yaml"):
        os.utime(p, (old, old))
    return root


LIVE_GREEN = [
    {"name": "smoke_onboarding_paywall", "file": ".maestro/flows/a.yaml", "passed": True, "seconds": 3.5,
     "tags": ["paywall", "smoke"], "detail": ""},
    {"name": "extra", "file": ".maestro/flows/b.yaml", "passed": True, "seconds": 1.0, "tags": [], "detail": ""},
]
LIVE_MIXED = [
    {"name": "ok", "file": ".maestro/flows/ok.yaml", "passed": True, "seconds": 2.0, "tags": [], "detail": ""},
    {"name": "bad", "file": ".maestro/flows/bad.yaml", "passed": False, "seconds": 4.0, "tags": ["smoke"],
     "detail": '{"success": false, "error": "Element not found: Definitely not here"}'},
]


class FakeRun:
    """Stands in for subprocess.run: simctl answers with BOOTED; `maestro test` writes the JUnit
    `report`; maestro-live writes `live` as its --json results (and the JUnit report)."""

    def __init__(self, report: str | None, exit_code: int = 0, live: list | None = None, stderr: str = ""):
        self.report, self.exit_code, self.live, self.stderr, self.calls = report, exit_code, live, stderr, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[:2] == ["xcrun", "simctl"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(BOOTED), "")
        if cmd[0].endswith("maestro-live"):
            if self.live is not None:
                out = Path(cmd[cmd.index("--json") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(self.live))
                Path(cmd[cmd.index("--junit") + 1]).write_text("<testsuites/>")
        elif "test" in cmd and self.report is not None:
            out = Path(cmd[cmd.index("--output") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(self.report)
        return subprocess.CompletedProcess(cmd, self.exit_code, "", self.stderr)

    def maestro_cmd(self) -> list[str]:
        return next(c for c, _ in self.calls if "test" in c)

    def live_call(self) -> tuple[list[str], dict]:
        return next((c, kw) for c, kw in self.calls if c[0].endswith("maestro-live"))


@pytest.fixture
def fake_maestro(monkeypatch):
    monkeypatch.setattr(maestro, "binary", lambda: "/fake/maestro")
    monkeypatch.setattr(maestro, "java_home", lambda: "/fake/jdk17")

    def install(report: str | None = None, exit_code: int = 0, live: list | None = None,
                stderr: str = "") -> FakeRun:
        fake = FakeRun(report, exit_code, live, stderr)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake
    return install


# ---- JUnit parsing ----

def test_parse_junit_reports_pass_fail_tags_and_failure_text():
    flows = maestro.parse_junit(FIXTURE.read_text())
    assert [(f["name"], f["passed"]) for f in flows] == [("ok", True), ("bad", False)]
    bad = flows[1]
    assert bad["tags"] == ["smoke"] and bad["status"] == "failed"
    assert "Definitely not here" in bad["failure"]
    assert flows[0]["tags"] == [] and flows[0]["failure"] is None


# ---- runner: maestro-live (default, Viewer up) ----

def test_run_flows_goes_through_maestro_live_by_default(tmp_path, fake_maestro):
    fake = fake_maestro(live=LIVE_GREEN)
    r = maestro.run_flows(_workspace(tmp_path), tags="smoke")
    assert r["ok"] is True and r["passed"] == 2 and r["failed"] == 0 and r["smoke_ok"] is True
    assert r["device"] == "SIM-UDID"  # the booted iPhone, not the watch
    assert r["runner"].startswith("maestro-live")
    cmd, kw = fake.live_call()
    # called by its repo path, not through PATH
    assert cmd[0] == str(maestro.LIVE_RUNNER) and maestro.LIVE_RUNNER.exists()
    assert cmd[cmd.index("--device") + 1] == "SIM-UDID"
    assert cmd[cmd.index("--tags") + 1] == "smoke"
    assert cmd[cmd.index("--json") + 1] == str(tmp_path / maestro.LIVE_JSON_REL)
    assert cmd[cmd.index("--junit") + 1] == str(tmp_path / maestro.REPORT_REL)
    assert "--no-open" not in cmd  # the Viewer always opens
    assert cmd[-1] == ".maestro" and kw["cwd"] == str(tmp_path)
    assert kw["env"]["MAESTRO_BIN"] == "/fake/maestro" and kw["env"]["JAVA_HOME"] == "/fake/jdk17"
    assert kw["env"]["MAESTRO_CLI_NO_ANALYTICS"] == "true"
    assert not any("test" in c for c, _ in fake.calls if not c[0].endswith("maestro-live"))
    flow = r["flows"][0]
    assert flow == {"name": "smoke_onboarding_paywall", "file": ".maestro/flows/a.yaml", "passed": True,
                    "status": "passed", "tags": ["paywall", "smoke"], "failure": None, "time": 3.5}
    marker = json.loads((tmp_path / maestro.MARKER_REL).read_text())
    assert marker["smoke_ok"] is True and marker["flows"] == r["flows"]
    assert maestro.smoke_check(tmp_path)["ok"] is True


def test_run_flows_live_failure_is_reported_per_flow(tmp_path, fake_maestro):
    fake_maestro(live=LIVE_MIXED, exit_code=1)
    r = maestro.run_flows(_workspace(tmp_path), device="GIVEN")
    assert r["ok"] is False and r["passed"] == 1 and r["failed"] == 1 and r["smoke_ok"] is False
    assert r["device"] == "GIVEN"
    failing = [f for f in r["flows"] if not f["passed"]]
    assert failing[0]["name"] == "bad" and "Definitely not here" in failing[0]["failure"]
    assert failing[0]["status"] == "failed"
    chk = maestro.smoke_check(tmp_path)
    assert chk["ok"] is False and "bad" in chk["reason"]


def test_run_flows_live_without_results(tmp_path, fake_maestro):
    fake_maestro(live=None, exit_code=1, stderr="maestro mcp exited unexpectedly")
    r = maestro.run_flows(_workspace(tmp_path))
    assert r["ok"] is False and "no results" in r["error"] and "mcp exited" in r["detail"]
    assert not (tmp_path / maestro.MARKER_REL).exists()


def test_run_flows_live_no_matching_flows(tmp_path, fake_maestro):
    fake_maestro(live=None, exit_code=2, stderr="no flows matched")
    r = maestro.run_flows(_workspace(tmp_path), tags="nope")
    assert r["ok"] is False and r["passed"] == 0 and "no flow ran" in r["error"]
    assert maestro.smoke_check(tmp_path)["ok"] is False


def test_run_flows_live_runner_missing_falls_back_to_plain_maestro(tmp_path, fake_maestro, monkeypatch):
    fake = fake_maestro(live=LIVE_GREEN)
    monkeypatch.setattr(maestro, "live_runner", lambda: None)
    maestro.run_flows(_workspace(tmp_path))
    cmd = fake.calls[-1][0]
    assert cmd[0] == "/fake/maestro" and "test" in cmd


def test_maestro_live_json_carries_tags():
    src = maestro.LIVE_RUNNER.read_text()
    assert '"tags": sorted(flow_tags(f))' in src  # run_flows needs tags for the smoke gate


# ---- runner: headless `maestro test` (CI only) ----

def test_run_flows_headless_all_green_writes_marker(tmp_path, fake_maestro):
    fake = fake_maestro(ALL_GREEN)
    r = maestro.run_flows(_workspace(tmp_path), tags="smoke", headless=True)
    assert r["ok"] is True and r["passed"] == 2 and r["failed"] == 0 and r["smoke_ok"] is True
    assert r["device"] == "SIM-UDID"
    assert not any(c[0].endswith("maestro-live") for c, _ in fake.calls)
    cmd = fake.maestro_cmd()
    assert cmd[:3] == ["/fake/maestro", "--device", "SIM-UDID"]
    assert cmd[cmd.index("--include-tags") + 1] == "smoke"
    assert cmd[cmd.index("--format") + 1] == "junit"
    assert cmd[cmd.index("--driver-host-port") + 1] == str(maestro.DEFAULT_DRIVER_PORT)
    assert cmd[-1] == ".maestro"
    env = next(kw for c, kw in fake.calls if "test" in c)["env"]
    assert env["MAESTRO_CLI_NO_ANALYTICS"] == "true" and env["JAVA_HOME"] == "/fake/jdk17"
    marker = json.loads((tmp_path / maestro.MARKER_REL).read_text())
    assert marker["smoke_ok"] is True
    assert maestro.smoke_check(tmp_path)["ok"] is True


def test_run_flows_headless_failure_is_reported_per_flow(tmp_path, fake_maestro):
    fake_maestro(FIXTURE.read_text(), exit_code=1)
    r = maestro.run_flows(_workspace(tmp_path), device="GIVEN", headless=True)
    assert r["ok"] is False and r["passed"] == 1 and r["failed"] == 1 and r["smoke_ok"] is False
    failing = [f for f in r["flows"] if not f["passed"]]
    assert failing[0]["name"] == "bad" and "Definitely not here" in failing[0]["failure"]
    chk = maestro.smoke_check(tmp_path)
    assert chk["ok"] is False and "bad" in chk["reason"]


def test_run_flows_without_workspace_or_binary(tmp_path, monkeypatch):
    assert "no .maestro/" in maestro.run_flows(tmp_path)["error"]
    _workspace(tmp_path)
    monkeypatch.setattr(maestro, "binary", lambda: None)
    assert "not installed" in maestro.run_flows(tmp_path)["error"]


def test_run_flows_headless_without_report(tmp_path, fake_maestro):
    fake_maestro(None, exit_code=1)
    r = maestro.run_flows(_workspace(tmp_path), headless=True)
    assert r["ok"] is False and "no JUnit report" in r["error"]
    assert not (tmp_path / maestro.MARKER_REL).exists()


def test_maestro_test_tool_is_registered_and_splits_tags(tmp_path, fake_maestro):
    from fastmcp import Client

    from appfactory.server import maestro_test, mcp

    async def _tools():
        async with Client(mcp) as c:
            return {t.name: t for t in await c.list_tools()}
    tools = asyncio.run(_tools())
    assert "maestro_test" in tools
    assert "headless" not in tools["maestro_test"].inputSchema.get("properties", {})  # Viewer is mandatory
    fake = fake_maestro(live=LIVE_GREEN)
    r = maestro_test(str(_workspace(tmp_path)), tags="smoke, paywall")
    assert r["ok"] is True
    cmd, _ = fake.live_call()
    assert cmd[cmd.index("--tags") + 1] == "smoke,paywall"


# ---- gate ----

def test_smoke_check_requirements(tmp_path):
    assert "no .maestro/" in maestro.smoke_check(tmp_path)["reason"]
    _workspace(tmp_path)
    assert "not run" in maestro.smoke_check(tmp_path)["reason"]
    mk = tmp_path / maestro.MARKER_REL
    mk.parent.mkdir(parents=True, exist_ok=True)
    flow = {"name": "a", "passed": True, "tags": []}
    mk.write_text(json.dumps({"flows": [flow], "ran_at": time.time()}))
    assert "tagged `smoke`" in maestro.smoke_check(tmp_path)["reason"]
    flow["tags"] = ["smoke"]
    mk.write_text(json.dumps({"flows": [flow], "ran_at": time.time()}))
    assert maestro.smoke_check(tmp_path)["ok"] is True
    # a flow edited after the run makes the result stale
    (tmp_path / ".maestro" / "flows" / "a.yaml").write_text("appId: com.x\n---\n- launchApp\n- back\n")
    mk.write_text(json.dumps({"flows": [flow], "ran_at": time.time() - 30}))
    assert "changed after the last run" in maestro.smoke_check(tmp_path)["reason"]


def test_features_gate_requires_maestro_smoke(tmp_path, monkeypatch):
    for name in ("_gate_build_marker", "_gate_revenuecat", "_check_no_unlimited_claims",
                 "_check_no_advanced_settings", "_check_analytics_coverage", "_check_no_push_permission",
                 "_check_onboarding_depth", "_check_rating_requests", "_check_native_chrome",
                 "_check_paywall_funnel", "_check_legal_urls"):
        monkeypatch.setattr(gates, name, lambda *a, **k: {"ok": True, "reason": "stub"})
    r = gates.validate_stage(tmp_path, "features")
    assert r["ok"] is False and ".maestro" in r["reason"]
    _workspace(tmp_path)
    mk = tmp_path / maestro.MARKER_REL
    mk.parent.mkdir(parents=True, exist_ok=True)
    mk.write_text(json.dumps({"flows": [{"name": "s", "passed": False, "tags": ["smoke"]}], "ran_at": time.time()}))
    r = gates.validate_stage(tmp_path, "features")
    assert r["ok"] is False and "failing" in r["reason"]
    mk.write_text(json.dumps({"flows": [{"name": "s", "passed": True, "tags": ["smoke"]}], "ran_at": time.time()}))
    assert gates.validate_stage(tmp_path, "features")["ok"] is True


def test_testflight_ship_refuses_without_green_smoke(tmp_path, monkeypatch):
    from appfactory import signing, store_setup
    from appfactory.server import testflight_ship
    monkeypatch.setattr(store_setup, "capabilities_pending", lambda d: [])
    shipped = []
    monkeypatch.setattr(signing, "ship_testflight", lambda *a: shipped.append(a) or {"ok": True})
    r = testflight_ship(str(tmp_path), "Hue.xcodeproj", "Hue", "com.example.hue")
    assert r["ok"] is False and "Maestro smoke gate" in r["error"] and not shipped
    _workspace(tmp_path)
    mk = tmp_path / maestro.MARKER_REL
    mk.parent.mkdir(parents=True, exist_ok=True)
    mk.write_text(json.dumps({"flows": [{"name": "s", "passed": True, "tags": ["smoke"]}], "ran_at": time.time()}))
    from conftest import approve_next
    args = (str(tmp_path), "Hue.xcodeproj", "Hue", "com.example.hue")
    first = testflight_ship(*args)
    assert first["ok"] is False and not shipped  # a live upload waits for the human
    assert testflight_ship(*args, approval_id=approve_next(first))["ok"] is True
    assert shipped


# ---- doctors ----

def test_doctor_reports_maestro_and_java(monkeypatch):
    monkeypatch.setattr(maestro, "binary", lambda: "/fake/maestro")
    monkeypatch.setattr(maestro, "java_home", lambda: "/fake/jdk")

    def fake_run(cmd, **kw):
        if cmd[-1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, "2.10.0\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", 'openjdk version "17.0.18" 2026-01-20\n')
    monkeypatch.setattr(subprocess, "run", fake_run)
    d = maestro.doctor()
    assert d["ok"] is True and d["maestro"]["version"] == "2.10.0" and d["java"]["version"] == 17
    assert d["maestro_live"]["path"] == str(maestro.LIVE_RUNNER)


def test_doctor_flags_missing_maestro_live(monkeypatch):
    monkeypatch.setattr(maestro, "binary", lambda: "/fake/maestro")
    monkeypatch.setattr(maestro, "java_home", lambda: "/fake/jdk")
    monkeypatch.setattr(maestro, "live_runner", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, "2.10.0\n", 'openjdk version "17.0.18"\n'))
    d = maestro.doctor()
    assert d["ok"] is False and d["maestro_live"]["path"] is None
    assert any("maestro-live missing" in n for n in d["notes"])


def test_doctor_flags_missing_maestro_and_old_java(monkeypatch):
    monkeypatch.setattr(maestro, "binary", lambda: None)
    monkeypatch.setattr(maestro, "java_home", lambda: "/fake/jdk8")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, "", 'java version "1.8.0_392"\n'))
    d = maestro.doctor()
    assert d["ok"] is False and d["maestro"] is None and d["java"]["version"] == 8
    assert any("maestro not installed" in n for n in d["notes"])
    assert any("Java 17+" in n for n in d["notes"])


def test_env_and_config_doctor_include_maestro(monkeypatch):
    from appfactory import server
    fake = {"ok": False, "maestro": None, "java": {"home": None, "version": None, "ok": False},
            "maestro_live": {"path": None, "on_path": None},
            "notes": ["maestro not installed: x"]}
    monkeypatch.setattr(maestro, "doctor", lambda: fake)
    monkeypatch.setattr(server, "_run", lambda *a, **k: {"ok": True, "stdout": "v"})
    e = server.env_doctor()
    assert e["available"]["maestro"] is False and e["available"]["java17"] is False
    assert e["available"]["maestro_live"] is False
    assert "maestro not installed: x" in e["notes"]
    assert server.config_doctor()["maestro"] is fake


# ---- template ----

def test_scaffold_ships_a_maestro_smoke_flow_with_the_bundle_id(tmp_path):
    r = app.scaffold("Hue", "com.example.hue", dest_dir=str(tmp_path), generate=False)
    assert r["ok"], r
    ws = Path(r["dir"]) / ".maestro"
    assert (ws / "config.yaml").exists()
    flow = (ws / "flows" / "smoke_onboarding_paywall.yaml").read_text()
    assert "appId: com.example.hue" in flow and "__BUNDLE_ID__" not in flow
    assert "- smoke" in flow
    # the smoke flow must stop at the paywall: it never taps a purchase button
    for buy in ("tapOn: {id: paywall_cta}", "offer_cta", "topup_pack"):
        assert buy not in flow
