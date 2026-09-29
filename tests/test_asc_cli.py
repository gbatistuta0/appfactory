"""asc_cli.py (the asc CLI wrapper) and ASCClient's first-class commands, against a fake `asc` at the
subprocess level (no network)."""

from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

from asc_fake import FakeAsc, err

from appfactory import asc, asc_cli, config


def _creds(monkeypatch, tmp_path: Path, complete: bool = True):
    p8 = tmp_path / "AuthKey_K1.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\n")
    c = {"asc_key_id": "K1", "asc_issuer_id": "ISS"} if complete else {"asc_key_id": "K1"}
    c["asc_key_filepath"] = str(p8)
    monkeypatch.setattr(config, "load_config", lambda: c)
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(k, raising=False)
    return p8


# ---- wrapper ----

def test_run_adds_json_output_and_debug_and_parses(monkeypatch, tmp_path):
    p8 = _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {("apps", "list"): {"data": [{"id": "1"}]}})
    seen = {}
    real = fake._exec

    def spy(argv, *, timeout, env, stdin):
        seen["argv"] = argv
        return real(argv, timeout=timeout, env=env, stdin=stdin)
    monkeypatch.setattr(asc_cli, "_exec", spy)
    r = asc_cli.run(["apps", "list", "--limit=1"])
    assert r["ok"] is True and r["data"] == {"data": [{"id": "1"}]} and r["status"] == 200
    assert seen["argv"] == ["/fake/asc", "--api-debug", "apps", "list", "--limit=1", "--output", "json"]
    env = fake.envs[-1]
    assert env["ASC_KEY_ID"] == "K1" and env["ASC_ISSUER_ID"] == "ISS" and env["ASC_PRIVATE_KEY_PATH"] == str(p8)
    assert env["ASC_SPINNER_DISABLED"] == "1"


def test_incomplete_creds_leave_auth_to_the_keychain_profile(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path, complete=False)
    fake = FakeAsc(monkeypatch)
    asc_cli.run(["apps", "list"])
    assert "ASC_KEY_ID" not in fake.envs[-1]
    assert asc_cli.auth_source() == "asc keychain profile"


