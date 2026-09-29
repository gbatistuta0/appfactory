"""Backend WP: mode selection + rendering, backend_deploy with fakes, legal, listing rules, SBP,
gates and config. No network, no real secrets."""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import pytest

from appfactory import ai, config, gates, legal, metadata, sbp, spec
from appfactory import supabase as supa
from backend_fixtures import REF, SUPA_URL, full_listing, make_app

FAKE = {"fal_key": "fal-not-real", "rc_secret_key": "sk-not-real", "supabase_access_token": "sbp-not-real",
        "support_email": "help@example.com", "legal_controller": "Ada Lovelace"}


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".cfg" / "config.toml")


# ---- supabase template: mode + render + secrets + auth ----

def test_apply_backend_mode_subscription_and_credits(tmp_path: Path):
    app, sp = make_app(tmp_path)
    r = supa.apply_backend_mode(app, sp)
    assert r["ok"] and r["functions"] == ["analyze", "usage-status", "delete-account", "legal", "rc-webhook"]
    assert not (app / "supabase" / "functions" / "ai-proxy").exists()
    assert not (app / "supabase" / "migrations_credits").exists()
    assert (app / "supabase" / "migrations" / "0001_core.sql").exists()
    assert supa.apply_backend_mode(app, sp)["removed"] == []          # idempotent

    capp, csp = make_app(tmp_path / "c", monetization="credits")
    supa.apply_backend_mode(capp, csp)
    assert (capp / "supabase" / "functions" / "ai-proxy").exists()
    assert (capp / "supabase" / "migrations" / "0003_credits.sql").exists()
    assert not (capp / "supabase" / "functions" / "analyze").exists()


def test_render_backend_from_spec(tmp_path: Path):
    app, sp = make_app(tmp_path, locales={"app": ["en", "tr"]}, usage={"daily_caps": {"photo": 5}},
                       consent={"health": True})
    supa.render_backend(app, sp)
    gen = (app / "supabase" / "functions" / "_shared" / "app.gen.ts").read_text()
    assert 'APP_NAME = "Hue"' in gen and 'SUPPORTED_LOCALES = ["en", "tr"] as const' in gen
    toml = (app / "supabase" / "config.toml").read_text()
    assert 'client_id = "com.example.hue"' in toml and 'project_id = "hue"' in toml
    contract = (app / "backend" / "CONTRACT.md").read_text()
    assert "| 5 per local calendar day | 20 per local calendar day |" in contract
    assert "Consent required before the first analysis: yes" in contract


def test_backend_secrets_and_auth_config():
    sp = spec.build("Hue", "com.example.hue", ai={"fallback_model": ""})
    secrets, missing = supa.backend_secrets(sp, {"fal_key": "f", "rc_secret_key": "s", "rc_project_id": "GLOBAL"},
                                            {"rc_project_id": "projHue"})
    assert secrets["RC_PROJECT_ID"] == "projHue"            # per-app id, never the global config one
    assert secrets["AI_MODEL"] == "google/gemini-3.6-flash" and secrets["AI_FALLBACK_MODEL"] == "none"
    assert secrets["PHOTO_DAILY_LIMIT"] == "12" and secrets["REQUIRE_CONSENT"] == "false"
    assert secrets["ENTITLEMENT_GRACE_HOURS"] == "72" and secrets["FREE_LIFETIME_SCANS"] == "1"
    assert missing == ["RC_WEBHOOK_SECRET"]
    _, missing2 = supa.backend_secrets(sp, {}, {})
    assert {"FAL_KEY", "RC_SECRET_KEY", "RC_PROJECT_ID"} <= set(missing2)
    assert supa.auth_config(sp) == {"external_anonymous_users_enabled": True, "external_apple_enabled": True,
                                    "external_apple_client_id": "com.example.hue",
                                    "security_manual_linking_enabled": True}


