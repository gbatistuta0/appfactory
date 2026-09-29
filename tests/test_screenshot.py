"""screenshot onboarding hero prompts — must be app-agnostic (NO leftovers from another app)."""
from __future__ import annotations

from appfactory import screenshot as ss


def test_onboarding_prompts_app_agnostic_no_headshot():
    prompts = ss._onboarding_prompts("a meditation timer", count=11)
    assert len(prompts) == 11
    assert len(set(prompts)) == 11  # all distinct (no repeated image)
    joined = " ".join(prompts).lower()
    for banned in ("headshot", "businesswoman", "businessman", "blazer", "suit", "teal"):
        assert banned not in joined, f"hardcoded foreign-app leftover leaked: {banned}"
    assert all("meditation timer" in p for p in prompts)  # concept in every prompt


def test_onboarding_prompts_uses_app_provided():
    prompts = ss._onboarding_prompts("x", count=4, prompts=["scene A", "scene B"])
    assert prompts == ["scene A", "scene B", "scene A", "scene B"]


def test_onboarding_prompts_empty_concept_safe():
    prompts = ss._onboarding_prompts("", count=3)
    assert len(prompts) == 3 and len(set(prompts)) == 3


def test_region_locale_for_apple_locale():
    assert ss.region_locale("de-DE") == "de_DE"
    assert ss.region_locale("tr") == "tr_TR"
    assert ss.region_locale("ar-SA") == "ar_SA"
    assert ss.region_locale("zh-Hant") == "zh-Hant_TW"
    assert ss.region_locale("no") == "nb_NO"


def test_capture_uses_the_store_status_bar_and_region(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ss, "run", lambda cmd, **kw: calls.append(cmd) or {"ok": True})
    monkeypatch.setattr(ss.time, "sleep", lambda s: None)
    ss.capture_all("UDID", tmp_path, "com.x.hue", locales=["tr"])
    bar = calls[0]
    assert bar[:4] == ["xcrun", "simctl", "status_bar", "UDID"]
    assert bar[bar.index("--batteryState") + 1] == "discharging" and bar[bar.index("--batteryLevel") + 1] == "100"
    assert bar[bar.index("--time") + 1].endswith(".000Z")
    launch = next(c for c in calls if c[2] == "launch")
    assert launch[launch.index("-AppleLocale") + 1] == "tr_TR"
