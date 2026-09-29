"""Phase 1 foundation tests: config, ASC client construction, tool registration."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

import pytest
from fastmcp import Client

from appfactory import config
from appfactory.server import mcp


def test_config_save_load_and_perms(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    config.update_config({"asc_key_id": "ABC", "fal_key": "secret123", "locales": ["en-US", "tr"]})
    c = config.load_config()
    assert c["asc_key_id"] == "ABC"
    assert c["fal_key"] == "secret123"
    assert c["locales"] == ["en-US", "tr"]
    # empty values must not wipe the existing config
    config.update_config({"asc_key_id": ""})
    assert config.load_config()["asc_key_id"] == "ABC"
    # 0600 izin
    assert stat.S_IMODE(os.stat(config.CONFIG_PATH).st_mode) == 0o600


def test_tools_registered():
    async def _list():
        async with Client(mcp) as c:
            return sorted(t.name for t in await c.list_tools())

    names = asyncio.run(_list())
    for expected in (
        "config_doctor", "config_set", "asc_token_check", "env_doctor",
        "build_xcode_version", "asc_list_apps", "asc_get_app",
    ):
        assert expected in names


def test_asc_client_requires_the_asc_binary(tmp_path: Path, monkeypatch):
    from appfactory import asc, asc_cli
    monkeypatch.setattr(asc_cli, "binary", lambda: None)
    with pytest.raises(asc.ASCError, match="brew install asc"):
        asc.ASCClient()


def test_incomplete_config_creds_fall_back_to_the_keychain_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    config.update_config({"asc_key_id": "ABC"})  # no issuer, no .p8
    from appfactory import asc_cli
    assert asc_cli.credentials_env() == {}
    assert asc_cli.auth_source() == "asc keychain profile"


def test_app_sanitize_target():
    from appfactory import app
    assert app._sanitize_target("Demo App") == "DemoApp"
    assert app._sanitize_target("123go")[0].isalpha()
    assert app._sanitize_target("!!!") == "App"


def test_app_replace_tokens(tmp_path: Path):
    from appfactory import app
    f = tmp_path / "AppConfig.swift"
    f.write_text('let bundle = "__BUNDLE_ID__"\nlet y = "__PRODUCT_YEARLY__"')
    app._replace_tokens(tmp_path, {"__BUNDLE_ID__": "com.x.y", "__PRODUCT_YEARLY__": "com.x.y.yearly"})
    out = f.read_text()
    assert "com.x.y" in out and "com.x.y.yearly" in out and "__BUNDLE_ID__" not in out


def test_inject_config_paywall_and_credit_defaults(tmp_path: Path):
    from appfactory import app
    f = tmp_path / "AppConfig.swift"
    f.write_text(
        "let y = __YEARLY_CREDITS__\nlet w = __WEEKLY_CREDITS__\n"
        "let s = __CREDIT_PACK_SMALL__\nlet show = __SHOW_OFFER_PAYWALL__"
    )
    res = app.inject_config(str(tmp_path))
    assert res["ok"] is True
    out = f.read_text()
    # yearly credits are PER MONTH and must beat the weekly plan's monthly equivalent
    # (10/week ~= 43/month), otherwise upgrading to yearly is pointless.
    assert "let y = 60" in out
    assert "let w = 10" in out
    assert "let s = 10" in out
    assert "let show = true" in out


def test_inject_config_paywall_hard_only_and_custom_credits(tmp_path: Path):
    from appfactory import app
    f = tmp_path / "AppConfig.swift"
    f.write_text("let y = __YEARLY_CREDITS__\nlet show = __SHOW_OFFER_PAYWALL__")
    res = app.inject_config(str(tmp_path), yearly_credits=20, paywall_strategy="hard_only")
    assert res["ok"] is True
    out = f.read_text()
    assert "let y = 20" in out
    assert "let show = false" in out


def test_inject_config_rejects_invalid_paywall_strategy(tmp_path: Path):
    from appfactory import app
    res = app.inject_config(str(tmp_path), paywall_strategy="bogus")
    assert res["ok"] is False


SAMPLE_META = """# en-US
## App Name
```
Demo App
```
## Subtitle
```
Best demo ever
```
## Promotional Text
```
Try it now
```
## Keyword Field
```
demo,app,test,utility
```
## Description
```
A great demo app description.
```
## What's New
```
First release.
```
# tr
## App Name
```
Demo Uygulama
```
## Subtitle
```
En iyi demo
```
## Promotional Text
```
Hemen dene
```
## Keyword Field
```
demo,uygulama,test
```
## Description
```
Harika bir demo açıklaması.
```
## What's New
```
İlk sürüm.
```
"""


def test_metadata_parse_and_export(tmp_path: Path):
    from appfactory import metadata as meta
    src = tmp_path / "apple-metadata.md"
    src.write_text(SAMPLE_META, encoding="utf-8")
    parsed = meta.parse(SAMPLE_META)
    assert set(parsed.keys()) == {"en-US", "tr"}
    assert parsed["en-US"]["name.txt"] == "Demo App"
    chk = meta.check(src)
    assert chk["ok"], chk
    dest = tmp_path / "fastlane" / "metadata"
    res = meta.export(src, dest)
    assert res["ok"] and res["count"] == 2
    assert (dest / "en-US" / "keywords.txt").read_text().strip() == "demo,app,test,utility"
    assert (dest / "tr" / "name.txt").read_text().strip() == "Demo Uygulama"


def test_metadata_limit_violation(tmp_path: Path):
    from appfactory import metadata as meta
    bad = SAMPLE_META.replace("Demo App", "X" * 40)  # name 40 > 30
    src = tmp_path / "bad.md"
    src.write_text(bad, encoding="utf-8")
    chk = meta.check(src)
    assert not chk["ok"]
    assert any("name.txt" in e for e in chk["errors"])


def test_pipeline_aso_gate(tmp_path: Path):
    """ASO gate: metadata gate is closed until aso is complete; opens once complete."""
    from appfactory import pipeline as pipe
    d = tmp_path / "DemoApp"
    d.mkdir()
    pipe.init(d, "DemoApp", "com.x.demo")
    (d / "DemoApp.xcodeproj").mkdir()  # scaffold gate: xcodeproj required
    (d / "project.yml").write_text(  # scaffold gate: iPhone-only + portrait required
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n'
        '    SUPPORTS_MACCATALYST: NO\n'
        '    SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD: NO\n'
        '    SUPPORTS_XR_DESIGNED_FOR_IPHONE_IPAD: NO\n',
        encoding="utf-8")
    assert pipe.mark(d, "scaffold", "done")["ok"]
    assert pipe.next_step(d)["next_stage"] == "repo"

    # aso not done → gate closed
    assert pipe.require_done(d, "aso") is not None

    # aso_run → outputs iskeleti + in_progress
    r = pipe.aso_run(d)
    assert r["ok"]
    assert pipe.load(d)["stages"]["aso"] == "in_progress"

    # empty skeleton → aso_complete fails (gate stays closed)
    assert not pipe.aso_complete(d)["ok"]
    assert pipe.load(d)["stages"]["aso"] != "done"

    # fill apple-metadata.md → aso_complete succeeds → gate opens
    meta_path = d / "outputs" / "DemoApp" / "02-metadata" / "apple-metadata.md"
    meta_path.write_text(SAMPLE_META, encoding="utf-8")
    assert pipe.aso_complete(d)["ok"]
    assert pipe.load(d)["stages"]["aso"] == "done"
    assert pipe.require_done(d, "aso") is None


def test_submit_for_review_requires_human_approval(monkeypatch):
    """Gated submit: without an approved approval_id it rejects without any API call, even with approvals off."""
    from appfactory import config, server
    config.save_config({"approvals": "off"})
    monkeypatch.setattr(server, "_asc", lambda: (_ for _ in ()).throw(AssertionError("API called")))

    async def _call(args):
        async with Client(mcp) as c:
            r = await c.call_tool("asc_submit_for_review", args)
            return r.data if hasattr(r, "data") else r

    d = asyncio.run(_call({"app_id": "123"}))
    assert d["ok"] is False and d["approval_required"] and "appfactory approve" in d["how"]
    assert "code" not in json.dumps(d)
    pending = asyncio.run(_call({"app_id": "123", "approval_id": d["approval_required"]}))
    assert pending["ok"] is False and "not approved" in pending["error"]


def test_submit_refuses_first_subscriptions_that_only_the_web_ui_can_submit(monkeypatch):
    """FIRST_SUBSCRIPTION_MUST_BE_SUBMITTED_ON_VERSION — the API cannot put the
    subscriptions into the version's review submission, so the tool stops before creating one."""
    from appfactory import asc, server
    made = []

    class FakeClient:
        def subscription_states(self, app_id):
            return {"com.x.weekly": "READY_TO_SUBMIT", "com.x.yearly": "MISSING_METADATA", "com.x.old": "APPROVED"}

        def create_review_submission(self, app_id):
            made.append(app_id)
            return {"ok": True, "data": {"data": {"id": "rs-1"}}}

    monkeypatch.setattr(server, "_asc", lambda: (FakeClient(), None))

    async def _call():
        async with Client(mcp) as c:
            first = await c.call_tool("asc_submit_for_review", {"app_id": "123"})
            first = first.data if hasattr(first, "data") else first
            aid = approve_next(first)
            r = await c.call_tool("asc_submit_for_review", {"app_id": "123", "approval_id": aid})
            return r.data if hasattr(r, "data") else r

    from conftest import approve_next
    d = asyncio.run(_call())
    assert d["ok"] is False and made == []
    assert len(d["blockers"]) == 2 and "In-App Purchases and Subscriptions" in d["next"]
    assert asc.submission_blockers({"a": "APPROVED", "b": "WAITING_FOR_REVIEW"}) == []


