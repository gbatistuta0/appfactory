# tests/test_gates.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from appfactory import gates
from appfactory import pipeline as pipe
from appfactory.server import mcp


def _init_manifest(app: Path, app_name="DemoApp", bundle="com.x.demo"):
    (app / ".appfactory").mkdir(parents=True, exist_ok=True)
    (app / ".appfactory" / "state.json").write_text(
        json.dumps({"app": app_name, "bundle_id": bundle, "dir": str(app),
                    "stages": {}}), encoding="utf-8")


def test_unknown_stage_returns_gate_none(tmp_path: Path):
    _init_manifest(tmp_path)
    # Now ALL real STAGES are gated → GATE_NONE only for names not in _GATES.
    r = gates.validate_stage(tmp_path, "future_unknown_stage")
    assert r["ok"] is True
    assert "no gate" in r["reason"]


def test_unrecognized_stage_name_is_gate_none(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "bogus")["ok"] is True


def test_design_gate_rejects_stitch_even_when_complete(tmp_path: Path):
    """Stitch artifacts (the pre-Claude Design manifest) no longer pass, however complete."""
    _init_manifest(tmp_path)
    d = tmp_path / ".appfactory" / "design"
    d.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, name in enumerate(["welcome", "create", "result", "paywall", "gallery", "settings"]
                             + [f"onb_{i}" for i in range(11)]):
        (d / f"{name}.html").write_text("<html></html>", encoding="utf-8")
        entries.append({"screen": name, "stitch_project_id": "p1", "prompt": f"prompt {i}",
                        "html_path": str(d / f"{name}.html")})
    (d / "screens.json").write_text(json.dumps(entries), encoding="utf-8")
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "design_review.json").write_text('{"fidelity_ok": true}', encoding="utf-8")
    r = gates.validate_stage(tmp_path, "design")
    assert r["ok"] is False and "Claude Design" in r["reason"]


def test_design_gate_fails_missing_screens_json(tmp_path: Path):
    _init_manifest(tmp_path)
    r = gates.validate_stage(tmp_path, "design")
    assert r["ok"] is False and "screens.json" in r["reason"]


def _write_catalog(app: Path, keys_locales: dict):
    res = app / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    strings = {}
    for key, locales in keys_locales.items():
        strings[key] = {"extractionState": "manual", "localizations": {
            loc: {"stringUnit": {"state": "translated", "value": v}} for loc, v in locales.items()}}
    (res / "Localizable.xcstrings").write_text(
        json.dumps({"sourceLanguage": "en", "strings": strings, "version": "1.0"}),
        encoding="utf-8")


def _write_swift(app: Path, body: str):
    src = app / "Sources"
    src.mkdir(parents=True, exist_ok=True)
    (src / "ContentView.swift").write_text(body, encoding="utf-8")


def test_localize_gate_passes_when_all_translated(tmp_path: Path):
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")\nButton("Save") {}')
    _write_catalog(tmp_path, {
        "Continue": {"tr": "Devam", "de-DE": "Weiter"},
        "Save": {"tr": "Kaydet", "de-DE": "Speichern"}})
    assert gates._gate_localize(tmp_path, required_locales={"tr", "de-DE"})["ok"] is True


def test_localize_gate_fails_missing_key(tmp_path: Path):
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")\nText("Gallery")')
    _write_catalog(tmp_path, {"Continue": {"tr": "Devam", "de-DE": "Weiter"}})
    r = gates._gate_localize(tmp_path, required_locales={"tr", "de-DE"})
    assert r["ok"] is False and "Gallery" in str(r["detail"]["missing"])


def test_localize_gate_fails_undertranslated_key(tmp_path: Path):
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")\nText("Save")')
    # Save only exists in tr → de-DE missing (half-English bug)
    _write_catalog(tmp_path, {
        "Continue": {"tr": "Devam", "de-DE": "Weiter"},
        "Save": {"tr": "Kaydet"}})
    r = gates._gate_localize(tmp_path, required_locales={"tr", "de-DE"})
    assert r["ok"] is False and "Save" in str(r["detail"]["missing"])


def test_localize_gate_fails_no_catalog(tmp_path: Path):
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")')
    r = gates.validate_stage(tmp_path, "localize")
    assert r["ok"] is False


