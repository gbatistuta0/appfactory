"""Run options: the declarative list, validation, saving, the scaffold merge and the pipeline refusal."""

from __future__ import annotations

import json

import pytest

from appfactory import config, gates, options, pipeline, server, spec


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".appfactory")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".appfactory" / "config.toml")
    return tmp_path


def _defaults() -> dict:
    return {o["id"]: o["default"] for o in options.OPTIONS}


def test_list_covers_every_service_but_research_and_the_required_toggles():
    ids = set(options.BY_ID)
    assert set(config.SERVICES) - {"research"} <= ids
    for want in ("monetization", "free_trial", "trial_days", "hard_paywall", "offer_paywall", "onboarding_quiz",
                 "mascot", "app_languages", "store_locales", "screenshots", "app_preview", "custom_product_pages",
                 "analytics_events", "rating_prompts", "healthkit", "sign_in_with_apple", "github_issues", "e2e_smoke"):
        assert want in ids
    for o in options.OPTIONS:
        assert o["kind"] in ("bool", "choice", "list", "number") and o["question"].endswith("?")
        assert set(o["requires"]) <= ids


def test_listing_has_current_values_and_instruction():
    r = server.run_options()
    assert r["ok"] and "run_options_save" in r["instruction"] and r["confirmed"] is False
    assert {o["id"]: o["current"] for o in r["options"]}["monetization"] == "subscription"


def test_validation_errors():
    a = _defaults()
    assert options.validate(a) == []
    assert any("missing" in e for e in options.validate({"apple": True}))
    bad = {**a, "free_trial": "yes", "monetization": "ads", "trial_days": 99, "bogus": 1}
    errs = " ".join(options.validate(bad))
    assert "unknown option ids" in errs and "free_trial" in errs and "monetization" in errs and "trial_days" in errs
    assert any("requires supabase" in e for e in options.validate({**a, "supabase": False}))
    errs = options.validate({**a, "monetization": "credits", "revenuecat": False})
    assert any("requires revenuecat" in e for e in errs)
    assert any("en" in e for e in options.validate({**a, "app_languages": ["de", "en"]}))
    # a trial length without a trial is fine
    assert options.validate({**a, "free_trial": False}) == []


def test_save_pending_then_scaffold_merges_and_consumes(tmp_path):
    a = {**_defaults(), "lottie": False, "free_trial": False, "mascot": False, "screenshots": False}
    r = server.run_options_save(a)
    assert r["ok"] and "lottie" not in r["services"] and r["saved_to"].endswith("run_options.json")
    assert options.confirmed()
    sp = options.merge_pending(spec.build("Zed", "com.example.zed"))
    assert sp["options_confirmed"] and sp["options"]["screenshots"] is False
    assert all(p["intro"] is None for p in sp["subscription"]["products"])
    options.consume_pending()
    assert not options.confirmed()


def test_save_into_existing_spec_and_stage_na(tmp_path):
    app = tmp_path / "App"
    app.mkdir()
    spec.save(app, spec.build("App", "com.example.app"))
    pipeline.init(app, "App", "com.example.app")
    a = {**_defaults(), "trial_days": 7, "app_preview": False, "healthkit": True}
    r = server.run_options_save(a, str(app))
    assert r["ok"], r
    sp = spec.load(app)
    assert sp["options_confirmed"] and sp["health"]["enabled"] and sp["consent"]["health"]
    assert sp["subscription"]["products"][0]["intro"]["duration"] == "P7D"
    g = gates.validate_stage(app, "app_preview")
    assert g["ok"] and g["option_disabled"] == "app_preview"
    assert "n/a" in pipeline.stage_instruction(app, "app_preview")


def test_pipeline_and_preflight_refuse_until_confirmed(tmp_path):
    app = tmp_path / "App"
    app.mkdir()
    pipeline.init(app, "App", "com.example.app")
    for r in (server.pipeline_next(str(app)), server.orchestrator_next_action(str(app)),
              server.orchestrator_preflight()):
        assert r["ok"] is False and r["options_unconfirmed"] and "run_options" in r["error"]
    assert server.pipeline_next(str(app), skip_options_check=True)["next_stage"] == "scaffold"
    server.run_options_save(_defaults())
    assert server.pipeline_next(str(app))["next_stage"] == "scaffold"


def test_playbook_asks_options_first():
    text = server.playbook()
    before = text.split("## Before you start", 1)[1]
    assert before.lstrip().startswith("0. **Setup first") and "\n1. **Ask about every optional part first.**" in before
    assert "setup_status()" in before and "run_options()" in before
