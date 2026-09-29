"""Scaffold driven by app.spec.json: monetization stripping, modules, generated Swift, StoreKit,
onboarding length, String Catalogs, backend mode, inject_config, gates on the result."""

import json
import re
from pathlib import Path

import pytest

from appfactory import app, gates, localize, spec, storekit

LANGS = ["es", "pt-BR", "de", "fr", "tr"]


def _scaffold(tmp_path: Path, **overrides):
    r = app.scaffold("Hue", "com.example.hue", dest_dir=str(tmp_path), spec=overrides or None, generate=False)
    assert r["ok"], r
    return Path(r["dir"]), r


def _swift(root: Path) -> str:
    return "\n".join(p.read_text() for p in (root / "Sources").rglob("*.swift"))


@pytest.fixture(scope="module")
def hue(tmp_path_factory):
    return _scaffold(tmp_path_factory.mktemp("sub"))


def test_strip_blocks():
    text = "a\n// @if credits\nb\n// @endif\n  # @if health\nc\n  # @endif\nd\n"
    assert app.strip_blocks(text, {"credits": False, "health": True}) == "a\nc\nd\n"
    assert app.strip_blocks(text, {"credits": True}) == "a\nb\nd\n"


def test_subscription_scaffold_strips_credit_economy(hue):
    root, r = hue
    assert r["monetization"] == "subscription"
    assert not (root / "Sources" / "Credits").exists()
    src = _swift(root)
    for banned in ("CreditManager", "TopUpSheet", "creditPack", "@if ", "@endif", "__APP_NAME__", "__BUNDLE_ID__"):
        assert banned not in src, banned
    assert "AIService.analyze" in src and "generateImage" not in src
    assert json.loads((root / "app.spec.json").read_text())["bundle_id"] == "com.example.hue"
    yml = (root / "project.yml").read_text()
    assert "HealthKit" not in yml and "@if" not in yml
    assert "com.apple.developer.applesignin" in yml and "HueTests" in yml and "HueUITests" in yml
    assert not (root / "Sources" / "Health").exists() and not (root / "Tests" / "HealthTests.swift").exists()
    # backend pruned to the subscription mode
    assert (root / "supabase" / "functions" / "analyze").exists()
    assert not (root / "supabase" / "functions" / "ai-proxy").exists()


def test_generated_swift_follows_spec(hue):
    root, _ = hue
    s = spec.load(root)
    app_spec = (root / "Sources/App/AppSpec.swift").read_text()
    for p in spec.products(s):
        assert f'id: "{p["id"]}"' in app_spec
    assert 'usd: Decimal(string: "49.99")!' in app_spec and "introDays: 3" in app_spec
    assert re.search(r'key: "yearly_offer".*introDays: nil.*offering: "offer"', app_spec)
    assert 'appLocales: [String] = ["en", "es", "pt-BR", "de", "fr", "tr"]' in app_spec
    assert 'eventPrefix = "hue_"' in app_spec
    assert "static let aiEnabled = true" in app_spec
    src = (root / "Sources/Paywall/PaywallSource.swift").read_text()
    cases = re.findall(r"^    case (\w+)", src, re.M)
    assert len(cases) == len(s["placements"]) == 8
    assert 'case billingIssue = "billing_issue"' in src
    assert "case .offerAfterOnboarding, .appOpenOffer: return true" in src
    assert storekit.parity(s, root / storekit.STOREKIT_REL) == []


def test_onboarding_matches_spec_and_gates(hue):
    root, r = hue
    ids = app.onboarding_step_ids(root)
    assert len(ids) == 26 == r["onboarding"]["steps"]
    assert ids[0] == "welcome" and ids[-2:] == ["paywall", "offer"]
    assert gates._check_onboarding_depth(root)["ok"]
    assert gates._check_no_push_permission(root)["ok"]
    src = _swift(root)
    assert "requestAuthorization(options" not in src
    # rating requests are mandatory at success moments, never in onboarding
    assert gates._check_rating_requests(root)["ok"], gates._check_rating_requests(root)
    onboarding = "\n".join(p.read_text() for p in (root / "Sources" / "Onboarding").rglob("*.swift"))
    assert "requestReview" not in onboarding
    app_spec = (root / "Sources/App/AppSpec.swift").read_text()
    assert "static let ratingMinDaysBetween = 60" in app_spec and "static let ratingMilestones: [Int] = [7, 30]" in app_spec


