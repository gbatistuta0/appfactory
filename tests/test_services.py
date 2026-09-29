"""Optional services: tool gating, n/a pipeline stages, and a scaffold that compiles without disabled SDKs.

Golden safety: with every service on (no `services` key in the config, as for every existing install)
the scaffold is byte-identical to tests/fixtures/scaffold_golden.json, recorded before service gating.
After an intended template change, regenerate it with `uv run python tests/test_services.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from appfactory import app, config, gates, pipeline, server

GOLDEN = Path(__file__).parent / "fixtures" / "scaffold_golden.json"
GOLDEN_CASES = {
    "subscription": {},
    "credits": {"monetization": "credits"},
    "health": {"health": {"enabled": True, "read": ["stepCount"], "write": []}, "consent": {"health": True}},
}


def _snapshot(overrides: dict) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as d:
        r = app.scaffold("Gold", "com.example.gold", dest_dir=d, spec=overrides or None, generate=False)
        assert r["ok"], r
        root = Path(r["dir"])
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}


def _services(monkeypatch, *off: str) -> None:
    """Config with every service on except `off`."""
    on = [s for s in config.SERVICES if s not in off]
    monkeypatch.setattr(config, "load_config", lambda: {"services": on})


@pytest.fixture
def all_on(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})  # no `services` key = everything on


# ---------- golden safety ----------

def test_all_services_on_scaffold_is_unchanged(all_on):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for case, overrides in GOLDEN_CASES.items():
        snap = _snapshot(overrides)
        assert sorted(snap) == sorted(golden[case]), f"{case}: file list changed"
        changed = [f for f in snap if snap[f] != golden[case][f]]
        assert not changed, f"{case}: files differ from the golden scaffold: {changed[:10]}"


def test_all_on_explicit_services_list_matches_absent_key(monkeypatch):
    _services(monkeypatch)  # explicit list with everything
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _snapshot({}) == golden["subscription"]


def test_all_on_gates_and_instructions_unchanged(all_on, tmp_path):
    pipeline.init(tmp_path, "Hue", "com.example.hue")
    for stage in pipeline.STAGES:
        assert gates.stage_disabled_service(stage) is None
        assert pipeline.stage_instruction(tmp_path, stage) == pipeline.STAGE_INSTRUCTIONS.get(stage, "")
    assert gates.validate_stage(tmp_path, "repo") == {"ok": False, "reason": ".git missing (repo not created)"}
    assert "n/a" not in pipeline.status(tmp_path)


# ---------- scaffold per disabled service ----------

def _scaffold(tmp_path: Path, **overrides) -> Path:
    r = app.scaffold("Svc", "com.example.svc", dest_dir=str(tmp_path), spec=overrides or None, generate=False)
    assert r["ok"], r
    return Path(r["dir"])


def _all_text(root: Path) -> str:
    """Swift + XcodeGen code, comment lines dropped."""
    lines = (line for p in root.rglob("*") if p.is_file() and p.suffix in {".swift", ".yml"}
             for line in p.read_text(encoding="utf-8").splitlines())
    return "\n".join(line for line in lines if not line.lstrip().startswith(("//", "#")))


def test_no_markers_left(monkeypatch, tmp_path):
    _services(monkeypatch, "revenuecat", "supabase", "firebase")
    text = _all_text(_scaffold(tmp_path))
    assert "@if " not in text and "@endif" not in text and "__FREE_USES__" not in text


def test_revenuecat_off(monkeypatch, tmp_path):
    _services(monkeypatch, "revenuecat")
    root = _scaffold(tmp_path)
    text = _all_text(root)
    assert "import RevenueCat" not in text and "Purchases." not in text
    yml = (root / "project.yml").read_text(encoding="utf-8")
    assert "purchases-ios" not in yml and "package: RevenueCat" not in yml
    assert "Firebase" in yml  # the others stay
    sm = (root / "Sources/Core/StoreManager.swift").read_text(encoding="utf-8")
    assert "product.purchase()" in sm and "AppStore.sync()" in sm and "currentEntitlements" in sm
    assert json.loads((root / "app.spec.json").read_text())["services"]["revenuecat"] is False


def test_firebase_off(monkeypatch, tmp_path):
    _services(monkeypatch, "firebase")
    root = _scaffold(tmp_path)
    text = _all_text(root)
    assert "import Firebase" not in text and "FirebaseApp" not in text and "FirebaseAnalytics.Analytics" not in text
    yml = (root / "project.yml").read_text(encoding="utf-8")
    assert "firebase-ios-sdk" not in yml and "package: Firebase" not in yml
    assert "import RevenueCat" in text
    assert "static func log(" in (root / "Sources/Core/Analytics.swift").read_text()  # the catalog stays


def test_supabase_off(monkeypatch, tmp_path):
    _services(monkeypatch, "supabase")
    root = _scaffold(tmp_path)
    assert not (root / "supabase").exists()
    gate = (root / "Sources/Core/LocalUsageGate.swift").read_text(encoding="utf-8")
    assert "static let freeUses = 1" in gate
    assert "LocalUsageGate.allows" in (root / "Sources/Main/GenerationFlow.swift").read_text()
    spec = json.loads((root / "app.spec.json").read_text())
    assert spec["ai"]["enabled"] is False and spec["services"]["supabase"] is False
    assert "aiEnabled = false" in (root / "Sources/App/AppSpec.swift").read_text()


def test_supabase_on_has_no_local_gate(all_on, tmp_path):
    root = _scaffold(tmp_path)
    assert (root / "supabase").is_dir() and not (root / "Sources/Core/LocalUsageGate.swift").exists()


def test_ai_service_off_makes_the_app_non_ai(monkeypatch, tmp_path):
    _services(monkeypatch, "ai")
    root = _scaffold(tmp_path)
    assert json.loads((root / "app.spec.json").read_text())["ai"]["enabled"] is False


def test_spec_overrides_config(monkeypatch, tmp_path):
    _services(monkeypatch, "revenuecat")
    root = _scaffold(tmp_path, services={"revenuecat": True})
    assert "import RevenueCat" in _all_text(root)


def test_incompatible_combinations_are_refused(monkeypatch, tmp_path):
    _services(monkeypatch, "revenuecat")
    r = app.scaffold("Svc", "com.example.svc", dest_dir=str(tmp_path), spec={"monetization": "credits"}, generate=False)
    assert not r["ok"] and "credits" in r["error"]
    _services(monkeypatch, "supabase")
    r = app.scaffold("Svc", "com.example.svc", dest_dir=str(tmp_path), spec={"ai": {"enabled": True}}, generate=False)
    assert not r["ok"] and "supabase" in r["error"]


def test_strip_blocks_negation():
    text = "a\n// @if !x\nb\n// @endif\n# @if x\nc\n# @endif\n"
    assert app.strip_blocks(text, {"x": True}) == "a\nc\n"
    assert app.strip_blocks(text, {"x": False}) == "a\nb\n"


# ---------- tools ----------

def test_disabled_service_tool_returns_without_side_effects(monkeypatch):
    _services(monkeypatch, "github")
    called = []
    monkeypatch.setattr(server.gh_mod, "create_private_repo", lambda *a, **k: called.append(1))
    r = server.github_create_repo("/tmp/x", "x")
    assert r["ok"] is False and r["service_disabled"] == "github"
    assert "appfactory services enable github" in r["error"] and not called


def test_tool_needing_two_services_reports_the_disabled_one(monkeypatch):
    _services(monkeypatch, "maestro")
    assert server.maestro_test("/tmp/x")["service_disabled"] == "maestro"


def test_every_gated_tool_exists_and_names_known_services():
    names = {n for n in dir(server) if callable(getattr(server, n))}
    for tool, needed in server.TOOL_SERVICES.items():
        assert tool in names, tool
        assert set(needed) <= set(config.SERVICES), (tool, needed)


def test_research_tools_are_never_gated():
    for t in ("idea_harvest", "idea_evaluate", "aso_search_hints", "aso_niche_score", "pricing_unit_economics",
              "metadata_check", "onboarding_plan", "legal_render", "design_research_collect", "pipeline_status",
              "pipeline_next", "config_doctor", "env_doctor"):
        assert t not in server.TOOL_SERVICES


def test_research_tools_work_without_a_config_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    script = f"""
import json
from appfactory import app, server, config
assert not config.CONFIG_PATH.exists()
r = app.scaffold("Nc", "com.example.nc", dest_dir={str(tmp_path)!r}, generate=False)
assert r["ok"], r
d = r["dir"]
from appfactory import pipeline
pipeline.init(d, "Nc", "com.example.nc")
out = {{
  "config_doctor": server.config_doctor(),
  "env_doctor": server.env_doctor(),
  "onboarding_plan": server.onboarding_plan(),
  "aso_unit_economics": server.aso_unit_economics(),
  "metadata_check": server.metadata_check(d + "/missing.md"),
  "pipeline_status": server.pipeline_status(d),
  "pipeline_next": server.pipeline_next(d),
  "legal_render": server.legal_render(d),
  "pricing_unit_economics": server.pricing_unit_economics(d, cost_photo=0.01, cost_text=0.001),
  "design_research_brief_template": server.design_research_brief_template(d),
}}
print(json.dumps({{k: isinstance(v, dict) and "service_disabled" not in v for k, v in out.items()}}))
"""
    env = {**os.environ, "HOME": str(home)}
    res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    results = json.loads(res.stdout.strip().splitlines()[-1])
    assert all(results.values()), results


# ---------- gates + pipeline ----------

def test_disabled_stage_is_skipped_and_reported(monkeypatch, tmp_path):
    _services(monkeypatch, "github", "apple")
    pipeline.init(tmp_path, "Hue", "com.example.hue")
    g = gates.validate_stage(tmp_path, "repo")
    assert g["ok"] and g["skipped"] and g["service_disabled"] == "github"
    assert gates.validate_stage(tmp_path, "testflight")["service_disabled"] == "apple"
    assert "n/a" in pipeline.stage_instruction(tmp_path, "asc_app")
    st = pipeline.status(tmp_path)
    assert st["n/a"]["repo"] == "github" and st["n/a"]["iap"] == "apple"
    assert pipeline.mark(tmp_path, "repo")["ok"]


def test_design_off_accepts_a_local_icon(monkeypatch, tmp_path):
    from appfactory import icon
    from appfactory.design import receipt
    _services(monkeypatch, "design")
    master = tmp_path / "design" / "icon.png"
    master.parent.mkdir(parents=True)
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * 1024 for _ in range(1024))
    master.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1024, 1024, 8, 2, 0, 0, 0))
                       + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    r = icon.install(tmp_path)
    assert r["ok"], r
    marker = json.loads(Path(r["marker"]).read_text())
    assert marker["source"] == "local" and marker["master_sha256"] == receipt.sha256(master)
    g = gates.validate_stage(tmp_path, "icon")
    assert g["ok"], g
    monkeypatch.setattr(config, "load_config", lambda: {})
    assert not gates.validate_stage(tmp_path, "icon")["ok"]  # with Claude Design on, a local icon is refused


if __name__ == "__main__":
    config.load_config = lambda: {}  # all services on
    GOLDEN.write_text(json.dumps({k: _snapshot(v) for k, v in GOLDEN_CASES.items()}, indent=1, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")
