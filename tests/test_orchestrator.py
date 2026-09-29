# tests/test_orchestrator.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from appfactory import orchestrator as orch
from appfactory.server import mcp


def test_route_known_stages():
    assert orch.route("design") == "design-agent"
    assert orch.route("icon") == "design-agent"  # the icon is a Claude Design board
    assert orch.route("features") == "feature-agent"
    assert orch.route("aso") == "aso-agent"
    assert orch.route("iap") == "asc-agent"
    assert orch.route("submission_prep") == "asc-agent"


def test_route_unknown_stage_defaults_general():
    assert orch.route("bogus") == "general-purpose"


def test_every_pipeline_stage_is_routable():
    from appfactory import pipeline as pipe
    # Even if unknown stages fall back to 'general-purpose', all known STAGES must be explicitly mapped
    for s in pipe.STAGES:
        assert s in orch.STAGE_AGENT, f"{s} missing from STAGE_AGENT"


def test_attempts_start_at_zero(tmp_path: Path):
    assert orch.attempts(tmp_path, "design") == 0


def test_record_attempt_increments_and_persists(tmp_path: Path):
    assert orch.record_attempt(tmp_path, "design") == 1
    assert orch.record_attempt(tmp_path, "design") == 2
    assert orch.attempts(tmp_path, "design") == 2
    # persistent: a fresh read also sees 2
    assert json.loads((tmp_path / ".appfactory" / "attempts.json").read_text())["design"] == 2
    # different stage is independent
    assert orch.attempts(tmp_path, "features") == 0


def test_should_retry_until_max(tmp_path: Path):
    for _ in range(orch.MAX_ATTEMPTS - 1):
        orch.record_attempt(tmp_path, "design")
    assert orch.should_retry(tmp_path, "design") is True   # MAX-1 attempts
    orch.record_attempt(tmp_path, "design")                # reached MAX
    assert orch.should_retry(tmp_path, "design") is False


def test_write_needs_human_creates_file(tmp_path: Path):
    p = orch.write_needs_human(tmp_path, "design", "Stitch timeout 5x",
                               "Check the Stitch MCP, then say 'continue'")
    f = Path(p)
    assert f.name == "NEEDS_HUMAN.md"
    txt = f.read_text(encoding="utf-8")
    assert "design" in txt
    assert "Stitch timeout 5x" in txt
    assert "Check the Stitch MCP" in txt
    assert "continue" in txt


from appfactory import config as cfg


def _all_keys():
    return {k: "x" for k in orch.REQUIRED_CONFIG_KEYS}


