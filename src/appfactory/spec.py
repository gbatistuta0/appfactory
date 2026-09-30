"""app_spec — the single source of truth for one app.

Every generator reads `<app_dir>/app.spec.json`: the StoreKit file, the ASC and
RevenueCat setup, the Supabase caps, the String Catalog locales, the design
generators and the paywalls. Keeping one file is what guarantees store parity
(ASC == RevenueCat == Configuration.storekit), a rule learned the hard way.

Defaults encode the proven decisions: subscription-only, weekly + yearly both
with a 3-day free trial in one group, a trial-less `yearly.offer`, 6 in-app
languages, 8 store locales, placements shared by analytics and RevenueCat.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from pathlib import Path
from typing import Any

SPEC_FILE = "app.spec.json"

APP_LOCALES = ["en", "es", "pt-BR", "de", "fr", "tr"]
STORE_LOCALES = ["en-US", "en-GB", "es-MX", "es-ES", "pt-BR", "de-DE", "fr-FR", "tr"]

# Raw value == analytics `from` == RevenueCat placement id.
PLACEMENTS = [
    "onboarding", "offer_after_onboarding", "free_scan_used", "daily_cap",
    "settings", "history_locked", "app_open_offer",
    # Paywall shown while Apple retries a failed renewal (entitlement lapsed); default offering.
    "billing_issue",
]
OFFER_PLACEMENTS = ["offer_after_onboarding", "app_open_offer"]
# Run options that reshape the app live in the spec `options` block; a missing key means on.
SHAPING_OPTIONS = ("hard_paywall", "offer_paywall", "onboarding_quiz", "rating_prompts", "sign_in_with_apple",
                   "e2e_smoke")
# Placements the SwiftUI template references directly (onboarding funnel, Settings upgrade row,
# the 429 daily-cap route). A spec may add placements but never drop these.
REQUIRED_PLACEMENTS = ["onboarding", "offer_after_onboarding", "settings", "daily_cap", "billing_issue"]
# Onboarding length bounds: the features gate wants >= 12 steps; the template skeleton has 26.
# Without the personalization quiz the funnel is a short run of intro screens.
ONBOARDING_SCREENS_RANGE = (14, 40)
ONBOARDING_SCREENS_RANGE_NO_QUIZ = (3, 40)
# Template steps each option removes (see OnboardingSteps.swift): 15 quiz/emotional steps, the account
# step, the hard paywall step, the offer step.
_ONBOARDING_DROPS = {"onboarding_quiz": 15, "sign_in_with_apple": 1, "hard_paywall": 1, "offer_paywall": 1}

DEFAULTS: dict[str, Any] = {
    "monetization": "subscription",  # subscription | credits (legacy credits model)
    "locales": {"app": APP_LOCALES, "store": STORE_LOCALES},
    "subscription": {
        "group": "Premium",
        "entitlement": "premium",
        "products": [
            {"key": "yearly", "suffix": "yearly", "period": "P1Y", "usd": 49.99, "level": 1,
             "intro": {"type": "free", "duration": "P3D"}, "offering": "default", "package": "$rc_annual"},
            {"key": "weekly", "suffix": "weekly", "period": "P1W", "usd": 7.99, "level": 2,
             "intro": {"type": "free", "duration": "P3D"}, "offering": "default", "package": "$rc_weekly"},
            {"key": "yearly_offer", "suffix": "yearly.offer", "period": "P1Y", "usd": 29.99, "level": 1,
             "intro": None, "offering": "offer", "package": "$rc_annual"},
        ],
        # App Store Billing Grace Period: subscribers keep access while Apple retries a
        # failed renewal. store_setup PATCHes the app's subscriptionGracePeriod. duration is the ASC
        # enum (THREE_DAYS | SIXTEEN_DAYS | TWENTY_EIGHT_DAYS); Apple gives weekly subscriptions 6 days
        # for the 16/28-day options. renewals: ALL_RENEWALS (incl. trial-to-paid) | PAID_TO_PAID_ONLY.
        "grace_period": {"enabled": True, "duration": "SIXTEEN_DAYS", "renewals": "ALL_RENEWALS", "sandbox": True},
        # Local price overrides on top of Apple's equalization (store/pricing.md §7).
        "price_overrides": {
            "EUR": {"yearly": 49.99, "weekly": 7.99, "yearly_offer": 29.99},
            "BRL": {"yearly": 199.90, "weekly": 34.90, "yearly_offer": 119.90},
            "TRY": {"yearly": 1249.99, "weekly": 199.99, "yearly_offer": 749.99},
        },
    },
    "placements": PLACEMENTS,
    "offer_placements": OFFER_PLACEMENTS,
    "usage": {
        "free_lifetime_scans": 1,
        "daily_caps": {"photo": 12, "text": 20},  # subscriber caps, reset at local midnight
        "abuse_limits": {"free_attempts": 5, "hard_attempts": 60},  # rolling 24 h
        "entitlement_grace_hours": 72,
    },
    # AI is an optional edge, not a requirement. enabled=False scaffolds a
    # non-AI subscription app: the analyze edge function is neither deployed nor gated, FAL_KEY is not
    # required, and the ai_proxy stage only verifies the non-AI backend deploy (usage-status,
    # delete-account, legal, rc-webhook) + the published legal pages. Default True (back-compat).
    "ai": {
        "enabled": True,
        "model": "google/gemini-3.6-flash",
        "fallback_model": "google/gemini-3.8-flash",
        "reasoning": "minimal",
        "timeout_ms": 25000,
    },
    "consent": {"health": False},
    # Optional Apple Health module (off by default). HealthKit quantity type identifiers without the
    # HKQuantityTypeIdentifier prefix. Requires consent.health: nothing is read or written before
    # consent. Scaffold keeps Sources/Health + the entitlement + usage strings only when enabled.
    "health": {
        "enabled": False,
        "read": ["activeEnergyBurned", "bodyMass"],
        "write": ["dietaryEnergyConsumed", "dietaryProtein", "dietaryCarbohydrates", "dietaryFatTotal", "bodyMass"],
    },
    # Extra App ID capability types for store_setup (IN_APP_PURCHASE is always on, APPLE_ID_AUTH follows options.sign_in_with_apple;
    # HEALTHKIT follows spec.health.enabled, PUSH_NOTIFICATIONS spec.push.enabled).
    "capabilities": [],
    "analytics": {"event_prefix": None},  # defaults to "<slug>_"
    # App-level App Store Connect settings store_setup keeps in sync (each of these blocked the first submission until set by hand).
    "store": {
        # ASC appCategories ids (e.g. HEALTH_AND_FITNESS, PHOTO_AND_VIDEO). None = not managed yet.
        "primary_category": None,
        "secondary_category": None,
        # DOES_NOT_USE_THIRD_PARTY_CONTENT | USES_THIRD_PARTY_CONTENT (e.g. Open Food Facts data).
        "content_rights": "DOES_NOT_USE_THIRD_PARTY_CONTENT",
        # Version copyright. None = "© <year> <display_name>": the brand, never a personal name.
        "copyright": None,
        # Territories where neither the app nor its subscriptions are available (generative AI
        # needs a licence in China). Subscription PRICES still cover them: ASC refuses the first
        # subscription submission with MISSING_PRICING_DATA for an unpriced territory.
        "excluded_territories": ["CHN"],
    },
    # App Store App Preview: Claude-authored from real simulator recordings.
    # locales None = every store locale; shared maps a locale to the locale whose video it reuses
    # (en-GB → en-US). Apple's 6.9" spec: 886x1920, <= 30 fps, 15–30 s; poster = autoplay first frame.
    "preview": {
        "locales": None,
        "shared": {"en-GB": "en-US", "es-MX": "es-ES"},
        "size": [886, 1920],
        "fps": 30,
        "min_s": 15,
        "max_s": 30,
        "poster": "00:00:05:00",
    },
    # App Store rating requests at success moments (mandatory; never inside onboarding). The app
    # asks through RatingPolicy only: at least `min_days_between` days apart, at most `max_per_year`
    # per trailing 365 days, never in a session with a failure. Triggers: the core action succeeded
    # `success_count` times on `distinct_days` different days, and each `milestones` value (active
    # days or a streak, the app decides) once, ever.
    "rating": {
        "success_count": 5,
        "distinct_days": 3,
        "milestones": [7, 30],
        "min_days_between": 60,
        "max_per_year": 3,
    },
    # Price anchor for the offer paywall: the offer's monthly price must stay below
    # one of these in every storefront (a burger works; a coffee failed).
    "offer_anchor": {"item": "burger", "label_key": "offer.anchor.burger"},
    "design": {
        "tokens": {
            "background": "#FFF8F0", "ink": "#1F1A17", "muted": "#6B5F55", "line": "#EFE4D8",
            "accent": "#FF7A45", "accent_text": "#C2410C", "selected_fill": "#FFEDE3",
            "cta": "#F0612B", "cta_disabled": "#F4C3AF", "success": "#2FBF8F",
        },
        "fonts": {"display": "Bricolage Grotesque", "body": "Figtree"},
        "onboarding_screens": 26,
        "mascot": None,  # {"name": ..., "species": ..., "states": [...]}
    },
}

MASCOT_STATES = ["idle", "wave", "cheer", "think", "love", "snap", "trophy", "sleep"]

_ISO_DURATION = re.compile(r"^P\d+[DWMY]$")

# Intro-offer lengths App Store Connect models (SubscriptionOfferDuration); nothing else can be created.
INTRO_DURATIONS = ("P3D", "P1W", "P2W", "P1M", "P2M", "P3M", "P6M", "P1Y")
# Day-based spellings of the same lengths — older run options wrote these, so they stay readable.
INTRO_DURATION_ALIASES = {"P7D": "P1W", "P14D": "P2W", "P30D": "P1M"}
# Free-trial lengths the run options offer, in days → the duration App Store Connect accepts.
TRIAL_DAYS = {3: "P3D", 7: "P1W", 14: "P2W", 30: "P1M"}


def intro_duration(iso: str) -> str:
    """Canonical intro-offer duration: P7D → P1W, P14D → P2W, P30D → P1M; anything else unchanged."""
    return INTRO_DURATION_ALIASES.get(iso, iso)


# ASC SubscriptionGracePeriodDuration / renewalType values (Apple API reference, checked 2026-09-24).
HEALTH_TYPES = {
    "activeEnergyBurned", "basalEnergyBurned", "bodyMass", "height", "stepCount", "bodyFatPercentage",
    "dietaryEnergyConsumed", "dietaryProtein", "dietaryCarbohydrates", "dietaryFatTotal", "dietaryWater",
    "dietarySugar", "dietaryFiber",
}
APP_CATEGORIES = {
    "BOOKS", "BUSINESS", "DEVELOPER_TOOLS", "EDUCATION", "ENTERTAINMENT", "FINANCE", "FOOD_AND_DRINK", "GAMES",
    "GRAPHICS_AND_DESIGN", "HEALTH_AND_FITNESS", "LIFESTYLE", "MAGAZINES_AND_NEWSPAPERS", "MEDICAL", "MUSIC",
    "NAVIGATION", "NEWS", "PHOTO_AND_VIDEO", "PRODUCTIVITY", "REFERENCE", "SHOPPING", "SOCIAL_NETWORKING",
    "SPORTS", "STICKERS", "TRAVEL", "UTILITIES", "WEATHER",
}
CONTENT_RIGHTS = ("DOES_NOT_USE_THIRD_PARTY_CONTENT", "USES_THIRD_PARTY_CONTENT")
GRACE_DURATIONS = ("THREE_DAYS", "SIXTEEN_DAYS", "TWENTY_EIGHT_DAYS")
GRACE_RENEWALS = ("ALL_RENEWALS", "PAID_TO_PAID_ONLY")


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else v
        return out
    return copy.deepcopy(over) if over is not None else copy.deepcopy(base)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower()) or "app"


def build(name: str, bundle_id: str, **overrides: Any) -> dict[str, Any]:
    """Return a full spec for a new app: defaults + identity + overrides."""
    spec = copy.deepcopy(_merge(DEFAULTS, overrides))  # never alias DEFAULTS
    spec["name"] = name
    spec["display_name"] = overrides.get("display_name") or name
    spec["bundle_id"] = bundle_id
    spec["sku"] = overrides.get("sku") or bundle_id.replace(".", "")
    if not spec["analytics"].get("event_prefix"):
        spec["analytics"]["event_prefix"] = f"{slug(name)}_"
    return apply_option_effects(spec)


def option(spec: dict[str, Any] | None, name: str) -> bool:
    """A run option from spec `options` (missing = on: every spec written before the option is unchanged)."""
    return ((spec or {}).get("options") or {}).get(name) is not False


def offer_on(spec: dict[str, Any] | None) -> bool:
    """The discounted offer paywall exists: it needs the hard paywall it follows."""
    return option(spec, "offer_paywall") and option(spec, "hard_paywall")


def required_placements(spec: dict[str, Any] | None) -> list[str]:
    return [p for p in REQUIRED_PLACEMENTS if offer_on(spec) or p != "offer_after_onboarding"]


def onboarding_screens_range(spec: dict[str, Any] | None) -> tuple[int, int]:
    return ONBOARDING_SCREENS_RANGE if option(spec, "onboarding_quiz") else ONBOARDING_SCREENS_RANGE_NO_QUIZ


def natural_onboarding_screens(spec: dict[str, Any] | None) -> int:
    """The template's step count (health off) minus the steps the options remove."""
    n = DEFAULTS["design"]["onboarding_screens"]
    flags = {"hard_paywall": option(spec, "hard_paywall"), "offer_paywall": offer_on(spec),
             "onboarding_quiz": option(spec, "onboarding_quiz"), "sign_in_with_apple": option(spec, "sign_in_with_apple")}
    return n - sum(k for opt, k in _ONBOARDING_DROPS.items() if not flags[opt])