def test_localize_gate_fails_when_nothing_translated(tmp_path: Path):
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")')
    res = tmp_path / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "Localizable.xcstrings").write_text(json.dumps({
        "sourceLanguage": "en", "version": "1.0",
        "strings": {"Continue": {"localizations": {
            "tr": {"stringUnit": {"state": "new", "value": ""}}}}}}), encoding="utf-8")
    assert gates.validate_stage(tmp_path, "localize")["ok"] is False


def test_localize_gate_fails_incomplete_48(tmp_path: Path):
    # All UI keys translated but only 2 languages → 48-coverage fail (dispatcher default IN_APP_LOCALES)
    _init_manifest(tmp_path)
    _write_swift(tmp_path, 'Text("Continue")')
    _write_catalog(tmp_path, {"Continue": {"tr": "Devam", "de-DE": "Weiter"}})
    r = gates.validate_stage(tmp_path, "localize")
    assert r["ok"] is False and "missing languages" in r["reason"]


def test_features_gate_requires_build_and_test(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "features")["ok"] is False  # marker missing
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "features.json").write_text(json.dumps({"build_ok": True, "test_ok": False}))
    assert gates.validate_stage(tmp_path, "features")["ok"] is False  # test fail
    (v / "features.json").write_text(json.dumps({"build_ok": True, "test_ok": True}))
    # build+test OK but no paywall funnel source → still fail (REQUIRED funnel)
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    src = tmp_path / "Sources"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Views.swift").write_text(
        "struct PaywallView: View { enum Variant { case hard, offer } }\n"
        "struct PaywallFlow: View { var body: some View { PaywallView() } }\n"
    )
    # funnel present but no App.swift onboarding→paywall link → still fail
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    (src / "App.swift").write_text(
        "@AppStorage(\"onboarding_completed\") var onboarded = false\n"
        ".fullScreenCover { PaywallFlow { } }\n"
    )
    # funnel + link present but no paywall legal links → still fail
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    (src / "Views.swift").write_text(
        "struct PaywallView: View { enum Variant { case hard, offer }\n"
        "  func body() { Button(\"Restore\"){}; Button(\"Terms of Use\"){ openURL(AppConfig.termsURL) }\n"
        "    Button(\"Privacy Policy\"){ openURL(AppConfig.privacyURL) } } }\n"
        "struct PaywallFlow: View { var body: some View { PaywallView() } }\n"
    )
    # legal links present but the required funnel analytics are not wired → still fail
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    (src / "Analytics.swift").write_text(
        "// catalog events wired across the app\n"
        + "\n".join(f"Tracker.log(.{e})" for e in gates._REQUIRED_EVENTS) + "\n"
    )
    # analytics wired but RevenueCat SPM unverifiable (no project.yml) → still fail
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    (tmp_path / "project.yml").write_text(
        "packages:\n  RevenueCat:\n    url: https://github.com/RevenueCat/purchases-ios.git\n"
        "targets:\n  App:\n    dependencies:\n      - package: RevenueCat\n        product: RevenueCat\n"
    )
    (src / "StoreManager.swift").write_text("import RevenueCat\n")
    # RC wired but the two-product offer funnel is not declared → still fail
    assert gates.validate_stage(tmp_path, "features")["ok"] is False
    (src / "AppConfig.swift").write_text(
        "static let yearlyOfferProductID = \"y.offer\"\n"
        "static let weeklyOfferProductID = \"w.offer\"\n"
        "static func offerProductID(_ id: String) -> String { id + \".offer\" }\n"
    )
    # funnel complete but no success-moment rating request → still fail (mandatory since 2026-09-27)
    r = gates.validate_stage(tmp_path, "features")
    assert r["ok"] is False and "RatingPolicy" in r["reason"]
    _write_rating(src)
    # rating wired but the tabs are not the native iOS 26 chrome → still fail
    r = gates.validate_stage(tmp_path, "features")
    assert r["ok"] is False and "TabView" in r["reason"]
    _write_native_tabs(src)
    (v / "features.json").write_text(json.dumps({"build_ok": True, "test_ok": True, "sdk": "iphonesimulator26.2"}))
    # everything static passes but the Maestro smoke flows never ran → still fail
    r = gates.validate_stage(tmp_path, "features")
    assert r["ok"] is False and ".maestro" in r["reason"]
    (tmp_path / ".maestro").mkdir()
    (v / "maestro.json").write_text(json.dumps(
        {"flows": [{"name": "smoke_onboarding_paywall", "passed": True, "tags": ["smoke"]}], "ran_at": 9e9}))
    assert gates.validate_stage(tmp_path, "features")["ok"] is True