class FakeSupabase:
    def __init__(self, applied=()):
        self.sql: list[str] = []
        self.secrets: dict[str, str] = {}
        self.auth: dict = {}
        self.applied = list(applied)

    def run_sql(self, ref, sql):
        self.sql.append(sql)
        if "select version from supabase_migrations" in sql:
            return {"ok": True, "data": [{"version": v} for v in self.applied]}
        return {"ok": True, "data": []}

    def set_secrets(self, ref, secrets):
        self.secrets.update(secrets)
        return {"ok": True}

    def update_auth_config(self, ref, body):
        self.auth = body
        return {"ok": True}


def test_backend_deploy_with_fakes(tmp_path: Path):
    app, sp = make_app(tmp_path)
    supa.apply_backend_mode(app, sp)
    config.update_app_outputs(app, rc_project_id="projHue")
    client, calls = FakeSupabase(applied=["0001"]), []

    def runner(cmd, cwd=None, timeout=120, env=None):
        calls.append((cmd, (env or {}).get("SUPABASE_ACCESS_TOKEN")))
        return {"ok": True, "stdout": "", "stderr": ""}

    r = ai.deploy_backend(app, REF, client=client, runner=runner, config=FAKE, dry_run=False)
    assert r["ok"] is True, r
    mig_files = [m["file"] for m in r["steps"]["migrations"] if not m.get("skipped")]
    assert mig_files == ["0002_analytics.sql", "0003_consent.sql", "0004_calendar_caps.sql", "0005_events_revenue.sql"]
    assert any("insert into supabase_migrations.schema_migrations" in s and "'0002'" in s for s in client.sql)
    assert client.secrets["RC_PROJECT_ID"] == "projHue" and client.secrets["FAL_KEY"] == "fal-not-real"
    assert client.auth["external_apple_client_id"] == "com.example.hue"
    deployed = [c[0][3] for c in calls if c[0][:3] == ["supabase", "functions", "deploy"]]
    assert deployed == ["analyze", "usage-status", "delete-account", "legal", "rc-webhook"]
    legal_cmd = next(c[0] for c in calls if c[0][:4] == ["supabase", "functions", "deploy", "legal"])
    assert "--no-verify-jwt" in legal_cmd
    analyze_cmd = next(c[0] for c in calls if c[0][:4] == ["supabase", "functions", "deploy", "analyze"])
    assert "--no-verify-jwt" not in analyze_cmd
    assert calls[0][0][:2] == ["deno", "run"]                          # legal build first
    # secrets are reported by name only
    dumped = json.dumps(r)
    assert "fal-not-real" not in dumped and "sk-not-real" not in dumped and "sbp-not-real" not in dumped
    marker = json.loads((app / ".appfactory" / "verify" / "backend_deploy.json").read_text())
    assert marker["ok"] and "FAL_KEY" in marker["secret_names"] and "fal-not-real" not in json.dumps(marker)
    outs = config.app_outputs(app)
    assert outs["supabase_url"] == SUPA_URL and outs["legal_base"] == f"{SUPA_URL}/functions/v1/legal"
    assert r["legal_urls"]["privacy"] == f"{SUPA_URL}/functions/v1/legal/privacy"


def test_backend_deploy_dry_run_and_missing_secrets(tmp_path: Path):
    app, sp = make_app(tmp_path)
    supa.apply_backend_mode(app, sp)
    plan = ai.deploy_backend(app, REF, dry_run=True)
    assert plan["dry_run"] and "RC_PROJECT_ID" in plan["missing_secrets"]
    assert plan["migrations"][0] == "0001_core.sql"
    r = ai.deploy_backend(app, REF, client=FakeSupabase(), runner=lambda *a, **k: {"ok": True},
                          config={"supabase_access_token": "x"}, dry_run=False)
    assert r["ok"] is False and set(r["missing_required_secrets"]) == {"FAL_KEY", "RC_SECRET_KEY", "RC_PROJECT_ID"}
    failing = FakeSupabase()
    failing.run_sql = lambda ref, sql: ({"ok": True, "data": []} if "select version" in sql
                                        else {"ok": False, "error": "syntax error"})
    config.update_app_outputs(app, rc_project_id="p")
    r2 = ai.deploy_backend(app, REF, client=failing, runner=lambda *a, **k: {"ok": True}, config=FAKE, dry_run=False)
    assert r2["ok"] is False and len(r2["steps"]["migrations"]) == 1   # stops at the first failure


