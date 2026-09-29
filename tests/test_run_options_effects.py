"""Run options that reshape the app are acted on, end to end: spec, StoreKit, store_setup, template, gates.

Every option is on by default; the golden scaffold test (test_services.py) keeps that path byte-identical.
Here each option is turned off and nothing of it may be left behind (code, imports, products), while the
gates report the matching part as n/a instead of failing or silently passing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from appfactory import app, config, design, gates, options, pipeline, server, spec as spec_mod
from appfactory import storekit, store_setup, team

ALL_OPTIONS = ("hard_paywall", "offer_paywall", "onboarding_quiz", "rating_prompts", "sign_in_with_apple",
               "github_issues", "e2e_smoke")


@pytest.fixture(autouse=True)
def _all_services_on(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {})


def _scaffold(tmp_path: Path, off: tuple[str, ...] = (), **spec) -> Path:
    opts = {o: False for o in off}
    r = app.scaffold("Opt", "com.example.opt", dest_dir=str(tmp_path), generate=False,
                     spec={**spec, **({"options": {**spec.get("options", {}), **opts}} if opts else {})})
    assert r["ok"], r
    return Path(r["dir"])


def _code(root: Path) -> str:
    """Swift + XcodeGen + Maestro code of the scaffold, comment lines dropped."""
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in {".swift", ".yml", ".yaml"} and ".xcodeproj" not in p.parts:
            out += [re.sub(r"\s//.*$", "", ln) for ln in p.read_text(encoding="utf-8").splitlines()
                    if not ln.lstrip().startswith(("//", "#"))]
    return "\n".join(out)


def _step_ids(root: Path) -> list[str]:
    return app.onboarding_step_ids(root)


def _marker_free(root: Path) -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*")
                     if p.is_file() and p.suffix in {".swift", ".yml", ".yaml", ".md"} and ".xcodeproj" not in p.parts)
    assert not re.search(r"^\s*(//|#|<!--)\s*@(if|endif)\b", text, re.M)


# ---------- offer_paywall ----------

def test_offer_paywall_off_removes_offer_products_everywhere(tmp_path):
    root = _scaffold(tmp_path, ("offer_paywall",))
    sp = spec_mod.load(root)
    assert spec_mod.validate(sp) == []
    assert [p["key"] for p in sp["subscription"]["products"]] == ["yearly", "weekly"]
    assert sp["offer_placements"] == [] and "offer_after_onboarding" not in sp["placements"]
    assert all("yearly_offer" not in t for t in sp["subscription"]["price_overrides"].values())
    # StoreKit: no offer product
    assert not any(".offer" in s["productID"] for g in storekit.generate(sp)["subscriptionGroups"]
                   for s in g["subscriptions"])
    assert storekit.parity(sp, root / storekit.STOREKIT_REL) == []
    # store_setup + RevenueCat: only the default offering, no offer product, no offer placement
    d = store_setup.desired_state(sp, {})
    assert [o["lookup_key"] for o in d["revenuecat"]["offerings"]] == ["default"]
    assert set(d["revenuecat"]["placements"].values()) == {"default"}
    assert not any(s["product_id"].endswith(".offer") for s in d["subscriptions"])
    # template: no offer screen, no code, no anchor, dismissing the hard paywall ends onboarding
    assert not (root / "Sources/Paywall/OfferPaywallView.swift").exists()
    code = _code(root)
    assert "OfferPaywallView" not in code and "offerAfterOnboarding" not in code and "offerSeen" not in code
    assert "offerAnchor" not in (root / "Sources/App/AppSpec.swift").read_text()
    assert "offer" not in _step_ids(root)
    view = (root / "Sources/Onboarding/OnboardingView.swift").read_text()
    assert "HardPaywallView(source: .onboarding, personalization: personalization, onPurchased: finish, onClose: finish)" in view
    _marker_free(root)


def test_offer_paywall_validation_and_dependency():
    sp = spec_mod.build("Opt", "com.example.opt", options={"offer_paywall": False})
    assert spec_mod.validate(sp) == []
    sp["subscription"]["products"].append({"key": "yearly_offer", "suffix": "yearly.offer", "period": "P1Y", "usd": 29.99,
                                           "level": 1, "intro": None, "offering": "offer", "package": "$rc_annual"})
    assert any("offer paywall is off" in e for e in spec_mod.validate(sp))
    bad = spec_mod.build("Opt", "com.example.opt", options={"hard_paywall": False, "offer_paywall": True})
    assert any("needs options.hard_paywall" in e for e in spec_mod.validate(bad))
    # turning it back on restores the offer product, its placements and price overrides
    on = options.apply_to_spec(spec_mod.build("Opt", "com.example.opt", options={"offer_paywall": False}),
                               {"offer_paywall": True, "hard_paywall": True})
    assert spec_mod.validate(on) == []
    assert "yearly_offer" in [p["key"] for p in on["subscription"]["products"]]
    assert on["offer_placements"] == spec_mod.OFFER_PLACEMENTS


def test_offer_paywall_gate_is_n_a_and_hard_only_is_still_checked(tmp_path):
    root = _scaffold(tmp_path, ("offer_paywall",))
    r = gates._check_paywall_funnel(root)
    assert r["ok"] and "offer paywall n/a" in r["reason"], r
    # the offer code comes back → the gate says so
    (root / "Sources/Paywall/OfferPaywallView.swift").write_text("struct OfferPaywallView {}\n")
    assert not gates._check_paywall_funnel(root)["ok"]


# ---------- hard_paywall ----------

def test_hard_paywall_off_ends_onboarding_in_the_app(tmp_path):
    root = _scaffold(tmp_path, ("hard_paywall", "offer_paywall"))
    sp = spec_mod.load(root)
    assert spec_mod.validate(sp) == [] and not spec_mod.offer_on(sp)
    assert "paywall" not in _step_ids(root) and "offer" not in _step_ids(root)
    view = (root / "Sources/Onboarding/OnboardingView.swift").read_text()
    assert "HardPaywallView" not in view and "model.finished" in view
    assert "finished = true" in (root / "Sources/Onboarding/OnboardingModel.swift").read_text()
    # the paywall stays reachable from placements (Settings, limit hits)
    assert "HardPaywallView" in (root / "Sources/Main/RootTabView.swift").read_text()
    assert "tab_create" in (root / ".maestro/flows/smoke_onboarding_paywall.yaml").read_text()
    assert "paywall_cta" not in (root / ".maestro/flows/smoke_onboarding_paywall.yaml").read_text().split("---", 1)[1].replace(
        "assertNotVisible: {id: paywall_cta}", "")
    r = gates._check_paywall_funnel(root)
    assert r["ok"] and "hard + offer paywall in onboarding n/a" in r["reason"], r
    assert sp["design"]["onboarding_screens"] == len(_step_ids(root))
    _marker_free(root)


def test_hard_paywall_off_implies_offer_off_even_when_only_hard_is_answered(tmp_path):
    sp = spec_mod.build("Opt", "com.example.opt", options={"hard_paywall": False})
    assert spec_mod.validate(sp) == []
    assert not any(p["offering"] == "offer" for p in sp["subscription"]["products"])


def test_hard_paywall_on_gate_rejects_a_missing_paywall_link(tmp_path):
    root = _scaffold(tmp_path, ("offer_paywall",))
    for f in (root / "Sources").rglob("*.swift"):
        f.write_text(f.read_text().replace("HardPaywallView", "SomethingElse"))
    assert not gates._check_paywall_funnel(root)["ok"]


# ---------- onboarding_quiz ----------

def test_quiz_off_is_a_short_intro_without_questions(tmp_path):
    root = _scaffold(tmp_path, ("onboarding_quiz",))
    ids = _step_ids(root)
    steps = (root / "Sources/Onboarding/OnboardingSteps.swift").read_text()
    assert "kind: .question" not in steps and "kind: .picker" not in steps
    assert "static let personalizationSteps: [String] = []" in steps
    assert ids[0] == "welcome" and ids[-2:] == ["paywall", "offer"] and len(ids) < 14
    assert "highlightsCard" not in (root / "Sources/Paywall/HardPaywallView.swift").read_text()
    sp = spec_mod.load(root)
    assert spec_mod.validate(sp) == [] and sp["design"]["onboarding_screens"] == len(ids)
    # gates that count quiz steps skip
    r = gates._check_onboarding_depth(root)
    assert r["ok"] and r["reason"].startswith("n/a"), r
    _marker_free(root)


def test_quiz_off_with_healthkit_keeps_the_consent_step_and_the_spec_count(tmp_path):
    root = _scaffold(tmp_path, ("onboarding_quiz",), health={"enabled": True, "read": ["stepCount"], "write": []},
                     consent={"health": True})
    ids = _step_ids(root)
    assert "health" in ids and spec_mod.load(root)["design"]["onboarding_screens"] == len(ids)


def test_quiz_on_keeps_the_depth_gate(tmp_path):
    root = _scaffold(tmp_path)
    assert gates._check_onboarding_depth(root)["reason"].startswith("onboarding ")
    steps = root / "Sources/Onboarding/OnboardingSteps.swift"
    steps.write_text(steps.read_text().replace("kind: .question", "kind: .info"))
    assert not gates._check_onboarding_depth(root)["ok"]


def test_quiz_off_design_skeleton_and_validation():
    sp = spec_mod.build("Opt", "com.example.opt", options={"onboarding_quiz": False})
    doc = design.skeleton(sp)
    kinds = [s["kind"] for s in doc["onboarding"]]
    assert not {"question", "picker", "preferences"} & set(kinds)
    assert kinds[-3:] == ["account", "paywall", "offer"]
    errs = design.validate_screens(doc, sp)
    assert not any("paywall" in e or "screens <" in e for e in errs), errs


# ---------- rating_prompts ----------

def test_rating_prompts_off_strips_the_rating_code(tmp_path):
    root = _scaffold(tmp_path, ("rating_prompts",))
    assert not (root / "Sources/Core/RatingPolicy.swift").exists()
    assert not (root / "Tests/RatingPolicyTests.swift").exists()
    code = _code(root)
    for leftover in ("RatingPolicy", "requestReview", "ratingRequest", "ratingTrigger", "ratingSuccessCount"):
        assert leftover not in code, leftover
    r = gates._check_rating_requests(root)
    assert r["ok"] and r["reason"].startswith("n/a"), r
    (root / "Sources/Main/Oops.swift").write_text("import StoreKit\nlet x = requestReview\n")
    assert not gates._check_rating_requests(root)["ok"]
    _marker_free(root)


def test_rating_prompts_on_is_still_required(tmp_path):
    root = _scaffold(tmp_path)
    assert gates._check_rating_requests(root)["ok"]
    (root / "Sources/Core/RatingPolicy.swift").unlink()
    assert not gates._check_rating_requests(root)["ok"]


# ---------- sign_in_with_apple ----------

def test_sign_in_with_apple_off_has_no_capability_entitlement_or_ui(tmp_path):
    root = _scaffold(tmp_path, ("sign_in_with_apple",))
    assert not (root / "Sources/Core/AuthProvider.swift").exists()
    code = _code(root)
    for leftover in ("AuthenticationServices", "SignInWithAppleButton", "AccountStepScreen", "AuthProviders",
                     "linkIdentity", "signInWithIdToken", "identityAlreadyExists", "linkedProvider", "applesignin",
                     "AppleSignIn"):
        assert leftover not in code, leftover
    assert "account" not in _step_ids(root)
    sp = spec_mod.load(root)
    assert "APPLE_ID_AUTH" not in [c["capabilityType"] for c in store_setup.capabilities(sp)]
    assert "APPLE_ID_AUTH" not in [c["capabilityType"] for c in store_setup.desired_state(sp, {})["capabilities"]]
    assert "NSPrivacyCollectedDataTypeEmailAddress" not in (root / "Privacy/PrivacyInfo.xcprivacy").read_text()
    assert "applesignin" not in (root / "Tests/PaywallTests.swift").read_text().lower()
    assert "SupabaseAuth" in code  # anonymous auth stays
    assert "Sign in with Apple" not in (root / "store/review-notes.md").read_text()
    _marker_free(root)


def test_sign_in_with_apple_scaffold_gate_follows_the_option(tmp_path):
    root = _scaffold(tmp_path, ("sign_in_with_apple",))
    sp = spec_mod.load(root)
    yml = (root / "project.yml").read_text()
    assert gates._check_scaffold_spec(root, sp, yml)["ok"]
    dirty = yml.replace("properties:", "properties:\n        com.apple.developer.applesignin: [Default]", 1)
    assert not gates._check_scaffold_spec(root, sp, dirty)["ok"]


# ---------- e2e_smoke ----------

def test_e2e_smoke_off_has_no_maestro_workspace_and_the_gate_is_n_a(tmp_path, monkeypatch):
    root = _scaffold(tmp_path, ("e2e_smoke",))
    assert not (root / ".maestro").exists()
    v = root / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "features.json").write_text(json.dumps({"build_ok": True, "test_ok": True, "sdk": "iphonesimulator26.2"}))
    for name in ("_gate_revenuecat", "_check_no_unlimited_claims", "_check_no_advanced_settings",
                 "_check_analytics_coverage", "_check_no_push_permission", "_check_native_chrome", "_check_legal_urls"):
        monkeypatch.setattr(gates, name, lambda *_a, **_k: {"ok": True})
    r = gates._gate_features(root)
    assert r["ok"] and r["e2e_smoke"] == "n/a", r
    # on: the same call needs the smoke flows
    on = _scaffold(tmp_path / "on")
    (on / ".appfactory" / "verify").mkdir(parents=True, exist_ok=True)
    (on / ".appfactory" / "verify" / "features.json").write_text(
        json.dumps({"build_ok": True, "test_ok": True, "sdk": "iphonesimulator26.2"}))
    assert not gates._gate_features(on)["ok"]


def test_testflight_ship_skips_the_smoke_gate_only_when_the_option_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_approval", lambda *a, **k: None)
    monkeypatch.setattr(store_setup, "capabilities_pending", lambda _d: [])
    monkeypatch.setattr(server.sign_mod, "ship_testflight", lambda *a: {"ok": True, "shipped": True})
    off = _scaffold(tmp_path / "off", ("e2e_smoke",))
    assert server.testflight_ship(str(off), "p", "s", "b")["shipped"] is True
    on = _scaffold(tmp_path / "on")
    r = server.testflight_ship(str(on), "p", "s", "b")
    assert r["ok"] is False and "Maestro smoke gate" in r["error"]


# ---------- github_issues ----------

def test_github_issues_off_skips_tools_steps_and_docs(tmp_path):
    root = _scaffold(tmp_path, ("github_issues",))
    # pipeline instruction
    pipeline.init(root, "Opt", "com.example.opt")
    assert "github_issue" not in pipeline.stage_instruction(root, "repo")
    assert "github_create_repo" in pipeline.stage_instruction(root, "repo")
    # tools are n/a and never reach gh
    r = server.github_issue_create("me/opt", "t", ["ios"], "b", app_dir=str(root))
    assert r["ok"] and r["skipped"] and r["option_disabled"] == "github_issues"
    assert server.github_issues_bootstrap("me/opt", app_dir=str(root))["skipped"] is True
    # team docs
    res = team.brief(root)
    assert res["ok"], res
    docs = (root / "docs/TEAM.md").read_text() + (root / "docs/CHECKLIST.md").read_text()
    for gone in ("GitHub Issues", "gh issue", "github_issues_bootstrap", "(`#12`)", "commit or issue", "@if", "@endif"):
        assert gone not in docs, gone


def test_github_issues_on_keeps_the_issue_instructions(tmp_path):
    root = _scaffold(tmp_path)
    pipeline.init(root, "Opt", "com.example.opt")
    assert "github_issues_bootstrap" in pipeline.stage_instruction(root, "repo")
    assert team.brief(root)["ok"]
    assert "GitHub Issues" in (root / "docs/TEAM.md").read_text()
    assert "@if" not in (root / "docs/TEAM.md").read_text()


def test_github_issue_tools_read_the_pending_answers_before_the_app_exists(tmp_path):
    p = options.pending_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"answers": {"github_issues": False}, "options_confirmed": True}))
    assert server.github_issue_create("me/x", "t", [], "b")["skipped"] is True


# ---------- shared ----------

def test_every_stage_instruction_edit_still_matches():
    for oid, edits in pipeline.OPTION_OFF_EDITS.items():
        for stage, pattern, repl in edits:
            text = pipeline.STAGE_INSTRUCTIONS[stage]
            assert re.search(pattern, text, re.S), f"{oid}/{stage}: the instruction text drifted, update the edit"
            assert re.sub(pattern, repl, text, flags=re.S) != text


def test_all_options_off_scaffold_is_clean_and_valid(tmp_path):
    root = _scaffold(tmp_path, ALL_OPTIONS, services={"revenuecat": False, "supabase": False, "firebase": False},
                     ai={"enabled": False})
    sp = spec_mod.load(root)
    assert spec_mod.validate(sp) == []
    assert sp["design"]["onboarding_screens"] == len(_step_ids(root)) == 8
    code = _code(root)
    for leftover in ("OfferPaywallView", "RatingPolicy", "AuthProviders", "SignInWithAppleButton", "requestReview",
                     "@if", "@endif"):
        assert leftover not in code, leftover
    assert not (root / ".maestro").exists()
    _marker_free(root)


def test_defaults_change_nothing_in_the_spec_or_the_flags():
    sp = spec_mod.build("Opt", "com.example.opt")
    assert "options" not in sp and sp["design"]["onboarding_screens"] == 26
    assert all(app.feature_flags(sp)[f] for f in ("hard_paywall", "offer_paywall", "quiz", "ratings", "siwa", "e2e_smoke"))
    assert options.apply_to_spec(sp, {o["id"]: o["default"] for o in options.OPTIONS
                                      if o["store"].startswith("spec.")})["design"]["onboarding_screens"] == 26