_NATIVE_TABS = (
    "struct MainTabs: View { var body: some View { TabView(selection: $s) {\n"
    "  Tab(\"Home\", systemImage: \"house\", value: 1) { HomeView() }\n"
    "  Tab(value: 0, role: .search) { CreateView() } label: { Label(\"Create\", image: \"c\") } }\n"
    "  .modifier(Min()) } }\n"
    "struct Min: ViewModifier { func body(content: Content) -> some View {\n"
    "  if #available(iOS 26, *) { content.tabBarMinimizeBehavior(.onScrollDown) } else { content } } }\n")


def _write_native_tabs(src: Path) -> None:
    (src / "Main").mkdir(parents=True, exist_ok=True)
    (src / "Main" / "MainTabs.swift").write_text(_NATIVE_TABS)


def test_native_chrome_check(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gates, "_ios_sdk_version", lambda: "26.2")
    src = tmp_path / "Sources"
    _write_native_tabs(src)
    assert gates._check_native_chrome(tmp_path)["ok"] is True
    # a custom-drawn top bar / tab bar fails
    (src / "DesignSystem.swift").write_text("struct StitchTopBar<T: View>: View { }\n")
    r = gates._check_native_chrome(tmp_path)
    assert r["ok"] is False and "StitchTopBar" in r["reason"]
    (src / "DesignSystem.swift").write_text("struct FloatingTabBar: View { }\n")
    assert "FloatingTabBar" in gates._check_native_chrome(tmp_path)["reason"]
    (src / "DesignSystem.swift").write_text("let x = 1\n")
    # hiding the system tab bar (a custom bar drawn instead) fails
    (src / "Main" / "Home.swift").write_text("HomeView().toolbar(.hidden, for: .tabBar)\n")
    assert "tab bar is hidden" in gates._check_native_chrome(tmp_path)["reason"]
    # a hidden navigation bar fails in the main app, not in the onboarding/paywall funnel
    (src / "Main" / "Home.swift").write_text("HomeView().navigationBarHidden(true)\n")
    assert "navigation bar is hidden" in gates._check_native_chrome(tmp_path)["reason"]
    (src / "Main" / "Home.swift").unlink()
    (src / "Onboarding").mkdir()
    (src / "Onboarding" / "OnboardingView.swift").write_text("Step().toolbar(.hidden, for: .navigationBar)\n")
    assert gates._check_native_chrome(tmp_path)["ok"] is True
    # the main action must be the search-role tab, and the bar minimizes on scroll
    (src / "Main" / "MainTabs.swift").write_text(_NATIVE_TABS.replace("role: .search", "role: nil"))
    assert "search-role" in gates._check_native_chrome(tmp_path)["reason"]
    (src / "Main" / "MainTabs.swift").write_text(_NATIVE_TABS.replace("tabBarMinimizeBehavior", "x"))
    assert "minimize" in gates._check_native_chrome(tmp_path)["reason"]
    # tab items only (no Tab API) fail
    (src / "Main" / "MainTabs.swift").write_text("TabView { A().tabItem { Text(\"a\") } }\n")
    assert "TabView" in gates._check_native_chrome(tmp_path)["reason"]
    _write_native_tabs(src)
    # the build SDK must be iOS 26+: the marker's sdk wins over the installed Xcode
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True)
    (v / "features.json").write_text(json.dumps({"sdk": "iphonesimulator18.5"}))
    assert "SDK" in gates._check_native_chrome(tmp_path)["reason"]
    (v / "features.json").write_text(json.dumps({"sdk": "iphonesimulator26.0"}))
    assert gates._check_native_chrome(tmp_path)["ok"] is True
    (v / "features.json").unlink()
    monkeypatch.setattr(gates, "_ios_sdk_version", lambda: None)
    assert "unknown" in gates._check_native_chrome(tmp_path)["reason"]