def test_create_app_auto_falls_through_on_name_taken(monkeypatch):
    """name_taken flag (even if the marker is truncated in stderr HEAD) → move to next candidate."""
    from appfactory import asc
    calls = []

    def fake_produce(bundle_id, name, sku=None, primary_language="en-US"):
        calls.append(name)
        if name == "Taken One":  # in the real world the marker is in stderr HEAD, tail is backtrace
            return {"ok": False, "stdout": "", "stderr": "...backtrace only...", "name_taken": True}
        return {"ok": True, "stdout": "Created", "stderr": "", "name_taken": False}

    class FakeClient:
        def get_app_by_bundle(self, b):
            return {"data": {"data": [{"id": "999", "attributes": {"name": "Free One"}}]}}

    monkeypatch.setattr(asc, "create_app_via_produce", fake_produce)
    monkeypatch.setattr(asc, "ASCClient", FakeClient)
    r = asc.create_app_auto("com.x.y", ["Taken One", "Free One"])
    assert r["ok"] is True and r["app_id"] == "999"
    assert calls == ["Taken One", "Free One"]  # first is taken → fell back to the second


def test_resolve_sim_udid_exact_and_fallback(monkeypatch):
    """If the default 'iPhone 16' is missing, auto-fall back to an available sim (udid) — live-run finding."""
    from appfactory import build
    fake = {"simulators": [
        {"name": "iPhone 16 Pro", "udid": "AAA", "runtime": "iOS-18-6"},
        {"name": "17", "udid": "BBB", "runtime": "iOS-26-2"},
        {"name": "iPad Air", "udid": "CCC", "runtime": "iOS-18-6"},
    ]}
    monkeypatch.setattr(build, "list_simulators", lambda: fake)
    assert build._resolve_sim_udid("17") == "BBB"          # exact name match
    assert build._resolve_sim_udid("iPhone 16") == "AAA"   # missing → fall back to iPhone-named sim
    monkeypatch.setattr(build, "list_simulators", lambda: {"simulators": []})
    assert build._resolve_sim_udid("17") is None           # None when there is no simulator


