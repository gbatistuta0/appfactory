import json
from pathlib import Path

from appfactory import app, gates, orchestrator, pipeline


def _scaffold(tmp_path: Path) -> Path:
    r = app.scaffold("Gt", "com.example.gt", dest_dir=str(tmp_path), generate=False)
    assert r["ok"], r
    return Path(r["dir"])


def _marker(a: Path, **data) -> None:
    mk = a / ".appfactory" / "verify" / "analytics.json"
    mk.parent.mkdir(parents=True, exist_ok=True)
    mk.write_text(json.dumps(data), encoding="utf-8")


def test_analytics_stage_sits_after_localize_and_routes_to_features():
    assert pipeline.STAGES.index("analytics") == pipeline.STAGES.index("localize") + 1
    assert orchestrator.route("analytics") == "feature-agent"
    assert "screen" in pipeline.STAGE_INSTRUCTIONS["analytics"]


def test_template_is_instrumented_and_needs_the_marker(tmp_path):
    a = _scaffold(tmp_path)
    assert "marker" in gates.validate_stage(a, "analytics")["reason"]
    _marker(a, build_ok=True, per_screen=False)
    assert not gates.validate_stage(a, "analytics")["ok"]
    _marker(a, build_ok=True, per_screen=True)
    r = gates.validate_stage(a, "analytics")
    assert r["ok"], r


def test_screen_without_screen_enter_fails(tmp_path):
    a = _scaffold(tmp_path)
    _marker(a, build_ok=True, per_screen=True)
    extra = a / "Sources" / "Main" / "HistoryView.swift"
    extra.write_text("import SwiftUI\nstruct HistoryView: View {\n    var body: some View { Text(\"History\") }\n}\n",
                     encoding="utf-8")
    r = gates.validate_stage(a, "analytics")
    assert not r["ok"] and "HistoryView.swift" in r["reason"]


def test_unlisted_analytics_param_is_reported(tmp_path):
    a = _scaffold(tmp_path)
    assert gates._check_analytics_params(gates._read_app_sources(a))["ok"]
    extra = a / "Sources" / "Main" / "Extra.swift"
    extra.write_text('func f() { Tracker.log(.resultView, ["mode": "photo", "from": x]) }\n', encoding="utf-8")
    r = gates._check_analytics_params(gates._read_app_sources(a))
    assert not r["ok"] and "mode (Extra.swift)" in r["reason"]