# ---- legal ----

def test_legal_render_resolves_health_blocks_and_fills_factory_values(tmp_path: Path):
    app, sp = make_app(tmp_path)
    r = legal.render(app, sp, config=FAKE)
    pp = (app / "store" / "privacy" / "privacy-policy.en.md").read_text()
    priv = (app / "backend" / "PRIVACY.md").read_text()
    assert "Apple Health" not in pp and "HealthKit" not in priv.split("## Processors")[0]
    assert "{{APP_NAME}}" not in pp and "Hue Privacy Policy" in pp and "help@example.com" in pp
    assert "Ada Lovelace" in pp
    assert "APP_PURPOSE" in r["remaining_placeholders"]["store/privacy/privacy-policy.en.md"]
    terms = (app / "store" / "privacy" / "terms.en.md").read_text()
    assert "3-day free trial" in terms and "yearly and weekly plans" in terms
    assert "try one analysis for free" in terms

    happ, hsp = make_app(tmp_path / "h", consent={"health": True})
    legal.render(happ, hsp, config=FAKE)
    hpp = (happ / "store" / "privacy" / "privacy-policy.en.md").read_text()
    hpriv = (happ / "backend" / "PRIVACY.md").read_text()
    assert "## Apple Health" in hpp and "never used for advertising" in hpp
    assert "## Apple Health (HealthKit)" in hpriv and "never sent to the AI model provider" in hpriv
    assert "<!-- if:" not in hpp and "<!-- endif" not in hpriv


def test_legal_check_and_urls(tmp_path: Path):
    app, sp = make_app(tmp_path)
    chk = legal.check(app, sp)
    assert chk["ok"] is False and "privacy/en" in chk["blocking"]
    assert "privacy/tr" in chk["missing_translations"]
    src = app / "store" / "privacy"
    for doc in ("privacy-policy", "terms", "support"):
        (src / f"{doc}.en.md").write_text("# Hue\n\nAll filled. help@example.com\n")
    chk2 = legal.check(app, sp)
    assert chk2["ok"] is True and "terms/en" in chk2["publishable"]
    (src / "terms.tr.md").write_text("# Hue\n{{CONTROLLER}}\n")
    assert "terms/tr" in legal.check(app, sp)["blocking"]
    assert legal.is_legal_url(f"{SUPA_URL}/functions/v1/legal/privacy?lang=pt-BR", "privacy")
    assert not legal.is_legal_url("https://gist.githubusercontent.com/u/1/raw/2/privacy.md")
    assert legal.app_language("es-MX", ["en", "es", "pt-BR"]) == "es"
    assert legal.app_language("pt-PT", ["en", "pt-BR"]) == "pt-BR"
    assert legal.app_language("ja", ["en", "tr"]) == "en"


def test_legal_verify_live_with_fake_get():
    def get(url):
        lang = url.split("lang=")[1]
        if lang == "tr":
            return 200, {"Content-Language": "en"}, "help@example.com"
        return 200, {"Content-Language": lang}, "Contact help@example.com"
    r = legal.verify_live(SUPA_URL, "help@example.com", ["en", "tr"], get=get)
    assert r["ok"] is False and r["checked"] == 4
    assert all("served en" in f["problems"] for f in r["failed"])


# ---- listing rules ----