def test_newcomer_traction_dead_zone():
    """Dead zone: if newcomers cannot hold on, the niche LOOKS soft but cannot be entered.

    weak_ratio alone gives the wrong sign (a dead niche piles up tractionless apps, raising the score).
    TWO windows are required; 12 months alone hides a closed door (the hairstyle case).
    """
    from datetime import datetime, timedelta, timezone
    from appfactory.aso import _newcomer_traction

    def rel(days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def apps(*pairs):
        return [{"released": rel(d), "ratings_count": c} for d, c in pairs]

    # 1. Dead zone (plant identifier): nobody gained traction in 12 months.
    dead = _newcomer_traction(apps((300, 0), (200, 5), (150, 29), (100, 65), (60, 68)))
    assert dead["dead_zone"] is True
    assert dead["window_12mo"]["traction_over_500"] == 0

    # 2. DOOR CLOSED (hairstyle): 12 months shows traction but all older than 6 months;
    #    6 entries in the last 6 months, best has 4 ratings. A single window would MISS this.
    closed = _newcomer_traction(apps(
        (330, 10264), (300, 2732), (240, 1652),           # old cohort: gained traction
        (80, 4), (70, 3), (60, 2), (40, 1), (30, 1), (20, 0),  # new cohort: zero
    ))
    assert closed["dead_zone"] is True, "the 6-month window must catch the closure"
    assert closed["window_12mo"]["traction_over_500"] == 3   # the far window still says 'open'
    assert "DOOR CLOSED" in closed["reason"]

    # 3. Healthy: traction in both windows.
    alive = _newcomer_traction(apps((300, 5000), (200, 3200), (90, 800), (40, 250), (20, 30)))
    assert alive["dead_zone"] is False and alive["penalty"] == 0

    # 4. Age effect: fresh niche, apps are new but gaining traction; must NOT count as dead.
    young = _newcomer_traction(apps((80, 140), (60, 320), (40, 110), (25, 60), (15, 20)))
    assert young["dead_zone"] is False, "a 3-month-old app cannot be expected to have 500 ratings"

    # 5. Few samples in the near window = no evidence, do not declare dead.
    sparse_near = _newcomer_traction(apps((340, 900), (320, 700), (300, 1200), (60, 3)))
    assert sparse_near["dead_zone"] is False

    # 6. A single app with traction = weak signal, penalized but not dead.
    thin = _newcomer_traction(apps((300, 900), (200, 12), (100, 40), (50, 150)))
    assert thin["dead_zone"] is False and thin["penalty"] == 15

    # 7. Must not crash when the released field is missing.
    assert _newcomer_traction([{"ratings_count": 10}])["window_12mo"]["count"] == 0

    # 8. EMPTY list = measurement failed (rate limit), NOT a "clean niche". It must be flagged
    #    with measured=False, otherwise a scan reads it as 'enterable'.
    empty = _newcomer_traction([])
    assert empty["measured"] is False and empty["dead_zone"] is False
    assert "NOT MEASURED" in empty["reason"]
    assert _newcomer_traction([{"ratings_count": 10}])["measured"] is True