def test_read_only_env_is_passed_through(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    monkeypatch.setenv("ASC_READ_ONLY", "1")
    fake = FakeAsc(monkeypatch, {("api",): err("ASC_READ_ONLY is set; refusing POST /v1/bundleIds", code=6)})
    r = asc_cli.api("POST", "/v1/bundleIds", body={"data": {}})
    assert fake.envs[-1]["ASC_READ_ONLY"] == "1"
    assert r["ok"] is False and r["read_only"] is True and "refusing" in r["error"][0]["detail"]


def test_flag_values_escape_the_at_prefix():
    assert asc_cli.flag("notes", "@env:SECRET") == "--notes=@@env:SECRET"
    assert asc_cli.flag("contact-email", "a@b.com") == "--contact-email=a@b.com"
    assert asc_cli.flag("family-sharable", True) == "--family-sharable=true"
    assert asc_cli.flags(app_id="1", skip=None) == ["--app-id=1"]


def test_api_get_keeps_the_old_client_shape(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {("api", "GET", "/v1/apps"): {"data": [{"id": "1234567890"}]}})
    r = asc_cli.api("GET", "/v1/apps", params={"filter[bundleId]": "com.x", "limit": 5})
    assert r == {"ok": True, "status": 200, "data": {"data": [{"id": "1234567890"}]}}
    assert fake.calls[-1] == ["api", "GET", "/v1/apps", "--allow-unknown-path",
                              "--query=filter[bundleId]=com.x", "--query=limit=5"]


def test_api_write_confirms_and_sends_the_body_on_stdin(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {("api", "POST"): {"data": {"id": "new"}}, ("api", "DELETE"): ""})
    body = {"data": {"type": "profiles", "attributes": {"name": "@x"}}}
    r = asc_cli.api("POST", "/v1/profiles", body=body)
    assert r["ok"] and r["data"]["data"]["id"] == "new"
    assert fake.calls[-1][-3:] == ["--confirm", "--body-file", "-"] and json.loads(fake.stdins[-1]) == body
    d = asc_cli.api("DELETE", "/v1/profiles/p1")
    assert d == {"ok": True, "status": 200, "data": {}} and "--body-file" not in fake.calls[-1]


def test_api_error_carries_status_and_detail(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch, {("api",): err("api: The specified resource does not exist", status=404, code=4)})
    r = asc_cli.api("GET", "/v1/apps/000")
    assert r == {"ok": False, "status": 404,
                 "error": [{"status": "404", "detail": "api: The specified resource does not exist"}]}


def test_missing_binary_and_timeout(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    monkeypatch.setattr(asc_cli, "binary", lambda: None)
    r = asc_cli.run(["apps", "list"])
    assert r["ok"] is False and r["missing_binary"] and "brew install asc" in r["error"]
    assert asc_cli.api("GET", "/v1/apps")["ok"] is False
    monkeypatch.setattr(asc_cli, "binary", lambda: "/fake/asc")

    def slow(argv, *, timeout, env, stdin):
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(asc_cli, "_exec", slow)
    t = asc_cli.run(["builds", "upload"], timeout=5)
    assert t["ok"] is False and "timed out after 5s" in t["error"]


def test_non_json_stdout_is_kept_as_text(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch, {(): "5.7.0 (commit: unknown)"})   # `asc --version` has no command words
    v = asc_cli.version()
    assert v == {"ok": True, "path": "/fake/asc", "version": "5.7.0 (commit: unknown)"}


# ---- ASCClient first-class commands ----

def test_reads_use_first_class_commands(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {
        ("apps", "list"): {"data": [{"id": "A1", "attributes": {"bundleId": "com.x", "name": "X"}}]},
        ("subscriptions", "list"): {"data": [{"id": "s1", "attributes": {"productId": "com.x.weekly", "state": "READY_TO_SUBMIT"}},
                                             {"id": "s2", "attributes": {"productId": "com.x.yearly", "state": "APPROVED"}}]},
    })
    cl = asc.ASCClient()
    r = cl.get_app_by_bundle("com.x")
    assert r["ok"] and r["data"]["data"][0]["id"] == "A1"
    assert fake.calls[-1] == ["apps", "list", "--bundle-id=com.x"]
    assert cl.subscription_states("A1") == {"com.x.weekly": "READY_TO_SUBMIT", "com.x.yearly": "APPROVED"}
    assert fake.calls[-1] == ["subscriptions", "list", "--app=A1", "--paginate", "--limit=200"]


def test_create_commands(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {("subscriptions", "create"): {"data": {"id": "sub-1"}},
                                 ("review", "submissions-create"): {"data": {"id": "rs-1"}}})
    cl = asc.ASCClient()
    r = cl.create_subscription("g1", "com.x.yearly", "Yearly", "ONE_YEAR")
    assert r["ok"] and r["data"]["data"]["id"] == "sub-1"
    assert fake.calls[-1] == ["subscriptions", "create", "--group-id=g1", "--product-id=com.x.yearly",
                              "--reference-name=Yearly", "--subscription-period=ONE_YEAR"]
    cl.create_bundle_id("com.x", "X")
    assert fake.calls[-1] == ["bundle-ids", "create", "--identifier=com.x", "--name=X", "--platform=IOS"]
    assert cl.create_review_submission("A1")["data"]["data"]["id"] == "rs-1"
    cl.submit_review("rs-1")
    assert fake.calls[-1] == ["review", "submissions-submit", "--id=rs-1", "--confirm"]


def test_price_is_imported_for_every_equalized_territory(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    captured = {}

    def importer(args, stdin):
        path = FakeAsc.flag(args, "input")
        captured["rows"] = list(csv.reader(io.StringIO(Path(path).read_text())))
        return {"total": 3, "created": 3, "failed": 0}
    fake = FakeAsc(monkeypatch, {
        ("subscriptions", "pricing", "price-points", "list"): {"data": [{"id": "pp-usa", "attributes": {"customerPrice": "49.99"}}]},
        ("subscriptions", "pricing", "price-points", "equalizations"): {"data": [
            {"id": "pp-tur", "attributes": {"customerPrice": "1999.99"}, "relationships": {"territory": {"data": {"id": "TUR"}}}},
            {"id": "pp-chn", "attributes": {"customerPrice": "398.00"}, "relationships": {"territory": {"data": {"id": "CHN"}}}}]},
        ("subscriptions", "pricing", "prices", "import"): importer,
    })
    r = asc.ASCClient().set_subscription_price("sub1", "49.99")
    assert r == {"ok": True, "territories_set": 3, "skipped_or_failed": 0}
    assert captured["rows"] == [["territory", "price", "price_point_id"], ["USA", "49.99", "pp-usa"],
                                ["TUR", "1999.99", "pp-tur"], ["CHN", "398.00", "pp-chn"]]
    imp = fake.find("subscriptions", "pricing", "prices", "import")[0]
    assert "--confirm" in imp and not Path(FakeAsc.flag(imp, "input")).exists()   # temp CSV removed


def test_price_point_missing_is_reported(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch)
    r = asc.ASCClient().set_subscription_price("sub1", "49.99")
    assert r["ok"] is False and "49.99" in r["error"]


def test_finalize_subscription_follows_spec_intro(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {
        ("pricing", "territories", "list"): {"data": [{"id": "USA"}, {"id": "CHN"}, {"id": "TUR"}]},
        ("subscriptions", "pricing", "price-points", "list"): {"data": [{"id": "pp1", "attributes": {"customerPrice": "49.99"}}]},
        ("subscriptions", "pricing", "prices", "import"): {"created": 1, "failed": 0},
        ("subscriptions", "offers", "introductory", "create"): {"total": 2, "created": 2, "skipped": 0, "failed": 0},
        ("api", "POST"): {"data": {"id": "loc-1"}},
    })
    cl = asc.ASCClient()
    r = cl.finalize_subscription("sub1", "Hue Yearly", "desc", "49.99", period="ONE_YEAR",
                                 intro={"type": "free", "duration": "P3D"})
    assert r["ok"] is True and "note" in r
    avail = fake.find("subscriptions", "pricing", "availability", "edit")[0]
    assert FakeAsc.flag(avail, "territories") == "USA,TUR"            # CHN stays excluded
    offer = fake.find("subscriptions", "offers", "introductory", "create")[0]
    assert "--all-territories" in offer and FakeAsc.flag(offer, "offer-mode") == "FREE_TRIAL"
    assert FakeAsc.flag(offer, "offer-duration") == "THREE_DAYS"
    order = [FakeAsc.words(c)[:3] for c in fake.calls]
    assert order.index(("api", "POST", "/v1/subscriptionLocalizations")) < order.index(
        ("subscriptions", "pricing", "availability")) < order.index(("subscriptions", "pricing", "prices"))
    fake.calls.clear()
    cl.finalize_subscription("sub2", "Hue Offer", "desc", "29.99", period="ONE_YEAR")
    assert not fake.find("subscriptions", "offers", "introductory")   # offer product: no intro offer


def test_intro_offer_failures_are_listed(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch, {("subscriptions", "offers", "introductory", "create"): {
        "total": 3, "created": 1, "skipped": 1, "failed": 1, "failures": [{"territory": "BRA", "error": "x"}]}})
    r = asc.ASCClient().create_intro_offer_all_territories("sub1", "FREE_TRIAL", "ONE_WEEK")
    assert r == {"ok": False, "created": 1, "already": 1, "failed": ["BRA"]}


def test_submission_requirements_use_first_class_commands(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {
        ("apps", "list"): {"data": [{"id": "A1", "attributes": {"name": "Hue"}}]},
        ("versions", "list"): {"data": [{"id": "V1"}]},
        ("pricing", "schedule", "view"): err("no schedule", status=404),
        ("review", "details-for-version"): {"data": {"id": "RD1"}},
    })
    r = asc.ASCClient().finalize_submission_requirements(
        "com.x", copyright="© 2026 X", contact_first="A", contact_last="B", contact_phone="+1",
        contact_email="a@b.com", review_notes="@notes")
    assert r["ok"] is True, r
    assert fake.find("apps", "content-rights", "edit")[0][-1] == "--uses-third-party-content=false"
    assert fake.find("versions", "update")[0] == ["versions", "update", "--version-id=V1", "--copyright=© 2026 X"]
    assert "--all-none" in fake.find("age-rating", "edit")[0]
    assert "--free" in fake.find("pricing", "schedule", "create")[0]
    upd = fake.find("review", "details-update")[0]
    assert "--id=RD1" in upd and "--notes=@@notes" in upd and "--contact-email=a@b.com" in upd
    assert not fake.find("review", "details-create")


def test_upload_result_parsing(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {("screenshots", "upload"): {"setId": "set", "results": [
        {"fileName": "01.png", "assetId": "shot-1", "state": "uploaded"}]}})
    r = asc.ASCClient().upload_screenshot("loc-1", tmp_path / "01.png", "APP_IPHONE_67")
    assert r == {"ok": True, "id": "shot-1"}
    assert fake.calls[-1][:2] == ["screenshots", "upload"] and "--device-type=APP_IPHONE_67" in fake.calls[-1]
    FakeAsc(monkeypatch, {("video-previews", "upload"): err("upload failed", status=409)})
    bad = asc.ASCClient().upload_preview("loc-1", tmp_path / "p.mp4", "IPHONE_67")
    assert bad["ok"] is False and bad["step"] == "upload" and "upload failed" in bad["error"]


# ---- MCP tools ----

def _call(tool: str, args: dict | None = None):
    import asyncio

    from fastmcp import Client

    from appfactory.server import mcp

    async def go():
        async with Client(mcp) as c:
            r = await c.call_tool(tool, args or {})
            return r.data if hasattr(r, "data") else r
    return asyncio.run(go())


def test_asc_token_check_is_a_live_read_through_asc(monkeypatch, tmp_path):
    p8 = _creds(monkeypatch, tmp_path)
    fake = FakeAsc(monkeypatch, {
        (): "5.7.0",
        ("auth", "status"): {"credentials": [{"name": "appfactory"}]},
        ("apps", "list"): {"data": [{"id": "1"}]},
    })
    r = _call("asc_token_check")
    assert r["ok"] is True and r["auth_source"].startswith("config.toml") and r["p8"] == str(p8)
    assert r["key_id"] == "K1" and r["keychain_profiles"] == ["appfactory"]
    assert ["apps", "list", "--limit=1"] in fake.calls
    FakeAsc(monkeypatch, {(): "5.7.0", ("apps", "list"): err("401 NOT_AUTHORIZED", status=401)})
    bad = _call("asc_token_check")
    assert bad["ok"] is False and "NOT_AUTHORIZED" in bad["error"]


def test_asc_list_apps_tool_shape(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch, {("apps", "list"): {"data": [
        {"id": "1234567891", "attributes": {"bundleId": "com.example.app", "name": "Example", "sku": "EX1"}}]}})
    r = _call("asc_list_apps")
    assert r == {"ok": True, "count": 1, "apps": [
        {"id": "1234567891", "bundleId": "com.example.app", "name": "Example", "sku": "EX1"}]}


def test_doctors_report_the_asc_cli(monkeypatch, tmp_path):
    _creds(monkeypatch, tmp_path)
    FakeAsc(monkeypatch, {(): "5.7.0", ("auth", "status"): {"credentials": []}})
    env = _call("env_doctor")
    assert env["available"]["asc"] is True
    doc = _call("config_doctor")
    assert doc["asc_cli"]["ok"] is True and doc["asc_cli"]["version"] == "5.7.0"
    monkeypatch.setattr(asc_cli, "binary", lambda: None)
    assert _call("config_doctor")["asc_cli"]["ok"] is False
    assert "brew install asc" in _call("env_doctor")["notes"][0]
