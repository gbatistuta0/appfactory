"""gates — MACHINE verification of each stage's quality rules (a gate that cannot be bypassed).

pipeline.mark(stage,"done") calls this; if it fails, the stage does NOT become 'done'.
Leaf module: depends only on config + aso (NOT on pipeline → no import cycle).
Reads the manifest directly from .appfactory/state.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

# Legacy Stitch manifest (pre-Claude Design apps). No longer accepted by the design gate.
LEGACY_STITCH_MANIFEST_REL = ".appfactory/design/screens.json"

GATE_NONE = {"ok": True, "reason": "no gate (no strict gate defined for this stage)"}


def _load_manifest(app: Path) -> dict[str, Any]:
    p = app / ".appfactory" / "state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_spec(app: Path) -> dict[str, Any] | None:
    """app.spec.json if present (spec-driven checks); None keeps the legacy behaviour."""
    p = app / "app.spec.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# Stages that only make sense with an optional service: with that service disabled the stage is
# reported as skipped ("n/a") instead of failing. Stages with partial service use guard inside their
# gate (backend, features, icon, screenshots, design).
STAGE_SERVICES: dict[str, tuple[str, ...]] = {
    "repo": ("github",),
    "design": ("design",),
    "ai_proxy": ("supabase",),
    "asc_app": ("apple",),
    "iap": ("apple",),
    "metadata": ("apple",),
    "deliver": ("apple",),
    "app_preview": ("apple",),
    "custom_product_pages": ("apple",),
    "testflight": ("apple", "xcode"),
    "submission_prep": ("apple",),
}


def stage_disabled_service(stage: str) -> str | None:
    """The disabled service that makes `stage` n/a, or None."""
    from . import config as cfg
    return cfg.first_disabled(STAGE_SERVICES.get(stage, ()))


def _on(service: str) -> bool:
    from . import config as cfg
    return cfg.first_disabled((service,)) is None


def validate_stage(app_dir: str | Path, stage: str) -> dict[str, Any]:
    """Run the gate for a stage. Undefined stage → GATE_NONE (passes)."""
    app = Path(app_dir).expanduser()
    off = stage_disabled_service(stage)
    if off:
        from . import config as cfg
        return {"ok": True, "skipped": True, "service_disabled": off,
                "reason": f"n/a — stage '{stage}' skipped: " + cfg.disabled_message(off)}
    from . import options as options_mod
    opt = options_mod.stage_disabled_option(app, stage)
    if opt:
        return {"ok": True, "skipped": True, "option_disabled": opt,
                "reason": f"n/a — stage '{stage}' skipped: the user turned off the '{opt}' run option"}
    fn = _GATES.get(stage)
    if fn is None:
        return dict(GATE_NONE)
    return fn(app)


CLAUDE_SCREENS_REL = "design/screens.json"
CLAUDE_CANVAS_REL = "design/project/canvas.json"
DESIGN_REVIEW_REL = ".appfactory/verify/design_review.json"


def _gate_design(app: Path) -> dict[str, Any]:
    """Claude Design is the only accepted design source: design/screens.json → generated canvas → uploaded."""
    if (app / CLAUDE_SCREENS_REL).exists():
        return _gate_design_claude(app)
    if (app / LEGACY_STITCH_MANIFEST_REL).exists():
        return {"ok": False, "reason": f"Stitch designs ({LEGACY_STITCH_MANIFEST_REL}) are no longer accepted — "
                f"redesign in Claude Design: design_screens_skeleton → {CLAUDE_SCREENS_REL} → design_generate → "
                "upload → design_record_upload"}
    return {"ok": False, "reason": f"no design: write {CLAUDE_SCREENS_REL} (design_screens_skeleton → adapt every screen "
            "→ design_generate → upload to Claude Design → design_record_upload)"}


def _check_design_review(app: Path) -> dict[str, Any]:
    """Visual fidelity sign-off: every SwiftUI screen compared against its board (every app, every time)."""
    review = app / DESIGN_REVIEW_REL
    if not review.exists():
        return {"ok": False, "reason": f"design_review missing — compare every SwiftUI screen's screenshot with its "
                f'design board and write {DESIGN_REVIEW_REL} {{"fidelity_ok": true}} (a generic template restyle is rejected)'}
    try:
        rv = json.loads(review.read_text(encoding="utf-8"))
        if not rv.get("fidelity_ok"):
            return {"ok": False, "reason": "design_review fidelity_ok != true (screens do not match the design)"}
        if not rv.get("platform_rules_ok"):
            from .design.rules import APP_RULES
            return {"ok": False, "reason": "design_review platform_rules_ok != true — confirm the structural rules: "
                    + " | ".join(APP_RULES)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"design_review unreadable: {e}"}
    return {"ok": True}


def _gate_design_claude(app: Path) -> dict[str, Any]:
    from . import design as design_mod
    from .design import screens as screens_mod

    try:
        doc = json.loads((app / CLAUDE_SCREENS_REL).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{CLAUDE_SCREENS_REL} unreadable: {e}"}
    from .design import research
    rc = research.check(app)
    if not rc["ok"]:
        return rc
    spec = _load_spec(app) or {}
    errs = design_mod.validate_screens(doc, spec) + research.derive_problems(app, spec, doc)
    if errs:
        more = f" (+{len(errs) - 3} more)" if len(errs) > 3 else ""
        return {"ok": False, "reason": f"{CLAUDE_SCREENS_REL}: " + "; ".join(errs[:3]) + more, "problems": errs}
    canvas_p = app / CLAUDE_CANVAS_REL
    if not canvas_p.exists():
        return {"ok": False, "reason": f"{CLAUDE_CANVAS_REL} missing — run design_generate and upload the project"}
    try:
        boards = json.loads(canvas_p.read_text(encoding="utf-8")).get("boards") or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"canvas.json unreadable: {e}"}
    files = screens_mod.files(doc)
    stale = sorted(f for f in files.values() if f not in boards or not (canvas_p.parent / f).exists())
    if stale:
        return {"ok": False, "reason": f"canvas is stale (re-run design_generate): missing {', '.join(stale[:5])}"}
    if not any(b.get("page") == "mascot" for b in boards.values()):
        return {"ok": False, "reason": "canvas has no mascot motion page — re-run design_generate"}
    from .design import brand
    missing = [f for f in [brand.ICON_BOARD, *brand.store_files(research.load_brief(app) or {})] if f not in boards]
    if missing:
        return {"ok": False, "reason": f"canvas has no icon/store boards ({', '.join(missing[:3])}) — re-run design_generate"}
    authored = design_mod.authored_problems(app)
    if authored:
        more = f" (+{len(authored) - 3} more)" if len(authored) > 3 else ""
        return {"ok": False, "reason": "authored boards: " + "; ".join(authored[:3]) + more, "problems": authored}
    from .design import receipt
    up = receipt.check_after_brief(app)
    if not up["ok"]:
        return up
    if not list(app.rglob("DesignSystem.swift")):
        return {"ok": False, "reason": "DesignSystem.swift missing (design tokens → SwiftUI translation missing)"}
    review = _check_design_review(app)
    if not review["ok"]:
        return review
    return {"ok": True, "reason": f"Claude Design: {len(doc['onboarding'])} onboarding + {len(doc['main'])} main screens, "
            f"each individually specified and authored from the brief, uploaded to project {up['project_id']}, "
            "fidelity approved"}


def _gate_design_research(app: Path) -> dict[str, Any]:
    """Competitor/top-chart references downloaded + a cited, differentiated brief (design/research/)."""
    from .design import research
    return research.check(app)


# title:/subtitle: intentionally broad — the playbook says to scan SettingsRow(title:)/option subtitles too.
# BROAD: bare-arg LocalizedStringKeys (genderChip("Girl")), arrays and String(localized:) are caught as well
# (these once slipped through unlocalized → onboarding/paywall stayed in English).
_LOC_PATTERNS = [
    re.compile(r'Text\(\s*"([^"\\]+)"'),
    re.compile(r'Button\(\s*"([^"\\]+)"'),
    re.compile(r'Label\(\s*"([^"\\]+)"'),
    re.compile(r'\.navigationTitle\(\s*"([^"\\]+)"'),
    re.compile(r'\.alert\(\s*"([^"\\]+)"'),
    re.compile(r'\btitle:\s*"([^"\\]+)"'),
    re.compile(r'\bsubtitle:\s*"([^"\\]+)"'),
    re.compile(r'\b(?:uploadLabel|label|placeholder|message|header|note|caption|hint|prompt2|cta):\s*"([^"\\]+)"'),
    re.compile(r'(?:genderChip|onbUploadTile|traitChip|featureChip|pill|chip)\(\s*"([^"\\]+)"'),
    re.compile(r'LocalizedStringKey\(\s*"([^"\\]+)"'),
    re.compile(r'String\(localized:\s*"([^"\\]+)"'),
]
# Non-UI code/payload keys (must not be localized) — false-positive filtering.
_NON_UI_KEYS = {
    "action", "url", "prompt", "model", "result", "image", "images", "detail", "error",
    "from", "gender", "style", "props", "name", "CFBundleShortVersionString", "%@", "·",
    "Authorization", "Content-Type", "apikey", "image_url", "image_urls", "data",
}


_SKIP_SWIFT_DIRS = ("/.build/", "/build/", "SourcePackages", "checkouts", "DerivedData",
                    "/Pods/", "Tests", ".xcodeproj", ".xcassets")


def _extract_ui_keys(app: Path) -> set[str]:
    keys: set[str] = set()
    # Only the app's OWN sources (Sources/). Dependency/SPM/build .swift files (Firebase,
    # SwiftProtobuf etc.) are EXCLUDED — otherwise their strings would count as "missing localization".
    roots = [app / "Sources"] if (app / "Sources").exists() else [app]
    for root in roots:
        for sw in root.rglob("*.swift"):
            sp = str(sw)
            if any(skip in sp for skip in _SKIP_SWIFT_DIRS):
                continue
            txt = sw.read_text(encoding="utf-8", errors="ignore")
            for pat in _LOC_PATTERNS:
                keys.update(m.group(1) for m in pat.finditer(txt))
            # [LocalizedStringKey]/[String] arrays: UI arrays such as ForEach(["EYES","SMILE",...]).
            for arr in re.finditer(r'\[\s*((?:(?:LocalizedStringKey\()?"[^"\\]+"\)?\s*,\s*)+(?:LocalizedStringKey\()?"[^"\\]+"\)?)\s*\]', txt):
                for s in re.findall(r'"([^"\\]+)"', arr.group(1)):
                    # a single-word UI label or a sentence with spaces; exclude pure code keys
                    # all-caps single tokens in arrays are flags/codes (["YES", "TRUE"]), not copy
                    if s and (s[0].isupper() or " " in s) and not (s.isupper() and " " not in s):
                        keys.add(s)
    # Drop code/payload keys and single-character punctuation/format strings.
    # dotted identifiers without spaces (queue labels, bundle ids, semantic keys) are not copy
    return {k for k in keys if k not in _NON_UI_KEYS and len(k) > 1 and "%" not in k
            and not ("." in k and " " not in k)}


def _gate_localize(app: Path, required_locales: set[str] | None = None) -> dict[str, Any]:
    cat = app / "Resources" / "Localizable.xcstrings"
    if not cat.exists():
        return {"ok": False, "reason": "Localizable.xcstrings missing (localize has not run)"}
    try:
        strings = json.loads(cat.read_text(encoding="utf-8")).get("strings", {})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"catalog unreadable: {e}"}

    ui_keys = _extract_ui_keys(app)
    if not ui_keys:
        return {"ok": True, "reason": "no UI strings extracted from code (gate passed vacuously)"}

    # Languages the catalog supports = union of translated languages across all keys
    app_locales: set[str] = set()
    for meta in strings.values():
        for loc, unit in meta.get("localizations", {}).items():
            if unit.get("stringUnit", {}).get("state") == "translated":
                app_locales.add(loc)

    if not app_locales:
        return {"ok": False, "reason": "catalog has no translations in the 'translated' state (localize incomplete)"}

    # Full language coverage. required_locales > app.spec.json locales.app (minus the en source)
    # > legacy config.IN_APP_LOCALES for apps without a spec.
    from . import config as cfg
    spec = _load_spec(app)
    if required_locales is not None:
        req = set(required_locales)
    elif spec and spec.get("locales", {}).get("app"):
        req = {loc for loc in spec["locales"]["app"] if loc != "en"}
    else:
        req = set(cfg.IN_APP_LOCALES)
    cov_gap = req - app_locales
    if cov_gap:
        return {"ok": False, "reason": f"localize missing languages ({len(cov_gap)}/{len(req)}): {', '.join(sorted(cov_gap)[:6])}…",
                "detail": {"missing_locales": sorted(cov_gap)}}

    missing: dict[str, Any] = {}
    for key in sorted(ui_keys):
        meta = strings.get(key)
        if not meta:
            missing[key] = "key not in catalog"
            continue
        locs = {loc for loc, u in meta.get("localizations", {}).items()
                if u.get("stringUnit", {}).get("state") == "translated"}
        # Per-key requirement = IN_APP_LOCALES (req). NOT the app_locales union — otherwise a stray code
        # on a single key (bare 'en'/'de') would wrongly mark every key as "missing".
        gap = req - locs
        if gap:
            missing[key] = f"missing languages: {', '.join(sorted(gap))}"

    if missing:
        return {"ok": False, "reason": f"{len(missing)} UI keys missing/partially translated",
                "detail": {"missing": missing, "app_locales": sorted(app_locales)}}
    from . import localize as loc_mod
    plural = loc_mod.plural_problems({"strings": strings}, sorted(req))
    if plural:
        return {"ok": False, "reason": f"{len(plural)} plural form(s) missing, e.g. {plural[0]} (CLDR categories per language)",
                "detail": {"plural": plural}}
    return {"ok": True, "reason": f"{len(ui_keys)} UI keys, complete in {len(app_locales)} languages"}


def _gate_build_marker(app: Path, stage: str, require_test: bool) -> dict[str, Any]:
    mk = app / ".appfactory" / "verify" / f"{stage}.json"
    if not mk.exists():
        return {"ok": False, "reason": f"{stage} verify marker missing "
                f"({mk.relative_to(app)} — run build/test and write it)"}
    try:
        data = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"marker unreadable: {e}"}
    if not data.get("build_ok"):
        return {"ok": False, "reason": "build_ok != true (build_for_sim is not green)"}
    if require_test and not data.get("test_ok"):
        return {"ok": False, "reason": "test_ok != true (UI tests are not green)"}
    return {"ok": True, "reason": f"{stage}: build" + (" + test" if require_test else "") + " green"}


def _read_app_sources(app: Path) -> dict[str, str]:
    """Read every .swift file under the app as {filename: contents} (excluding tests/build)."""
    out: dict[str, str] = {}
    for sw in app.rglob("*.swift"):
        s = str(sw)
        if "/.build/" in s or "/build/" in s or "Tests" in s:
            continue
        out[sw.name] = sw.read_text(encoding="utf-8", errors="ignore")
    return out


def _check_paywall_funnel(app: Path) -> dict[str, Any]:
    """MANDATORY subscription funnel: HARD paywall after onboarding + OFFER paywall on dismiss.
    The source must contain both the two-stage funnel and the onboarding→paywall link."""
    from . import spec as spec_mod
    spec = _load_spec(app)
    hard, offer = spec_mod.option(spec, "hard_paywall"), spec_mod.offer_on(spec)
    src = _read_app_sources(app)
    blob = "\n".join(src.values())
    if not (hard and offer):
        return _check_paywall_partial(src, blob, hard)
    # 1) Is there a two-stage funnel (PaywallFlow coordinator or hard+offer variants)?
    has_funnel = ("PaywallFlow" in blob) or ("HardPaywallView" in blob and "OfferPaywallView" in blob) \
        or (".offer" in blob and ".hard" in blob and "Paywall" in blob)
    if not has_funnel:
        return {"ok": False, "reason": "paywall funnel MISSING — hard paywall + OFFER paywall on dismiss "
                "is mandatory. Add PaywallFlow (hard→offer)."}
    # 1b) TWO-PRODUCT model is MANDATORY — NOT a promotional/introductory offer.
    # (Promo offers did not show up in `promotionalOffers` on the simulator + needed a signature/edge function;
    #  intro offers apply AUTOMATICALLY to everyone → discount on the hard paywall too. Both are WRONG.)
    # The offer paywall sells a SEPARATE discounted product (yearly.offer/weekly.offer) via plain purchase() (WYSIWYG).
    if "purchaseWithPromo" in blob or "promotionalOffer(offerID" in blob:
        return {"ok": False, "reason": "promotional offer in use — REMOVE it. The offer paywall must sell a SEPARATE discounted "
                "product (yearly.offer/weekly.offer) via plain purchase() (two-product model)."}
    cfg = src.get("AppConfig.swift", "")
    if "offerProductID" not in cfg and "OfferProductID" not in cfg:
        return {"ok": False, "reason": "two-product offer model MISSING — add yearlyOfferProductID + "
                "weeklyOfferProductID + offerProductIDs to AppConfig (the offer paywall sells a separate discounted "
                "product, NO promotional offer/signature)."}
    # 2) Does the paywall open on first launch (after onboarding)? The link may live in App.swift (fullScreenCover)
    # OR in RootTabView.onAppear (seen_initial_paywall + PaywallFlow) — both are valid.
    app_swift = src.get("App.swift", "") or src.get("AppFactoryApp.swift", "")
    onboarding_view = next((t for t in src.values() if "struct OnboardingView" in t), "")
    shown = (("Paywall" in app_swift) and ("onboard" in app_swift.lower())) or \
            ("seen_initial_paywall" in blob and "PaywallFlow" in blob) or \
            ("HardPaywallView" in onboarding_view and "OfferPaywallView" in onboarding_view)
    if not shown:
        return {"ok": False, "reason": "paywall does not open on first launch — PaywallFlow (hard→offer) "
                "must be presented after onboarding (App.swift fullScreenCover or RootTabView seen_initial_paywall)."}
    miss = _paywall_legal_missing(src, blob)
    if miss:
        return {"ok": False, "reason": f"paywall legal links missing: {', '.join(miss)} "
                "(Apple MANDATORY: Restore · Terms of Use · Privacy Policy must be on the paywall)"}
    return {"ok": True, "reason": "paywall funnel (onboarding→hard→offer) + legal links wired"}


def _paywall_legal_missing(src: dict[str, str], blob: str) -> list[str]:
    """MANDATORY legal links on the paywall (Apple): Restore + Terms + Privacy."""
    paywall_blob = src.get("Views.swift", "") + blob  # the paywall usually lives in Views.swift
    low = paywall_blob.lower()
    has_terms = ("termsurl" in low) or ("terms of use" in low) or ("terms" in low and "openurl" in low)
    has_privacy = ("privacyurl" in low) or ("privacy policy" in low)
    has_restore = "restore" in low
    return [n for n, ok in (("Restore", has_restore), ("Terms", has_terms), ("Privacy", has_privacy)) if not ok]


def _check_paywall_partial(src: dict[str, str], blob: str, hard: bool) -> dict[str, Any]:
    """The funnel checks when the user turned off the offer paywall (hard_paywall stays) or the hard paywall
    too: the paywall still exists (Settings, limit hits) with its legal links and no promotional offers;
    the offer parts are n/a, never silently passed."""
    if "purchaseWithPromo" in blob or "promotionalOffer(offerID" in blob:
        return {"ok": False, "reason": "promotional offer in use — REMOVE it (two-product model; the offer paywall is off)"}
    if "HardPaywallView" not in blob:
        return {"ok": False, "reason": "HardPaywallView missing — the paywall must stay reachable from placements"}
    onboarding_view = next((t for t in src.values() if "struct OnboardingView" in t), "")
    app_swift = src.get("App.swift", "") or src.get("AppFactoryApp.swift", "")
    shown = (("Paywall" in app_swift) and ("onboard" in app_swift.lower())) or \
            ("seen_initial_paywall" in blob and "PaywallFlow" in blob) or ("HardPaywallView" in onboarding_view)
    if hard and not shown:
        return {"ok": False, "reason": "paywall does not open after onboarding — HardPaywallView must be presented "
                "from OnboardingView (hard_paywall is on)"}
    if not hard and "HardPaywallView" in onboarding_view:
        return {"ok": False, "reason": "OnboardingView presents the paywall although the hard_paywall option is off"}
    if "OfferPaywallView" in blob:
        return {"ok": False, "reason": "OfferPaywallView present although the offer_paywall option is off"}
    miss = _paywall_legal_missing(src, blob)
    if miss:
        return {"ok": False, "reason": f"paywall legal links missing: {', '.join(miss)} "
                "(Apple MANDATORY: Restore · Terms of Use · Privacy Policy must be on the paywall)"}
    note = ("hard paywall after onboarding; offer paywall n/a (offer_paywall option off)" if hard
            else "paywall from placements only; hard + offer paywall in onboarding n/a (hard_paywall option off)")
    return {"ok": True, "reason": f"{note}; legal links wired"}


def _gate_revenuecat(app: Path) -> dict[str, Any]:
    """RevenueCat is MANDATORY — subscription/credit verification happens in RC (Apple JWS FORBIDDEN).
    project.yml must have both the RC SPM package (purchases-ios / RevenueCat package) and a
    `product: RevenueCat` dependency; Sources needs ≥1 `import RevenueCat`;
    there must be NO Apple JWS leftovers (jwsRepresentation). Pure file reads."""
    pj = app / "project.yml"
    if not pj.exists():
        return {"ok": False, "reason": "project.yml missing — cannot verify RevenueCat SPM (RC mandatory, Apple JWS forbidden)"}
    yml = pj.read_text(encoding="utf-8", errors="ignore")
    has_package = ("purchases-ios" in yml) or re.search(r'^\s*RevenueCat:\s*$', yml, re.M) is not None
    has_dep = re.search(r'product:\s*RevenueCat\b', yml) is not None
    if not (has_package and has_dep):
        return {"ok": False, "reason": "no RevenueCat SPM in project.yml — RC mandatory (Apple JWS forbidden): "
                "needs the RevenueCat package (purchases-ios) + a `product: RevenueCat` dependency"}
    src = _read_app_sources(app)
    if not any("import RevenueCat" in txt for txt in src.values()):
        return {"ok": False, "reason": "no `import RevenueCat` in Sources — RC mandatory (Apple JWS forbidden)"}
    if _load_spec(app) is not None and not any("Purchases.isConfigured" in txt for txt in src.values()):
        return {"ok": False, "reason": "RevenueCat calls are not guarded by Purchases.isConfigured "
                "(Purchases.shared is a fatalError when unconfigured — tests/offline launches crash)"}
    leftovers = [name for name, txt in src.items() if "jwsRepresentation" in txt]
    if leftovers:
        return {"ok": False, "reason": f"Apple JWS leftover (jwsRepresentation) found ({', '.join(sorted(leftovers))}) "
                "— verification moved to RC, remove the JWS code"}
    return {"ok": True, "reason": "RevenueCat SPM (project.yml) + import RevenueCat + no JWS leftovers"}


# Misleading "unlimited" claims (credit-limited model; Apple 3.1.2 rejection). Latin tokens are
# case-insensitive substrings; `ilimitad` covers Spanish/Portuguese ilimitado/ilimitada,
# `illimité` covers French; CJK tokens match exactly.
_BANNED_UNLIMITED_LATIN = ("unlimited", "no limits", "sınırsız", "illimité", "ilimitad")
_BANNED_UNLIMITED_CJK = ("无限", "無制限", "무제한")


def _check_no_unlimited_claims(app: Path) -> dict[str, Any]:
    """Misleading 'unlimited' claims are FORBIDDEN in the paywall, screenshot captions and xcstrings.
    Scans Sources/ (including Views.swift), marketing/screenshots/copy/*.json and
    Resources/Localizable.xcstrings. Pure file reads; only existing paths."""
    targets: list[Path] = []
    src_dir = app / "Sources"
    if src_dir.exists():
        for sw in src_dir.rglob("*.swift"):
            s = str(sw)
            if "/.build/" in s or "/build/" in s or "Tests" in s:
                continue
            targets.append(sw)
    copy_dir = app / "marketing" / "screenshots" / "copy"
    if copy_dir.exists():
        targets.extend(sorted(copy_dir.glob("*.json")))
    xc = app / "Resources" / "Localizable.xcstrings"
    if xc.exists():
        targets.append(xc)

    for f in targets:
        try:
            blob = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        low = blob.lower()
        for w in _BANNED_UNLIMITED_LATIN:
            if w in low:
                return {"ok": False, "reason": f"misleading 'unlimited' claim found ({f.name}: '{w}') "
                        "— contradicts the credit-limited model, Apple 3.1.2 rejection → replace with accurate app-specific wording"}
        for w in _BANNED_UNLIMITED_CJK:
            if w in blob:
                return {"ok": False, "reason": f"misleading 'unlimited' claim found ({f.name}: '{w}') "
                        "— contradicts the credit-limited model, Apple 3.1.2 rejection → replace with accurate app-specific wording"}
    return {"ok": True, "reason": "no misleading 'unlimited' claims (paywall + captions + xcstrings clean)"}


def _check_no_advanced_settings(app: Path) -> dict[str, Any]:
    """An 'Advanced Settings' section is FORBIDDEN in the screen architecture (it leaked into recent apps).
    Scans Sources/ (especially RootTabView.swift). Pure file reads."""
    for name, txt in _read_app_sources(app).items():
        if "advanced settings" in txt.lower():
            return {"ok": False, "reason": f"an 'Advanced Settings' section is FORBIDDEN in the screen architecture ({name}) "
                    "— it leaked into recent apps; remove it from RootTabView Settings"}
    return {"ok": True, "reason": "no 'Advanced Settings' section (screen architecture clean)"}


# The weekly portfolio review compares the SAME funnel across ALL apps — without these events
# no week-by-week roadmap can be drawn. They come wired in the template; do not drop them
# while writing app-specific code. (Full catalog: Analytics.swift `Tracker.Event`.)
_REQUIRED_EVENTS = [
    "onboardingStart", "onboardingStepView", "onboardingComplete",
    "paywallView", "paywallDismiss",
    "purchaseStart", "purchaseSuccess", "purchaseCancel",
    "generateStart", "generateSuccess", "generateFail",
    "resultShare", "screenEnter",
]
# credits monetization (legacy) additionally drives the top-up flow from this event.
_REQUIRED_EVENTS_CREDITS = ["creditsExhausted"]


def _check_analytics_coverage(app: Path) -> dict[str, Any]:
    """Are the critical funnel events wired (REQUIRED for the weekly portfolio comparison)?

    Also rejects raw-string `Tracker.log("...")`: if every app invents its own names the
    portfolio-wide funnel cannot be compared — the catalog (`Tracker.Event`) is the single source of truth.
    """
    sources = _read_app_sources(app)
    if not sources:
        return {"ok": True, "reason": "no sources (skipped)"}
    all_text = "\n".join(sources.values())
    spec = _load_spec(app) or {}
    required = _REQUIRED_EVENTS + (_REQUIRED_EVENTS_CREDITS if spec.get("monetization") == "credits" else [])
    missing = [e for e in required if f".{e}" not in all_text]
    if missing:
        return {"ok": False, "reason": f"analytics events missing: {', '.join(missing)} — the weekly funnel "
                "review requires the same event set in every app (Analytics.swift Tracker.Event)"}
    # off-catalog raw strings (excluding Analytics.swift's own definition)
    for name, txt in sources.items():
        if name.endswith("Analytics.swift"):
            continue
        if 'Tracker.log("' in txt:
            return {"ok": False, "reason": f"{name}: raw-string Tracker.log(\"...\") used — "
                    "use the catalog (Tracker.log(.eventName)); app-specific events: Tracker.log(custom:) (spec prefix)"}
    gate = _check_analytics_gated(sources)
    if not gate["ok"]:
        return gate
    params = _check_analytics_params(sources)
    if not params["ok"]:
        return params
    return {"ok": True, "reason": f"{len(required)} critical funnel events wired (catalog-typed) + prod-only gate"}


def _check_analytics_params(sources: dict[str, str]) -> dict[str, Any]:
    """Every parameter a call site sends is in Tracker.firebaseKeys: Firebase gets only allowlisted keys,
    so an unlisted one is dropped SILENTLY (e.g. mode, source, edited, trial … never reached GA4)."""
    analytics = next((t for n, t in sources.items() if n.endswith("Analytics.swift") and "firebaseKeys" in t), None)
    if analytics is None:
        return {"ok": True, "reason": "no firebaseKeys allowlist (skipped)"}
    block = analytics[analytics.index("firebaseKeys"):]
    allowed = set(re.findall(r'"([a-z_]+)"', block[: block.index("]") + 1]))
    used: dict[str, str] = {}
    for name, txt in sources.items():
        for m in re.finditer(r'Tracker\.log\((?:\.[A-Za-z]+|custom:\s*"[^"]*")\s*,\s*\[([^\]]*)\]', txt):
            for k in re.findall(r'(?:^|[\[,])\s*"([a-z_]+)"\s*:', m.group(1)):
                used.setdefault(k, name)
    dropped = sorted(k for k in used if k not in allowed)
    if dropped:
        return {"ok": False, "reason": f"analytics params never reach Firebase (not in Tracker.firebaseKeys): "
                f"{', '.join(f'{k} ({used[k]})' for k in dropped[:6])} — add them to the allowlist"}
    return {"ok": True, "reason": f"{len(used)} analytics params allowlisted"}


def _check_analytics_gated(sources: dict[str, str]) -> dict[str, Any]:
    """Analytics leave the device only from production App Store builds: Firebase may be configured
    only behind the AnalyticsGate (`Tracker.isSending`), and automatic screen reporting stays off."""
    for name, txt in sources.items():
        if "FirebaseApp.configure()" not in txt:
            continue
        i = txt.find("FirebaseApp.configure()")
        window = txt[max(0, i - 400):i]
        if "isSending" not in window:
            return {"ok": False, "reason": f"{name}: FirebaseApp.configure() is not behind Tracker.isSending — "
                    "DEBUG/simulator/test/TestFlight builds would send analytics (AnalyticsGate rule)"}
    return {"ok": True, "reason": "Firebase starts only when the analytics gate is open"}


def _check_no_push_permission(app: Path) -> dict[str, Any]:
    """Do NOT ask for push notification permission — it LOWERS retention.

    Field report (2026-07): removing notifications entirely DOUBLED retention. The permission
    prompt creates an early "no" moment in onboarding and breaks the funnel; users who decline
    get no notifications anyway, and those who accept do not come back via push (in our model
    the reason to return is the credit refresh, not a notification).

    UNUserNotificationCenter ITSELF is not forbidden (it may be a local-reminder app) —
    what is forbidden is ASKING FOR PERMISSION: requestAuthorization / registerForRemoteNotifications.
    """
    hits = []
    for name, txt in _read_app_sources(app).items():
        for pat in ("requestAuthorization", "registerForRemoteNotifications",
                    "UIApplication.shared.registerForRemote"):
            if pat in txt:
                hits.append(f"{name}: {pat}")
    if hits:
        return {"ok": False, "reason": "push permission request FORBIDDEN (it lowers retention) — remove: "
                + ", ".join(hits[:4])}
    return {"ok": True, "reason": "no push permission request"}


# Onboarding step count: a longer onboarding INCREASES conversion (the user has invested and
# arrives at the paywall warmed up). 9 steps proved too few; the field standard is 12-15. 12 = floor.
_MIN_ONBOARDING_STEPS = 12
_MIN_ONBOARDING_QUESTIONS = 5


def _check_onboarding_depth(app: Path) -> dict[str, Any]:
    """Onboarding must have at least 12 steps + 5 questions (count of kind: .question).
    n/a when the user turned the personalization quiz off (a short run of intro screens)."""
    from . import spec as spec_mod
    if not spec_mod.option(_load_spec(app), "onboarding_quiz"):
        return {"ok": True, "reason": "n/a — onboarding quiz turned off (short intro screens: no step or question minimum)"}
    src = _read_app_sources(app)
    candidates = [t for t in src.values() if "OnboardingStep" in t]
    # The step catalog is the file with the most `kind: .x` entries (not the model/view files).
    txt = max(candidates, key=lambda t: len(re.findall(r"kind:\s*\.(\w+)", t)), default=None)
    if txt is None:
        return {"ok": True, "reason": "no onboarding source (skipped)"}
    # Both syntaxes are valid: `kind: .question` and the template's `question: OnbQuestion(...)`.
    # The step count is read from `kind:` OR from `.init(title:` — whichever is used.
    kinds = re.findall(r"kind:\s*\.(\w+)", txt)
    if kinds:
        total = len(kinds)
        questions = sum(1 for k in kinds if k == "question")
    else:
        total = len(re.findall(r"\.init\(title:", txt))
        questions = len(re.findall(r"question:\s*OnbQuestion\(", txt))
    if total == 0:
        return {"ok": True, "reason": "onboarding steps unreadable (skipped)"}
    if total < _MIN_ONBOARDING_STEPS:
        return {"ok": False, "reason": f"onboarding has {total} steps — at least {_MIN_ONBOARDING_STEPS} required "
                f"(a longer onboarding increases conversion); add info/emotional/social-proof steps"}
    if questions < _MIN_ONBOARDING_QUESTIONS:
        return {"ok": False, "reason": f"onboarding has {questions} questions — at least {_MIN_ONBOARDING_QUESTIONS} required "
                "(kind: .question; answers feed the experience and the paywall message)"}
    return {"ok": True, "reason": f"onboarding {total} steps / {questions} questions"}


def _gate_analytics(app: Path) -> dict[str, Any]:
    """End-of-development instrumentation: catalog coverage, a screen_enter on every screen view
    file, and the build marker with per_screen=true."""
    cov = _check_analytics_coverage(app)
    if not cov["ok"]:
        return cov
    views = [p for p in (app / "Sources").rglob("*.swift")
             if re.search(r"\bstruct \w+(Screen|View)\s*:\s*View\b", p.read_text(encoding="utf-8", errors="ignore"))
             and re.search(r"(Screen|View)\.swift$", p.name)
             and not re.search(r"(Mascot|Lottie|Motion|Controls|Components)", p.name)]
    missing = sorted(p.name for p in views if "Tracker.screen(" not in p.read_text(encoding="utf-8", errors="ignore")
                     and ".trackScreen(" not in p.read_text(encoding="utf-8", errors="ignore"))
    if missing:
        return {"ok": False, "reason": f"screen_enter missing in {len(missing)} screen file(s): {', '.join(missing[:8])}",
                "detail": {"missing": missing}}
    mk = _gate_build_marker(app, "analytics", require_test=False)
    if not mk["ok"]:
        return mk
    data = json.loads((app / ".appfactory" / "verify" / "analytics.json").read_text(encoding="utf-8"))
    if not data.get("per_screen"):
        return {"ok": False, "reason": "analytics marker needs per_screen=true after the per-screen review"}
    return {"ok": True, "reason": f"analytics: catalog + {len(views)} screen files instrumented"}


def _gate_features(app: Path) -> dict[str, Any]:
    b = _gate_build_marker(app, "features", require_test=True)
    if not b["ok"]:
        return b
    rc = _gate_revenuecat(app) if _on("revenuecat") else {"ok": True}
    if not rc["ok"]:
        return rc
    u = _check_no_unlimited_claims(app)
    if not u["ok"]:
        return u
    adv = _check_no_advanced_settings(app)
    if not adv["ok"]:
        return adv
    an = _check_analytics_coverage(app)
    if not an["ok"]:
        return an
    np_ = _check_no_push_permission(app)
    if not np_["ok"]:
        return np_
    ob = _check_onboarding_depth(app)
    if not ob["ok"]:
        return ob
    rt = _check_rating_requests(app)
    if not rt["ok"]:
        return rt
    nc = _check_native_chrome(app)
    if not nc["ok"]:
        return nc
    f = _check_paywall_funnel(app)
    if not f["ok"]:
        return f
    lg = _check_legal_urls(app) if _on("supabase") else {"ok": True}
    if not lg["ok"]:
        return lg
    if not _on("maestro"):
        return {"ok": True, "maestro": "n/a", "reason": "features checks passed; Maestro smoke n/a (maestro service disabled)"}
    from . import spec as spec_mod
    if not spec_mod.option(_load_spec(app), "e2e_smoke"):
        return {"ok": True, "maestro": "n/a", "e2e_smoke": "n/a",
                "reason": "features checks passed; Maestro smoke n/a (e2e_smoke run option turned off)"}
    # End-to-end: the Maestro smoke flows (launch → onboarding → paywall) must be green.
    from . import maestro
    return maestro.smoke_check(app)


# Rule: every app is native iOS 26 with the system Liquid Glass chrome.
MIN_BUILD_SDK = 26
_CUSTOM_CHROME = re.compile(r"\b(?:struct|class)\s+(\w*(?:TabBar|TopBar|NavBar|NavigationBar))\b")
_HIDDEN_TAB_BAR = re.compile(r"\.toolbar(?:Visibility)?\(\s*\.hidden\s*,\s*for:\s*\.tabBar\s*\)")
_HIDDEN_NAV_BAR = re.compile(r"\.navigationBarHidden\(\s*true\s*\)|"
                             r"\.toolbar(?:Visibility)?\(\s*\.hidden\s*,\s*for:\s*\.navigationBar\s*\)")


def _ios_sdk_version() -> str | None:
    """The iOS SDK the selected Xcode builds with (`xcrun --sdk iphoneos --show-sdk-version`)."""
    import subprocess
    try:
        out = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"],
                             capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _sdk_major(sdk: str | None) -> int | None:
    m = re.search(r"(\d+)(?:\.\d+)*\s*$", sdk or "")
    return int(m.group(1)) if m else None


def _check_native_chrome(app: Path) -> dict[str, Any]:
    """Native iOS 26 chrome: the system TabView (Tab API, main action as the search-role tab,
    minimize on scroll), NavigationStack bars/toolbars, system sheets and controls — Liquid Glass on iOS 26.
    Fails on a custom tab/top/nav bar type, a hidden system tab bar, a hidden navigation bar outside the
    onboarding/paywall funnel, no system TabView, or a build SDK older than iOS 26 (the features marker's
    `sdk`, else the selected Xcode's iphoneos SDK)."""
    root = app / "Sources"
    files = {sw.relative_to(app).as_posix(): sw.read_text(encoding="utf-8", errors="ignore")
             for sw in root.rglob("*.swift")} if root.exists() else {}
    if not files:
        files = _read_app_sources(app)
    for rel, txt in files.items():
        m = _CUSTOM_CHROME.search(txt)
        if m:
            return {"ok": False, "reason": f"{rel}: custom chrome `{m.group(1)}` — use the system chrome "
                    "(TabView tab bar, NavigationStack .navigationTitle/.toolbar); it is Liquid Glass on iOS 26"}
        if _HIDDEN_TAB_BAR.search(txt):
            return {"ok": False, "reason": f"{rel}: the system tab bar is hidden — no custom tab bars; "
                    "use the system TabView bar (Liquid Glass on iOS 26)"}
        funnel = "/Onboarding/" in f"/{rel}" or "/Paywall/" in f"/{rel}"
        if not funnel and _HIDDEN_NAV_BAR.search(txt):
            return {"ok": False, "reason": f"{rel}: the navigation bar is hidden — main-app screens use the "
                    "system navigation bar (.navigationTitle + .toolbar items, system back button)"}
    blob = "\n".join(files.values())
    if "TabView" not in blob or not re.search(r"\bTab\(", blob):
        return {"ok": False, "reason": "no system TabView with the Tab API — the tabs must be the system "
                "TabView (iOS 18+ Tab API, tab items fallback) so iOS 26 draws the Liquid Glass tab bar"}
    if "role: .search" not in blob:
        return {"ok": False, "reason": "the main action is not the search-role tab — "
                "Tab(value:role: .search) (the trailing glass circle on iOS 26)"}
    if "tabBarMinimizeBehavior" not in blob:
        return {"ok": False, "reason": "the tab bar does not minimize on scroll — "
                "`if #available(iOS 26, *) { .tabBarMinimizeBehavior(.onScrollDown) }`"}
    sdk = None
    mk = app / ".appfactory" / "verify" / "features.json"
    if mk.exists():
        try:
            sdk = json.loads(mk.read_text(encoding="utf-8")).get("sdk")
        except Exception:  # noqa: BLE001
            sdk = None
    sdk = sdk or _ios_sdk_version()
    major = _sdk_major(sdk)
    if major is None or major < MIN_BUILD_SDK:
        return {"ok": False, "reason": f"build SDK {sdk or 'unknown'} — apps are built with the iOS "
                f"{MIN_BUILD_SDK} SDK (Xcode 26+) so the system chrome is Liquid Glass; record it as "
                "\"sdk\" (e.g. \"iphonesimulator26.2\") in .appfactory/verify/features.json"}
    return {"ok": True, "reason": f"native iOS 26 chrome: system TabView (search-role main action, minimizes "
            f"on scroll), system bars, SDK {sdk}"}


def _check_rating_requests(app: Path) -> dict[str, Any]:
    """App Store rating requests are MANDATORY at success moments and FORBIDDEN in onboarding
    (App Review rejects a rating step inside onboarding).
    - no `requestReview` / SKStoreReviewController in any onboarding source (Sources/Onboarding/**
      or inside `struct OnboardingView`);
    - RatingPolicy (60-day gap, yearly cap, no bad-session ask) is in the app;
    - a success-moment hook asks it (`RatingPolicy.shared.request(…)`) and a view asks the system
      (`.ratingRequest(…)` or `requestReview()`), outside onboarding."""
    files = {}
    for sw in (app / "Sources").rglob("*.swift") if (app / "Sources").exists() else []:
        files[sw.relative_to(app).as_posix()] = sw.read_text(encoding="utf-8", errors="ignore")
    if not files:
        files = _read_app_sources(app)
    asks = re.compile(r"requestReview|SKStoreReviewController")
    from . import spec as spec_mod
    if not spec_mod.option(_load_spec(app), "rating_prompts"):
        # the user turned rating prompts off: n/a, but no rating request code may remain
        code = {rel: re.sub(r"//.*", "", txt) for rel, txt in files.items()}  # comments may still say RatingPolicy
        left = sorted(rel for rel, txt in code.items() if asks.search(txt) or "RatingPolicy" in txt)
        if left:
            return {"ok": False, "reason": f"rating prompts are turned off but rating code remains in {', '.join(left[:4])}"}
        return {"ok": True, "reason": "n/a — rating prompts turned off (no rating request code present)"}
    main_blob = []
    for rel, txt in files.items():
        if "/Onboarding/" in f"/{rel}" and asks.search(txt):
            return {"ok": False, "reason": f"{rel}: a rating request inside onboarding is forbidden (Apple rejects it) — "
                    "ask at a success moment in the main app through RatingPolicy"}
        i = txt.find("struct OnboardingView")
        if i != -1:
            rest = txt[i:]
            nxt = re.search(r'\n(?:struct|enum|final class|class|extension) ', rest[1:])
            scope = rest[: nxt.start() + 1] if nxt else rest
            if asks.search(scope):
                return {"ok": False, "reason": "OnboardingView asks for a rating — forbidden (Apple rejects it); "
                        "ask at a success moment in the main app through RatingPolicy"}
            txt = txt[:i] + (rest[nxt.start() + 1:] if nxt else "")
        main_blob.append(txt)
    blob = "\n".join(main_blob)
    if "class RatingPolicy" not in blob:
        return {"ok": False, "reason": "RatingPolicy missing — App Store rating requests at success moments are "
                "mandatory (template Sources/Core/RatingPolicy.swift: 60-day gap, 3 a year, never after a failure)"}
    hook = re.search(r"RatingPolicy\.shared\.request\(", blob)
    ask = ".ratingRequest(" in blob or "requestReview()" in blob
    if not (hook and ask):
        return {"ok": False, "reason": "no success-moment rating hook — call RatingPolicy.shared.request(…) where the "
                "core action succeeds and attach .ratingRequest($trigger) to a view that stays on screen"}
    return {"ok": True, "reason": "rating requests at success moments (RatingPolicy), none in onboarding"}


def _check_legal_urls(app: Path) -> dict[str, Any]:
    """In-app legal links (paywall + Settings) must be the app's Supabase `legal` function — the same
    URLs App Store Connect gets (GitHub gists are no longer accepted):
      https://<ref>.supabase.co/functions/v1/legal/privacy | /terms   (support: /legal/support, https or mailto)
    The app appends ?lang=<app language> at runtime."""
    from . import legal as legal_mod
    src = _read_app_sources(app)
    cfg = src.get("AppConfig.swift", "")
    if "privacyURL" not in cfg and "termsURL" not in cfg:
        return {"ok": True, "reason": "paywall funnel + rating at success moments (no legal links)"}
    fail = []
    computed = re.search(r'privacyURL:\s*String\s*\{\s*functionsURL\s*\+\s*"/legal/privacy"', cfg)
    if computed:
        # Template form: the URLs derive from supabaseURL (filled by app_inject_config).
        m = re.search(r'supabaseURL\s*=\s*"([^"]*)"', cfg)
        base = m.group(1) if m else ""
        if base.startswith("__"):
            return {"ok": False, "reason": "AppConfig.supabaseURL not injected yet (app_inject_config) — "
                    "the Supabase legal links cannot resolve"}
        for doc in ("privacy", "terms"):
            if not legal_mod.is_legal_url(f"{base}/functions/v1/legal/{doc}", doc):
                fail.append(f"{doc}: {base} is not https://<ref>.supabase.co")
        if fail:
            return {"ok": False, "reason": "legal links → " + "; ".join(fail)}
        return {"ok": True, "reason": "paywall funnel + legal (Supabase legal function, ?lang=) + rating at success moments"}
    for key, doc in (("privacyURL", "privacy"), ("termsURL", "terms"), ("supportURL", None)):
        m = re.search(rf'{key}\s*=\s*(?:URL\(string:\s*)?"([^"]*)"', cfg)
        if not m:
            if key != "supportURL":
                fail.append(f"{key} missing")
            continue
        url = m.group(1)
        if key == "supportURL":
            if not (legal_mod.is_legal_url(url) or url.startswith("mailto:") or url.startswith("https://")):
                fail.append(f"{key} must be https (legal/support) or mailto")
            continue
        if "gist.github" in url:
            fail.append(f"{key} is a GitHub gist — use the Supabase legal function")
        elif not legal_mod.is_legal_url(url, doc):
            fail.append(f"{key} is not https://<ref>.supabase.co/functions/v1/legal/{doc}")
    if fail:
        return {"ok": False, "reason": "legal links → " + "; ".join(fail) +
                " — paywall + Settings + ASC use the same Supabase legal URLs (legal_urls from backend_deploy)"}
    return {"ok": True, "reason": "paywall funnel + legal (Supabase legal function) + rating at success moments"}


# Backward-compatible name (older callers).
_check_iphone_legal_gist = _check_legal_urls


def _gate_icon(app: Path) -> dict[str, Any]:
    sets = list(app.rglob("AppIcon.appiconset/Contents.json"))
    if not sets:
        return {"ok": False, "reason": "AppIcon.appiconset/Contents.json missing"}
    contents = min(sets, key=lambda p: len(p.parts))
    try:
        images = json.loads(contents.read_text(encoding="utf-8")).get("images", [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"Contents.json unreadable: {e}"}
    filled = [im for im in images if im.get("filename") and (contents.parent / im["filename"]).exists()]
    if not filled:
        return {"ok": False, "reason": "appiconset has no filled icon (filename + file)"}
    return _check_icon_from_claude_design(app, [contents.parent / im["filename"] for im in filled])


def _check_icon_from_claude_design(app: Path, installed: list[Path]) -> dict[str, Any]:
    """The shipped icon is the Claude Design master (B01-AppIcon board), installed by icon_install."""
    from .design import receipt
    mk = app / ".appfactory" / "verify" / "icon.json"
    if not mk.exists():
        return {"ok": False, "reason": "icon not from Claude Design: design B01-AppIcon.dc.html → design_export_png → "
                "design/icon.png → design_generate + upload + design_record_upload → icon_install"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"verify/icon.json unreadable: {e}"}
    local = not _on("design")
    if d.get("source") != "claude_design" and not (local and d.get("source") == "local"):
        return {"ok": False, "reason": "verify/icon.json source != claude_design (generated icons are not accepted)"}
    master = app / str(d.get("master", ""))
    if not master.is_file() or receipt.sha256(master) != d.get("master_sha256"):
        return {"ok": False, "reason": "icon master changed since icon_install — re-run icon_install"}
    if not any(receipt.sha256(p) == d.get("installed_sha256") for p in installed):
        return {"ok": False, "reason": "AppIcon.appiconset does not hold the installed Claude Design icon — re-run icon_install"}
    if local:
        return {"ok": True, "design": "n/a", "reason": "app icon: locally authored master installed by icon_install "
                "(design service disabled)"}
    from .design import brand
    up = receipt.check(app, required=[brand.ICON_BOARD, "icon.png"])
    if not up["ok"]:
        return up
    if (receipt.load(app) or {}).get("files", {}).get("icon.png") != d.get("master_sha256"):
        return {"ok": False, "reason": "the icon.png uploaded to Claude Design is not the installed master"}
    return {"ok": True, "reason": f"app icon from Claude Design ({brand.ICON_BOARD}, project {up['project_id']})"}


def _gate_scaffold(app: Path) -> dict[str, Any]:
    if not (app / ".appfactory" / "state.json").exists():
        return {"ok": False, "reason": "manifest missing"}
    if not list(app.glob("*.xcodeproj")):
        return {"ok": False, "reason": "*.xcodeproj missing (scaffold/xcodegen has not run)"}
    pj = app / "project.yml"
    if not pj.exists():
        return {"ok": False, "reason": "project.yml missing (xcodegen source)"}
    txt = pj.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r'TARGETED_DEVICE_FAMILY:\s*"?1"?\s*$', txt, re.M):
        return {"ok": False, "reason": "not iPhone-only (TARGETED_DEVICE_FAMILY=1 required)"}
    orient = re.search(r'UISupportedInterfaceOrientations[^\n]*:\s*([^\n]+)', txt)
    if not orient or "Portrait" not in orient.group(1) or "Landscape" in orient.group(1):
        return {"ok": False, "reason": "not portrait-only (UISupportedInterfaceOrientations must be Portrait, not Landscape)"}
    # iPHONE ONLY: TARGETED_DEVICE_FAMILY=1 alone is not enough — modern Xcode still ships the app
    # on iPad/Mac/Vision as "Designed for iPhone". These flags must be NO.
    for flag in ("SUPPORTS_MACCATALYST", "SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD",
                 "SUPPORTS_XR_DESIGNED_FOR_IPHONE_IPAD"):
        if not re.search(rf'{flag}:\s*NO\b', txt):
            return {"ok": False, "reason": f"{flag}: NO missing — the app shows up on iPad/Mac/Vision. "
                    "For iPhone ONLY, all 3 of these flags must be NO in project.yml."}
    spec = _load_spec(app)
    if spec is not None:
        sc = _check_scaffold_spec(app, spec, txt)
        if not sc["ok"]:
            return sc
        return {"ok": True, "reason": "manifest + xcodeproj + iPhone-only + portrait-only + " + sc["reason"]}
    return {"ok": True, "reason": "manifest + xcodeproj + iPhone-only (Mac/iPad/Vision off) + portrait-only"}


def scheme_block(project_yml: str, name: str) -> str:
    """The text of one scheme under `schemes:` in an XcodeGen project.yml ("" when absent)."""
    m = re.search(r"^schemes:\s*$", project_yml, re.M)
    if not m:
        return ""
    rest = project_yml[m.end():]
    head = re.search(rf"^(\s+){re.escape(name)}:\s*$", rest, re.M)
    if not head:
        return ""
    indent = len(head.group(1))
    body = []
    for line in rest[head.end():].splitlines():
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def _sanitize_scheme(app: Path, spec: dict[str, Any]) -> str:
    projects = sorted(app.glob("*.xcodeproj"))
    if projects:
        return projects[0].stem
    return re.sub(r"[^A-Za-z0-9]", "", spec.get("name", "")) or "App"


def _check_scaffold_spec(app: Path, spec: dict[str, Any], project_yml: str) -> dict[str, Any]:
    """Spec-driven scaffold: valid spec, StoreKit parity, generated Swift in sync, test targets,
    storekit scheme, Sign in with Apple capability, no Firebase auto screen reporting."""
    from . import app as app_mod
    from . import spec as spec_mod
    from . import storekit as storekit_mod
    errs = spec_mod.validate(spec)
    if errs:
        return {"ok": False, "reason": "app.spec.json invalid: " + "; ".join(errs)}
    mism = storekit_mod.parity(spec, app / storekit_mod.STOREKIT_REL)
    if mism:
        return {"ok": False, "reason": "Configuration.storekit ≠ spec (storekit_generate): " + "; ".join(mism[:4]),
                "detail": {"mismatches": mism}}
    for rel, render in (("Sources/App/AppSpec.swift", app_mod.render_app_spec_swift),
                        ("Sources/Paywall/PaywallSource.swift", app_mod.render_paywall_source_swift)):
        f = app / rel
        if not f.exists() or f.read_text(encoding="utf-8") != render(spec):
            return {"ok": False, "reason": f"{rel} out of sync with app.spec.json (run app_sync_spec)"}
    needs = {
        "unit test target (bundle.unit-test)": "bundle.unit-test" in project_yml,
        "UI test target (bundle.ui-testing)": "bundle.ui-testing" in project_yml,
        "scheme storeKitConfiguration": "storeKitConfiguration:" in project_yml,
        "coverage (gatherCoverageData)": "gatherCoverageData: true" in project_yml,
        **({"Sign in with Apple entitlement": "com.apple.developer.applesignin" in project_yml}
           if spec_mod.option(spec, "sign_in_with_apple") else {}),
        "FirebaseAutomaticScreenReportingEnabled NO": re.search(
            r"FirebaseAutomaticScreenReportingEnabled:\s*NO", project_yml) is not None,
    }
    missing = [k for k, ok in needs.items() if not ok]
    if missing:
        return {"ok": False, "reason": "project.yml missing: " + ", ".join(missing)}
    if not spec_mod.option(spec, "sign_in_with_apple") and "com.apple.developer.applesignin" in project_yml:
        return {"ok": False, "reason": "project.yml still has the Sign in with Apple entitlement (sign_in_with_apple option is off)"}
    main_scheme = scheme_block(project_yml, _sanitize_scheme(app, spec))
    if "storeKitConfiguration" in main_scheme:
        return {"ok": False, "reason": "the main scheme carries a StoreKit configuration — on a device that is Xcode's "
                "StoreKit-testing environment (Billing Problem sheet loop); keep it in the <App>StoreKitSim / "
                "UnitTests simulator schemes only"}
    if spec.get("monetization") == "subscription" and (app / "Sources" / "Credits").exists():
        return {"ok": False, "reason": "subscription app still ships the credit economy (Sources/Credits)"}
    return {"ok": True, "reason": "spec valid + StoreKit parity + AppSpec/PaywallSource in sync + tests/coverage + SIWA"}


def _gate_aso(app: Path) -> dict[str, Any]:
    from . import aso
    m = _load_manifest(app)
    chk = aso.validate_metadata(m.get("app") or app.name, m.get("dir") or str(app))
    ok = bool(chk.get("ok"))
    return {"ok": ok, "reason": "ASO metadata complete" if ok else "ASO metadata incomplete/over limit",
            "detail": chk}


def _gate_backend(app: Path) -> dict[str, Any]:
    """Firebase installed (MANDATORY for every app): GoogleService-Info.plist + GA4 project (GOOGLE_APP_ID + PROJECT_ID).
    NOTE: IS_ANALYTICS_ENABLED MAY be `false` in the plist — shipped production apps have it that way too;
    analytics works via the GA4 link + runtime collection, the plist flag does NOT need to be `true`
    (live finding: forcing true made a fresh GA4 property wait hours for propagation, which was wrong).
    With app.spec.json (subscription mode) the Supabase template must also be in place (_check_backend_template)."""
    if not _on("firebase"):
        if not _on("supabase"):
            return {"ok": True, "skipped": True, "reason": "n/a — firebase and supabase services disabled"}
        t = _check_backend_template(app)
        return t if not t["ok"] else {"ok": True, "firebase": "n/a", "reason": "Firebase n/a (service disabled)"
                                      + (f"; {t['reason']}" if t.get("checked") else "")}
    plists = [p for p in app.rglob("GoogleService-Info.plist")
              if "build" not in p.parts and ".git" not in p.parts]
    if not plists:
        return {"ok": False, "reason": "GoogleService-Info.plist missing (Firebase not set up)"}
    txt = min(plists, key=lambda p: len(p.parts)).read_text(encoding="utf-8", errors="ignore")
    if "GOOGLE_APP_ID" not in txt or "PROJECT_ID" not in txt:
        return {"ok": False, "reason": "Firebase plist incomplete (no GOOGLE_APP_ID/PROJECT_ID — setup half done)"}
    t = _check_backend_template(app) if _on("supabase") else {"ok": True}
    if not t["ok"]:
        return t
    return {"ok": True, "reason": "Firebase installed (plist + GA4 project; analytics via GA4 link)"
            + (f"; {t['reason']}" if t.get("checked") else "")}


def _check_backend_template(app: Path) -> dict[str, Any]:
    """Subscription-mode Supabase backend present and rendered from the spec: function set, migrations,
    auth config (anonymous + Sign in with Apple + manual linking), app.gen.ts, CONTRACT.md."""
    spec = _load_spec(app)
    if not spec or spec.get("monetization", "subscription") != "subscription":
        return {"ok": True, "reason": "no subscription spec (skipped)", "checked": False}
    from . import spec as spec_mod
    from . import supabase as supa
    sb = app / "supabase"
    missing = [f for f in supa.functions_for(spec) if not (sb / "functions" / f / "index.ts").exists()]
    if missing:
        return {"ok": False, "reason": f"Supabase functions missing: {', '.join(missing)} (subscription template)"}
    # analysis.ts = the AI prompt + schema; a non-AI app (spec.ai.enabled=false) has none to fill.
    if spec_mod.ai_enabled(spec) and not (sb / "functions" / "_shared" / "analysis.ts").exists():
        return {"ok": False, "reason": "supabase/functions/_shared/analysis.ts missing (app prompt + schema)"}
    migs = sorted(p.name for p in (sb / "migrations").glob("*.sql")) if (sb / "migrations").exists() else []
    if not migs or not any("core" in m for m in migs):
        return {"ok": False, "reason": "supabase/migrations (subscription schema) missing"}
    if (sb / "migrations_credits").exists() or (sb / "functions" / "ai-proxy").exists():
        return {"ok": False, "reason": "credits-mode files still present: run apply_backend_mode (backend_render)"}
    toml = (sb / "config.toml").read_text(encoding="utf-8") if (sb / "config.toml").exists() else ""
    for needle, what in (("enable_anonymous_sign_ins = true", "anonymous sign-ins"),
                         ("enable_manual_linking = true", "manual identity linking"),
                         ("[auth.external.apple]", "Sign in with Apple provider")):
        if needle not in toml:
            return {"ok": False, "reason": f"supabase/config.toml: {what} not configured"}
    if f'client_id = "{spec.get("bundle_id")}"' not in toml:
        return {"ok": False, "reason": "supabase/config.toml: Apple client_id must be the bundle id (backend_render)"}
    gen = sb / "functions" / "_shared" / "app.gen.ts"
    gtxt = gen.read_text(encoding="utf-8") if gen.exists() else ""
    if f"SUPPORTED_LOCALES = {supa._ts_list(spec['locales']['app'])}" not in gtxt or "__DISPLAY_NAME__" in gtxt:
        return {"ok": False, "reason": "functions/_shared/app.gen.ts not rendered from the spec (backend_render)"}
    if not (app / "backend" / "CONTRACT.md").exists():
        return {"ok": False, "reason": "backend/CONTRACT.md missing (the iOS app builds against it)"}
    return {"ok": True, "reason": "Supabase subscription backend rendered from the spec", "checked": True}


def _read_iap_state(app: Path) -> dict[str, Any]:
    """Read IAP state from ASC (live, best-effort). Returns ok:False without creds/network."""
    m = _load_manifest(app)
    bundle = m.get("bundle_id")
    if not bundle:
        return {"ok": False, "error": "no bundle_id in manifest"}
    try:
        from . import asc
        client = asc.ASCClient()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

    def _get(path: str, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        r = client.request("GET", path, params=params or None)
        while r.get("ok"):
            out += r.get("data", {}).get("data", [])
            nxt = r.get("data", {}).get("links", {}).get("next")
            if not nxt:
                break
            r = client.request("GET", nxt)
        return out

    apps = _get("/v1/apps", **{"filter[bundleId]": bundle})
    if not apps:
        return {"ok": False, "error": "ASC app not found"}
    app_id = apps[0]["id"]
    groups = _get(f"/v1/apps/{app_id}/subscriptionGroups", limit=50)
    if not groups:
        return {"ok": False, "error": "no subscription group"}
    gid = groups[0]["id"]
    group_locales = [d["attributes"]["locale"]
                     for d in _get(f"/v1/subscriptionGroups/{gid}/subscriptionGroupLocalizations", limit=200)]
    subscriptions, avail_ok, price_ok = [], True, True
    for s in _get(f"/v1/subscriptionGroups/{gid}/subscriptions", limit=50):
        sid = s["id"]
        locs = [d["attributes"]["locale"]
                for d in _get(f"/v1/subscriptions/{sid}/subscriptionLocalizations", limit=200)]
        offers = _get(f"/v1/subscriptions/{sid}/introductoryOffers", limit=200)
        modes = sorted({f"{(o.get('attributes') or {}).get('offerMode')} {(o.get('attributes') or {}).get('duration')}"
                        for o in offers})
        subscriptions.append({"id": sid, "product_id": s["attributes"].get("productId"),
                              "group_level": s["attributes"].get("groupLevel"),
                              "localizations": locs, "intro_offers": len(offers), "intro_modes": modes})
        if not client.request("GET", f"/v1/subscriptions/{sid}/subscriptionAvailability").get("ok"):
            avail_ok = False
        # one page is enough to know a price exists (following links.next with limit=1 walked all
        # ~175 territories, one asc process each)
        if not client.request("GET", f"/v1/subscriptions/{sid}/prices", params={"limit": 1}).get("data", {}).get("data"):
            price_ok = False
    return {"ok": True, "subscriptions": subscriptions, "group_localizations": group_locales,
            "availability": avail_ok, "price": price_ok}


# A trial product must carry its intro offer in (nearly) every sold territory (~174); this floor
# catches single-territory or partial setups.
MIN_INTRO_TERRITORIES = 100


def _check_iap_against_spec(subs: list[dict[str, Any]], spec: dict[str, Any], group_locales: set[str]) -> dict[str, Any]:
    from . import spec as spec_mod
    from .asc import SPEC_INTRO_DURATIONS
    by_pid = {s.get("product_id"): s for s in subs}
    store_locs = set(spec["locales"]["store"])
    for p in spec_mod.products(spec):
        s = by_pid.get(p["id"])
        if s is None:
            return {"ok": False, "reason": f"subscription missing: {p['id']} (spec product not in ASC — store_setup apply)"}
        if s.get("group_level") is not None and s["group_level"] != p["level"]:
            return {"ok": False, "reason": f"{p['id']}: group level {s['group_level']} != spec {p['level']}"}
        missing_locs = store_locs - set(s.get("localizations") or [])
        if missing_locs:
            return {"ok": False, "reason": f"{p['id']}: localizations missing {sorted(missing_locs)}"}
        intro = p.get("intro")
        n = int(s.get("intro_offers") or 0)
        if not intro:
            if n:
                return {"ok": False, "reason": f"{p['id']}: an offer product must NOT have an intro offer ({n} found) — spec: none"}
            continue
        iso = spec_mod.intro_duration(intro["duration"])
        want = f"FREE_TRIAL {SPEC_INTRO_DURATIONS.get(iso, iso)}"
        modes = s.get("intro_modes")
        if modes is not None and modes != [want]:
            return {"ok": False, "reason": f"{p['id']}: intro offer {modes} != spec {want}"}
        if n < MIN_INTRO_TERRITORIES:
            return {"ok": False, "reason": f"{p['id']}: intro offer in {n} territories (< {MIN_INTRO_TERRITORIES}; "
                    "intro offers are per territory — store_setup apply)"}
    behind = store_locs - group_locales
    if behind:
        return {"ok": False, "reason": f"GROUP localizations missing: {', '.join(sorted(behind))}"}
    return {"ok": True}


def _gate_iap(app: Path, iap_state: dict[str, Any] | None = None, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """IAP: subscriptions + subscription & GROUP localizations + availability + price + intro offers.
    With app.spec.json, checked against the SPEC: every product exists, group level matches, store locales
    complete, trial products carry the spec's intro offer (FREE_TRIAL + duration, per territory), offer products have NONE.
    Without a spec (legacy): an intro offer on every subscription except .offer products. Without iap_state, reads ASC."""
    if iap_state is None:
        iap_state = _read_iap_state(app)
    if not iap_state.get("ok"):
        return {"ok": False, "reason": f"could not read ASC IAP state: {iap_state.get('error', '?')}"}
    subs = iap_state.get("subscriptions") or []
    if not subs:
        return {"ok": False, "reason": "no subscriptions"}
    sub_locales: set[str] = set()
    for s in subs:
        locs = set(s.get("localizations") or [])
        if not locs:
            return {"ok": False, "reason": f"subscription {s.get('id', '?')} has no localizations"}
        sub_locales |= locs
    group_locales = set(iap_state.get("group_localizations") or [])
    if not group_locales:
        return {"ok": False, "reason": "no GROUP localizations (the group name must be filled in every language)"}
    behind = sub_locales - group_locales
    if behind:
        return {"ok": False, "reason": f"group localizations lag behind the subscriptions, missing: {', '.join(sorted(behind))}"}
    spec = spec if spec is not None else _load_spec(app)
    if spec:
        chk = _check_iap_against_spec(subs, spec, group_locales)
        if not chk["ok"]:
            return chk
    else:
        is_offer = lambda s: str(s.get("product_id") or "").endswith(".offer")  # noqa: E731
        no_offer = [s.get("id", "?") for s in subs if not is_offer(s) and not s.get("intro_offers")]
        if no_offer:
            return {"ok": False, "reason": f"no intro offer ({', '.join(no_offer)}) — required on trial products"}
        extra = [s.get("id", "?") for s in subs if is_offer(s) and s.get("intro_offers")]
        if extra:
            return {"ok": False, "reason": f"an offer product must not have an intro offer ({', '.join(extra)})"}
    if not iap_state.get("availability"):
        return {"ok": False, "reason": "subscription availability not set"}
    if not iap_state.get("price"):
        return {"ok": False, "reason": "subscription price not set"}
    return {"ok": True, "reason": f"{len(subs)} subscriptions + group loc ({len(group_locales)} languages) + availability + price"
            + (" + spec intro offers" if spec else "")}


def _gate_submission_prep(app: Path) -> dict[str, Any]:
    """Submit readiness: the asc agent runs finalize (5 fields) + App Privacy (browser readback) and
    writes .appfactory/verify/submission_prep.json (App Privacy is not in Apple's API → marker)."""
    mk = app / ".appfactory" / "verify" / "submission_prep.json"
    if not mk.exists():
        return {"ok": False, "reason": "submission_prep marker missing (finalize the 5 fields + App Privacy)"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"marker unreadable: {e}"}
    need = ["content_rights", "copyright", "age_rating", "review_contact", "price", "app_privacy"]
    missing = [k for k in need if not d.get(k)]
    if missing:
        return {"ok": False, "reason": f"submission_prep missing: {', '.join(missing)}"}
    return {"ok": True, "reason": "submit readiness complete (5 finalize fields + App Privacy)"}


def _gate_marker(app: Path, stage: str, required_keys: list[str]) -> dict[str, Any]:
    """Generic evidence-marker gate: .appfactory/verify/<stage>.json exists + required_keys truthy.
    The agent writes it AFTER doing the work and verifying via ASC/HTTP (an evidence marker for stages
    where a deterministic network read is hard; same pattern as submission_prep/features)."""
    mk = app / ".appfactory" / "verify" / f"{stage}.json"
    if not mk.exists():
        return {"ok": False, "reason": f"{stage} verify marker missing (write .appfactory/verify/{stage}.json)"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{stage} marker unreadable: {e}"}
    missing = [k for k in required_keys if not d.get(k)]
    if missing:
        return {"ok": False, "reason": f"{stage} marker missing fields: {', '.join(missing)}"}
    return {"ok": True, "reason": f"{stage} verified (marker)"}


def _gate_repo(app: Path) -> dict[str, Any]:
    """PRIVATE repo created + pushed: .git remote configured."""
    import subprocess
    if not (app / ".git").exists():
        return {"ok": False, "reason": ".git missing (repo not created)"}
    r = subprocess.run(["git", "-C", str(app), "remote"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {"ok": False, "reason": "no git remote (github_create_repo/push has not run)"}
    return {"ok": True, "reason": f"repo remote: {r.stdout.split()[0]}"}


def _gate_ai_proxy(app: Path) -> dict[str, Any]:
    """AI backend deployed. Subscription spec: backend_deploy marker (ok, the full function set, no
    missing required secret). Legacy/credits: the ai_proxy marker. spec.ai.enabled=false: the AI part
    is n/a (analyze + FAL_KEY not required) but the non-AI deploy + legal pages still gate."""
    spec = _load_spec(app)
    if not spec or spec.get("monetization", "subscription") != "subscription":
        return _gate_marker(app, "ai_proxy", ["ok"])
    from . import spec as spec_mod
    from . import supabase as supa
    ai_on = spec_mod.ai_enabled(spec)
    mk = app / ".appfactory" / "verify" / "backend_deploy.json"
    if not mk.exists():
        return {"ok": False, "reason": "backend_deploy marker missing (.appfactory/verify/backend_deploy.json — run backend_deploy)"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"backend_deploy marker unreadable: {e}"}
    if not d.get("ok"):
        return {"ok": False, "reason": "backend_deploy ok != true (migrations/secrets/auth/functions)"}
    missing = [f for f in supa.functions_for(spec) if f not in (d.get("functions") or [])]
    if missing:
        return {"ok": False, "reason": f"functions not deployed: {', '.join(missing)}"}
    req = [s for s in (d.get("missing_secrets") or []) if s in supa.required_secrets(spec)]
    if req:
        return {"ok": False, "reason": f"missing secrets: {', '.join(req)} (analyze returns 503)"}
    if not d.get("legal_published"):
        return {"ok": False, "reason": "legal pages not published (store/privacy placeholders — legal_check)"}
    if not ai_on:
        # AI part of the stage is n/a (no analyze, no FAL_KEY, no eval/unit-economics); the
        # non-AI backend deploy + published legal pages are still required.
        return {"ok": True, "ai": "n/a", "reason": "AI n/a (spec.ai.enabled=false); backend deployed: "
                + ", ".join(d.get("functions") or [])}
    return {"ok": True, "reason": f"backend deployed: {', '.join(d['functions'])}"}


def _gate_asc_app(app: Path) -> dict[str, Any]:
    """ASC app record exists (marker app_id or outputs asc_app_id). With a spec, the App ID
    capabilities (IN_APP_PURCHASE, APPLE_ID_AUTH, HEALTHKIT if spec.health) must be applied first."""
    from . import config as cfg
    outs = cfg.app_outputs(app)
    base = _gate_marker(app, "asc_app", ["app_id"])
    if not base["ok"] and not outs.get("asc_app_id"):
        return base
    if _load_spec(app):
        from . import store_setup
        pending = store_setup.capabilities_pending(app)
        if pending:
            return {"ok": False, "reason": f"App ID capabilities not applied: {', '.join(pending)} "
                    "(store_setup mode=apply target=capabilities)"}
    return {"ok": True, "reason": f"ASC app {outs.get('asc_app_id') or 'marker'} + capabilities"}


def _gate_metadata(app: Path) -> dict[str, Any]:
    """metadata marker (privacy_url + category); with store/metadata/listing.json and a spec, the
    listing must pass every rule (limits, keyword 95–100, no overlaps, disclosure + Terms + Privacy
    at the end, Supabase legal URLs with the locale's ?lang=, IAP copy)."""
    base = _gate_marker(app, "metadata", ["privacy_url", "category"])
    if not base["ok"]:
        return base
    spec = _load_spec(app)
    if spec:
        from . import legal as legal_mod
        mk = json.loads((app / ".appfactory" / "verify" / "metadata.json").read_text(encoding="utf-8"))
        if not legal_mod.is_legal_url(str(mk.get("privacy_url", "")).split("?")[0], "privacy"):
            return {"ok": False, "reason": "metadata privacy_url must be the Supabase legal function (…/legal/privacy)"}
        if (app / "store" / "metadata" / "listing.json").exists():
            from . import metadata as meta
            chk = meta.listing_check(app)
            if not chk["ok"]:
                errs = chk.get("errors") or [chk.get("error")]
                return {"ok": False, "reason": f"listing.json: {len(errs)} problem(s), first: {errs[0]}", "detail": errs}
    return {"ok": True, "reason": "metadata verified" + (" + listing rules" if spec else " (marker)")}


def _gate_deliver(app: Path) -> dict[str, Any]:
    return _gate_marker(app, "deliver", ["ok"])


def _gate_screenshots(app: Path) -> dict[str, Any]:
    """Configured languages × a rich screen set: marker locales ≥ (target-1) (margin in case Apple rejects one)."""
    mk = app / ".appfactory" / "verify" / "screenshots.json"
    if not mk.exists():
        return {"ok": False, "reason": "screenshots marker missing"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"screenshots marker unreadable: {e}"}
    locales = int(d.get("locales", 0) or 0)
    from . import config as cfg
    target = len(cfg.load_config().get("locales", cfg.APP_STORE_LOCALES))
    minimum = max(1, target - 1)
    if locales < minimum:
        return {"ok": False, "reason": f"screenshots {locales} locale < {minimum} ({target}-language target, a rich set is mandatory)"}
    # Visual-quality review is mandatory: modern fonts + colors close to the app palette (hard requirement).
    rev = app / ".appfactory" / "verify" / "screenshots_review.json"
    if not rev.exists():
        return {"ok": False, "reason": "screenshots_review.json missing (a review of font modernity + app color match is required)"}
    try:
        r = json.loads(rev.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"screenshots_review unreadable: {e}"}
    if not r.get("fonts_modern"):
        return {"ok": False, "reason": "screenshot fonts are not modern/polished (fonts_modern!=true) → retry"}
    if not r.get("colors_match_app"):
        return {"ok": False, "reason": "screenshot colors do not match the app palette (colors_match_app!=true) → retry"}
    # Captions must be APP-SPECIFIC: generic template / foreign-app words (portrait/headshot) are FORBIDDEN.
    cap = _check_screenshot_captions(app)
    if not cap["ok"]:
        return cap
    # Misleading 'unlimited' claims in captions/paywall are FORBIDDEN (credit-limited model; Apple 3.1.2).
    u = _check_no_unlimited_claims(app)
    if not u["ok"]:
        return u
    cd = _check_store_creatives(app, r) if _on("design") else {"ok": True}
    if not cd["ok"]:
        return cd
    return {"ok": True, "reason": f"screenshots {locales} locales + fonts/colors + app-specific captions + Claude Design layout PASSED"}


def _check_store_creatives(app: Path, review: dict[str, Any]) -> dict[str, Any]:
    """App Store screenshot layouts are Claude Design boards (store page), uploaded, real captions/captures,
    applied to the compositor config, and the branded output reviewed against them."""
    from . import design as design_mod
    from .design import brand, receipt, research
    concept = research.check_screenshot_concept(app)
    if not concept["ok"]:
        return concept
    brief = research.load_brief(app) or {}
    files = brand.store_files(brief)
    out = app / "design" / "project"
    try:
        lay_doc = json.loads((out / brand.STORE_LAYOUT).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        lay_doc = {}
    if lay_doc.get("brief_sha256") != research.brief_sha(app) or lay_doc.get("boards") != files:
        return {"ok": False, "reason": "store_layout.json is not from the brief's current screenshot concept — "
                "re-run design_generate"}
    bad = brand.placeholders(out, files)
    if bad:
        return {"ok": False, "reason": f"Claude Design store boards missing or still placeholders ({', '.join(bad[:3])}) — "
                "write the ASO captions (copy/en-US.json) + capture, re-run design_generate, author, upload"}
    not_authored = [p for p in design_mod.authored_problems(app) if p.split(":")[0] in files]
    if not_authored:
        return {"ok": False, "reason": "store boards: " + "; ".join(not_authored[:3])}
    up = receipt.check_after_brief(app, required=[*files, brand.STORE_LAYOUT])
    if not up["ok"]:
        return up
    lay = brand.layout_matches(app)
    if not lay["ok"]:
        return lay
    if not review.get("matches_claude_design"):
        return {"ok": False, "reason": "screenshots_review.matches_claude_design != true — compare the branded "
                "screenshots with the Claude Design store boards"}
    if not review.get("store_rules_ok"):
        from .design.rules import STORE_RULES
        return {"ok": False, "reason": "screenshots_review.store_rules_ok != true — confirm: " + " | ".join(STORE_RULES)}
    return {"ok": True}


# Foreign-app leakage / generic template captions (a "Your portrait is ready" caption was once caught).
_BANNED_CAPTION_TOKENS = ("portrait", "headshot", "cosplay")
_GENERIC_CAPTION_PHRASES = (
    "create something beautiful",
    "bring your idea to life",
    "all your creations in one place",
    "your portrait is ready",
)


def _check_screenshot_captions(app: Path) -> dict[str, Any]:
    """Is marketing/screenshots/copy/<locale>.json app-specific? Generic/foreign captions = fail."""
    copy_dir = app / "marketing" / "screenshots" / "copy"
    files = sorted(copy_dir.glob("*.json")) if copy_dir.exists() else []
    from . import config as cfg
    target = len(cfg.load_config().get("locales", cfg.APP_STORE_LOCALES))
    minimum = max(1, target - 1)
    if len(files) < minimum:
        return {"ok": False, "reason": f"screenshot caption copy {len(files)} locale < {minimum} "
                "(app-specific copy/<locale>.json required — generated from ASO, NOT a generic fallback)"}
    for f in files:
        try:
            entries = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"caption {f.name} unreadable: {e}"}
        for e in entries if isinstance(entries, list) else []:
            blob = f"{e.get('headline', '')} {e.get('subhead', '')}".lower()
            for tok in _BANNED_CAPTION_TOKENS:
                if tok in blob:
                    return {"ok": False, "reason": f"caption '{f.name}' contains a foreign-app word: "
                            f"'{tok}' (generic template leakage) → rewrite app-specifically"}
            for ph in _GENERIC_CAPTION_PHRASES:
                if ph in blob:
                    return {"ok": False, "reason": f"caption '{f.name}' contains a generic template phrase: "
                            f"'{ph}' → rewrite app-specifically"}
    return {"ok": True, "reason": f"app-specific captions in {len(files)} locales"}


def _gate_testflight(app: Path) -> dict[str, Any]:
    """TestFlight build is PROCESSING/VALID in ASC (marker build_state)."""
    mk = app / ".appfactory" / "verify" / "testflight.json"
    if not mk.exists():
        return {"ok": False, "reason": "testflight marker missing"}
    try:
        d = json.loads(mk.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"testflight marker unreadable: {e}"}
    state = str(d.get("build_state", "")).upper()
    if state not in ("VALID", "PROCESSING"):
        return {"ok": False, "reason": f"testflight build_state '{state}' (must be VALID/PROCESSING)"}
    return {"ok": True, "reason": f"testflight build {state}"}


def _gate_app_preview(app: Path) -> dict[str, Any]:
    """App Preview: Claude-authored from REAL simulator recordings, one per spec.preview
    locale or a documented share, every file inside Apple's spec (886x1920, <=30 fps, H.264, 15–30 s,
    stereo AAC or silent), self-reviewed to 8+ on every criterion for the exact final file, rendered
    deterministically, then uploaded (marker uploaded=true after preview_upload)."""
    from . import preview as preview_mod
    if not (app / "app.spec.json").exists():
        return _gate_marker(app, "app_preview", ["uploaded"])
    chk = preview_mod.check(app)
    review = preview_mod.review_status(app)
    problems = chk["problems"] + review["problems"]
    if problems:
        return {"ok": False, "reason": f"app preview: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""),
                "detail": {"problems": problems}}
    mk = _gate_marker(app, "app_preview", ["uploaded"])
    if not mk["ok"]:
        return mk
    return {"ok": True, "reason": f"app preview: {len(chk['plan'])} locales, real footage, self-review 8+, uploaded"}


def _gate_custom_product_pages(app: Path) -> dict[str, Any]:
    """At least one CPP created and uploaded (marker pages non-empty)."""
    return _gate_marker(app, "custom_product_pages", ["pages"])


_GATES: dict[str, Callable[[Path], dict[str, Any]]] = {
    "backend": _gate_backend,
    "app_preview": _gate_app_preview,
    "custom_product_pages": _gate_custom_product_pages,
    "iap": _gate_iap,
    "submission_prep": _gate_submission_prep,
    "repo": _gate_repo,
    "ai_proxy": _gate_ai_proxy,
    "asc_app": _gate_asc_app,
    "metadata": _gate_metadata,
    "screenshots": _gate_screenshots,
    "deliver": _gate_deliver,
    "testflight": _gate_testflight,
    "design_research": _gate_design_research,
    "design": _gate_design,
    "localize": _gate_localize,
    "features": _gate_features,
    "analytics": _gate_analytics,
    "icon": _gate_icon,
    "scaffold": _gate_scaffold,
    "aso": _gate_aso,
}
