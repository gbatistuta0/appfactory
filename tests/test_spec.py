import pytest

from appfactory import spec


def _hue():
    return spec.build("Hue", "com.example.hue")


def test_defaults_are_valid():
    assert spec.validate(_hue()) == []


def test_identity_and_prefix():
    s = _hue()
    assert s["sku"] == "comexamplehue"
    assert s["analytics"]["event_prefix"] == "hue_"
    assert spec.product_id(s, "yearly_offer") == "com.example.hue.yearly.offer"


def test_default_monetization():
    s = _hue()
    by_key = {p["key"]: p for p in spec.products(s)}
    assert by_key["yearly"]["intro"] == {"type": "free", "duration": "P3D"}
    assert by_key["weekly"]["intro"] == {"type": "free", "duration": "P3D"}
    assert by_key["yearly_offer"]["intro"] is None
    assert by_key["weekly"]["level"] > by_key["yearly"]["level"]  # weekly -> yearly is an upgrade
    assert s["locales"]["app"] == ["en", "es", "pt-BR", "de", "fr", "tr"]
    assert len(s["locales"]["store"]) == 8


def test_overrides_merge_deeply():
    s = spec.build("Hue", "com.example.hue", usage={"daily_caps": {"photo": 5}})
    assert s["usage"]["daily_caps"] == {"photo": 5, "text": 20}
    assert s["usage"]["free_lifetime_scans"] == 1


def test_offer_product_with_trial_is_rejected():
    s = _hue()
    s["subscription"]["products"][2]["intro"] = {"type": "free", "duration": "P3D"}
    assert any("never carry an intro" in e for e in spec.validate(s))


def test_unknown_override_product_and_bad_locale():
    s = _hue()
    s["subscription"]["price_overrides"]["EUR"]["monthly"] = 9.99
    s["locales"]["app"] = ["tr", "en"]
    errs = spec.validate(s)
    assert any("unknown product monthly" in e for e in errs)
    assert any("en fallback" in e for e in errs)


def test_bad_mascot_state():
    s = spec.build("Hue", "com.example.hue",
                   design={"mascot": {"name": "Hue", "species": "chameleon", "states": ["idle", "dance"]}})
    assert any("mascot states" in e for e in spec.validate(s))


def test_save_load_roundtrip(tmp_path):
    s = _hue()
    spec.save(tmp_path, s)
    assert spec.load(tmp_path) == s
    s["monetization"] = "ads"
    with pytest.raises(ValueError):
        spec.save(tmp_path, s)


def test_required_placements_and_onboarding_bounds():
    s = _hue()
    s["placements"] = [p for p in s["placements"] if p != "daily_cap"]
    s["offer_placements"] = ["offer_after_onboarding"]
    s["design"]["onboarding_screens"] = 8
    errs = spec.validate(s)
    assert any("daily_cap" in e for e in errs)
    assert any("onboarding_screens" in e for e in errs)
    s = _hue()
    s["placements"].append("Bad-Name")
    assert any("snake_case" in e for e in spec.validate(s))


def test_grace_period_default_and_validation():
    s = _hue()
    assert s["subscription"]["grace_period"] == {
        "enabled": True, "duration": "SIXTEEN_DAYS", "renewals": "ALL_RENEWALS", "sandbox": True}
    s["subscription"]["grace_period"]["duration"] = "DAY_16"   # not an ASC enum value
    s["subscription"]["grace_period"]["renewals"] = "SOME"
    errs = spec.validate(s)
    assert any("grace_period.duration" in e for e in errs)
    assert any("grace_period.renewals" in e for e in errs)
    off = spec.build("Hue", "com.example.hue", subscription={"grace_period": {"enabled": False}})
    assert spec.validate(off) == []


def test_usage_free_scans_and_caps_validation():
    s = spec.build("Hue", "com.example.hue", usage={"free_lifetime_scans": 3, "daily_caps": {"video": 2}})
    errs = spec.validate(s)
    assert any("free_lifetime_scans" in e for e in errs)
    assert any("daily_caps" in e for e in errs)


def test_capabilities_override_validation():
    assert spec.build("Hue", "com.example.hue")["capabilities"] == []
    ok = spec.build("Hue", "com.example.hue", capabilities=["ASSOCIATED_DOMAINS"])
    assert spec.validate(ok) == []
    bad = spec.build("Hue", "com.example.hue", capabilities=["push notifications"])
    assert any("capabilities" in e for e in spec.validate(bad))


def test_health_module_off_by_default_and_needs_consent():
    s = _hue()
    assert s["health"]["enabled"] is False
    s["health"]["enabled"] = True
    assert any("consent.health" in e for e in spec.validate(s))
    s["consent"]["health"] = True
    assert spec.validate(s) == []
    s["health"]["write"].append("dietaryCaffeine")
    assert any("not supported" in e for e in spec.validate(s))


def test_billing_issue_placement_uses_default_offering():
    s = _hue()
    assert len(s["placements"]) == 8 and s["placements"][-1] == "billing_issue"
    assert "billing_issue" not in s["offer_placements"]


def test_store_block_is_validated():
    s = spec.build("Hue", "com.example.hue", store={"primary_category": "HEALTH_AND_FITNESS",
                                                     "secondary_category": "FOOD_AND_DRINK"})
    assert spec.validate(s) == []
    assert spec.store(s)["excluded_territories"] == ["CHN"]
    bad = spec.build("Hue", "com.example.hue", store={"primary_category": "Health", "content_rights": "MAYBE",
                                                       "excluded_territories": ["CN"]})
    errs = " ".join(spec.validate(bad))
    assert "primary_category" in errs and "content_rights" in errs and "alpha-3" in errs
    same = spec.build("Hue", "com.example.hue", store={"primary_category": "NEWS", "secondary_category": "NEWS"})
    assert any("differ" in e for e in spec.validate(same))


def test_rating_rules_default_and_limits():
    s = _hue()
    assert spec.rating(s) == {"success_count": 5, "distinct_days": 3, "milestones": [7, 30],
                              "min_days_between": 60, "max_per_year": 3}
    old = {k: v for k, v in s.items() if k != "rating"}   # a spec written before the rating block
    assert spec.rating(old)["min_days_between"] == 60 and spec.validate(old) == []
    for bad in ({"min_days_between": 30}, {"max_per_year": 5}, {"milestones": [7, 7]}, {"success_count": 0}):
        assert spec.validate(spec.build("Hue", "com.example.hue", rating=bad)), bad
