"""Run options — every optional part of a run, asked before any work starts.

One declarative list (OPTIONS). The agent shows each question to the user (run_options), then saves
the answers (run_options_save): services go to config.toml, everything else into app.spec.json, or,
before the app exists, into ~/.appfactory/run_options.json, which app_scaffold merges and consumes.
Defaults are the opinionated "appfactory" preset. Nothing App Store requires is optional here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import config as cfg
from . import spec as spec_mod

PENDING_FILE = "run_options.json"
INSTRUCTION = ("Ask the user each question one at a time (or as a compact checklist if the agent supports "
               "multi-select), then call run_options_save")


def _svc(sid: str, question: str, requires: list[str] | None = None) -> dict[str, Any]:
    return {"id": sid, "question": question, "kind": "bool", "choices": None, "default": True,
            "store": "config.services", "requires": requires or []}


def _opt(oid: str, question: str, kind: str, default: Any, path: str, *, choices: list | None = None,
         requires: list[str] | None = None, requires_when: Any = True, **extra: Any) -> dict[str, Any]:
    return {"id": oid, "question": question, "kind": kind, "choices": choices, "default": default,
            "store": f"spec.{path}", "requires": requires or [], "requires_when": requires_when, **extra}


OPTIONS: list[dict[str, Any]] = [
    # --- services (config.toml `services`) ---
    _svc("apple", "Use App Store Connect (create the app, in-app purchases, metadata, TestFlight uploads)?"),
    _svc("xcode", "Use local Xcode builds, the simulator and archives?"),
    _svc("supabase", "Use a Supabase backend (database, edge functions, server-side limits)?"),
    _svc("revenuecat", "Use RevenueCat for subscriptions and entitlements?"),
    _svc("ai", "Enable the AI service (server-side proxy; keys never ship in the app)?", ["supabase"]),
    _svc("firebase", "Use Firebase Analytics?"),
    _svc("github", "Create a private GitHub repo for the app?"),
    _svc("design", "Design screens with the claude-design MCP (otherwise boards are authored locally)?"),
    _svc("maestro", "Run end-to-end UI tests with Maestro on the simulator?"),
    _svc("lottie", "Use Lottie animations (fetch and recolor)?"),
    # --- app spec ---
    _opt("monetization", "Monetize with auto-renewing subscriptions or with a credits economy?",
         "choice", "subscription", "monetization", choices=["subscription", "credits"],
         requires=["revenuecat", "supabase", "ai_features"], requires_when="credits"),
    _opt("ai_features", "Does the app have AI features (calls go through the server-side proxy)?",
         "bool", True, "ai.enabled", requires=["ai", "supabase"]),
    _opt("free_trial", "Offer a free trial on the main subscriptions?", "bool", True, "options.free_trial"),
    _opt("trial_days", "How many days should the free trial last?", "number", 3, "options.trial_days",
         min=1, max=30, requires=["free_trial"], requires_when="*"),
    _opt("hard_paywall", "Show a hard, personalized paywall right after onboarding?", "bool", True,
         "options.hard_paywall"),
    _opt("offer_paywall", "Show a discounted offer paywall when the user dismisses the hard paywall?",
         "bool", True, "options.offer_paywall", requires=["hard_paywall"]),
    _opt("grace_period", "Turn on the App Store billing grace period for failed renewals?", "bool", True,
         "subscription.grace_period.enabled"),
    _opt("free_uses", "How many free uses before the paywall (lifetime, server-enforced)?", "choice", 1,
         "usage.free_lifetime_scans", choices=[0, 1]),
    _opt("onboarding_quiz", "Include a personalization quiz in onboarding?", "bool", True,
         "options.onboarding_quiz"),
    _opt("mascot", "Give the app an illustrated mascot?", "bool", False, "options.mascot"),
    _opt("app_languages", "Which in-app languages (String Catalog codes, English first)?", "list",
         list(spec_mod.APP_LOCALES), "locales.app"),
    _opt("store_locales", "Which App Store listing locales?", "list", list(spec_mod.STORE_LOCALES),
         "locales.store"),
    _opt("excluded_territories", "Which App Store territories should the app NOT be sold in (ISO alpha-3)?",
         "list", ["CHN"], "store.excluded_territories"),
    _opt("screenshots", "Build localized App Store screenshots?", "bool", True, "options.screenshots"),
    _opt("app_preview", "Make an App Store preview video?", "bool", True, "options.app_preview",
         requires=["apple"]),
    _opt("custom_product_pages", "Create Custom Product Pages for Search Ads themes?", "bool", True,
         "options.custom_product_pages", requires=["apple"]),
    _opt("analytics_events", "Instrument the analytics event catalog on every screen?", "bool", True,
         "options.analytics_events", requires=["firebase"]),
    _opt("rating_prompts", "Ask for App Store ratings at success moments (never in onboarding)?", "bool", True,
         "options.rating_prompts"),
    _opt("healthkit", "Read or write Apple Health data (HealthKit, consent first)?", "bool", False,
         "health.enabled"),
    _opt("sign_in_with_apple", "Offer Sign in with Apple (links the anonymous account)?", "bool", True,
         "options.sign_in_with_apple", requires=["supabase"]),
    _opt("github_issues", "Track postponed work as GitHub issues?", "bool", True, "options.github_issues",
         requires=["github"]),
    _opt("e2e_smoke", "Require green end-to-end smoke tests before the features stage and TestFlight?", "bool",
         True, "options.e2e_smoke", requires=["maestro"]),
]
BY_ID = {o["id"]: o for o in OPTIONS}

# Stages an option can switch off (reported n/a and skipped by the gate, like a disabled service).
STAGE_OPTIONS = {"screenshots": "screenshots", "app_preview": "app_preview",
                 "custom_product_pages": "custom_product_pages", "analytics": "analytics_events"}


# ---------------------------------------------------------------- storage helpers
def pending_path() -> Path:
    return cfg.CONFIG_DIR / PENDING_FILE


def load_pending() -> dict[str, Any]:
    p = pending_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _get(d: dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = copy.deepcopy(value)


def _spec_file(app_dir: str | None) -> Path | None:
    if not app_dir:
        return None
    p = spec_mod.path(app_dir)
    return p if p.exists() else None


def current(app_dir: str | None = None) -> dict[str, Any]:
    """Current value of every option: config services, then the app spec or the pending answers, else default."""
    on = cfg.enabled_services()
    sp_file = _spec_file(app_dir)
    source = json.loads(sp_file.read_text(encoding="utf-8")) if sp_file else {}
    pending = load_pending().get("answers", {})
    out = {}
    for o in OPTIONS:
        if o["store"] == "config.services":
            out[o["id"]] = o["id"] in on
            continue
        val = _get(source, o["store"][len("spec."):]) if source else None
        if val is None:
            val = pending.get(o["id"])
        out[o["id"]] = copy.deepcopy(o["default"] if val is None else val)
    return out


def listing(app_dir: str | None = None) -> dict[str, Any]:
    vals = current(app_dir)
    return {"ok": True, "instruction": INSTRUCTION, "confirmed": confirmed(app_dir),
            "options": [{**o, "current": vals[o["id"]]} for o in OPTIONS]}


# ---------------------------------------------------------------- validation
def _active(o: dict[str, Any], v: Any) -> bool:
    when = o.get("requires_when", True)
    return v is not None and (when == "*" or v == when)


def validate(answers: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    unknown = sorted(set(answers) - set(BY_ID))
    if unknown:
        errs.append(f"unknown option ids: {unknown}")
    missing = [o["id"] for o in OPTIONS if o["id"] not in answers]
    if missing:
        errs.append(f"answer every option (missing: {missing})")
    for o in OPTIONS:
        if o["id"] not in answers:
            continue
        v, kind = answers[o["id"]], o["kind"]
        if kind == "bool" and not isinstance(v, bool):
            errs.append(f"{o['id']}: must be true or false")
        elif kind == "choice" and v not in o["choices"]:
            errs.append(f"{o['id']}: must be one of {o['choices']}")
        elif kind == "number" and (isinstance(v, bool) or not isinstance(v, int)
                                   or not o.get("min", v) <= v <= o.get("max", v)):
            errs.append(f"{o['id']}: must be an integer in {o.get('min')}..{o.get('max')}")
        elif kind == "list" and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
            errs.append(f"{o['id']}: must be a list of strings")
    if errs:
        return errs
    if not answers["app_languages"] or answers["app_languages"][0] != "en":
        errs.append("app_languages: must start with en (the fallback language)")
    if not answers["store_locales"]:
        errs.append("store_locales: needs at least one locale")
    for o in OPTIONS:
        v = answers[o["id"]]
        if o["kind"] == "bool" and v is False:
            continue
        # a number option only matters when its parent is on (trial_days needs free_trial)
        if o["kind"] == "number":
            off = [r for r in o["requires"] if answers.get(r) is False]
            if off:
                continue
        if not _active(o, v):
            continue
        for r in o["requires"]:
            if answers.get(r) is False:
                errs.append(f"{o['id']}={v!r} requires {r} (turn {r} on or change {o['id']})")
    return errs


# ---------------------------------------------------------------- applying
def apply_to_spec(spec: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of spec with the answers written to their spec paths (+ derived fields)."""
    sp = copy.deepcopy(spec)
    for o in OPTIONS:
        if o["store"].startswith("spec.") and o["id"] in answers:
            _set(sp, o["store"][len("spec."):], answers[o["id"]])
    # free trial → every non-offer product's intro offer
    trial = answers.get("free_trial")
    days = answers.get("trial_days") or 3
    for p in (sp.get("subscription") or {}).get("products", []):
        if p.get("offering") == "offer" or trial is None:
            continue
        p["intro"] = {"type": "free", "duration": f"P{days}D"} if trial else None
    if "healthkit" in answers:
        sp.setdefault("consent", {})["health"] = bool(answers["healthkit"])
    if answers.get("mascot") is False and isinstance(sp.get("design"), dict):
        sp["design"]["mascot"] = None
    spec_mod.apply_option_effects(sp)  # offer products, placements, onboarding length follow the options
    sp["options_confirmed"] = True
    return sp