def apply_option_effects(spec: dict[str, Any]) -> dict[str, Any]:
    """Make the spec agree with its `options`, in place: without the offer paywall there are no offer
    products, offer placements or offer price overrides (and they come back when it is turned on again);
    the onboarding length follows the funnel unless the spec set its own."""
    sub = spec.get("subscription")
    if isinstance(sub, dict) and isinstance(sub.get("products"), list):
        prods = sub["products"]
        offer_defaults = [p for p in DEFAULTS["subscription"]["products"] if p["offering"] == "offer"]
        if offer_on(spec):
            have = {p.get("key") for p in prods}
            back = [copy.deepcopy(p) for p in offer_defaults if p["key"] not in have]
            if back and not any(p.get("offering") == "offer" for p in prods):
                prods.extend(back)
                for cur, table in DEFAULTS["subscription"]["price_overrides"].items():
                    for p in back:
                        if p["key"] in table:
                            sub.setdefault("price_overrides", {}).setdefault(cur, {}).setdefault(p["key"], table[p["key"]])
                spec["placements"] = list(spec.get("placements", [])) + [
                    x for x in OFFER_PLACEMENTS if x not in spec.get("placements", [])]
                spec["offer_placements"] = list(OFFER_PLACEMENTS)
        else:
            gone = {p.get("key") for p in prods if p.get("offering") == "offer"}
            sub["products"] = [p for p in prods if p.get("offering") != "offer"]
            for cur in list((sub.get("price_overrides") or {})):
                table = {k: v for k, v in sub["price_overrides"][cur].items() if k not in gone}
                sub["price_overrides"][cur] = table
            drop = set(spec.get("offer_placements") or []) | {"offer_after_onboarding"}
            spec["placements"] = [x for x in spec.get("placements", []) if x not in drop]
            spec["offer_placements"] = []
    design = spec.get("design")
    if isinstance(design, dict):
        shaped = [o for o in _ONBOARDING_DROPS if not (offer_on(spec) if o == "offer_paywall" else option(spec, o))]
        # a length the funnel produced itself (any option mix) follows the funnel; a custom one stays
        auto = {DEFAULTS["design"]["onboarding_screens"] - sum(c) for c in itertools.product(*[(0, k) for k in _ONBOARDING_DROPS.values()])}
        if shaped and (not option(spec, "onboarding_quiz") or design.get("onboarding_screens") in auto):
            design["onboarding_screens"] = natural_onboarding_screens(spec)
    return spec


