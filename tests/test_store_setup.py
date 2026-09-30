"""store_setup: plan/check/apply against in-memory ASC and RevenueCat (fake HTTP, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appfactory import config, store_setup as ss
from backend_fixtures import make_app

CFG = {"support_email": "help@example.com", "legal_controller": "Ada Lovelace",
       "review_contact_phone": "+90 555 123 45 67", "rc_secret_key": "sk_test_not_real"}
S2S = "https://api.revenuecat.com/v1/incoming-webhooks/apple-server-to-server-notification/" + "a" * 32


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".cfg" / "config.toml")


def _apis(sp, **rc_kw):
    return (ss.MemoryAscApi(sp["bundle_id"], sku=sp["sku"], app_name="Hue"),
            ss.MemoryRcApi(**rc_kw))


def _apply(app, sp, asc, rc, **kw):
    return ss.run(app, mode="apply", confirm=sp["bundle_id"], asc_api=asc, rc_api=rc, config=CFG, **kw)


def test_plan_is_offline_and_orders_capabilities_first(tmp_path: Path):
    app, sp = make_app(tmp_path)
    r = ss.run(app, mode="plan", config={})
    assert r["ok"] is True, r["lines"]
    kinds = [ln.split()[0] for ln in r["lines"]]
    first_non_cap = next(i for i, ln in enumerate(r["lines"]) if "capability" not in ln)
    assert all("capability" in ln for ln in r["lines"][:first_non_cap])
    assert any("capability APPLE_ID_AUTH (PRIMARY_APP_CONSENT)" in ln for ln in r["lines"][:first_non_cap])
    assert "CREATE" in kinds
    assert not (app / ".appfactory" / "outputs.json").exists()   # plan writes nothing


def test_capabilities_from_spec():
    from appfactory import spec
    base = spec.build("Hue", "com.example.hue")
    assert [c["capabilityType"] for c in ss.capabilities(base)] == ["IN_APP_PURCHASE", "APPLE_ID_AUTH"]
    apple = ss.capabilities(base)[1]
    assert apple["settings"] == [{"key": "APPLE_ID_AUTH_APP_CONSENT", "options": [{"key": "PRIMARY_APP_CONSENT"}]}]
    health = dict(base, health={"enabled": True}, push={"enabled": False}, capabilities=["ASSOCIATED_DOMAINS"])
    assert [c["capabilityType"] for c in ss.capabilities(health)] == [
        "IN_APP_PURCHASE", "APPLE_ID_AUTH", "HEALTHKIT", "ASSOCIATED_DOMAINS"]
    assert "PUSH_NOTIFICATIONS" in [c["capabilityType"] for c in ss.capabilities(dict(base, push={"enabled": True}))]


def test_capabilities_check_reports_missing_and_extra_then_apply_is_idempotent(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, _ = _apis(sp)
    asc._put({"type": "bundleIdCapabilities", "id": "cap-push", "attributes": {"capabilityType": "PUSH_NOTIFICATIONS"},
              "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": "bid-1"}}}})
    asc._put({"type": "bundleIdCapabilities", "id": "cap-gc", "attributes": {"capabilityType": "GAME_CENTER"},
              "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": "bid-1"}}}})
    chk = ss.run(app, mode="check", target="capabilities", asc_api=ss.DryRunApi(asc), config=CFG)
    assert any(ln.startswith("CREATE") and "APPLE_ID_AUTH" in ln for ln in chk["lines"])
    assert any(ln.startswith("OK") and "IN_APP_PURCHASE" in ln for ln in chk["lines"])
    assert any(ln.startswith("EXTRA") and "GAME_CENTER" in ln for ln in chk["lines"])
    assert any(ln.startswith("CONFLICT") and "PUSH_NOTIFICATIONS" in ln for ln in chk["lines"])
    assert asc.writes == []   # check never writes
    assert ss.capabilities_pending(app) == ["APPLE_ID_AUTH", "IN_APP_PURCHASE"]

    # apply refuses without the confirmation
    assert ss.run(app, mode="apply", target="capabilities", asc_api=asc, config=CFG)["ok"] is False
    ap = ss.run(app, mode="apply", target="capabilities", confirm=sp["bundle_id"], asc_api=asc, config=CFG)
    types = {c["attributes"]["capabilityType"]: c for c in asc.items("bundleIdCapabilities")}
    assert types["APPLE_ID_AUTH"]["attributes"]["settings"][0]["options"] == [{"key": "PRIMARY_APP_CONSENT"}]
    assert ap["summary"]["changes"] == 1
    assert ss.capabilities_pending(app) == []
    again = ss.run(app, mode="apply", target="capabilities", confirm=sp["bundle_id"], asc_api=asc, config=CFG)
    assert again["summary"]["changes"] == 0


def test_unregistered_bundle_id_is_a_conflict(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, _ = _apis(sp)
    asc.store["bundleIds"].clear()
    r = ss.run(app, mode="check", target="capabilities", asc_api=ss.DryRunApi(asc), config=CFG)
    assert r["ok"] is False and any("not registered" in ln for ln in r["lines"])


def test_apply_asc_matches_the_spec(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, rc = _apis(sp)
    r = _apply(app, sp, asc, rc, target="asc", rc_apple_notification_url=S2S)
    assert r["ok"] is True, [ln for ln in r["lines"] if ln.startswith(("CONFLICT", "ERROR"))]
    subs = {s["attributes"]["productId"]: s for s in asc.items("subscriptions")}
    assert set(subs) == {"com.example.hue.yearly", "com.example.hue.weekly", "com.example.hue.yearly.offer"}
    assert subs["com.example.hue.weekly"]["attributes"]["groupLevel"] == 2
    assert subs["com.example.hue.yearly"]["attributes"]["subscriptionPeriod"] == "ONE_YEAR"

    offers = asc.items("subscriptionIntroductoryOffers")
    by_sub: dict[str, set[str]] = {}
    for o in offers:
        sid = o["relationships"]["subscription"]["data"]["id"]
        by_sub.setdefault(sid, set()).add(o["relationships"]["territory"]["data"]["id"])
        assert (o["attributes"]["offerMode"], o["attributes"]["duration"]) == ("FREE_TRIAL", "THREE_DAYS")
    offer_id = subs["com.example.hue.yearly.offer"]["id"]
    assert offer_id not in by_sub                                   # offer product: NO intro offer
    for key in ("yearly", "weekly"):
        terrs = by_sub[subs[f"com.example.hue.{key}"]["id"]]
        assert "CHN" not in terrs and "USA" in terrs and len(terrs) == 9   # one per sold territory

    # availability before prices, no CHN
    writes = [k for _, k in asc.writes]
    assert writes.index("subscriptionAvailabilities") < writes.index("subscriptionPrices")
    av = asc.items("subscriptionAvailabilities")[0]
    assert "CHN" not in {t["id"] for t in av["relationships"]["availableTerritories"]["data"]}

    # price overrides by currency (EUR → DEU/FRA/ESP, BRL, TRY), latest price wins
    yid = subs["com.example.hue.yearly"]["id"]
    prices = [p for p in asc.items("subscriptionPrices") if p["relationships"]["subscription"]["data"]["id"] == yid]
    latest: dict[str, str] = {}
    for p in sorted(prices, key=lambda x: x["attributes"]["startDate"]):
        latest[p["relationships"]["territory"]["data"]["id"]] = p["relationships"]["subscriptionPricePoint"]["data"]["id"].split("|")[3]
    assert latest["USA"] == "49.99" and latest["TUR"] == "1249.99" and latest["BRA"] == "199.9"
    # CHN is not sold (availability above) but still PRICED: the first subscription submission is refused
    # with MISSING_PRICING_DATA for any unpriced territory
    assert latest["DEU"] == "49.99" and latest["CHN"] == "49.99"

    # app level: availability without CHN, free price, content rights, brand copyright, no demo account
    avail = asc.items("appAvailabilities")[0]
    assert avail["attributes"]["availableInNewTerritories"] is True
    terr = {t["relationships"]["territory"]["data"]["id"]: t["attributes"]["available"] for t in asc.items("territoryAvailabilities")}
    assert terr["CHN"] is False and terr["USA"] is True and len(terr) == 10
    free = asc.items("appPrices")[0]
    assert free["relationships"]["appPricePoint"]["data"]["id"] == "app-pp|USA|0.0"
    assert asc.items("apps")[0]["attributes"]["contentRightsDeclaration"] == "DOES_NOT_USE_THIRD_PARTY_CONTENT"
    assert asc.items("appStoreVersions")[0]["attributes"]["copyright"].endswith(" Hue")
    assert "Ada" not in asc.items("appStoreVersions")[0]["attributes"]["copyright"]
    assert asc.items("appStoreReviewDetails")[0]["attributes"]["demoAccountRequired"] is False
    assert any("spec.store.primary_category" in m for m in r["manual"])

    gp = asc.items("subscriptionGracePeriods")[0]["attributes"]
    assert gp == {"optIn": True, "sandboxOptIn": True, "duration": "SIXTEEN_DAYS", "renewalType": "ALL_RENEWALS"}
    app_attrs = asc.items("apps")[0]["attributes"]
    assert app_attrs["subscriptionStatusUrl"] == S2S and app_attrs["subscriptionStatusUrlVersion"] == "V2"
    assert app_attrs["subscriptionStatusUrlForSandbox"] == S2S
    assert asc.items("ageRatingDeclarations")[0]["attributes"]["healthOrWellnessTopics"] is False
    contact = asc.items("appStoreReviewDetails")[0]["attributes"]
    assert contact["contactFirstName"] == "Ada" and contact["contactEmail"] == "help@example.com"
    info = {x["attributes"]["locale"]: x["attributes"] for x in asc.items("appInfoLocalizations")}
    assert info["tr"]["privacyPolicyUrl"].endswith("/legal/privacy?lang=tr")
    assert len(asc.items("subscriptionGroupLocalizations")) == 8

    outs = config.app_outputs(app)
    assert outs["asc_app_id"] == "app-1" and outs["rc_apple_notification_url"] == S2S
    marker = json.loads((app / ss.MARKER_REL).read_text())
    assert marker["ok"] is True
    # the phone never appears in the report
    assert not any("555" in ln for ln in r["lines"])

    again = _apply(app, sp, asc, rc, target="asc")
    assert again["summary"]["changes"] == 0, [ln for ln in again["lines"] if ln.startswith(("CREATE", "UPDATE"))]


def test_missing_s2s_url_is_exactly_one_manual_line(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, rc = _apis(sp)
    r = _apply(app, sp, asc, rc, target="asc")
    s2s = [m for m in r["manual"] if "Server-to-Server" in m]
    assert s2s == [ss.RC_S2S_MANUAL]
    assert "subscriptionStatusUrl" not in asc.items("apps")[0]["attributes"]
    bad = ss.run(app, mode="check", rc_apple_notification_url="https://example.com/hook", config=CFG)
    assert bad["ok"] is False and "incoming-webhooks" in bad["error"]


def test_intro_offer_on_offer_product_and_wrong_period_are_conflicts(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, rc = _apis(sp)
    _apply(app, sp, asc, rc, target="asc", rc_apple_notification_url=S2S)
    offer = next(s for s in asc.items("subscriptions") if s["attributes"]["productId"].endswith(".offer"))
    asc._put({"type": "subscriptionIntroductoryOffers", "id": "rogue", "attributes": {"offerMode": "FREE_TRIAL", "duration": "THREE_DAYS"},
              "relationships": {"subscription": {"data": {"type": "subscriptions", "id": offer["id"]}},
                                "territory": {"data": {"type": "territories", "id": "USA"}}}})
    weekly = next(s for s in asc.items("subscriptions") if s["attributes"]["productId"].endswith(".weekly"))
    weekly["attributes"]["subscriptionPeriod"] = "ONE_MONTH"
    r = ss.run(app, mode="check", target="asc", asc_api=ss.DryRunApi(asc), config=CFG)
    conflicts = [ln for ln in r["lines"] if ln.startswith("CONFLICT")]
    assert any("yearly.offer" in c and "spec says none" in c for c in conflicts)
    assert any("weekly" in c and "cannot be reused" in c for c in conflicts)
    assert r["ok"] is False


def test_sku_mismatch_and_missing_app_are_conflicts(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc = ss.MemoryAscApi(sp["bundle_id"], sku="OTHER", app_name="Hue")
    r = ss.run(app, mode="check", target="asc", asc_api=ss.DryRunApi(asc), config=CFG)
    assert any("SKU OTHER" in ln for ln in r["lines"])
    asc.store["apps"].clear()
    r2 = ss.run(app, mode="check", target="asc", asc_api=ss.DryRunApi(asc), config=CFG)
    assert any("asc_create_app" in ln for ln in r2["lines"])


def test_check_refuses_incomplete_listing(tmp_path: Path):
    app, sp = make_app(tmp_path, listing=False)
    import shutil
    from appfactory import app as app_mod
    shutil.copy(app_mod.TEMPLATE_DIR / "store" / "metadata" / "listing.json", app / "store" / "metadata" / "listing.json")
    r = ss.run(app, mode="check", config=CFG)
    assert r["ok"] is False and r["errors"]
    assert ss.run(app, mode="plan", config={})["validation_errors"]   # plan still runs, lists them


def test_asc_live_adapter_retries_gets_only():
    calls = []

    class FakeClient:
        def __init__(self, results):
            self.results = results

        def request(self, method, path, params=None, json=None):
            calls.append(method)
            return self.results.pop(0)

    api = ss.LiveAscApi(FakeClient([{"ok": False, "status": 500}, {"ok": True, "data": {"data": []}}]), sleep=lambda s: None)
    assert api.get("/v1/x") == {"data": []}
    assert calls == ["GET", "GET"]
    calls.clear()
    post = ss.LiveAscApi(FakeClient([{"ok": False, "status": 500, "error": "boom"}]), sleep=lambda s: None)
    with pytest.raises(ss.ApiError):
        post.post("/v1/x", {})
    assert calls == ["POST"]   # writes are never retried in-run


def test_apply_rc_creates_everything_and_is_idempotent(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _, rc = _apis(sp)
    r = _apply(app, sp, None, rc, target="rc")
    assert r["ok"] is True, r["lines"]
    assert [p["name"] for p in rc.projects] == ["Hue"]
    assert {p["store_identifier"] for p in rc.products} == {
        "com.example.hue.yearly", "com.example.hue.weekly", "com.example.hue.yearly.offer"}
    ent = rc.entitlements[0]
    assert ent["lookup_key"] == "premium" and len(ent["_attached"]) == 3
    offerings = {o["lookup_key"]: o for o in rc.offerings}
    assert offerings["default"]["is_current"] is True and offerings["offer"]["is_current"] is False
    pk = {(k["_offering"], k["lookup_key"]): k for k in rc.packages}
    yearly_offer = next(p["id"] for p in rc.products if p["store_identifier"].endswith("yearly.offer"))
    assert pk[(offerings["offer"]["id"], "$rc_annual")]["_products"] == [yearly_offer]
    assert (offerings["default"]["id"], "$rc_weekly") in pk
    rule = rc.rules[0]
    placements = {p["placement_identifier"]: p["offering_id"] for p in rule["placements"]["placement_offerings"]}
    assert placements["offer_after_onboarding"] == offerings["offer"]["id"]
    assert placements["app_open_offer"] == offerings["offer"]["id"]
    assert placements["free_scan_used"] == offerings["default"]["id"]
    assert rule["state"] == "active" and rule["placements"]["fallback_offering_id"] == offerings["default"]["id"]
    outs = config.app_outputs(app)
    assert outs["rc_project_id"] == rc.projects[0]["id"] and outs["rc_app_id"] and outs["rc_public_key"] == "appl_test"
    n = len(rc.writes)
    again = _apply(app, sp, None, rc, target="rc")
    assert again["summary"]["changes"] == 0 and len(rc.writes) == n


def test_rc_fallbacks_emit_mcp_plans(tmp_path: Path):
    app, sp = make_app(tmp_path)
    # project-scoped key: cannot create projects → MCP create-project plan, nothing else
    r = _apply(app, sp, None, ss.MemoryRcApi(can_create_project=False), target="rc")
    assert r["mcp_plan"][0]["tool"] == "create-project" and r["mcp_plan"][0]["args"]["body"]["name"] == "Hue"
    # targeting rule REST refused → structured MCP create-targeting-rule plan
    rc = ss.MemoryRcApi(projects=[{"id": "projX", "name": "Hue"}], targeting_rest=False)
    r2 = _apply(app, sp, None, rc, target="rc")
    plan = [p for p in r2["mcp_plan"] if p["tool"] == "create-targeting-rule"][0]
    assert plan["args"]["project_id"] == "projX"
    assert len(plan["args"]["body"]["placements"]["placement_offerings"]) == len(sp["placements"])


def test_rc_conflicting_targeting_rule(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _, rc = _apis(sp)
    _apply(app, sp, None, rc, target="rc")
    rc.rules[0]["placements"]["placement_offerings"][0]["offering_id"] = "other"
    r = ss.run(app, mode="check", target="rc", rc_api=ss.DryRunApi(rc), config=CFG)
    assert any(ln.startswith("CONFLICT") and "targeting rule" in ln for ln in r["lines"])


def test_rc_targeting_rule_missing_placement_is_added(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _, rc = _apis(sp)
    _apply(app, sp, None, rc, target="rc")
    offs = rc.rules[0]["placements"]["placement_offerings"]
    dropped = offs.pop()["placement_identifier"]  # live rule predates a new placement
    offs.append({"placement_identifier": "legacy_extra", "offering_id": "keep"})
    r = _apply(app, sp, None, rc, target="rc")
    assert any(ln.startswith("UPDATE") and dropped in ln for ln in r["lines"])
    have = {x["placement_identifier"] for x in rc.rules[0]["placements"]["placement_offerings"]}
    assert dropped in have and "legacy_extra" in have and len(rc.rules) == 1
    assert rc.rules[0]["placements"]["fallback_offering_id"]


def test_live_rc_adapter_backs_off_on_429_and_retries_get_5xx():
    class R:
        def __init__(self, code, body=b"{}", headers=None):
            self.status_code, self.content, self.headers = code, body, headers or {}
            self.text = body.decode()

        def json(self):
            return json.loads(self.content or b"{}")

    class Http:
        def __init__(self, seq):
            self.seq, self.calls = seq, []

        def request(self, method, url, params=None, json=None):
            self.calls.append((method, url))
            return self.seq.pop(0)

    http = Http([R(429, b'{"backoff_ms": 10}'), R(503), R(200, b'{"items": []}')])
    api = ss.LiveRcApi("k", http=http, sleep=lambda s: None)
    assert api.get("/projects") == {"items": []}
    assert http.calls[0][1] == "https://api.revenuecat.com/v2/projects" and len(http.calls) == 3
    http2 = Http([R(500, b'{"x":1}')])
    with pytest.raises(ss.ApiError):
        ss.LiveRcApi("k", http=http2, sleep=lambda s: None).post("/projects", {})
    assert len(http2.calls) == 1


def test_pricing_unit_economics_uses_measured_cost(tmp_path: Path):
    app, sp = make_app(tmp_path)
    res = app / "backend" / "eval" / "results"
    res.mkdir(parents=True)
    (res / "2026-09-24T17-22-18.json").write_text(json.dumps({"scores": [
        {"model": sp["ai"]["model"], "cost_per_call_usd": 0.002, "cost_per_call_by_mode": {"photo": 0.0022, "text": 0.0016}}]}))
    out = ss.write_pricing(app)
    assert out["ok"] and out["cost_photo"] == 0.0022 and out["cost_text"] == 0.0016
    caps = next(r for r in out["rows"] if r["profile"].startswith("Both caps"))
    assert caps["ai_cost_year"] == round((12 * 0.0022 + 20 * 0.0016) * 365, 2)
    md = (app / "store" / "pricing.md").read_text()
    assert "Measured AI cost per call (backend/eval/results/2026-09-24T17-22-18.json)" in md
    assert "`com.example.hue.yearly.offer`" in md and "Not generated yet" not in md
    assert "SIXTEEN_DAYS" in md
    empty, _ = make_app(tmp_path / "b")
    assert ss.write_pricing(empty)["ok"] is False
    assert ss.write_pricing(empty, cost_photo=0.003, cost_text=0.002)["ok"] is True


def test_categories_and_content_rights_follow_the_spec(tmp_path: Path):
    app, sp = make_app(tmp_path, store={"primary_category": "HEALTH_AND_FITNESS", "secondary_category": "FOOD_AND_DRINK",
                                        "content_rights": "USES_THIRD_PARTY_CONTENT", "copyright": "© 2026 Hue Labs"})
    asc, rc = _apis(sp)
    r = _apply(app, sp, asc, rc, target="asc", rc_apple_notification_url=S2S)
    assert r["ok"] is True, r["lines"]
    rel = asc.items("appInfos")[0]["relationships"]
    assert rel["primaryCategory"]["data"] == {"type": "appCategories", "id": "HEALTH_AND_FITNESS"}
    assert rel["secondaryCategory"]["data"]["id"] == "FOOD_AND_DRINK"
    assert asc.items("apps")[0]["attributes"]["contentRightsDeclaration"] == "USES_THIRD_PARTY_CONTENT"
    assert asc.items("appStoreVersions")[0]["attributes"]["copyright"] == "© 2026 Hue Labs"
    assert not any("category" in m for m in r["manual"])
    again = _apply(app, sp, asc, rc, target="asc")
    assert again["summary"]["changes"] == 0, [ln for ln in again["lines"] if ln.startswith(("CREATE", "UPDATE"))]


def test_existing_app_availability_is_never_overwritten(tmp_path: Path):
    app, sp = make_app(tmp_path)
    asc, rc = _apis(sp)
    asc._put({"type": "appAvailabilities", "id": "av-1", "attributes": {"availableInNewTerritories": True},
              "relationships": {"app": {"data": {"type": "apps", "id": "app-1"}}}})
    for t, on in (("USA", True), ("CHN", True)):
        asc._put({"type": "territoryAvailabilities", "id": f"ta-{t}", "attributes": {"available": on},
                  "relationships": {"territory": {"data": {"type": "territories", "id": t}},
                                    "appAvailability": {"data": {"type": "appAvailabilities", "id": "av-1"}}}})
    r = _apply(app, sp, asc, rc, target="asc", rc_apple_notification_url=S2S)
    assert any(ln.startswith("CONFLICT") and "excluded ['CHN']" in ln for ln in r["lines"])
    assert len(asc.items("appAvailabilities")) == 1


def test_review_notes_are_synced_without_markers_or_phone(tmp_path: Path):
    app, sp = make_app(tmp_path)
    notes = app / ss.REVIEW_NOTES_REL
    # the template's notes still carry placeholders: not synced, one MANUAL line
    asc, rc = _apis(sp)
    r = _apply(app, sp, asc, rc, target="asc", rc_apple_notification_url=S2S)
    assert any("review notes not synced" in m and "placeholders" in m for m in r["manual"])
    assert "notes" not in asc.items("appStoreReviewDetails")[0]["attributes"]

    notes.write_text("# Notes\n<!-- review-notes:start -->\n```text\nHue analyses colours. No login needed.\n"
                     "APPLE WATCH <!-- delete if not embedded -->\nNothing else.\n```\n<!-- review-notes:end -->\n")
    assert ss.review_notes_text(notes.read_text()) == "Hue analyses colours. No login needed.\nAPPLE WATCH\nNothing else."
    r = _apply(app, sp, asc, rc, target="asc")
    detail = asc.items("appStoreReviewDetails")[0]["attributes"]
    assert detail["notes"].startswith("Hue analyses colours.") and "<!--" not in detail["notes"]
    assert not any("review notes" in m for m in r["manual"])

    assert ss.review_notes_problems("Call +90 555 123 45 67 any time")
    assert ss.review_notes_problems("x" * 4001)
    assert ss.review_notes_problems("Released 2026-09-27, build 6.") == []


def test_every_trial_length_option_plans_clean(tmp_path: Path):
    """Each free-trial length run_options offers must pass store_setup's own validation (issue #1)."""
    from appfactory import options, spec as spec_mod
    answers = {o["id"]: o["default"] for o in options.OPTIONS}
    for days, iso in sorted(spec_mod.TRIAL_DAYS.items()):
        app, sp = make_app(tmp_path / f"trial{days}")
        spec_mod.save(app, options.apply_to_spec(sp, {**answers, "free_trial": True, "trial_days": days}))
        intros = {p["intro"]["duration"] for p in spec_mod.load(app)["subscription"]["products"] if p.get("intro")}
        assert intros == {iso}, (days, intros)
        r = ss.run(app, mode="plan", config=CFG)
        assert r["ok"] is True, (days, r["lines"])


def test_day_spelled_intro_duration_is_normalised(tmp_path: Path):
    """A spec written before the fix (P7D) still plans as the ONE_WEEK offer ASC models."""
    from appfactory import spec as spec_mod
    app, sp = make_app(tmp_path)
    for p in sp["subscription"]["products"]:
        if p.get("intro"):
            p["intro"]["duration"] = "P7D"
    spec_mod.save(app, sp)
    d = ss.desired_state(spec_mod.load(app), {})
    assert {s["intro_offer"]["duration"] for s in d["subscriptions"] if s["intro_offer"]} == {"ONE_WEEK"}
    assert [e for e in ss.validate_desired(d) if "intro" in e] == []
    assert ss.run(app, mode="plan", config=CFG)["ok"] is True