def _write_rating(src: Path) -> None:
    (src / "Core").mkdir(parents=True, exist_ok=True)
    (src / "Core" / "RatingPolicy.swift").write_text("final class RatingPolicy { static let shared = RatingPolicy() }\n")
    (src / "RootTabView.swift").write_text(
        "struct RootTabView: View { @State var t: RatingPolicy.Trigger?\n"
        "  var body: some View { Text(\"\").onChange(of: n) { t = RatingPolicy.shared.request(forSuccessCount: n, distinctDays: d) }\n"
        "    .ratingRequest($t) } }\n")


def test_rating_requests_are_mandatory_and_never_in_onboarding(tmp_path: Path):
    src = tmp_path / "Sources"
    src.mkdir()
    assert "RatingPolicy missing" in gates._check_rating_requests(tmp_path)["reason"]
    (src / "Core").mkdir()
    (src / "Core" / "RatingPolicy.swift").write_text("final class RatingPolicy {}\n")
    assert "success-moment" in gates._check_rating_requests(tmp_path)["reason"]
    _write_rating(src)
    assert gates._check_rating_requests(tmp_path)["ok"] is True
    # A rejected pattern: a rating step inside onboarding, in any onboarding file
    (src / "Onboarding" / "Screens").mkdir(parents=True)
    (src / "Onboarding" / "Screens" / "InfoScreens.swift").write_text(
        "struct RatingScreen: View { @Environment(\\.requestReview) var requestReview }\n")
    r = gates._check_rating_requests(tmp_path)
    assert r["ok"] is False and "InfoScreens.swift" in r["reason"]
    (src / "Onboarding" / "Screens" / "InfoScreens.swift").unlink()
    (src / "Views.swift").write_text("struct OnboardingView: View { func done() { requestReview() } }\nstruct X {}\n")
    assert "OnboardingView" in gates._check_rating_requests(tmp_path)["reason"]


def test_icon_gate(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "icon")["ok"] is False
    ai = tmp_path / "Resources" / "Assets.xcassets" / "AppIcon.appiconset"
    ai.mkdir(parents=True, exist_ok=True)
    (ai / "icon1024.png").write_bytes(b"\x89PNG")
    (ai / "Contents.json").write_text(json.dumps(
        {"images": [{"size": "1024x1024", "filename": "icon1024.png", "idiom": "ios-marketing"}]}))
    # a filled appiconset alone is not enough: the icon must come from Claude Design (icon_install)
    r = gates.validate_stage(tmp_path, "icon")
    assert r["ok"] is False and "Claude Design" in r["reason"]  # happy path: test_design.py::test_icon_install_and_gate


def test_scaffold_gate(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "scaffold")["ok"] is False  # xcodeproj missing
    (tmp_path / "DemoApp.xcodeproj").mkdir()
    assert gates.validate_stage(tmp_path, "scaffold")["ok"] is False  # project.yml missing
    (tmp_path / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n',
        encoding="utf-8")
    # iPhone-only flags missing → fail
    assert gates.validate_stage(tmp_path, "scaffold")["ok"] is False
    (tmp_path / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n'
        '    SUPPORTS_MACCATALYST: NO\n'
        '    SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD: NO\n'
        '    SUPPORTS_XR_DESIGNED_FOR_IPHONE_IPAD: NO\n',
        encoding="utf-8")
    assert gates.validate_stage(tmp_path, "scaffold")["ok"] is True


def test_scaffold_gate_fails_without_iphone_only_flags(tmp_path: Path):
    _init_manifest(tmp_path)
    (tmp_path / "DemoApp.xcodeproj").mkdir()
    (tmp_path / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n',
        encoding="utf-8")  # no SUPPORTS_ flags → visible on iPad/Mac
    r = gates.validate_stage(tmp_path, "scaffold")
    assert r["ok"] is False and "SUPPORTS_" in r["reason"]


