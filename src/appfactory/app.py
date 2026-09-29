"""app_* — scaffold a new SwiftUI app from the core template, driven by app.spec.json.

Template: templates/swiftui-subscription/ (XcodeGen project.yml + Sources + Resources + Tests +
UITests + supabase/). `scaffold` builds (or takes) the app's spec, writes it to the app dir, and
derives everything else from it:

- monetization `subscription` (default) strips the credit economy (Sources/Credits, credit UI,
  credit-only strings); `credits` keeps it (legacy credits model);
- optional modules (`health`) are kept only when the spec enables them;
- `Sources/App/AppSpec.swift` + `Sources/Paywall/PaywallSource.swift` are generated from the spec;
- `Resources/Configuration.storekit` is generated from the spec (storekit.py);
- the onboarding skeleton is trimmed/padded to `design.onboarding_screens`;
- the String Catalogs keep exactly `locales.app`;
- the Supabase template is pruned/rendered for the spec's backend mode.

Blocks between `// @if <flag>` / `# @if <flag>` / `<!-- @if <flag> -->` and the matching `@endif` line are kept only when
the flag is on (flags: subscription, credits, health, the optional services revenuecat, supabase,
firebase, and the run options hard_paywall, offer_paywall, quiz, ratings, siwa, e2e_smoke); `@if !<flag>`
keeps a block only when the flag is off. Service flags come from the user's
enabled services (config.enabled_services), overridable per app with spec `services: {name: bool}`:
- revenuecat off → StoreKit 2-only StoreManager, no RevenueCat package;
- supabase off → no supabase/ backend, AI off, on-device free-usage gate (LocalUsageGate);
- firebase off → Tracker keeps the event catalog but sends nothing, no Firebase package.

Run options (spec `options`, all on by default) reshape the app the same way:
- hard_paywall off → onboarding ends in the app, the paywall opens from placements only;
- offer_paywall off → no offer products/placements, no OfferPaywallView, dismissing the paywall ends onboarding;
- onboarding_quiz off → onboarding is a short run of intro screens, the paywall is not personalized;
- rating_prompts off → no RatingPolicy or review request; sign_in_with_apple off → no capability, entitlement or SIWA UI;
- e2e_smoke off → no .maestro workspace.
"""

from __future__ import annotations

import json
import re
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import spec as spec_mod
from . import storekit as storekit_mod
from .proc import run

PKG_ROOT = Path(__file__).resolve().parent.parent.parent  # AppFactory/
# checkout: <repo>/templates; installed wheel: appfactory/templates (force-included)
TEMPLATES_ROOT = PKG_ROOT / "templates" if (PKG_ROOT / "templates").is_dir() else Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR = TEMPLATES_ROOT / "swiftui-subscription"
DEFAULT_DEST = Path.home() / "Desktop" / "AppFactoryApps"

TEXT_EXTS = {".yml", ".yaml", ".swift", ".storekit", ".json", ".plist", ".md", ".toml", ".ts", ".xcstrings", ".py", ".sh"}
SKIP_DIRS = {"build", ".git", "node_modules", ".appfactory", "DerivedData", ".build"}

# Files / dirs that exist only for one monetization mode or module (relative to the app root).
MODE_ONLY_PATHS = {"credits": ["Sources/Credits"]}
MODULE_PATHS = {"health": ["Sources/Health", "Tests/HealthTests.swift"]}
# Service-only paths; a `!flag` key lists paths that exist only while that service is off.
SERVICE_PATHS = {"supabase": ["supabase"], "!supabase": ["Sources/Core/LocalUsageGate.swift"]}
# Paths that exist only while a run option is on (spec `options`; see feature_flags).
OPTION_PATHS = {
    "offer_paywall": ["Sources/Paywall/OfferPaywallView.swift"],
    "ratings": ["Sources/Core/RatingPolicy.swift", "Tests/RatingPolicyTests.swift"],
    "siwa": ["Sources/Core/AuthProvider.swift"],
    "e2e_smoke": [".maestro"],
}
# Optional services the template can compile without.
TEMPLATE_SERVICES = ("revenuecat", "supabase", "firebase")