def ai_enabled(spec: dict[str, Any] | None) -> bool:
    """spec.ai.enabled (missing = True: every spec written before the flag existed is an AI app)."""
    if not spec:
        return True
    return bool((spec.get("ai") or {}).get("enabled", True))


def product_id(spec: dict[str, Any], key: str) -> str:
    for p in spec["subscription"]["products"]:
        if p["key"] == key:
            return f"{spec['bundle_id']}.{p['suffix']}"
    raise KeyError(key)


def products(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Products with their resolved store ids."""
    return [{**p, "id": f"{spec['bundle_id']}.{p['suffix']}"} for p in spec["subscription"]["products"]]


def validate(spec: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty means the spec is usable."""
    errs: list[str] = []
    for k in ("name", "bundle_id", "sku"):
        if not spec.get(k):
            errs.append(f"missing {k}")
    if spec.get("monetization") not in ("subscription", "credits"):
        errs.append("monetization must be subscription|credits")
    locs = spec.get("locales", {})
    if not locs.get("app") or locs["app"][0] != "en":
        errs.append("locales.app must start with the en fallback")
    sub = spec.get("subscription", {})
    prods = sub.get("products", [])
    keys = [p.get("key") for p in prods]
    if len(set(keys)) != len(keys):
        errs.append("duplicate product keys")
    for p in prods:
        if not _ISO_DURATION.match(p.get("period", "")):
            errs.append(f"{p.get('key')}: bad period")
        if not isinstance(p.get("usd"), (int, float)) or p["usd"] <= 0:
            errs.append(f"{p.get('key')}: bad usd price")
        intro = p.get("intro")
        if intro and intro_duration(intro.get("duration", "")) not in INTRO_DURATIONS:
            errs.append(f"{p.get('key')}: intro duration must be one of {list(INTRO_DURATIONS)} "
                        f"(or an alias: {list(INTRO_DURATION_ALIASES)})")
        if p.get("offering") == "offer" and intro:
            errs.append(f"{p.get('key')}: offer products never carry an intro offer")
    for cur, table in sub.get("price_overrides", {}).items():
        for k in table:
            if k not in keys:
                errs.append(f"price_overrides.{cur}: unknown product {k}")
    grace = sub.get("grace_period")
    if grace is not None:
        if not isinstance(grace, dict):
            errs.append("subscription.grace_period must be an object")
        elif grace.get("enabled"):
            if grace.get("duration") not in GRACE_DURATIONS:
                errs.append(f"subscription.grace_period.duration must be one of {list(GRACE_DURATIONS)}")
            if not isinstance(grace.get("sandbox", False), bool):
                errs.append("subscription.grace_period.sandbox must be a boolean")
            if grace.get("renewals") not in GRACE_RENEWALS:
                errs.append(f"subscription.grace_period.renewals must be one of {list(GRACE_RENEWALS)}")
    health = spec.get("health") or {}
    if health.get("enabled"):
        bad = [t for t in list(health.get("read", [])) + list(health.get("write", [])) if t not in HEALTH_TYPES]
        if bad:
            errs.append(f"health types not supported: {bad} (allowed: {sorted(HEALTH_TYPES)})")
        if not spec.get("consent", {}).get("health"):
            errs.append("health.enabled requires consent.health (no Health access before consent)")
    caps = spec.get("capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(c, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", c) for c in caps):
        errs.append("capabilities must be a list of ASC capability types, e.g. ASSOCIATED_DOMAINS")
    ai_block = spec.get("ai") or {}
    if "enabled" in ai_block and not isinstance(ai_block["enabled"], bool):
        errs.append("ai.enabled must be a boolean")
    if not ai_enabled(spec) and spec.get("monetization") == "credits":
        errs.append("ai.enabled=false needs monetization subscription (credits mode is the AI proxy)")
    usage = spec.get("usage", {})
    if usage.get("free_lifetime_scans") not in (0, 1):
        errs.append("usage.free_lifetime_scans must be 0 or 1 (the database enforces one lifetime free analysis)")
    if not set(usage.get("daily_caps", {})) <= {"photo", "text"}:
        errs.append("usage.daily_caps keys must be photo and/or text (the analyze modes)")
    if not set(spec.get("offer_placements", [])) <= set(spec.get("placements", [])):
        errs.append("offer_placements must be a subset of placements")
    missing_pl = [p for p in required_placements(spec) if p not in spec.get("placements", [])]
    if missing_pl:
        errs.append(f"placements must include {missing_pl} (the template uses them)")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", p) for p in spec.get("placements", [])):
        errs.append("placements must be snake_case identifiers")
    screens = spec.get("design", {}).get("onboarding_screens")
    lo, hi = onboarding_screens_range(spec)
    if not isinstance(screens, int) or not lo <= screens <= hi:
        errs.append(f"design.onboarding_screens must be an integer in {lo}..{hi}")
    offerings = {p.get("offering") for p in prods}
    if option(spec, "hard_paywall") is False and (spec.get("options") or {}).get("offer_paywall") is True:
        errs.append("options.offer_paywall needs options.hard_paywall (the offer follows the hard paywall)")
    if offer_on(spec):
        if spec.get("monetization") == "subscription" and not {"default", "offer"} <= offerings:
            errs.append("subscription mode needs products in both the default and offer offerings")
    else:
        if spec.get("monetization") == "subscription" and "default" not in offerings:
            errs.append("subscription mode needs products in the default offering")
        if "offer" in offerings:
            errs.append("offer paywall is off (options): the spec must have no products in the offer offering")
        if spec.get("offer_placements"):
            errs.append("offer paywall is off (options): offer_placements must be empty")
    mascot = spec.get("design", {}).get("mascot")
    if mascot and not set(mascot.get("states", [])) <= set(MASCOT_STATES):
        errs.append(f"mascot states must come from {MASCOT_STATES}")
    errs += _validate_store(spec.get("store") or {})
    errs += _validate_preview(preview(spec), spec.get("locales", {}).get("store") or [])
    errs += _validate_rating(rating(spec))
    return errs