def save(answers: dict[str, Any], app_dir: str | None = None) -> dict[str, Any]:
    errs = validate(answers)
    if errs:
        return {"ok": False, "errors": errs}
    c = cfg.load_config()
    c["services"] = [s for s in cfg.SERVICES if cfg.SERVICES[s].get("always_on") or answers.get(s)]
    cfg.save_config(c)
    sp_file = _spec_file(app_dir)
    if sp_file:
        sp = apply_to_spec(json.loads(sp_file.read_text(encoding="utf-8")), answers)
        try:
            spec_mod.save(app_dir, sp)
        except ValueError as e:
            return {"ok": False, "errors": [f"spec rejected the answers: {e}"]}
        where = str(sp_file)
    else:
        p = pending_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"answers": answers, "options_confirmed": True}, indent=2) + "\n",
                     encoding="utf-8")
        where = str(p)
    return {"ok": True, "options_confirmed": True, "services": c["services"], "saved_to": where}


def merge_pending(spec: dict[str, Any]) -> dict[str, Any]:
    """app_scaffold: apply the pending answers to a new spec (unchanged when there are none)."""
    pending = load_pending()
    if not pending.get("options_confirmed"):
        return spec
    return apply_to_spec(spec, pending.get("answers", {}))


def consume_pending() -> None:
    pending_path().unlink(missing_ok=True)