def test_scaffold_gate_fails_without_portrait(tmp_path: Path):
    _init_manifest(tmp_path)
    (tmp_path / "DemoApp.xcodeproj").mkdir()
    (tmp_path / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n', encoding="utf-8")  # portrait missing
    r = gates.validate_stage(tmp_path, "scaffold")
    assert r["ok"] is False and "portrait" in r["reason"].lower()


def test_scaffold_gate_fails_ipad(tmp_path: Path):
    _init_manifest(tmp_path)
    (tmp_path / "DemoApp.xcodeproj").mkdir()
    (tmp_path / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1,2"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n',
        encoding="utf-8")  # iPad dahil
    assert gates.validate_stage(tmp_path, "scaffold")["ok"] is False


def test_backend_gate_requires_firebase_plist(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "backend")["ok"] is False  # plist missing
    res = tmp_path / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    # incomplete plist (no GOOGLE_APP_ID/PROJECT_ID) → fail
    (res / "GoogleService-Info.plist").write_text(
        "<plist><dict><key>BUNDLE_ID</key><string>x</string></dict></plist>", encoding="utf-8")
    assert gates.validate_stage(tmp_path, "backend")["ok"] is False
    # Firebase installed (GA4 project present) — passes EVEN IF IS_ANALYTICS_ENABLED is false (shipped apps do that)
    (res / "GoogleService-Info.plist").write_text(
        "<plist><dict><key>GOOGLE_APP_ID</key><string>1:1:ios:2</string>"
        "<key>PROJECT_ID</key><string>exampleproj</string>"
        "<key>IS_ANALYTICS_ENABLED</key><false/></dict></plist>", encoding="utf-8")
    assert gates.validate_stage(tmp_path, "backend")["ok"] is True


def test_iap_gate_passes_full():
    st = {"ok": True, "subscriptions": [{"id": "s1", "localizations": ["en-US", "tr"], "intro_offers": 1}],
          "group_localizations": ["en-US", "tr"], "availability": True, "price": True}
    assert gates._gate_iap(Path("/x"), st)["ok"] is True


def test_iap_gate_fails_missing_group_localization():
    st = {"ok": True, "subscriptions": [{"id": "s1", "localizations": ["en-US", "tr"]}],
          "group_localizations": [], "availability": True, "price": True}
    r = gates._gate_iap(Path("/x"), st)
    assert r["ok"] is False and "GROUP" in r["reason"]


def test_iap_gate_fails_group_behind_subs():
    st = {"ok": True, "subscriptions": [{"id": "s1", "localizations": ["en-US", "tr", "de-DE"]}],
          "group_localizations": ["en-US"], "availability": True, "price": True}
    r = gates._gate_iap(Path("/x"), st)
    assert r["ok"] is False and ("tr" in r["reason"] or "de-DE" in r["reason"])


def test_iap_gate_fails_no_subscription_avail_or_price():
    base = {"ok": True, "subscriptions": [{"id": "s1", "localizations": ["en-US"], "intro_offers": 1}],
            "group_localizations": ["en-US"]}
    assert gates._gate_iap(Path("/x"), {"ok": True, "subscriptions": [],
            "group_localizations": ["en-US"], "availability": True, "price": True})["ok"] is False
    assert gates._gate_iap(Path("/x"), {**base, "availability": False, "price": True})["ok"] is False
    assert gates._gate_iap(Path("/x"), {**base, "availability": True, "price": False})["ok"] is False


def test_iap_gate_fails_reader_error():
    assert gates._gate_iap(Path("/x"), {"ok": False, "error": "no creds"})["ok"] is False


def test_iap_gate_fails_no_intro_offer():
    st = {"ok": True, "subscriptions": [{"id": "s1", "localizations": ["en-US"], "intro_offers": 0}],
          "group_localizations": ["en-US"], "availability": True, "price": True}
    r = gates._gate_iap(Path("/x"), st)
    assert r["ok"] is False and "intro offer" in r["reason"].lower()


def test_submission_prep_gate(tmp_path: Path):
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "submission_prep")["ok"] is False  # marker missing
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    full = {k: True for k in ["content_rights", "copyright", "age_rating", "review_contact", "price", "app_privacy"]}
    (v / "submission_prep.json").write_text(json.dumps({**full, "app_privacy": False}), encoding="utf-8")
    assert gates.validate_stage(tmp_path, "submission_prep")["ok"] is False  # app_privacy missing
    (v / "submission_prep.json").write_text(json.dumps(full), encoding="utf-8")
    assert gates.validate_stage(tmp_path, "submission_prep")["ok"] is True