def _validate_store(store: dict[str, Any]) -> list[str]:
    errs = []
    for k in ("primary_category", "secondary_category"):
        v = store.get(k)
        if v is not None and v not in APP_CATEGORIES:
            errs.append(f"store.{k} must be an ASC category id ({', '.join(sorted(APP_CATEGORIES)[:4])}, …)")
    if store.get("primary_category") and store.get("primary_category") == store.get("secondary_category"):
        errs.append("store.secondary_category must differ from the primary one")
    if store.get("content_rights", CONTENT_RIGHTS[0]) not in CONTENT_RIGHTS:
        errs.append(f"store.content_rights must be one of {list(CONTENT_RIGHTS)}")
    excl = store.get("excluded_territories", [])
    if not isinstance(excl, list) or not all(isinstance(t, str) and re.fullmatch(r"[A-Z]{3}", t) for t in excl):
        errs.append("store.excluded_territories must be ISO 3166 alpha-3 codes, e.g. CHN")
    return errs


def _validate_rating(r: dict[str, Any]) -> list[str]:
    errs = []
    ints = {k: r.get(k) for k in ("success_count", "distinct_days", "min_days_between", "max_per_year")}
    if not all(isinstance(v, int) and v >= 1 for v in ints.values()):
        errs.append("rating.success_count / distinct_days / min_days_between / max_per_year must be positive integers")
    elif r["min_days_between"] < 60:
        errs.append("rating.min_days_between must be at least 60 (RatingPolicy; Apple shows 3 prompts a year at most)")
    elif r["max_per_year"] > 3:
        errs.append("rating.max_per_year must be at most 3 (Apple's own yearly limit)")
    ms = r.get("milestones")
    if not isinstance(ms, list) or not all(isinstance(m, int) and m >= 2 for m in ms) or len(set(ms)) != len(ms):
        errs.append("rating.milestones must be distinct integers >= 2 (active days or a streak)")
    return errs