_IF_RE = re.compile(r"^\s*(?://|#|<!--)\s*@if\s+(!?\w+)\s*(?:-->)?\s*$")
_ENDIF_RE = re.compile(r"^\s*(?://|#|<!--)\s*@endif\s*(?:-->)?\s*$")
_MODULE_TAG_RE = re.compile(r"\[module:(\w+)\]")


def _sanitize_target(name: str) -> str:
    """Xcode target/scheme name: alphanumeric, starts with a letter."""
    t = re.sub(r"[^A-Za-z0-9]", "", name)
    if not t:
        t = "App"
    if not t[0].isalpha():
        t = "App" + t
    return t


def _iter_text_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_EXTS:
            continue
        if SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        yield p


def _replace_tokens(root: Path, tokens: dict[str, str]) -> None:
    """Replace tokens in text files under root (build/.git etc. are skipped)."""
    for p in _iter_text_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # skip binary/unreadable file
        new = text
        for k, v in tokens.items():
            new = new.replace(k, v)
        if new != text:
            p.write_text(new, encoding="utf-8")


def _flag_on(flags: dict[str, bool], name: str) -> bool:
    """`flag` or `!flag` against the flag table (unknown flags are off)."""
    if name.startswith("!"):
        return not flags.get(name[1:], False)
    return bool(flags.get(name, False))


def strip_blocks(text: str, flags: dict[str, bool]) -> str:
    """Keep `@if <flag>` / `@if !<flag>` blocks whose condition holds (marker lines removed), drop the others."""
    out: list[str] = []
    stack: list[bool] = []
    for line in text.splitlines(keepends=True):
        m = _IF_RE.match(line)
        if m:
            stack.append(_flag_on(flags, m.group(1)))
            continue
        if _ENDIF_RE.match(line):
            if stack:
                stack.pop()
            continue
        if all(stack):
            out.append(line)
    return "".join(out)


def feature_flags(spec: dict[str, Any]) -> dict[str, bool]:
    mode = spec.get("monetization", "subscription")
    services = spec.get("services") or {}
    return {
        "subscription": mode == "subscription",
        "credits": mode == "credits",
        "health": bool((spec.get("health") or {}).get("enabled")),
        **{s: services.get(s, True) is not False for s in TEMPLATE_SERVICES},
        "hard_paywall": spec_mod.option(spec, "hard_paywall"),
        "offer_paywall": spec_mod.offer_on(spec),
        "quiz": spec_mod.option(spec, "onboarding_quiz"),
        "ratings": spec_mod.option(spec, "rating_prompts"),
        "siwa": spec_mod.option(spec, "sign_in_with_apple"),
        "e2e_smoke": spec_mod.option(spec, "e2e_smoke"),
    }


