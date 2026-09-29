"""spec.ai.enabled: AI is an optional edge. A non-AI app skips the analyze
function in deploy + gates and does not need FAL_KEY; the default stays an AI app (back-compat)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appfactory import ai, config, gates, pipeline, spec
from appfactory import supabase as supa
from backend_fixtures import REF, make_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".cfg" / "config.toml")


def test_default_is_ai_enabled_and_back_compat():
    s = spec.build("Hue", "com.example.hue")
    assert s["ai"]["enabled"] is True and spec.ai_enabled(s)
    legacy = {k: v for k, v in s.items() if k != "ai"} | {"ai": {"model": "m"}}   # pre-flag spec
    assert spec.ai_enabled(legacy) and spec.ai_enabled(None)
    assert supa.functions_for(s) == supa.FUNCTION_SETS["subscription"]
    assert "FAL_KEY" in supa.required_secrets(s)


def test_flag_validation():
    off = spec.build("Hue", "com.example.hue", ai={"enabled": False})
    assert spec.validate(off) == []
    assert "ai.enabled must be a boolean" in spec.validate(spec.build("Hue", "com.example.hue", ai={"enabled": "no"}))
    cred = spec.build("Hue", "com.example.hue", ai={"enabled": False}, monetization="credits")
    assert any("credits mode" in e for e in spec.validate(cred))


def test_non_ai_functions_and_secrets():
    off = spec.build("Hue", "com.example.hue", ai={"enabled": False})
    assert supa.functions_for(off) == ["usage-status", "delete-account", "legal", "rc-webhook"]
    assert supa.required_secrets(off) == ("RC_SECRET_KEY", "RC_PROJECT_ID")
    secrets, missing = supa.backend_secrets(off, {"fal_key": "f", "rc_secret_key": "s"}, {"rc_project_id": "p"})
    assert "FAL_KEY" not in secrets and "FAL_KEY" not in missing


def test_non_ai_deploy_skips_analyze(tmp_path: Path):
    app, sp = make_app(tmp_path, ai={"enabled": False})
    supa.apply_backend_mode(app, sp)
    config.update_app_outputs(app, rc_project_id="projHue")
    calls = []

    class Fake:
        def run_sql(self, ref, sql):
            return {"ok": True, "data": []}

        def set_secrets(self, ref, s):
            self.s = s
            return {"ok": True}

        def update_auth_config(self, ref, b):
            return {"ok": True}

    def runner(cmd, cwd=None, timeout=120, env=None):
        calls.append(cmd)
        return {"ok": True, "stdout": "", "stderr": ""}

    fake = Fake()
    r = ai.deploy_backend(app, REF, client=fake, runner=runner,
                          config={"rc_secret_key": "sk", "supabase_access_token": "t"}, dry_run=False)
    assert r["ok"] is True, r
    deployed = [c[3] for c in calls if c[:3] == ["supabase", "functions", "deploy"]]
    assert deployed == ["usage-status", "delete-account", "legal", "rc-webhook"]
    assert "FAL_KEY" not in fake.s and r["missing_required_secrets"] == []
    marker = json.loads((app / ".appfactory" / "verify" / "backend_deploy.json").read_text())
    assert marker["ai_enabled"] is False and "analyze" not in marker["functions"]
    assert ai.plan_backend(app)["functions"] == deployed


def _manifest(app: Path) -> None:
    d = app / ".appfactory"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"app": "Hue", "bundle_id": "com.example.hue", "dir": str(app),
                                              "stages": {s: "done" for s in pipeline.STAGES[:6]}}))


def test_gates_honour_the_flag(tmp_path: Path):
    app, sp = make_app(tmp_path, ai={"enabled": False})
    _manifest(app)
    (app / "Resources").mkdir()
    (app / "Resources" / "GoogleService-Info.plist").write_text("<key>GOOGLE_APP_ID</key><key>PROJECT_ID</key>")
    supa.apply_backend_mode(app, sp)
    supa.render_backend(app, sp)
    (app / "supabase" / "functions" / "_shared" / "analysis.ts").unlink()   # nothing to fill without AI
    assert gates.validate_stage(app, "backend")["ok"] is True
    v = app / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    marker = {"ok": True, "functions": ["usage-status", "delete-account", "legal", "rc-webhook"],
              "missing_secrets": ["FAL_KEY"], "legal_published": ["privacy/en"]}
    (v / "backend_deploy.json").write_text(json.dumps(marker))
    g = gates.validate_stage(app, "ai_proxy")
    assert g["ok"] is True and g["ai"] == "n/a"
    (v / "backend_deploy.json").write_text(json.dumps({**marker, "legal_published": []}))
    assert gates.validate_stage(app, "ai_proxy")["ok"] is False                # legal still gates
    (v / "backend_deploy.json").write_text(json.dumps({**marker, "functions": ["legal"]}))
    assert "usage-status" in gates.validate_stage(app, "ai_proxy")["reason"]

    # the same marker fails an AI app (analyze missing)
    on, sp_on = make_app(tmp_path / "on")
    _manifest(on)
    (on / ".appfactory" / "verify").mkdir(parents=True, exist_ok=True)
    (on / ".appfactory" / "verify" / "backend_deploy.json").write_text(json.dumps(marker))
    assert "analyze" in gates.validate_stage(on, "ai_proxy")["reason"]


def test_pipeline_instruction_follows_the_flag(tmp_path: Path):
    app, _ = make_app(tmp_path, ai={"enabled": False})
    assert "AI n/a" in pipeline.stage_instruction(app, "ai_proxy")
    assert "non-AI app" in pipeline.stage_instruction(app, "features")
    on, _ = make_app(tmp_path / "on")
    assert pipeline.stage_instruction(on, "ai_proxy") == pipeline.STAGE_INSTRUCTIONS["ai_proxy"]