def test_repo_gate(tmp_path: Path):
    import subprocess
    _init_manifest(tmp_path)
    assert gates.validate_stage(tmp_path, "repo")["ok"] is False  # .git missing
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    assert gates.validate_stage(tmp_path, "repo")["ok"] is False  # remote missing
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "git@github.com:x/y.git"], capture_output=True)
    assert gates.validate_stage(tmp_path, "repo")["ok"] is True


def test_marker_gates_ai_proxy_asc_app_metadata_deliver(tmp_path: Path):
    _init_manifest(tmp_path)
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    for stage in ("ai_proxy", "asc_app", "metadata", "deliver"):
        assert gates.validate_stage(tmp_path, stage)["ok"] is False  # marker missing
    (v / "ai_proxy.json").write_text('{"ok": true}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "ai_proxy")["ok"] is True
    (v / "asc_app.json").write_text('{"app_id": "6780997209"}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "asc_app")["ok"] is True
    (v / "metadata.json").write_text('{"privacy_url": "https://x.co/p", "category": "PHOTO_AND_VIDEO"}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "metadata")["ok"] is True
    (v / "metadata.json").write_text('{"privacy_url": "https://x.co/p"}', encoding="utf-8")  # category missing
    assert gates.validate_stage(tmp_path, "metadata")["ok"] is False
    (v / "deliver.json").write_text('{"ok": true}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "deliver")["ok"] is True


def test_screenshots_gate(tmp_path: Path):
    from design_fixtures import design_ready
    tmp_path = design_ready(tmp_path)
    _init_manifest(tmp_path)
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False  # no marker
    (v / "screenshots.json").write_text('{"locales": 12}', encoding="utf-8")  # < 40
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False
    (v / "screenshots.json").write_text('{"locales": 48}', encoding="utf-8")
    # locale sufficient but no font/color review marker → still fail
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False
    (v / "screenshots_review.json").write_text(
        '{"fonts_modern": false, "colors_match_app": true}', encoding="utf-8"
    )  # font not modern
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False
    (v / "screenshots_review.json").write_text(
        '{"fonts_modern": true, "colors_match_app": true}', encoding="utf-8"
    )
    # font/color OK but no app-specific caption copy → still fail
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False
    copy_dir = tmp_path / "marketing" / "screenshots" / "copy"
    copy_dir.mkdir(parents=True, exist_ok=True)
    import json as _json
    good = _json.dumps([{"headline": "Meet Your Baby", "subhead": "A face blended from both of you."}])
    for i in range(42):
        (copy_dir / f"loc{i}.json").write_text(good, encoding="utf-8")
    # captions OK but the Claude Design store boards are still placeholders → fail
    r = gates.validate_stage(tmp_path, "screenshots")
    assert r["ok"] is False and "Claude Design store boards" in r["reason"]
    from design_fixtures import store_ready
    store_ready(tmp_path)
    # boards uploaded + layout applied, but the branded output was not reviewed against them → fail
    r = gates.validate_stage(tmp_path, "screenshots")
    assert r["ok"] is False and "matches_claude_design" in r["reason"]
    (v / "screenshots_review.json").write_text(
        '{"fonts_modern": true, "colors_match_app": true, "matches_claude_design": true}', encoding="utf-8")
    r = gates.validate_stage(tmp_path, "screenshots")
    assert r["ok"] is False and "store_rules_ok" in r["reason"]  # store rules confirmed in the review
    (v / "screenshots_review.json").write_text('{"fonts_modern": true, "colors_match_app": true, '
                                               '"matches_claude_design": true, "store_rules_ok": true}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is True
    # compositor config drifted from the Claude Design layout → fail
    cfg_p = tmp_path / "marketing" / "screenshots" / "config.json"
    cfg = _json.loads(cfg_p.read_text())
    cfg["brandColorTop"] = "#0F766E"
    cfg_p.write_text(_json.dumps(cfg))
    r = gates.validate_stage(tmp_path, "screenshots")
    assert r["ok"] is False and "store layout" in r["reason"]
    from appfactory.design import brand
    brand.apply_layout(tmp_path)
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is True
    # generic/foreign-app caption leak (portrait) → fail
    (copy_dir / "loc0.json").write_text(
        _json.dumps([{"headline": "Your portrait is ready", "subhead": "Save and share."}]),
        encoding="utf-8",
    )
    assert gates.validate_stage(tmp_path, "screenshots")["ok"] is False


def test_testflight_gate(tmp_path: Path):
    _init_manifest(tmp_path)
    v = tmp_path / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    assert gates.validate_stage(tmp_path, "testflight")["ok"] is False  # marker missing
    (v / "testflight.json").write_text('{"build_state": "INVALID"}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "testflight")["ok"] is False
    (v / "testflight.json").write_text('{"build_state": "VALID"}', encoding="utf-8")
    assert gates.validate_stage(tmp_path, "testflight")["ok"] is True


SAMPLE_META_GATE = """# en-US
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
"""


def test_aso_gate_delegates(tmp_path: Path):
    _init_manifest(tmp_path, app_name="DemoApp")
    assert gates.validate_stage(tmp_path, "aso")["ok"] is False  # metadata missing
    md = tmp_path / "outputs" / "DemoApp" / "02-metadata"
    md.mkdir(parents=True, exist_ok=True)
    (md / "apple-metadata.md").write_text(SAMPLE_META_GATE, encoding="utf-8")
    assert gates.validate_stage(tmp_path, "aso")["ok"] is True


# ---------------------------------------------------------------------------
# Task 6: pipeline.mark() gate enforcement + pipeline.validate() helper
# ---------------------------------------------------------------------------

def test_mark_done_refused_when_gate_fails(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    r = pipe.mark(app, "scaffold", "done")  # xcodeproj missing → gate fail
    assert r["ok"] is False
    assert "gate" in r["error"].lower()
    assert r["gate_failure"]["ok"] is False
    assert pipe.load(app)["stages"]["scaffold"] == "pending"  # unchanged


def test_mark_done_allowed_when_gate_passes(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    (app / "DemoApp.xcodeproj").mkdir()
    (app / "project.yml").write_text(
        'settings:\n  base:\n    TARGETED_DEVICE_FAMILY: "1"\n'
        '    INFOPLIST_KEY_UISupportedInterfaceOrientations: UIInterfaceOrientationPortrait\n'
        '    SUPPORTS_MACCATALYST: NO\n'
        '    SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD: NO\n'
        '    SUPPORTS_XR_DESIGNED_FOR_IPHONE_IPAD: NO\n',
        encoding="utf-8")
    r = pipe.mark(app, "scaffold", "done")
    assert r["ok"] is True
    assert pipe.load(app)["stages"]["scaffold"] == "done"


def test_mark_non_done_status_not_gated(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    assert pipe.mark(app, "scaffold", "in_progress")["ok"] is True  # no gate


def test_pipeline_validate_helper(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")
    assert pipe.validate(app, "scaffold")["ok"] is False


# ---------------------------------------------------------------------------
# Task 7: pipeline_validate MCP tool
# ---------------------------------------------------------------------------

def test_pipeline_validate_tool_registered_and_runs(tmp_path: Path):
    app = tmp_path / "DemoApp"
    app.mkdir()
    pipe.init(app, "DemoApp", "com.x.demo")

    async def _call():
        async with Client(mcp) as c:
            names = sorted(t.name for t in await c.list_tools())
            assert "pipeline_validate" in names
            r = await c.call_tool("pipeline_validate", {"app_dir": str(app), "stage": "scaffold"})
            return r.data if hasattr(r, "data") else r

    d = asyncio.run(_call())
    assert d["ok"] is False  # xcodeproj missing


def test_no_push_permission_gate(tmp_path: Path):
    """Asking for push permission is FORBIDDEN — it lowers retention. UNUserNotificationCenter itself is allowed."""
    from appfactory.gates import _check_no_push_permission

    app = tmp_path / "app"
    src = app / "Sources"
    src.mkdir(parents=True)

    # source that does not ask for permission → passes
    (src / "App.swift").write_text("import SwiftUI\nstruct A: App { var body: some Scene { WindowGroup {} } }")
    assert _check_no_push_permission(app)["ok"] is True

    # USING local notifications is allowed (as long as it does not ask for permission)
    (src / "App.swift").write_text("let c = UNUserNotificationCenter.current()\nc.add(req)")
    assert _check_no_push_permission(app)["ok"] is True

    # ASKING for permission is forbidden
    (src / "App.swift").write_text("center.requestAuthorization(options: [.alert]) { _, _ in }")
    r = _check_no_push_permission(app)
    assert r["ok"] is False and "push permission" in r["reason"]

    (src / "App.swift").write_text("UIApplication.shared.registerForRemoteNotifications()")
    assert _check_no_push_permission(app)["ok"] is False


def test_onboarding_depth_gate(tmp_path: Path):
    """Onboarding requires >=12 steps and >=5 questions."""
    from appfactory.gates import _check_onboarding_depth

    app = tmp_path / "app"
    src = app / "Sources"
    src.mkdir(parents=True)

    def steps(n_info: int, n_question: int) -> str:
        body = "".join(f"OnboardingStep(kind: .info)\n" for _ in range(n_info))
        body += "".join(f"OnboardingStep(kind: .question)\n" for _ in range(n_question))
        return "struct OnboardingView: View {\n" + body + "}\n"

    # 9 steps is no longer enough
    (src / "Views.swift").write_text(steps(4, 5))
    r = _check_onboarding_depth(app)
    assert r["ok"] is False and "9 steps" in r["reason"]

    # 12 steps but only 3 questions → fails on the question count
    (src / "Views.swift").write_text(steps(9, 3))
    r = _check_onboarding_depth(app)
    assert r["ok"] is False and "3 questions" in r["reason"]

    # 12 steps + 5 questions → passes
    (src / "Views.swift").write_text(steps(7, 5))
    assert _check_onboarding_depth(app)["ok"] is True

    # no onboarding source → skip (no crash)
    (src / "Views.swift").write_text("struct Other: View {}")
    assert _check_onboarding_depth(app)["ok"] is True


def test_onboarding_depth_template_syntax(tmp_path: Path):
    """The template syntax (.init(title:) + question: OnbQuestion) must be counted too —
    `kind: .question` is not the only valid form."""
    from appfactory.gates import _check_onboarding_depth

    app = tmp_path / "app"
    src = app / "Sources"
    src.mkdir(parents=True)

    def tmpl(n_steps: int, n_q: int) -> str:
        rows = []
        for i in range(n_steps):
            q = ', question: OnbQuestion(prompt: "p", options: ["a","b"])' if i < n_q else ""
            rows.append(f'        .init(title: "T{i}", subtitle: "S{i}", systemImage: "x"{q}),')
        return ("struct OnboardingStep: Identifiable {}\n"
                "struct OnboardingView: View {\n"
                "    private let steps: [OnboardingStep] = [\n" + "\n".join(rows) + "\n    ]\n}\n")

    # current template: 12 steps but 1 question → must fail on the question count
    (src / "Views.swift").write_text(tmpl(12, 1))
    r = _check_onboarding_depth(app)
    assert r["ok"] is False and "1 question" in r["reason"]

    # 12 steps + 5 questions → passes
    (src / "Views.swift").write_text(tmpl(12, 5))
    r = _check_onboarding_depth(app)
    assert r["ok"] is True and "12 steps / 5 questions" in r["reason"]


def test_plural_forms_follow_cldr_per_language():
    from appfactory import localize
    unit = lambda *cats: {"variations": {"plural": {c: {"stringUnit": {"state": "translated", "value": c}} for c in cats}}}  # noqa: E731
    cat = {"strings": {"%lld days": {"localizations": {
        "en": unit("one", "other"), "ru": unit("one", "other"), "tr": unit("one", "other"),
        "ja": {"stringUnit": {"state": "translated", "value": "%lld日"}}, "fr": unit("one", "other")}},
        "Continue": {"localizations": {"en": {"stringUnit": {"state": "translated", "value": "Continue"}}}}}}
    probs = localize.plural_problems(cat, ["ru", "tr", "ja", "fr"])
    assert probs == ["ru '%lld days': missing plural ['few', 'many']"]
    assert localize.plural_problems(cat, ["ar"]) == ["ar '%lld days': missing plural ['few', 'many', 'one', 'other', 'two', 'zero']"]