def test_preflight_ok_when_keys_and_session_fresh(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    monkeypatch.setattr(cfg, "resolve_asc_key_filepath", lambda c: Path("/tmp/AuthKey_x.p8"))
    from appfactory import asc_cli
    monkeypatch.setattr(asc_cli, "binary", lambda: "/opt/homebrew/bin/asc")
    from appfactory import maestro
    monkeypatch.setattr(maestro, "binary", lambda: "/opt/x/.maestro/bin/maestro")
    r = orch.preflight()
    assert r["ok"] is True
    assert r["blockers"] == []
    assert r["caffeinate_cmd"] == orch.CAFFEINATE_CMD


def test_preflight_blocks_on_missing_key(monkeypatch):
    keys = _all_keys()
    del keys["fal_key"]
    monkeypatch.setattr(cfg, "load_config", lambda: keys)
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    r = orch.preflight()
    assert r["ok"] is False
    assert "fal_key" in r["missing_config"]
    assert any("fal_key" in b for b in r["blockers"])


def test_preflight_blocks_on_stale_session(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": False, "stale": True})
    r = orch.preflight()
    assert r["ok"] is False
    assert any("spaceauth" in b for b in r["blockers"])


def test_preflight_blocks_without_the_asc_cli(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    monkeypatch.setattr(cfg, "resolve_asc_key_filepath", lambda c: Path("/tmp/AuthKey_x.p8"))
    from appfactory import asc_cli
    monkeypatch.setattr(asc_cli, "binary", lambda: None)
    r = orch.preflight()
    assert r["ok"] is False and any("brew install asc" in b for b in r["blockers"])


def test_preflight_blocks_without_maestro(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    monkeypatch.setattr(cfg, "resolve_asc_key_filepath", lambda c: Path("/tmp/AuthKey_x.p8"))
    from appfactory import asc_cli, maestro
    monkeypatch.setattr(asc_cli, "binary", lambda: "/opt/homebrew/bin/asc")
    monkeypatch.setattr(maestro, "binary", lambda: None)
    r = orch.preflight()
    assert r["ok"] is False and any("maestro" in b for b in r["blockers"])


def test_preflight_blocks_without_maestro_live(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    monkeypatch.setattr(cfg, "resolve_asc_key_filepath", lambda c: Path("/tmp/AuthKey_x.p8"))
    from appfactory import asc_cli, maestro
    monkeypatch.setattr(asc_cli, "binary", lambda: "/opt/homebrew/bin/asc")
    monkeypatch.setattr(maestro, "binary", lambda: "/fake/maestro")
    monkeypatch.setattr(maestro, "live_runner", lambda: None)
    r = orch.preflight()
    assert r["ok"] is False and any("maestro-live missing" in b for b in r["blockers"])


def test_preflight_blocks_when_p8_unresolvable(monkeypatch):
    monkeypatch.setattr(cfg, "load_config", lambda: _all_keys())
    monkeypatch.setattr(cfg, "session_status", lambda: {"present": True, "stale": False})
    monkeypatch.setattr(cfg, "resolve_asc_key_filepath", lambda c: None)
    r = orch.preflight()
    assert r["ok"] is False
    assert any(".p8" in b for b in r["blockers"])


from appfactory import pipeline as pipe


def test_next_action_fresh_manifest(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    r = orch.next_action(app)
    assert r["done"] is False
    assert r["stage"] == "scaffold"
    assert r["agent"] == "scaffold-agent"
    assert r["attempts"] == 0
    assert r["should_retry"] is True
    assert isinstance(r["instruction"], str) and r["instruction"]


def test_next_action_reflects_attempts(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    orch.record_attempt(app, "scaffold")
    orch.record_attempt(app, "scaffold")
    r = orch.next_action(app)
    assert r["stage"] == "scaffold"
    assert r["attempts"] == 2


def test_next_action_done_when_all_stages_done(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    # Set up the manifest by directly writing ALL stages as done (no gates, for testing)
    mpath = app / ".appfactory" / "state.json"
    data = json.loads(mpath.read_text())
    data["stages"] = {s: "done" for s in pipe.STAGES}
    mpath.write_text(json.dumps(data), encoding="utf-8")
    r = orch.next_action(app)
    assert r["done"] is True


def test_next_action_missing_manifest(tmp_path: Path):
    r = orch.next_action(tmp_path / "nope")
    assert r["ok"] is False


def test_orchestrator_tools_registered_and_run(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")

    async def _call():
        async with Client(mcp) as c:
            names = sorted(t.name for t in await c.list_tools())
            for n in ("orchestrator_preflight", "orchestrator_next_action",
                      "orchestrator_record_attempt", "orchestrator_needs_human"):
                assert n in names, f"{n} not registered"
            na = await c.call_tool("orchestrator_next_action", {"app_dir": str(app), "skip_options_check": True})
            na = na.data if hasattr(na, "data") else na
            ra = await c.call_tool("orchestrator_record_attempt",
                                   {"app_dir": str(app), "stage": "scaffold"})
            ra = ra.data if hasattr(ra, "data") else ra
            return na, ra

    na, ra = asyncio.run(_call())
    assert na["stage"] == "scaffold" and na["agent"] == "scaffold-agent"
    assert ra["attempts"] == 1 and ra["should_retry"] is True