def apply_features(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Delete mode/module-only paths that are off and strip their `@if` blocks. Idempotent."""
    flags = feature_flags(spec)
    removed: list[str] = []
    for flag, rels in {**MODE_ONLY_PATHS, **MODULE_PATHS, **SERVICE_PATHS, **OPTION_PATHS}.items():
        if _flag_on(flags, flag):
            continue
        for rel in rels:
            p = root / rel
            if p.is_dir():
                shutil.rmtree(p)
                removed.append(rel)
            elif p.exists():
                p.unlink()
                removed.append(rel)
    for p in _iter_text_files(root):
        if p.suffix not in {".swift", ".yml", ".yaml", ".md"}:
            continue
        text = p.read_text(encoding="utf-8")
        if "@if " not in text:
            continue
        new = strip_blocks(text, flags)
        if new != text:
            p.write_text(new, encoding="utf-8")
    return {"flags": flags, "removed": removed}


# ---------- generated Swift ----------

def _swift_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _days(iso: str | None) -> int | None:
    if not iso:
        return None
    m = re.fullmatch(r"P(\d+)([DWMY])", iso)
    if not m:
        return None
    return int(m.group(1)) * {"D": 1, "W": 7, "M": 30, "Y": 365}[m.group(2)]


def _camel(raw: str) -> str:
    head, *rest = raw.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


def render_app_spec_swift(spec: dict[str, Any]) -> str:
    """Sources/App/AppSpec.swift — the spec values the binary needs."""
    health = spec.get("health") or {}
    anchor = spec.get("offer_anchor") or {}
    rating = spec_mod.rating(spec)
    lines = [
        "// GENERATED by AppFactory from app.spec.json — do not edit by hand.",
        "// Regenerate with app_sync_spec after changing the spec.",
        "import Foundation",
        "",
        "enum AppSpec {",
        f"    static let name = {_swift_str(spec['name'])}",
        f"    static let displayName = {_swift_str(spec.get('display_name') or spec['name'])}",
        f"    static let bundleID = {_swift_str(spec['bundle_id'])}",
        f"    static let monetization = {_swift_str(spec.get('monetization', 'subscription'))}",
        f"    static let entitlementID = {_swift_str(spec['subscription']['entitlement'])}",
        f"    static let subscriptionGroup = {_swift_str(spec['subscription']['group'])}",
        f"    static let appLocales: [String] = [{', '.join(_swift_str(x) for x in spec['locales']['app'])}]",
        f"    static let eventPrefix = {_swift_str(spec['analytics']['event_prefix'])}",
        f"    static let onboardingScreens = {int(spec['design']['onboarding_screens'])}",
        *([f"    static let offerAnchorItem = {_swift_str(anchor.get('item', 'burger'))}",
           f"    static let offerAnchorKey = {_swift_str(anchor.get('label_key', 'offer.anchor.burger'))}"]
          if spec_mod.offer_on(spec) else []),
        "    // false = non-AI app: the analyze edge function is not deployed; do not call AIService.",
        f"    static let aiEnabled = {'true' if spec_mod.ai_enabled(spec) else 'false'}",
        f"    static let consentRequired = {'true' if spec.get('consent', {}).get('health') else 'false'}",
        '    static let consentColumn = "consent_health_at"',
        f"    static let healthEnabled = {'true' if health.get('enabled') else 'false'}",
        f"    static let healthRead: [String] = [{', '.join(_swift_str(x) for x in health.get('read', []))}]",
        f"    static let healthWrite: [String] = [{', '.join(_swift_str(x) for x in health.get('write', []))}]",
        *([
            "    // App Store rating requests at success moments (RatingPolicy; never in onboarding).",
            f"    static let ratingSuccessCount = {int(rating['success_count'])}",
            f"    static let ratingDistinctDays = {int(rating['distinct_days'])}",
            f"    static let ratingMilestones: [Int] = [{', '.join(str(int(m)) for m in rating['milestones'])}]",
            f"    static let ratingMinDaysBetween = {int(rating['min_days_between'])}",
            f"    static let ratingMaxPerYear = {int(rating['max_per_year'])}",
        ] if spec_mod.option(spec, "rating_prompts") else []),
        "",
        "    struct Product: Equatable {",
        "        let key: String",
        "        let id: String",
        "        /// ISO 8601 period (P1W, P1M, P1Y).",
        "        let period: String",
        "        let usd: Decimal",
        "        /// Apple subscription level (1 = highest).",
        "        let level: Int",
        "        /// Free-trial length in days, nil = no intro offer.",
        "        let introDays: Int?",
        "        /// RevenueCat offering: \"default\" (hard paywall)" + (" or \"offer\"." if spec_mod.offer_on(spec) else "."),
        "        let offering: String",
        "        let package: String",
        "    }",
        "",
        "    static let products: [Product] = [",
    ]
    for p in spec_mod.products(spec):
        intro = p.get("intro")
        days = _days(intro.get("duration")) if intro and intro.get("type") == "free" else None
        usd = f"{Decimal(str(p['usd'])):.2f}"
        lines.append(
            f"        Product(key: {_swift_str(p['key'])}, id: {_swift_str(p['id'])}, period: {_swift_str(p['period'])}, "
            f"usd: Decimal(string: \"{usd}\")!, level: {int(p['level'])}, introDays: {days if days is not None else 'nil'}, "
            f"offering: {_swift_str(p.get('offering', 'default'))}, package: {_swift_str(p.get('package', ''))}),"
        )
    lines += ["    ]", "}", ""]
    return "\n".join(lines)


def render_paywall_source_swift(spec: dict[str, Any]) -> str:
    """Sources/Paywall/PaywallSource.swift — one case per spec placement."""
    offers = set(spec.get("offer_placements", []))
    lines = [
        "// GENERATED by AppFactory from app.spec.json (placements) — do not edit by hand.",
        "import Foundation",
        "",
        "/// Which door opened the paywall. Never free text: this value is the axis of the revenue",
        "/// funnel. The raw value is sent as `from` on paywall/purchase events and doubles as the",
        "/// RevenueCat placement id.",
        "enum PaywallSource: String, CaseIterable {",
    ]
    for raw in spec["placements"]:
        name = _camel(raw)
        lines.append(f"    case {name}" if name == raw else f"    case {name} = {_swift_str(raw)}")
    offer_cases = ", ".join("." + _camel(p) for p in spec["placements"] if p in offers)
    lines += [
        "",
        "    var eventValue: String { rawValue }",
        "",
        "    /// RevenueCat placement identifier (same string, so dashboards line up with analytics).",
        "    var placementID: String { rawValue }",
        "",
        "    /// Offer-type placements show the discounted products (RevenueCat offering \"offer\").",
        "    var isOffer: Bool {",
    ]
    if offer_cases:
        lines += ["        switch self {", f"        case {offer_cases}: return true", "        default: return false", "        }"]
    else:
        lines.append("        false")
    lines += ["    }", "}", ""]
    return "\n".join(lines)


PRIVACY_MANIFEST_REL = Path("Privacy") / "PrivacyInfo.xcprivacy"
# (collected data type, linked to the user, purposes) — what every AppFactory subscription app collects:
# the anonymous Supabase user id, the Sign in with Apple email, purchases (RevenueCat), the photo/text
# sent for analysis (not stored with the user), the saved results, analytics (Firebase, no IDFA).
_PRIVACY_BASE = [
    ("UserID", True, ["AppFunctionality", "Analytics"]),
    ("EmailAddress", True, ["AppFunctionality"]),
    ("PurchaseHistory", True, ["AppFunctionality", "Analytics"]),
    ("PhotosorVideos", False, ["AppFunctionality"]),
    ("OtherUserContent", True, ["AppFunctionality"]),
    ("ProductInteraction", True, ["Analytics"]),
    ("DeviceID", False, ["Analytics"]),
    ("OtherDiagnosticData", True, ["AppFunctionality"]),
]


def render_privacy_manifest(spec: dict[str, Any]) -> str:
    """Privacy/PrivacyInfo.xcprivacy: no tracking, the collected data types, and the required-reason
    APIs the template uses (UserDefaults CA92.1). App Store Connect refuses a build whose bundles lack
    one (ITMS-91053). Health and Fitness join when spec.health is enabled; an App Group
    (widgets) additionally needs the UserDefaults reason 1C8F.1."""
    data = [d for d in _PRIVACY_BASE if d[0] != "EmailAddress" or spec_mod.option(spec, "sign_in_with_apple")]
    if (spec.get("health") or {}).get("enabled"):
        data[:0] = [("Health", True, ["AppFunctionality"]), ("Fitness", True, ["AppFunctionality"])]
    reasons = ["CA92.1"] + (["1C8F.1"] if "APP_GROUPS" in (spec.get("capabilities") or []) else [])

    def entry(kind: str, linked: bool, purposes: list[str]) -> str:
        ps = "".join(f"\n\t\t\t\t<string>NSPrivacyCollectedDataTypePurpose{x}</string>" for x in purposes)
        return (f"\t\t<dict>\n\t\t\t<key>NSPrivacyCollectedDataType</key>\n\t\t\t<string>NSPrivacyCollectedDataType{kind}</string>"
                f"\n\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>\n\t\t\t<{'true' if linked else 'false'}/>"
                "\n\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>\n\t\t\t<false/>"
                f"\n\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>\n\t\t\t<array>{ps}\n\t\t\t</array>\n\t\t</dict>")
    body = "\n".join(entry(*d) for d in data)
    rs = "".join(f"\n\t\t\t\t<string>{r}</string>" for r in reasons)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            "<!-- GENERATED by AppFactory from app.spec.json (app_sync_spec). Keep it equal to the App Privacy answers. -->\n"
            '<plist version="1.0">\n<dict>\n\t<key>NSPrivacyTracking</key>\n\t<false/>\n'
            "\t<key>NSPrivacyTrackingDomains</key>\n\t<array/>\n"
            f"\t<key>NSPrivacyCollectedDataTypes</key>\n\t<array>\n{body}\n\t</array>\n"
            "\t<key>NSPrivacyAccessedAPITypes</key>\n\t<array>\n\t\t<dict>\n"
            "\t\t\t<key>NSPrivacyAccessedAPIType</key>\n\t\t\t<string>NSPrivacyAccessedAPICategoryUserDefaults</string>\n"
            f"\t\t\t<key>NSPrivacyAccessedAPITypeReasons</key>\n\t\t\t<array>{rs}\n\t\t\t</array>\n"
            "\t\t</dict>\n\t</array>\n</dict>\n</plist>\n")


def write_generated_swift(app_dir: str | Path, spec: dict[str, Any]) -> list[str]:
    app = Path(app_dir).expanduser()
    out = {
        app / "Sources" / "App" / "AppSpec.swift": render_app_spec_swift(spec),
        app / "Sources" / "Paywall" / "PaywallSource.swift": render_paywall_source_swift(spec),
        app / PRIVACY_MANIFEST_REL: render_privacy_manifest(spec),
    }
    for path, text in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return [str(p.relative_to(app)) for p in out]


# ---------- onboarding length ----------

ONBOARDING_REL = Path("Sources") / "Onboarding" / "OnboardingSteps.swift"
# Dropped first when the spec asks for fewer screens (keeps >= 5 questions at the 14 minimum).
ONBOARDING_DROP_ORDER = [
    "tone", "describe", "comparison", "trust", "almost", "daily_time", "potential",
    "how_it_works", "schedule", "experience", "right_place", "birth_year",
]
_STEP_RE = re.compile(r"^\s*// @step (\w+)\s*$")
_EXTRA_STEP = '''        // @step {id}
        .init(id: "{id}", kind: .question, title: "Tell us one more thing",
              subtitle: "It helps us personalize your plan.", icon: "questionmark.bubble", options: [
                  .init(id: "yes", title: "Yes"),
                  .init(id: "no", title: "No"),
                  .init(id: "not_sure", title: "Not sure"),
              ]),
'''


def _split_steps(text: str) -> tuple[str, list[tuple[str, str]], str]:
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if _STEP_RE.match(ln)]
    end = next(i for i, ln in enumerate(lines) if "// @end-steps" in ln)
    head = "".join(lines[: starts[0]])
    blocks = []
    for n, i in enumerate(starts):
        j = starts[n + 1] if n + 1 < len(starts) else end
        blocks.append((_STEP_RE.match(lines[i]).group(1), "".join(lines[i:j])))
    return head, blocks, "".join(lines[end:])


def onboarding_step_ids(app_dir: str | Path) -> list[str]:
    text = (Path(app_dir).expanduser() / ONBOARDING_REL).read_text(encoding="utf-8")
    return [sid for sid, _ in _split_steps(text)[1]]


def fit_onboarding(app_dir: str | Path, count: int) -> dict[str, Any]:
    """Trim or pad the onboarding skeleton to exactly `count` steps (spec design.onboarding_screens)."""
    path = Path(app_dir).expanduser() / ONBOARDING_REL
    head, blocks, tail = _split_steps(path.read_text(encoding="utf-8"))
    dropped: list[str] = []
    for sid in ONBOARDING_DROP_ORDER:
        if len(blocks) <= count:
            break
        if any(b[0] == sid for b in blocks):
            blocks = [b for b in blocks if b[0] != sid]
            dropped.append(sid)
    if len(blocks) > count:
        return {"ok": False, "error": f"cannot trim onboarding below {len(blocks)} steps"}
    added: list[str] = []
    insert_at = next((i for i, b in enumerate(blocks) if b[0] == "loading"), len(blocks))
    while len(blocks) < count:
        sid = f"extra_{len(added) + 1}"
        blocks.insert(insert_at, (sid, _EXTRA_STEP.format(id=sid)))
        insert_at += 1
        added.append(sid)
    path.write_text(head + "".join(b for _, b in blocks) + tail, encoding="utf-8")
    return {"ok": True, "steps": len(blocks), "dropped": dropped, "added": added}


# ---------- String Catalogs ----------

CATALOGS = [Path("Resources") / "Localizable.xcstrings", Path("Resources") / "InfoPlist.xcstrings"]


def prune_catalogs(app_dir: str | Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Keep exactly spec locales.app in the String Catalogs and drop keys tagged
    `[module:<flag>]` (in the key's comment) whose feature is off."""
    app = Path(app_dir).expanduser()
    locales = set(spec["locales"]["app"])
    flags = feature_flags(spec)
    report: dict[str, Any] = {}
    for rel in CATALOGS:
        path = app / rel
        if not path.exists():
            continue
        cat = json.loads(path.read_text(encoding="utf-8"))
        strings = cat.get("strings", {})
        removed_keys = 0
        for key in list(strings):
            m = _MODULE_TAG_RE.search(strings[key].get("comment", ""))
            if m and not flags.get(m.group(1), False):
                del strings[key]
                removed_keys += 1
                continue
            locs = strings[key].get("localizations")
            if locs:
                strings[key]["localizations"] = {k: v for k, v in locs.items() if k in locales}
        path.write_text(json.dumps(cat, ensure_ascii=False, indent=2, separators=(",", " : "), sort_keys=True) + "\n",
                        encoding="utf-8")
        report[str(rel)] = {"keys": len(strings), "removed_module_keys": removed_keys}
    return report


# ---------- scaffold ----------

def _resolve_spec(name: str | None, bundle_id: str | None, display_name: str | None,
                  spec: dict[str, Any] | str | None) -> dict[str, Any]:
    """spec: None (defaults), a path to an app.spec.json, a full spec dict, or a dict of overrides."""
    if isinstance(spec, str):
        p = Path(spec).expanduser()
        spec = json.loads((p / spec_mod.SPEC_FILE if p.is_dir() else p).read_text(encoding="utf-8"))
    overrides = dict(spec or {})
    name = name or overrides.get("name")
    bundle_id = bundle_id or overrides.get("bundle_id")
    if not name or not bundle_id:
        raise ValueError("name and bundle_id are required (argument or spec)")
    for k in ("name", "bundle_id"):
        overrides.pop(k, None)
    if display_name:
        overrides["display_name"] = display_name
    _merge_services(overrides)
    return spec_mod.build(name, bundle_id, **overrides)


def _merge_services(overrides: dict[str, Any]) -> None:
    """Enabled services (config) → spec `services`, only when one is off, so an all-on scaffold is
    unchanged. The spec's own `services` values win. Without Supabase or the AI service the app is
    non-AI unless the spec says otherwise."""
    from . import config as cfg
    on = cfg.enabled_services()
    services = {s: s in on for s in TEMPLATE_SERVICES} | dict(overrides.get("services") or {})
    if not all(services.values()):
        overrides["services"] = services
    ai = overrides.get("ai") if isinstance(overrides.get("ai"), dict) else {}
    if "enabled" not in ai and (services["supabase"] is False or "ai" not in on):
        overrides["ai"] = {**ai, "enabled": False}


def _service_problems(spec: dict[str, Any]) -> list[str]:
    flags = feature_flags(spec)
    errs = []
    if spec.get("monetization") == "credits" and not (flags["revenuecat"] and flags["supabase"]):
        errs.append("monetization 'credits' needs the revenuecat and supabase services (server-side credit ledger)")
    if spec_mod.ai_enabled(spec) and not flags["supabase"]:
        errs.append("ai.enabled needs the supabase service (AI calls go through the Supabase proxy)")
    return errs


def scaffold(name: str | None = None, bundle_id: str | None = None, display_name: str | None = None,
             dest_dir: str | None = None, spec: dict[str, Any] | str | None = None,
             generate: bool = True) -> dict[str, Any]:
    """Generate a new app from the template (+ xcodegen), everything driven by the app spec."""
    if not TEMPLATE_DIR.exists():
        return {"ok": False, "error": f"template not found: {TEMPLATE_DIR}"}
    try:
        app_spec = _resolve_spec(name, bundle_id, display_name, spec)
        from . import options as options_mod
        merged = options_mod.merge_pending(app_spec)  # the run options answered before the app existed
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)}
    pending_used = merged is not app_spec
    app_spec = merged
    errs = spec_mod.validate(app_spec) + _service_problems(app_spec)
    if errs:
        return {"ok": False, "error": "invalid spec: " + "; ".join(errs)}

    target = _sanitize_target(app_spec["name"])
    bundle = app_spec["bundle_id"]
    prefix = bundle.rsplit(".", 1)[0] if "." in bundle else bundle
    base = Path(dest_dir).expanduser() if dest_dir else DEFAULT_DEST
    dest = base / target
    if dest.exists():
        return {"ok": False, "error": f"destination already exists: {dest}"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE_DIR, dest, ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.xcodeproj", ".DS_Store"))

    features = apply_features(dest, app_spec)
    _replace_tokens(dest, {
        "__APP_NAME__": target,
        "__DISPLAY_NAME__": app_spec["display_name"],
        "__BUNDLE_ID__": bundle,
        "__BUNDLE_PREFIX__": prefix,
        "__FREE_USES__": str(int((app_spec.get("usage") or {}).get("free_lifetime_scans", 1))),
    })
    _fit_onboarding_count(dest, app_spec)
    spec_mod.save(dest, app_spec)
    if pending_used:
        options_mod.consume_pending()
    generated = write_generated_swift(dest, app_spec)
    storekit_path = storekit_mod.write(app_spec, dest)
    onboarding = fit_onboarding(dest, int(app_spec["design"]["onboarding_screens"]))
    catalogs = prune_catalogs(dest, app_spec)
    backend = _render_backend(dest, app_spec) if features["flags"]["supabase"] else {"supabase": "n/a"}

    result: dict[str, Any] = {
        "ok": True,
        "name": target,
        "display_name": app_spec["display_name"],
        "bundle_id": bundle,
        "dir": str(dest),
        "spec": str(spec_mod.path(dest)),
        "project": str(dest / f"{target}.xcodeproj"),
        "scheme": target,
        "monetization": app_spec["monetization"],
        "features": features,
        "generated": generated + [str(storekit_path.relative_to(dest))],
        "onboarding": onboarding,
        "catalogs": catalogs,
        "backend": backend,
    }
    if generate:
        gen = run(["xcodegen", "generate"], cwd=str(dest), timeout=120)
        if not gen.get("ok"):
            return {"ok": False, "error": "xcodegen failed", "detail": gen, "dir": str(dest)}
    return result


def _fit_onboarding_count(dest: Path, app_spec: dict[str, Any]) -> None:
    """Options that remove onboarding steps (or the HealthKit step) move the spec's screen count to the
    number of steps the scaffold really has, unless the spec set its own and the quiz is on."""
    if not any(not spec_mod.option(app_spec, o) for o in ("hard_paywall", "offer_paywall", "onboarding_quiz",
                                                          "sign_in_with_apple")):
        return
    design = app_spec["design"]
    if not spec_mod.option(app_spec, "onboarding_quiz") or design["onboarding_screens"] == spec_mod.natural_onboarding_screens(app_spec):
        design["onboarding_screens"] = len(onboarding_step_ids(dest))


def _render_backend(dest: Path, app_spec: dict[str, Any]) -> dict[str, Any]:
    """Prune supabase/ to the monetization mode and render the spec-driven backend files."""
    from . import supabase as supa_mod
    try:
        return {"mode": supa_mod.apply_backend_mode(dest, app_spec), "render": supa_mod.render_backend(dest, app_spec)}
    except Exception as e:  # noqa: BLE001 — scaffold must not die on a backend render problem
        return {"ok": False, "error": str(e)}


def sync_spec(app_dir: str) -> dict[str, Any]:
    """Re-derive AppSpec.swift, PaywallSource.swift and Configuration.storekit after a spec edit."""
    try:
        s = spec_mod.load(app_dir)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)}
    errs = spec_mod.validate(s)
    if errs:
        return {"ok": False, "error": "invalid spec: " + "; ".join(errs)}
    generated = write_generated_swift(app_dir, s)
    sk = storekit_mod.write(s, app_dir)
    return {"ok": True, "generated": generated + [str(sk)], "catalogs": prune_catalogs(app_dir, s)}