@pytest.mark.parametrize("count", [14, 20, 30])
def test_onboarding_trim_and_pad(tmp_path, count):
    root, r = _scaffold(tmp_path, design={"onboarding_screens": count})
    ids = app.onboarding_step_ids(root)
    assert len(ids) == count
    assert ids[0] == "welcome" and ids[-5:] == ["loading", "finale", "account", "paywall", "offer"]
    text = (root / app.ONBOARDING_REL).read_text()
    assert len(re.findall(r"kind:\s*\.question", text)) >= 5
    assert gates._check_onboarding_depth(root)["ok"]
    if count > 26:
        assert r["onboarding"]["added"] == ["extra_1", "extra_2", "extra_3", "extra_4"]


def test_catalogs_are_complete_for_spec_locales(hue):
    root, _ = hue
    cat = json.loads((root / "Resources/Localizable.xcstrings").read_text())["strings"]
    spec_fmt = re.compile(r"%(?:\d+\$)?(?:ll|l)?[@dfs]")
    for key, entry in cat.items():
        assert "[module:" not in entry.get("comment", ""), f"module key leaked: {key}"
        locs = entry["localizations"]
        assert set(locs) - {"en"} == set(LANGS), key
        source = locs.get("en", {}).get("stringUnit", {}).get("value", key)
        for lang in LANGS:
            unit = locs[lang]["stringUnit"]
            assert unit["state"] == "translated" and unit["value"], (key, lang)
            norm = lambda s: sorted(re.sub(r"\d+\$", "", m) for m in spec_fmt.findall(s))  # noqa: E731
            assert norm(unit["value"]) == norm(source), (key, lang)
    assert "offer.anchor.burger" in cat
    info = json.loads((root / "Resources/InfoPlist.xcstrings").read_text())["strings"]
    assert set(info) == {"CFBundleDisplayName"}  # health usage strings dropped with the module
    assert info["CFBundleDisplayName"]["localizations"]["tr"]["stringUnit"]["value"] == "Hue"
    r = gates._gate_localize(root)
    assert r["ok"], r


def test_credits_mode_keeps_credit_economy(tmp_path):
    root, _ = _scaffold(tmp_path, monetization="credits")
    assert (root / "Sources/Credits/CreditManager.swift").exists()
    src = _swift(root)
    assert "creditPackIDs" in src and "case outOfCredits" in src and "generateImage" in src
    assert "AIService.analyze" not in src
    doc = json.loads((root / storekit.STOREKIT_REL).read_text())
    assert len(doc["products"]) == len(storekit.CREDIT_PACKS)
    assert "Credits remaining" in json.loads((root / "Resources/Localizable.xcstrings").read_text())["strings"]
    assert (root / "supabase" / "functions" / "ai-proxy").exists()


def test_health_module_on(tmp_path):
    root, r = _scaffold(tmp_path, consent={"health": True}, health={"enabled": True})
    assert r["features"]["flags"]["health"]
    assert (root / "Sources/Health/HealthStore.swift").exists() and (root / "Tests/HealthTests.swift").exists()
    yml = (root / "project.yml").read_text()
    assert "com.apple.developer.healthkit: true" in yml and "NSHealthShareUsageDescription" in yml
    assert "HealthSettingsRow()" in _swift(root)
    ids = app.onboarding_step_ids(root)
    assert "health" in ids and len(ids) == 26
    info = json.loads((root / "Resources/InfoPlist.xcstrings").read_text())["strings"]
    assert "NSHealthUpdateUsageDescription" in info
    assert "consentRequired = true" in (root / "Sources/App/AppSpec.swift").read_text()


def test_scaffold_from_spec_file_and_rejects_bad_spec(tmp_path):
    s = spec.build("Hue", "com.example.hue", locales={"app": ["en", "tr"]})
    spec.save(tmp_path, s)
    r = app.scaffold(dest_dir=str(tmp_path / "out"), spec=str(tmp_path), generate=False)
    assert r["ok"], r
    cat = json.loads((Path(r["dir"]) / "Resources/Localizable.xcstrings").read_text())["strings"]
    assert set(cat["Continue"]["localizations"]) == {"tr"}
    bad = app.scaffold("Hue", "com.example.hue", dest_dir=str(tmp_path / "bad"), spec={"monetization": "ads"}, generate=False)
    assert bad["ok"] is False and "invalid spec" in bad["error"]
    assert app.scaffold(dest_dir=str(tmp_path / "x"), generate=False)["ok"] is False  # no name/bundle