def _validate_preview(p: dict[str, Any], store_locales: list[str]) -> list[str]:
    errs = []
    locs = p.get("locales")
    if locs is not None and (not isinstance(locs, list) or not set(locs) <= set(store_locales)):
        errs.append("preview.locales must be null or a subset of locales.store")
    targets = set(locs if locs is not None else store_locales)
    shared = p.get("shared") or {}
    for k, v in shared.items():
        if k == v:
            continue   # a self-map means "its own video" (overrides a default share)
        if k in targets and v not in targets:
            errs.append(f"preview.shared.{k} → {v}: the source locale must get its own preview")
        if shared.get(v, v) != v:
            errs.append(f"preview.shared.{k} → {v}: no chains (point at the locale that owns the video)")
    if p.get("size") != [886, 1920]:
        errs.append("preview.size must be [886, 1920] (ASC iPhone 6.9\" preview)")
    if not isinstance(p.get("fps"), int) or not 1 <= p["fps"] <= 30:
        errs.append("preview.fps must be at most 30")
    if not (isinstance(p.get("min_s"), (int, float)) and isinstance(p.get("max_s"), (int, float))
            and 15 <= p["min_s"] <= p["max_s"] <= 30):
        errs.append("preview.min_s / max_s must lie within 15–30 s")
    if not re.fullmatch(r"\d\d:\d\d:\d\d:\d\d", str(p.get("poster", ""))):
        errs.append("preview.poster must be a time code HH:MM:SS:FF")
    return errs


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec's App Preview rules over the defaults (older specs have no `preview` block)."""
    return {**DEFAULTS["preview"], **(spec.get("preview") or {})}


def rating(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec's rating rules over the defaults (older specs have no `rating` block)."""
    return {**DEFAULTS["rating"], **(spec.get("rating") or {})}


def store(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec's App Store settings over the defaults (older specs have no `store` block)."""
    return {**DEFAULTS["store"], **(spec.get("store") or {})}


def path(app_dir: str | Path) -> Path:
    return Path(app_dir).expanduser() / SPEC_FILE


def load(app_dir: str | Path) -> dict[str, Any]:
    return json.loads(path(app_dir).read_text(encoding="utf-8"))


def save(app_dir: str | Path, spec: dict[str, Any]) -> Path:
    errs = validate(spec)
    if errs:
        raise ValueError("; ".join(errs))
    p = path(app_dir)
    p.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p