def confirmed(app_dir: str | None = None) -> bool:
    sp_file = _spec_file(app_dir)
    if sp_file:
        try:
            if json.loads(sp_file.read_text(encoding="utf-8")).get("options_confirmed"):
                return True
        except Exception:  # noqa: BLE001
            pass
    return bool(load_pending().get("options_confirmed"))


def not_confirmed_error() -> dict[str, Any]:
    return {"ok": False, "options_unconfirmed": True,
            "error": "run options are not confirmed yet: call run_options(), ask the user every question, then "
                     "run_options_save(answers). Pass skip_options_check=true only if the user explicitly "
                     "said to keep the defaults without asking."}


def stage_disabled_option(app_dir: str | Path, stage: str) -> str | None:
    """The option (turned off in app.spec.json `options`) that makes `stage` n/a, or None."""
    oid = STAGE_OPTIONS.get(stage)
    if not oid:
        return None
    p = spec_mod.path(app_dir)
    if not p.exists():
        return None
    try:
        sp = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return oid if _get(sp, BY_ID[oid]["store"][len("spec."):]) is False else None


def is_off(app_dir: str | Path | None, oid: str) -> bool:
    """The user turned option `oid` off: in the app's spec, else (no app yet) in the pending answers."""
    sp_file = _spec_file(str(app_dir) if app_dir else None)
    if sp_file:
        try:
            sp = json.loads(sp_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return False
        return _get(sp, BY_ID[oid]["store"][len("spec."):]) is False
    return load_pending().get("answers", {}).get(oid) is False


def na_note(oid: str) -> str:
    return f"n/a: the user turned off the '{oid}' run option"