def test_listing_rules(tmp_path: Path):
    sp = spec.build("Hue", "com.example.hue")
    good = full_listing(sp)
    assert metadata.check_listing(good, sp) == []

    def errs(mutate):
        lst = json.loads(json.dumps(good))
        mutate(lst)
        return metadata.check_listing(lst, sp)

    assert any("name is 32 chars" in e for e in errs(lambda l: l["locales"]["en-US"].update(name="Hue: Color Analysis For Everyone")))
    assert any("keywords use" in e for e in errs(lambda l: l["locales"]["en-US"].update(keywords="a,b")))
    assert any("repeats in" in e for e in errs(lambda l: l["locales"]["en-US"].update(subtitle="Color Palette Finder")))
    assert any("indexed twice" in e for e in errs(lambda l: l["locales"]["es-MX"].update(subtitle="Signature Tono Look")))
    assert any("promotional_text" in e for e in errs(lambda l: l["locales"]["tr"].update(promotional_text="x" * 171)))
    assert any("disclosure" in e for e in errs(lambda l: l["locales"]["de-DE"].update(description="Just a body.")))
    assert any("must end with the Terms/Privacy" in e for e in errs(
        lambda l: l["locales"]["fr-FR"].update(description=l["locales"]["fr-FR"]["description"] + "\nMore text\nand more\nand more")))
    assert any("?lang=tr" in e for e in errs(lambda l: l["locales"]["tr"].update(
        description=l["locales"]["tr"]["description"].replace("lang=tr", "lang=en"))))
    assert any("privacy_url must be the Supabase" in e for e in errs(
        lambda l: l["locales"]["en-GB"].update(privacy_url="https://gist.githubusercontent.com/x/raw/p.md")))
    assert any("missing store locales" in e for e in errs(lambda l: l["locales"].pop("tr")))
    assert any("unlimited" in e for e in errs(lambda l: l["iap"]["products"]["weekly"]["tr"].update(description="Unlimited scans")))
    assert any("placeholders" in e for e in errs(lambda l: l["locales"]["en-US"].update(subtitle="{{SUBTITLE}}")))
    kw = good["locales"]["tr"]["keywords"]
    assert any("ASCII comma" in e for e in errs(lambda l: l["locales"]["tr"].update(keywords=kw.replace(",", "،", 1))))
    assert any("language name" in e for e in errs(
        lambda l: l["locales"]["tr"].update(keywords=",".join(kw.split(",")[:-1] + ["türkçe"]))))


def test_fold_strips_latin_diacritics_only():
    assert metadata.fold("Calorías") == "calorias" and metadata.fold("TÜRKÇE") == "turkce"
    assert metadata.fold("калорий") != metadata.fold("калории")   # й is not и
    assert metadata.fold("ガ") != metadata.fold("カ")
    assert metadata.words("سعرات، حرارية") == ["سعرات", "حرارية"]
    assert metadata.words("カロリー、食事") == ["カロリー", "食事"]


def test_render_listing_fills_legal_urls(tmp_path: Path):
    app, sp = make_app(tmp_path, listing=False)
    config.update_app_outputs(app, supabase_url=SUPA_URL)
    r = metadata.render_listing(app, sp)
    assert r["ok"] and r["legal_urls"]
    lst = metadata.load_listing(app)
    assert lst["locales"]["es-MX"]["privacy_url"] == f"{SUPA_URL}/functions/v1/legal/privacy?lang=es"
    assert lst["locales"]["tr"]["support_url"] == f"{SUPA_URL}/functions/v1/legal/support?lang=tr"
    assert f"{SUPA_URL}/functions/v1/legal/terms?lang=en" in lst["locales"]["en-US"]["description"]
    assert set(lst["iap"]["products"]) == {"yearly", "weekly", "yearly_offer"}
    assert metadata.listing_check(app)["ok"] is False                 # copy placeholders still open


# ---- SBP ----

def _report(rows: list[dict]) -> bytes:
    cols = ["App Name", "Subscription Name", "Customer Price", "Customer Currency", "Developer Proceeds",
            "Proceeds Currency", "Proceeds Reason", "Country", "Active Standard Price Subscriptions"]
    lines = ["\t".join(cols)] + ["\t".join(str(r.get(c, "")) for c in cols) for r in rows]
    return gzip.compress(("\n".join(lines) + "\n").encode())