# ---------- inject_config ----------

def _set_marker(text: str, key: str, value: str) -> str:
    return re.sub(rf"(=|return)\s*[^/\n]+?(\s*// appfactory:{key}\b)", rf"\g<1> {value}\g<2>", text)


def inject_config(
    project_dir: str,
    supabase_url: str | None = None,
    supabase_anon_key: str | None = None,
    ai_proxy_url: str | None = None,
    posthog_key: str | None = None,
    product_yearly: str | None = None,
    product_weekly: str | None = None,
    privacy_url: str | None = None,
    support_email: str | None = None,
    revenuecat_key: str | None = None,
    yearly_credits: int | None = None,
    weekly_credits: int | None = None,
    credit_pack_small: int | None = None,
    credit_pack_medium: int | None = None,
    credit_pack_large: int | None = None,
    paywall_strategy: str | None = None,
) -> dict[str, Any]:
    """Fill in the public config of a scaffolded app (AppConfig.swift): Supabase URL + anon key,
    RevenueCat public key, support email, paywall strategy, credit amounts (credits mode).

    Product ids, prices and trials come from app.spec.json (AppSpec.swift), never from here; the
    product_* / privacy_url / ai_proxy_url / posthog_key arguments only fill legacy tokens.
    paywall_strategy: "hard_only" | "hard_and_offer" (default). Values on `// appfactory:<key>`
    marker lines are rewritten in place, so inject_config can run again.
    """
    root = Path(project_dir).expanduser()
    if not root.exists():
        return {"ok": False, "error": f"directory not found: {root}"}
    if paywall_strategy not in (None, "hard_only", "hard_and_offer"):
        return {"ok": False, "error": "paywall_strategy must be: hard_only | hard_and_offer"}
    tokens = {
        "__SUPABASE_URL__": supabase_url,
        "__SUPABASE_ANON_KEY__": supabase_anon_key,
        "__AI_PROXY_URL__": ai_proxy_url,
        "__POSTHOG_KEY__": posthog_key,
        "__PRODUCT_YEARLY__": product_yearly,
        "__PRODUCT_WEEKLY__": product_weekly,
        "__PRIVACY_URL__": privacy_url,
        "__SUPPORT_EMAIL__": support_email,
        # Without an RC key keep an explicit placeholder (build compiles, RC stays unconfigured).
        "__REVENUECAT_KEY__": revenuecat_key or "appl_PENDING",
        # GOTCHA: yearly credits are PER MONTH, weekly credits are PER WEEK. The yearly allowance must
        # beat the weekly plan's monthly equivalent (weekly x 4.33) or upgrading to yearly is pointless.
        "__YEARLY_CREDITS__": str(yearly_credits or 60),
        "__WEEKLY_CREDITS__": str(weekly_credits or 10),
        "__CREDIT_PACK_SMALL__": str(credit_pack_small or 10),
        "__CREDIT_PACK_MEDIUM__": str(credit_pack_medium or 30),
        "__CREDIT_PACK_LARGE__": str(credit_pack_large or 60),
        "__SHOW_OFFER_PAYWALL__": "false" if paywall_strategy == "hard_only" else "true",
    }
    applied = {k: v for k, v in tokens.items() if v}
    _replace_tokens(root, applied)

    markers = {
        "paywall_strategy": None if paywall_strategy is None else ("false" if paywall_strategy == "hard_only" else "true"),
        "yearly_credits": yearly_credits, "weekly_credits": weekly_credits,
        "credit_pack_small": credit_pack_small, "credit_pack_medium": credit_pack_medium,
        "credit_pack_large": credit_pack_large,
    }
    marked: list[str] = []
    for p in root.rglob("AppConfig.swift"):
        if SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        text = p.read_text(encoding="utf-8")
        new = text
        for key, value in markers.items():
            if value is not None:
                new = _set_marker(new, key, str(value))
                marked.append(key)
        if new != text:
            p.write_text(new, encoding="utf-8")
    return {"ok": True, "injected": sorted(applied.keys()), "markers": sorted(set(marked)), "dir": str(root)}