def test_gates_on_scaffolded_app(tmp_path, monkeypatch):
    root, _ = _scaffold(tmp_path)
    (root / ".appfactory").mkdir(exist_ok=True)
    (root / ".appfactory" / "state.json").write_text("{}")
    (root / "Hue.xcodeproj").mkdir()
    assert gates._gate_scaffold(root)["ok"], gates._gate_scaffold(root)
    assert gates._check_analytics_coverage(root)["ok"]
    assert gates._check_paywall_funnel(root)["ok"]
    assert gates._gate_revenuecat(root)["ok"]
    assert gates._check_no_unlimited_claims(root)["ok"]
    # the template ships the native iOS 26 chrome (system TabView, search-role action, no custom bars)
    monkeypatch.setattr(gates, "_ios_sdk_version", lambda: "26.2")
    assert gates._check_native_chrome(root)["ok"], gates._check_native_chrome(root)
    # legal links resolve only after inject_config
    assert not gates._check_legal_urls(root)["ok"]
    app.inject_config(str(root), supabase_url="https://abcdefghijklmnopqrst.supabase.co", supabase_anon_key="anon")
    assert gates._check_legal_urls(root)["ok"], gates._check_legal_urls(root)
    # drift: storekit edited by hand
    sk = root / storekit.STOREKIT_REL
    sk.write_text(sk.read_text().replace('"49.99"', '"59.99"'))
    r = gates._gate_scaffold(root)
    assert not r["ok"] and "storekit" in r["reason"].lower()
    # spec edit without app_sync_spec → generated Swift out of sync; sync fixes both
    s = spec.load(root)
    s["subscription"]["products"][1]["usd"] = 9.99
    spec.save(root, s)
    assert not gates._gate_scaffold(root)["ok"]
    assert app.sync_spec(str(root))["ok"]
    assert gates._gate_scaffold(root)["ok"]
    assert 'Decimal(string: "9.99")' in (root / "Sources/App/AppSpec.swift").read_text()


def test_analytics_gate_rejects_ungated_firebase(tmp_path):
    root, _ = _scaffold(tmp_path)
    f = root / "Sources/App/App.swift"
    f.write_text(f.read_text().replace("if Tracker.isSending, Bundle.main", "if Bundle.main"))
    r = gates._check_analytics_coverage(root)
    assert not r["ok"] and "isSending" in r["reason"]


def test_inject_config_markers_are_rerunnable(tmp_path):
    root, _ = _scaffold(tmp_path, monetization="credits")
    cfg = root / "Sources/App/AppConfig.swift"
    app.inject_config(str(root), paywall_strategy="hard_only", yearly_credits=80, revenuecat_key="appl_x")
    text = cfg.read_text()
    assert "showOfferPaywall = false // appfactory:paywall_strategy" in text
    assert "yearlyMonthlyCredits = 80 // appfactory:yearly_credits" in text
    assert 'revenueCatKey = "appl_x"' in text
    app.inject_config(str(root), paywall_strategy="hard_and_offer", yearly_credits=90)
    text = cfg.read_text()
    assert "showOfferPaywall = true // appfactory:paywall_strategy" in text
    assert "yearlyMonthlyCredits = 90 // appfactory:yearly_credits" in text


def test_localize_uses_spec_locales(tmp_path):
    spec.save(tmp_path, spec.build("Hue", "com.example.hue"))
    assert localize.target_locales(tmp_path) == LANGS
    r = localize.build_catalog(tmp_path, {"Scan a color": {"tr": "Renk tara", "ja": "色", "de-DE": "Farbe scannen"}})
    assert r["target_locales"] == sorted(LANGS)
    cat = json.loads((tmp_path / "Resources/Localizable.xcstrings").read_text())["strings"]
    assert set(cat["Scan a color"]["localizations"]) == {"tr", "de"}  # ja is not an app locale
    # legacy apps (no spec) keep the configured list
    assert len(localize.target_locales(tmp_path / "nospec")) > 6


def test_localize_gate_uses_spec_locales(tmp_path):
    spec.save(tmp_path, spec.build("Hue", "com.example.hue", locales={"app": ["en", "tr"]}))
    (tmp_path / "Sources").mkdir()
    (tmp_path / "Sources/V.swift").write_text('Text("Continue")')
    (tmp_path / "Resources").mkdir()
    (tmp_path / "Resources/Localizable.xcstrings").write_text(json.dumps({"strings": {
        "Continue": {"localizations": {"tr": {"stringUnit": {"state": "translated", "value": "Devam"}}}}}}))
    assert gates._gate_localize(tmp_path)["ok"]  # only tr required, not 48 languages