SBP_CFG = {"asc_finance_key_id": "FIN123", "asc_issuer_id": "iss", "asc_vendor_number": "8800"}


def test_sbp_from_fake_gz_tsv():
    rows = [
        {"Customer Price": "49.99", "Customer Currency": "USD", "Developer Proceeds": "42.49", "Proceeds Currency": "USD",
         "Country": "US", "Active Standard Price Subscriptions": "3"},
        {"Customer Price": "7.99", "Customer Currency": "USD", "Developer Proceeds": "6.79", "Proceeds Currency": "USD",
         "Country": "US", "Active Standard Price Subscriptions": "2"},
        {"Customer Price": "59.99", "Customer Currency": "EUR", "Developer Proceeds": "42.86", "Proceeds Currency": "EUR",
         "Country": "DE", "Active Standard Price Subscriptions": "5"},   # VAT: ignored
        {"Customer Price": "49.99", "Customer Currency": "USD", "Developer Proceeds": "42.49", "Proceeds Currency": "USD",
         "Proceeds Reason": "Rate After One Year", "Country": "US"},       # 85% for everyone: ignored
    ]
    seen = []

    def fetch(url, params, headers):
        seen.append(params["filter[reportDate]"])
        return (404, b"") if params["filter[reportDate]"] == "2026-09-23" else (200, _report(rows))

    r = sbp.check("2026-09-23", fetch=fetch, config=SBP_CFG, token="t")
    assert r["ok"] and r["report_date"] == "2026-09-22" and r["verdict"] == "small_business_program" and r["sbp"] is True
    assert r["rows_used"] == 2 and abs(r["ratio"] - 0.85) < 0.001
    assert seen == ["2026-09-23", "2026-09-22"]
    std = [dict(rows[0], **{"Developer Proceeds": "34.99"})]
    r2 = sbp.check("2026-09-23", fetch=lambda u, p, h: (200, _report(std)), config=SBP_CFG, token="t")
    assert r2["verdict"] == "standard_rate" and r2["sbp"] is False


def test_sbp_errors():
    r = sbp.check(fetch=lambda u, p, h: (403, b""), config=SBP_CFG, token="t")
    assert r["ok"] is False and "Finance" in r["error"]
    assert sbp.check(config={})["ok"] is False
    none = sbp.check("2026-09-23", days_back=2, fetch=lambda u, p, h: (404, b""), config=SBP_CFG, token="t")
    assert none["ok"] and none["verdict"] == "unknown" and none["tried"] == ["2026-09-23", "2026-09-22"]
    plain = sbp.parse_report(b"Country\tCustomer Price\nUS\t1\n")
    assert plain == [{"Country": "US", "Customer Price": "1"}]


# ---- gates ----

def _manifest(app: Path) -> None:
    d = app / ".appfactory"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"app": "Hue", "bundle_id": "com.example.hue", "dir": str(app)}))


def _sub(pid, n_offers, modes, locs, level):
    return {"id": pid, "product_id": pid, "group_level": level, "localizations": locs,
            "intro_offers": n_offers, "intro_modes": modes}


def test_iap_gate_follows_spec():
    sp = spec.build("Hue", "com.example.hue")
    locs = sp["locales"]["store"]
    good = {"ok": True, "availability": True, "price": True, "group_localizations": locs, "subscriptions": [
        _sub("com.example.hue.yearly", 174, ["FREE_TRIAL THREE_DAYS"], locs, 1),
        _sub("com.example.hue.weekly", 174, ["FREE_TRIAL THREE_DAYS"], locs, 2),
        _sub("com.example.hue.yearly.offer", 0, [], locs, 1)]}
    assert gates._gate_iap(Path("/x"), good, spec=sp)["ok"] is True

    def fails(mutate, needle):
        st = json.loads(json.dumps(good))
        mutate(st)
        r = gates._gate_iap(Path("/x"), st, spec=sp)
        assert r["ok"] is False and needle in r["reason"], r

    fails(lambda s: s["subscriptions"][2].update(intro_offers=174, intro_modes=["FREE_TRIAL THREE_DAYS"]), "must NOT have an intro offer")
    fails(lambda s: s["subscriptions"][0].update(intro_modes=["PAY_UP_FRONT ONE_YEAR"]), "!= spec")
    fails(lambda s: s["subscriptions"][1].update(intro_offers=1), "territory")
    fails(lambda s: s["subscriptions"].pop(1), "com.example.hue.weekly")
    fails(lambda s: s["subscriptions"][1].update(group_level=1), "group level")
    fails(lambda s: s["subscriptions"][0]["localizations"].remove("tr"), "localizations missing")


