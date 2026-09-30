import json

from appfactory import spec, storekit


def _hue(**kw):
    return spec.build("Hue", "com.example.hue", **kw)


def test_generate_matches_default_layout(tmp_path):
    s = _hue()
    doc = storekit.generate(s)
    assert doc["settings"]["_locale"] == "en_US"
    groups = doc["subscriptionGroups"]
    assert len(groups) == 1 and groups[0]["name"] == "Premium"
    subs = {x["productID"]: x for x in groups[0]["subscriptions"]}
    assert set(subs) == {"com.example.hue.yearly", "com.example.hue.weekly", "com.example.hue.yearly.offer"}
    assert subs["com.example.hue.weekly"]["introductoryOffer"]["paymentMode"] == "free"
    assert subs["com.example.hue.weekly"]["introductoryOffer"]["subscriptionPeriod"] == "P3D"
    assert subs["com.example.hue.yearly"]["introductoryOffer"]["subscriptionPeriod"] == "P3D"
    assert "introductoryOffer" not in subs["com.example.hue.yearly.offer"]
    assert subs["com.example.hue.yearly"]["displayPrice"] == "49.99"
    assert subs["com.example.hue.weekly"]["groupNumber"] == 2
    assert doc["products"] == []  # subscription-only: no consumables
    path = storekit.write(s, tmp_path)
    assert storekit.parity(s, path) == []
    assert json.loads(path.read_text()) == doc


def test_parity_reports_every_drift(tmp_path):
    s = _hue()
    path = storekit.write(s, tmp_path)
    doc = json.loads(path.read_text())
    subs = doc["subscriptionGroups"][0]["subscriptions"]
    subs[0]["displayPrice"] = "59.99"
    subs[1].pop("introductoryOffer")
    subs[2]["introductoryOffer"] = {"paymentMode": "free", "subscriptionPeriod": "P3D", "numberOfPeriods": 1}
    subs.append({**subs[0], "productID": "com.example.hue.monthly"})
    doc["settings"]["_locale"] = "de_DE"
    path.write_text(json.dumps(doc))
    out = "\n".join(storekit.parity(s, path))
    assert "price 59.99" in out
    assert "weekly: intro offer None" in out
    assert "yearly.offer: intro offer ('free', 'P3D') != spec None" in out
    assert "monthly: in storekit but not in spec" in out
    assert "locale" in out
    assert storekit.parity(s, tmp_path / "missing.storekit")[0].startswith("storekit file not found")


def test_credits_mode_adds_packs_and_parity_checks_them(tmp_path):
    s = _hue(monetization="credits")
    path = storekit.write(s, tmp_path)
    ids = [p["productID"] for p in json.loads(path.read_text())["products"]]
    assert ids == [f"com.example.hue.{p['suffix']}" for p in storekit.CREDIT_PACKS]
    assert storekit.parity(s, path) == []
    # a subscription spec must not sell consumables
    assert any("consumables" in m for m in storekit.parity(_hue(), path))


def test_price_change_in_spec_flows_to_storekit(tmp_path):
    s = _hue()
    s["subscription"]["products"][1]["usd"] = 9.99
    path = storekit.write(s, tmp_path)
    assert storekit.parity(s, path) == []
    assert storekit.parity(_hue(), path)  # old spec now drifts


def test_day_spelled_trial_is_written_and_compared_as_a_week(tmp_path):
    """P7D and P1W are the same offer: the config is written canonically and parity accepts both."""
    s = _hue()
    for p in s["subscription"]["products"]:
        if p.get("intro"):
            p["intro"]["duration"] = "P7D"
    path = storekit.write(s, tmp_path)
    subs = {x["productID"]: x for x in json.loads(path.read_text())["subscriptionGroups"][0]["subscriptions"]}
    assert subs["com.example.hue.weekly"]["introductoryOffer"]["subscriptionPeriod"] == "P1W"
    assert storekit.parity(s, path) == []            # the P7D spec still matches
    week = _hue()
    for p in week["subscription"]["products"]:
        if p.get("intro"):
            p["intro"]["duration"] = "P1W"
    assert storekit.parity(week, path) == []         # and so does the canonical one


def test_mcp_entries(tmp_path):
    spec.save(tmp_path, _hue())
    r = storekit.generate_for_app(tmp_path)
    assert r["ok"] and len(r["products"]) == 3
    assert storekit.parity_for_app(tmp_path) == {"ok": True, "storekit": r["storekit"], "mismatches": []}
    assert storekit.parity_for_app(tmp_path / "nope")["ok"] is False