# Same regexes as Tests/LocalizationCompletenessTests.swift (literalKeys), run without Xcode.
_SWIFT_LITERAL_PATTERNS = [
    r'\bText\(\s*"([^"\\]+)"\s*\)', r'\bButton\(\s*"([^"\\]+)"', r'\bLabel\(\s*"([^"\\]+)"',
    r'\b(?:title|subtitle|cta|unit|label):\s*"([^"\\]+)"', r'String\(localized:\s*"([^"\\]+)"',
    r'\.alert\(\s*"([^"\\]+)"', r'confirmationDialog\(\s*"([^"\\]+)"', r'segment\(\.\w+,\s*"([^"\\]+)"',
]


@pytest.mark.parametrize("overrides", [{}, {"monetization": "credits"}, {"consent": {"health": True}, "health": {"enabled": True}}])
def test_every_literal_ui_key_is_in_catalog(tmp_path, overrides):
    root, _ = _scaffold(tmp_path, **overrides)
    cat = json.loads((root / "Resources/Localizable.xcstrings").read_text())["strings"]
    missing = set()
    for f in (root / "Sources").rglob("*.swift"):
        text = f.read_text()
        keys = {m for p in _SWIFT_LITERAL_PATTERNS for m in re.findall(p, text)}
        for block in re.findall(r"bullets:\s*\[([^\]]+)\]", text):
            keys |= set(re.findall(r'"([^"\\]+)"', block))
        for k in keys:
            if re.search(r"[A-Za-z]", k) and not ("." in k and " " not in k) and k not in cat:
                missing.add(f"{f.name}: {k}")
    assert not missing, sorted(missing)


def test_device_scheme_never_carries_the_storekit_file(hue):
    """A device under the local StoreKit configuration looped Apple's Billing Problem
    sheet. Only the simulator schemes may carry it; the scaffold gate enforces that."""
    root, _ = hue
    yml = (root / "project.yml").read_text()
    main = gates.scheme_block(yml, "Hue")
    assert "run:" in main and "storeKitConfiguration" not in main
    assert "storeKitConfiguration" in gates.scheme_block(yml, "HueStoreKitSim")
    assert "storeKitConfiguration" in gates.scheme_block(yml, "HueUnitTests")
    (root / "Hue.xcodeproj").mkdir(exist_ok=True)
    assert gates._check_scaffold_spec(root, spec.load(root), yml)["ok"]
    bad = yml.replace("    run:\n      config: Debug\n    test:", "    run:\n      config: Debug\n"
                      "      storeKitConfiguration: Resources/Configuration.storekit\n    test:", 1)
    r = gates._check_scaffold_spec(root, spec.load(root), bad)
    assert r["ok"] is False and "Billing Problem" in r["reason"]


def test_privacy_manifest_is_generated_from_the_spec(hue, tmp_path):
    import plistlib
    root, _ = hue
    m = plistlib.loads((root / app.PRIVACY_MANIFEST_REL).read_bytes())
    assert m["NSPrivacyTracking"] is False and m["NSPrivacyTrackingDomains"] == []
    kinds = {d["NSPrivacyCollectedDataType"] for d in m["NSPrivacyCollectedDataTypes"]}
    assert "NSPrivacyCollectedDataTypeUserID" in kinds and "NSPrivacyCollectedDataTypeHealth" not in kinds
    api = m["NSPrivacyAccessedAPITypes"][0]
    assert api["NSPrivacyAccessedAPIType"] == "NSPrivacyAccessedAPICategoryUserDefaults"
    assert api["NSPrivacyAccessedAPITypeReasons"] == ["CA92.1"]
    assert "Privacy/PrivacyInfo.xcprivacy" in (root / "project.yml").read_text()
    health = spec.build("Hue", "com.x.hue", health={"enabled": True}, consent={"health": True}, capabilities=["APP_GROUPS"])
    hm = plistlib.loads(app.render_privacy_manifest(health).encode())
    assert "NSPrivacyCollectedDataTypeHealth" in {d["NSPrivacyCollectedDataType"] for d in hm["NSPrivacyCollectedDataTypes"]}
    assert hm["NSPrivacyAccessedAPITypes"][0]["NSPrivacyAccessedAPITypeReasons"] == ["CA92.1", "1C8F.1"]