def test_legal_url_check_in_features(tmp_path: Path):
    src = tmp_path / "Sources"
    src.mkdir()
    (src / "AppConfig.swift").write_text(
        'static let privacyURL = "https://gist.githubusercontent.com/u/1/raw/2/privacy.md"\n'
        'static let termsURL = "https://gist.githubusercontent.com/u/1/raw/2/terms.md"\n')
    r = gates._check_legal_urls(tmp_path)
    assert r["ok"] is False and "gist" in r["reason"]
    (src / "AppConfig.swift").write_text(
        f'static let privacyURL = URL(string: "{SUPA_URL}/functions/v1/legal/privacy")!\n'
        f'static let termsURL = URL(string: "{SUPA_URL}/functions/v1/legal/terms")!\n'
        f'static let supportURL = URL(string: "mailto:help@example.com")!\n')
    assert gates._check_legal_urls(tmp_path)["ok"] is True


def test_backend_and_ai_proxy_gates_with_spec(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _manifest(app)
    res = app / "Resources"
    res.mkdir()
    (res / "GoogleService-Info.plist").write_text("<key>GOOGLE_APP_ID</key><key>PROJECT_ID</key>")
    r = gates.validate_stage(app, "backend")
    assert r["ok"] is False and "credits-mode" in r["reason"]
    supa.apply_backend_mode(app, sp)
    assert "app.gen.ts" in gates.validate_stage(app, "backend")["reason"] or \
        "client_id" in gates.validate_stage(app, "backend")["reason"]
    supa.render_backend(app, sp)
    assert gates.validate_stage(app, "backend")["ok"] is True

    assert gates.validate_stage(app, "ai_proxy")["ok"] is False
    v = app / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    marker = {"ok": True, "functions": supa.FUNCTION_SETS["subscription"], "missing_secrets": ["RC_WEBHOOK_SECRET"],
              "legal_published": ["privacy/en", "terms/en"]}
    (v / "backend_deploy.json").write_text(json.dumps(marker))
    assert gates.validate_stage(app, "ai_proxy")["ok"] is True
    (v / "backend_deploy.json").write_text(json.dumps({**marker, "missing_secrets": ["RC_PROJECT_ID"]}))
    assert "RC_PROJECT_ID" in gates.validate_stage(app, "ai_proxy")["reason"]


def test_asc_app_gate_requires_capabilities(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _manifest(app)
    assert gates.validate_stage(app, "asc_app")["ok"] is False
    config.update_app_outputs(app, asc_app_id="123")
    r = gates.validate_stage(app, "asc_app")
    assert r["ok"] is False and "APPLE_ID_AUTH" in r["reason"]
    config.update_app_outputs(app, capabilities_applied=["APPLE_ID_AUTH", "IN_APP_PURCHASE"])
    assert gates.validate_stage(app, "asc_app")["ok"] is True


def test_metadata_gate_with_listing(tmp_path: Path):
    app, sp = make_app(tmp_path)
    _manifest(app)
    v = app / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "metadata.json").write_text(json.dumps({"privacy_url": "https://x.co/p", "category": "LIFESTYLE"}))
    assert "Supabase legal" in gates.validate_stage(app, "metadata")["reason"]
    (v / "metadata.json").write_text(json.dumps({"privacy_url": f"{SUPA_URL}/functions/v1/legal/privacy?lang=en",
                                                 "category": "LIFESTYLE"}))
    assert gates.validate_stage(app, "metadata")["ok"] is True
    lst = metadata.load_listing(app)
    lst["locales"]["tr"]["keywords"] = "kisa"
    (app / "store" / "metadata" / "listing.json").write_text(json.dumps(lst))
    r = gates.validate_stage(app, "metadata")
    assert r["ok"] is False and "keywords" in r["reason"]


# ---- config + tools ----

def test_config_doctor_notes_and_known_keys(tmp_path: Path):
    config.update_config({"rc_project_id": "projExample", "rc_secret_key": "sk", "asc_finance_key_id": "NOPE"})
    notes = config.doctor_notes(config.load_config())
    assert any("rc_project_id" in n and "outputs.json" in n for n in notes)
    assert any("asc_finance_key_id" in n for n in notes)
    assert {"asc_finance_key_id", "asc_finance_key_filepath", "review_contact_phone", "rc_secret_key"} <= set(config.KNOWN_KEYS)
    assert {"rc_secret_key", "review_contact_phone"} <= config.SECRET_KEYS
    p8 = config.CONFIG_DIR / "AuthKey_FIN9.p8"
    p8.write_text("x")
    assert config.resolve_finance_key_filepath({"asc_finance_key_id": "FIN9"}) == p8
    from appfactory.server import config_doctor
    doc = config_doctor()
    assert doc["present"]["rc_secret_key"] == "***set***" and doc["notes"]


def test_backend_tools_registered():
    from fastmcp import Client

    from appfactory.server import mcp

    async def _list():
        async with Client(mcp) as c:
            return {t.name for t in await c.list_tools()}

    names = asyncio.run(_list())
    for n in ("backend_render", "backend_deploy", "legal_render", "legal_check", "legal_verify", "store_setup",
              "metadata_listing_check", "metadata_render_listing", "pricing_unit_economics", "asc_sbp_check"):
        assert n in names


def test_testflight_refuses_while_capabilities_pending(tmp_path: Path):
    app, sp = make_app(tmp_path)
    from appfactory.server import testflight_ship
    r = testflight_ship(str(app), "Hue.xcodeproj", "Hue", "com.example.hue")
    assert r["ok"] is False and "capabilities pending" in r["error"]


def test_sbp_fetches_the_report_with_asc_as_the_finance_key(monkeypatch, tmp_path):
    from asc_fake import FakeAsc, err
    p8 = tmp_path / "AuthKey_FIN123.p8"
    p8.write_text("k")
    rows = [{"Customer Price": "9.99", "Customer Currency": "USD", "Developer Proceeds": "8.49",
             "Proceeds Currency": "USD", "Country": "US"}]

    def sales(args, stdin):
        if FakeAsc.flag(args, "date") == "2026-09-23":
            return {"available": False}
        Path(FakeAsc.flag(args, "output")).write_bytes(_report(rows))
        return {"available": True}
    fake = FakeAsc(monkeypatch, {("analytics", "sales"): sales})
    r = sbp.check("2026-09-23", config={**SBP_CFG, "asc_finance_key_filepath": str(p8)})
    assert r["ok"] and r["report_date"] == "2026-09-22" and r["verdict"] == "small_business_program"
    call = fake.calls[-1]
    assert [FakeAsc.flag(call, k) for k in ("vendor", "type", "subtype", "frequency", "version")] == \
        ["8800", "SUBSCRIPTION", "SUMMARY", "DAILY", "1_3"]
    assert "--allow-missing" in call
    env = fake.envs[-1]
    assert env["ASC_KEY_ID"] == "FIN123" and env["ASC_PRIVATE_KEY_PATH"] == str(p8)
    FakeAsc(monkeypatch, {("analytics", "sales"): err("forbidden", status=403)})
    denied = sbp.check("2026-09-23", config={**SBP_CFG, "asc_finance_key_filepath": str(p8)})
    assert denied["ok"] is False and "Finance" in denied["error"]
