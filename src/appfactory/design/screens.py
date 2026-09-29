"""`design/screens.json` — one entry per screen, designed individually.

The design stage writes this file per app (starting from `skeleton()`), and every
generator, the design gate and `onboarding-plan.md` read it. Shape:

    {"version": 1,
     "onboarding": [{"id", "kind", "section", "title", "subtitle", "key", "options",
                     "select", "layout", "picker", "motion", "mascot", "data", ...}, ...],
     "main":       [{"id", "kind", "title", "tab", "motion", ...}, ...]}

Founder rules enforced here: every screen is its own spec (no duplicates / palette-swap
copies), the onboarding keeps the funnel's structure minus its dark patterns (no fake
reviews or stats, no spin wheel, no notification prompt, and never a rating prompt IN
onboarding — the app asks for a rating at its success moments instead), and every
weight picker offers kg AND lb. The look is not decided here: it comes from the design
brief (design/research/brief.json) and is authored in Claude Design.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .. import spec as spec_mod

SCREENS_REL = "design/screens.json"

ONBOARDING_KINDS = {
    "welcome", "question", "picker", "info", "emotional", "trust", "permission",
    "preferences", "loading", "plan_ready", "account", "paywall", "offer",
}
MAIN_KINDS = {
    "home", "empty", "capture", "analyzing", "result", "text_input", "progress",
    "history", "settings", "limit_sheet", "list",
}
PICKER_TYPES = {"wheel", "birthdate", "height_weight", "weight", "ruler", "slider"}
INFO_VISUALS = {"line_compare", "bars_compare", "growth_curve"}
MASCOT_STATES = ["idle", "wave", "cheer", "think", "love", "snap", "trophy", "sleep"]
REQUIRED_MAIN_KINDS = {"home", "settings"}
MIN_MAIN = 4

# Dark patterns from the Cal AI funnel that the factory never ships.
BANNED_KINDS = {
    "rating": "no rating prompt/slide in onboarding (ask for a review only after a success moment)",
    "rating_prompt": "no rating prompt in onboarding",
    "review_prompt": "no rating prompt in onboarding",
    "notification": "no notification permission prompt in onboarding",
    "notification_prompt": "no notification permission prompt in onboarding",
    "notifications": "no notification permission prompt in onboarding",
    "spin_wheel": "no spin-the-wheel discount",
    "wheel_of_fortune": "no spin-the-wheel discount",
    "fake_reviews": "no fake reviews",
    "testimonials": "no invented testimonials",
    "social_proof": "no invented user counts or stats",
}
_BANNED_COPY = [
    (re.compile(r"\b\d[\d,.]*\s*[kKmM]?\+?\s*(users|people|reviews|ratings|downloads|customers|members|installs)\b", re.I),
     "invented user/review counts"),
    (re.compile(r"★|\b[1-5][.,]\d\s*(stars?|rating)\b", re.I), "star ratings / review scores"),
    (re.compile(r"\bspin\b|wheel of fortune", re.I), "spin-wheel discount"),
    (re.compile(r"\brate us\b|leave (us )?a review|give us a rating", re.I), "rating prompt"),
    (re.compile(r"\b(turn on|enable|allow)\b.{0,20}\bnotifications?\b", re.I), "notification prompt"),
]
BANNED_COPY = _BANNED_COPY  # also applied to the authored boards (design.authored_problems)
_STAT = re.compile(r"\d+\s*(%|x\b|times\b)", re.I)  # "80% of users…", "2x faster"
_STAT_EXEMPT_KINDS = {"paywall", "offer", "picker", "loading"}
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_NON_SPEC_FIELDS = {"id", "key", "section", "file"}

WEIGHT_UNITS = {"kg", "lb"}


def path(app_dir: str | Path) -> Path:
    return Path(app_dir).expanduser() / SCREENS_REL


def load(app_dir: str | Path) -> dict[str, Any]:
    return json.loads(path(app_dir).read_text(encoding="utf-8"))


def save(app_dir: str | Path, doc: dict[str, Any]) -> Path:
    p = path(app_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def pascal(screen_id: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in screen_id.split("_") if part)


def board_file(prefix: str, index: int, screen_id: str) -> str:
    """S01-Welcome.dc.html / A03-Analyzing.dc.html — the canvas board file name."""
    return f"{prefix}{index:02d}-{pascal(screen_id)}.dc.html"


def files(doc: dict[str, Any]) -> dict[str, str]:
    out = {s["id"]: board_file("S", i, s["id"]) for i, s in enumerate(doc.get("onboarding", []), 1)}
    out.update({s["id"]: board_file("A", i, s["id"]) for i, s in enumerate(doc.get("main", []), 1)})
    return out


def is_weight_picker(picker: dict[str, Any]) -> bool:
    return picker.get("type") in ("weight", "height_weight") or picker.get("measure") == "weight"


def _copy_strings(scr: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("id", "kind", "icon", "color", "motion", "mascot", "type", "measure", "visual", "select", "layout"):
                    walk(x)

    walk({k: v for k, v in scr.items() if k not in _NON_SPEC_FIELDS})
    return out


def signature(scr: dict[str, Any]) -> str:
    """Canonical content of a screen without its identity — equal signatures = a copy."""
    return json.dumps({k: v for k, v in scr.items() if k not in _NON_SPEC_FIELDS}, sort_keys=True, ensure_ascii=False)


def _check_screen(scr: dict[str, Any], where: str, allowed: set[str]) -> list[str]:
    errs: list[str] = []
    sid = scr.get("id", "")
    tag = f"{where}.{sid or '?'}"
    if not isinstance(sid, str) or not _ID.match(sid):
        errs.append(f"{tag}: id must match {_ID.pattern}")
    kind = scr.get("kind")
    if kind in BANNED_KINDS:
        errs.append(f"{tag}: banned kind '{kind}' — {BANNED_KINDS[kind]}")
        return errs
    if kind not in allowed:
        errs.append(f"{tag}: unknown kind '{kind}' (allowed: {', '.join(sorted(allowed))})")
        return errs
    if not str(scr.get("title", "")).strip():
        errs.append(f"{tag}: title is required")
    if not str(scr.get("motion", "")).strip():
        errs.append(f"{tag}: motion moment is required (every screen has one)")
    if scr.get("mascot") and scr["mascot"] not in MASCOT_STATES:
        errs.append(f"{tag}: mascot state must be one of {MASCOT_STATES}")
    for s in _copy_strings(scr):
        for pat, why in _BANNED_COPY:
            if why == "rating prompt" and where != "onboarding":
                continue  # rating prompts belong at success moments in the app, never in onboarding
            if pat.search(s):
                errs.append(f"{tag}: copy contains {why}: {s!r}")
        if kind not in _STAT_EXEMPT_KINDS and _STAT.search(s):
            errs.append(f"{tag}: copy contains an unverified statistic: {s!r}")
    if kind == "question":
        opts = scr.get("options") or []
        if len(opts) < 2 or not all(isinstance(o, dict) and str(o.get("label", "")).strip() for o in opts):
            errs.append(f"{tag}: question needs >= 2 options with a label")
        if scr.get("select", "single") not in ("single", "multi"):
            errs.append(f"{tag}: select must be single|multi")
        if scr.get("layout", "list") not in ("list", "compact", "grid"):
            errs.append(f"{tag}: layout must be list|compact|grid")
    if kind == "picker":
        pk = scr.get("picker") or {}
        if pk.get("type") not in PICKER_TYPES:
            errs.append(f"{tag}: picker.type must be one of {sorted(PICKER_TYPES)}")
        elif is_weight_picker(pk) and "units" in pk and not WEIGHT_UNITS <= set(pk["units"]):
            errs.append(f"{tag}: weight pickers always offer a kg/lb toggle (units must include kg and lb)")
        if pk.get("type") == "wheel" and not (pk.get("values") or ("from" in pk and "to" in pk)):
            errs.append(f"{tag}: wheel picker needs values or from/to")
    if kind == "info" and scr.get("visual") not in INFO_VISUALS:
        errs.append(f"{tag}: info.visual must be one of {sorted(INFO_VISUALS)}")
    return errs


def validate(doc: Any, min_onboarding: int = 0, spec: dict[str, Any] | None = None) -> list[str]:
    """Problems with a screens doc; empty = ready to generate. `spec` (run options) decides which
    funnel screens are expected: hard paywall, offer paywall, account."""
    if not isinstance(doc, dict):
        return ["screens.json must be an object with onboarding[] and main[]"]
    onb, main = doc.get("onboarding"), doc.get("main")
    if not isinstance(onb, list) or not isinstance(main, list):
        return ["screens.json needs onboarding[] and main[] lists"]
    errs: list[str] = []
    for s in onb:
        errs += _check_screen(s, "onboarding", ONBOARDING_KINDS)
    for s in main:
        errs += _check_screen(s, "main", MAIN_KINDS)
    everything = onb + main
    ids = [s.get("id") for s in everything]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1 and i})
    if dup_ids:
        errs.append(f"duplicate screen ids: {', '.join(dup_ids)}")
    seen: dict[str, str] = {}
    for s in everything:
        sig = signature(s)
        if sig in seen:
            errs.append(f"screen '{s.get('id')}' duplicates '{seen[sig]}' — every screen is designed individually")
        else:
            seen[sig] = s.get("id", "?")
    titles = [str(s.get("title", "")).strip().lower() for s in everything]
    dup_titles = sorted({t for t in titles if t and titles.count(t) > 1})
    if dup_titles:
        errs.append(f"duplicate screen titles: {', '.join(dup_titles)}")
    if len(onb) < min_onboarding:
        errs.append(f"onboarding has {len(onb)} screens < {min_onboarding} (spec.design.onboarding_screens)")
    kinds = [s.get("kind") for s in onb]
    errs += funnel_problems(kinds, spec)
    main_kinds = {s.get("kind") for s in main}
    missing = sorted(REQUIRED_MAIN_KINDS - main_kinds)
    if missing:
        errs.append(f"main app screens missing: {', '.join(missing)}")
    if len(main) < MIN_MAIN:
        errs.append(f"main app has {len(main)} screens < {MIN_MAIN}")
    return errs


def funnel_problems(kinds: list[str], spec: dict[str, Any] | None = None) -> list[str]:
    """The paywall part of an onboarding kind list, against the hard_paywall / offer_paywall options."""
    hard, offer = spec_mod.option(spec, "hard_paywall"), spec_mod.offer_on(spec)
    if hard and offer:
        if kinds.count("paywall") != 1 or kinds.count("offer") != 1:
            return ["onboarding needs exactly one paywall and one offer screen (hard paywall → offer paywall)"]
        if kinds.index("offer") < kinds.index("paywall"):
            return ["the offer paywall must come after the hard paywall"]
        return []
    if hard:
        if kinds.count("paywall") != 1 or "offer" in kinds:
            return ["onboarding needs exactly one paywall screen and no offer screen (the offer paywall is off)"]
        return []
    if "paywall" in kinds or "offer" in kinds:
        return ["onboarding has no paywall or offer screen (the hard paywall is off: it opens from placements only)"]
    return []


# Skeleton screens the run options remove: the quiz (questions, pickers, preferences and the two info beats
# about the user's goal), the account step, the paywalls.
_QUIZ_KINDS = {"question", "picker", "preferences"}
_QUIZ_IDS = {"realistic", "potential"}


def _kept_by_options(s: dict[str, Any], spec: dict[str, Any]) -> bool:
    kind = s.get("kind")
    if kind in _QUIZ_KINDS or s.get("id") in _QUIZ_IDS:
        return spec_mod.option(spec, "onboarding_quiz")
    if kind == "account":
        return spec_mod.option(spec, "sign_in_with_apple")
    if kind == "paywall":
        return spec_mod.option(spec, "hard_paywall")
    if kind == "offer":
        return spec_mod.offer_on(spec)
    return True


# ---------------------------------------------------------------- skeleton

def _q(id_, section, title, options, motion, sub=None, select="single", layout="list", data="", default=None, **kw):
    d = {"id": id_, "kind": "question", "section": section, "title": title, "subtitle": sub,
         "options": options, "select": select, "layout": layout, "motion": motion, "data": data}
    if default is not None:
        d["default"] = default
    d.update(kw)
    return {k: v for k, v in d.items() if v is not None}


def _o(label, icon=None, sub=None, color=None):
    return {k: v for k, v in {"label": label, "icon": icon, "sub": sub, "color": color}.items() if v is not None}


_S1, _S2, _S3, _S4, _S5 = ("1 · Welcome & basics", "2 · You & your goal", "3 · Personalization",
                           "4 · Setup & your plan", "5 · Account & paywall")

_ONBOARDING = [
    {"id": "welcome", "kind": "welcome", "section": _S1, "title": "Your goal, made effortless.",
     "subtitle": "Snap, ask or type. {app} does the rest.", "cta": "Get started",
     "chips": ["Instant AI result", "Personal plan", "Made for you"], "mascot": "wave",
     "motion": "Scan line sweeps the hero, feature chips pop in, mascot waves"},
    _q("about", _S1, "Which describes you best?",
       [_o("Beginner", "sprout"), _o("Getting there", "target"), _o("Experienced", "bolt")],
       "Selected card fills, check bounces", sub="This helps us calibrate your plan.", data="Plan difficulty and tips tone"),
    _q("frequency", _S1, "How often do you want to use {app}?",
       [_o("A few times a week", "w1", "Now and then"), _o("Once a day", "w2", "A daily habit"),
        _o("Several times a day", "w3", "Whenever I need it")],
       "Dots light up in sequence", sub="We use this to pace your plan.", data="Daily goal and usage expectations"),
    _q("source", _S1, "Where did you hear about us?",
       [_o("TikTok", "music"), _o("Instagram", "camera"), _o("YouTube", "play"), _o("App Store", "store"),
        _o("Google", "search"), _o("Friend or family", "users"), _o("Other", "dots")],
       "Staggered list entrance", layout="compact", data="Attribution analytics (onboarding_answer)"),
    {"id": "long_term", "kind": "info", "visual": "line_compare", "section": _S1,
     "title": "{app} creates long-term results", "chart_label": "Your progress",
     "series": ["With {app}", "On your own"], "footnote": "Quick fixes fade. Small daily wins are what stick.",
     "mascot": "cheer", "motion": "Both lines draw in, mascot pops on the end point"},
    {"id": "birthdate", "kind": "picker", "section": _S2, "title": "When were you born?",
     "subtitle": "Your age helps us tune your plan.", "picker": {"type": "birthdate"},
     "motion": "Wheel detents with haptic, age chip pops", "data": "Age-based plan defaults"},
    _q("goal", _S2, "What is your main goal?",
       [_o("Look and feel better", "smile"), _o("Build a habit", "repeat"), _o("Learn and improve", "bulb")],
       "Card fill", sub="This shapes the plan we build for you.", default=[0], data="Plan focus and paywall headline"),
    {"id": "target", "kind": "picker", "section": _S2, "title": "How many minutes a day can you give?",
     "picker": {"type": "ruler", "min": 5, "max": 60, "step": 1, "default": 15, "unit": "min"},
     "motion": "Ruler ticks snap, number rolls", "data": "Daily goal size"},
    {"id": "realistic", "kind": "emotional", "section": _S2,
     "title": "**15 minutes a day** is a realistic target. You've got this!",
     "subtitle": "Based on your answers, this is a pace you can keep.", "mascot": "cheer",
     "motion": "Pulse rings expand, mascot cheers"},
    {"id": "pace", "kind": "picker", "section": _S2, "title": "How fast do you want to see results?",
     "picker": {"type": "slider", "min": 1, "max": 3, "step": 1, "default": 2, "unit": "",
                "zones": [{"label": "Steady", "msg": "Slow and steady builds habits that last."},
                          {"label": "Balanced", "msg": "The most balanced pace for most people."},
                          {"label": "Fast", "msg": "A fast pace. It asks more of you every day."}],
                "recommended": 1},
     "motion": "Active zone icon bounces, message card recolors", "data": "Plan intensity and target date"},
    {"id": "easier", "kind": "info", "visual": "bars_compare", "section": _S2,
     "title": "Reach your goal easier with {app}", "series": ["On your own", "With {app}"],
     "footnote": "{app} keeps it simple and keeps you on track.", "mascot": "cheer",
     "motion": "Bars grow from the baseline, mascot pops on top"},
    _q("obstacles", _S3, "What's holding you back?",
       [_o("Lack of consistency", "repeat"), _o("Busy schedule", "clock"), _o("Not sure where to start", "bulb"),
        _o("Lack of support", "users"), _o("Losing motivation", "bolt")],
       "Chip toggle with check pop", select="multi", layout="compact", data="Home tips and paywall benefit order"),
    _q("style", _S3, "Which style fits you?",
       [_o("Simple", "leaf", "Just the essentials"), _o("Detailed", "chart", "All the numbers"),
        _o("Playful", "smile", "Fun and light"), _o("Guided", "target", "Tell me what to do")],
       "Card fill", default=[0], data="Result detail level and AI prompt context"),
    _q("interests", _S3, "What are you most interested in?",
       [_o("Quick wins", color="#E4572E"), _o("Deep insights", color="#2F80ED"), _o("Daily routine", color="#F5B83D"),
        _o("Inspiration", color="#2FBF8F"), _o("Tracking", color="#C2410C"), _o("Learning", color="#9B7BFF")],
       "Chips pop in a grid", sub="{app} tailors your results to these.", select="multi", layout="grid", default=[0, 1],
       data="AI prompt context and home suggestions"),
    _q("accomplish", _S3, "What would you like to accomplish?",
       [_o("Feel more confident", "smile"), _o("Save time", "clock"), _o("Stay motivated and consistent", "target"),
        _o("Make better choices", "heart")],
       "Chip toggle", select="multi", data="Paywall benefit ordering"),
    {"id": "potential", "kind": "info", "visual": "growth_curve", "section": _S3,
     "title": "You have great potential to crush your goal", "chart_label": "Your progress",
     "milestones": ["Today", "3 days", "7 days", "30 days"],
     "footnote": "Results can take a few days to show. After the first week, momentum builds.",
     "mascot": "trophy", "motion": "Curve draws, milestone dots pop, trophy mascot bobs"},
    {"id": "trust", "kind": "trust", "section": _S3, "title": "Thank you for trusting us",
     "subtitle": "Now let's personalize {app} for you.",
     "privacy": "Your answers and photos are only used to run {app}. We never sell your data.",
     "mascot": "love", "motion": "Hearts float up around the mascot"},
    {"id": "permission", "kind": "permission", "section": _S4, "title": "Allow camera access",
     "subtitle": "{app} needs the camera to analyze what you capture.", "permission": {"icon": "camera2"},
     "rows": ["Capture in one tap", "Private by default", "Change it anytime in Settings"], "optional": True,
     "motion": "Sync dots pulse between the two tiles"},
    {"id": "preferences", "kind": "preferences", "section": _S4, "title": "A couple of preferences",
     "subtitle": "You can change these anytime in Settings.",
     "toggles": [{"title": "Show tips on results?", "sub": "Short suggestions under every result.", "default": True},
                 {"title": "Save results to history?", "sub": "Keep every result to compare later.", "default": True}],
     "motion": "Toggle springs", "data": "Result and history behavior"},
    {"id": "routine_time", "kind": "picker", "section": _S4, "title": "When do you usually have a moment?",
     "picker": {"type": "wheel", "values": ["Early morning", "Morning", "Midday", "Afternoon", "Evening", "Night"],
                "default": 1},
     "motion": "Wheel detents", "data": "Personalized home greeting (no push prompt)"},
    {"id": "meet_mascot", "kind": "emotional", "section": _S4, "title": "Meet {mascot}, your guide",
     "subtitle": "{mascot} cheers every step and keeps things light.", "mascot": "wave",
     "motion": "Mascot waves, pulse rings behind"},
    {"id": "loading", "kind": "loading", "section": _S4, "title": "We're setting everything up for you",
     "items": ["Your profile", "Your daily goal", "Your plan", "Your first tips", "Your progress view"],
     "statuses": ["Reading your answers…", "Building your plan…", "Tuning your goal…", "Finalizing…", "Your plan is ready"],
     "mascot": "think", "cta": "See my plan", "motion": "Percent counts to 100, checks tick in"},
    {"id": "plan_ready", "kind": "plan_ready", "section": _S4, "title": "Congratulations, your custom plan is ready!",
     "result_label": "Your goal:", "result": "15 min a day, balanced pace",
     "metrics": [{"label": "Daily goal", "value": "15", "unit": "min", "frac": 0.7},
                 {"label": "Focus", "value": "3", "unit": "areas", "frac": 0.6},
                 {"label": "Streak target", "value": "7", "unit": "days", "frac": 0.5},
                 {"label": "Level", "value": "2", "unit": "of 5", "frac": 0.4}],
     "score_label": "Plan fit", "score": 8, "cta": "Let's get started", "motion": "Confetti falls, rings fill"},
    {"id": "account", "kind": "account", "section": _S5, "title": "Save your progress",
     "subtitle": "Keep your plan safe and synced across your devices.", "mascot": "idle",
     "motion": "Mascot pops in, buttons rise"},
    {"id": "paywall", "kind": "paywall", "section": _S5, "title": "Your personal {app} plan",
     "locked": ["Daily goal", "Your plan", "Insights", "History", "Level"],
     "proof": "Built from your answers", "proof_sub": "Personalized to your goal and pace",
     "motion": "Plan card rises, CTA shine sweeps, close fades in late"},
    {"id": "offer", "kind": "offer", "section": _S5, "title": "One-time offer",
     "benefits": ["Unlimited AI results", "Your personal plan", "Full history", "Weekly insights"],
     "motion": "Price anchor pops, CTA shine sweeps"},
]

_MAIN = [
    {"id": "first_day", "kind": "empty", "title": "Make your first capture", "tab": "home", "mascot": "wave",
     "subtitle": "Take a photo and {app} does the rest.", "badge": "1 free result waiting",
     "motion": "Mascot bobs, pulse rings on the capture button"},
    {"id": "home", "kind": "home", "title": "Today", "tab": "home",
     "summary": {"value": "3", "label": "results left today", "frac": 0.4},
     "metrics": [{"label": "Streak", "value": "5 days"}, {"label": "This week", "value": "12"}, {"label": "Level", "value": "2"}],
     "items": [{"title": "Morning result", "sub": "08:40"}, {"title": "Afternoon result", "sub": "14:05"}],
     "motion": "Summary ring fills, cards rise in sequence"},
    {"id": "capture", "kind": "capture", "title": "Capture", "modes": ["Photo", "Describe", "Gallery"],
     "hint": "Fit your subject in the frame", "free_badge": "1 free result", "motion": "Scan line sweeps the frame"},
    {"id": "analyzing", "kind": "analyzing", "title": "Analyzing…", "subtitle": "This takes a few seconds.",
     "steps": ["Reading your photo", "Finding the details", "Preparing your result"], "mascot": "think",
     "motion": "Scan band sweeps, step spinner runs"},
    {"id": "result", "kind": "result", "title": "Your result", "tag": "Just now", "score": 8, "score_label": "Score",
     "headline_value": "82", "headline_unit": "match",
     "tiles": [{"label": "Detail A", "value": "24"}, {"label": "Detail B", "value": "48"}, {"label": "Detail C", "value": "12"}],
     "items": ["First finding", "Second finding", "Third finding"], "cta": "Save result",
     "motion": "Hero pops, sheet rises, steppers spring"},
    {"id": "describe", "kind": "text_input", "title": "Describe it",
     "subtitle": "Write it like you would tell a friend. {app} works out the rest.",
     "placeholder": "Describe what you want {app} to look at", "suggestions": ["Quick", "Detailed", "For today", "Compare"],
     "tip": "Tip: add details for a more accurate result.", "mascot": "think", "cta": "Analyze", "motion": "Chips pop in"},
    {"id": "progress", "kind": "progress", "title": "Progress", "tab": "progress",
     "summary": {"value": "12", "label": "results this week", "frac": 0.6}, "bars": [2, 3, 1, 2, 3, 1, 0],
     "chart_title": "This week", "motion": "Bars grow in sequence, ring fills"},
    {"id": "history", "kind": "history", "title": "History", "tab": "history",
     "days": [{"title": "Today", "value": "2 results"}, {"title": "Yesterday", "value": "3 results"},
              {"title": "Monday", "value": "1 result"}],
     "locked": "See your full history", "locked_sub": "Every result, every week, with {app} Premium.",
     "motion": "Day cards rise in sequence"},
    {"id": "settings", "kind": "settings", "title": "Settings", "tab": "settings", "mascot": "wave",
     "profile": "Your plan · 15 min a day",
     "groups": [{"title": "YOUR PLAN", "rows": [{"icon": "target", "label": "Adjust your goal"},
                                               {"icon": "users", "label": "Personal details"}]},
                {"title": "ACCOUNT", "rows": [{"icon": "gift", "label": "Manage subscription"},
                                             {"icon": "repeat", "label": "Restore purchases"},
                                             {"icon": "smile", "label": "Contact support"},
                                             {"icon": "shield", "label": "Privacy & Terms"},
                                             {"icon": "close", "label": "Delete account", "danger": True}]}],
     "motion": "Groups rise, toggles spring"},
    {"id": "daily_cap", "kind": "limit_sheet", "title": "That's all for today",
     "subtitle": "You used today's AI results. They reset at midnight.", "cta": "OK", "mascot": "sleep",
     "motion": "Sheet slides up, sleeping mascot breathes"},
]


def skeleton(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Default Cal AI-style funnel (26 onboarding screens) + main app screens.

    The design stage adapts every entry to the app (copy, options, pickers, data use),
    adding/removing screens as the product needs; it is never shipped unchanged.
    """
    doc = {"version": 1, "onboarding": copy.deepcopy(_ONBOARDING), "main": copy.deepcopy(_MAIN)}
    if spec:
        doc["onboarding"] = [s for s in doc["onboarding"] if _kept_by_options(s, spec)]
        tone = spec.get("design", {}).get("mascot") or {}
        if not tone:  # no mascot: the guide screen introduces the app instead
            for s in doc["onboarding"]:
                if s["id"] == "meet_mascot":
                    s["title"] = "Meet {app}, your guide"
                    s["subtitle"] = "{app} cheers every step and keeps things light."
    for part, prefix in (("onboarding", "onb"), ("main", "app")):
        for s in doc[part]:
            s.setdefault("key", f"{prefix}.{s['id']}")
    return doc


def from_brief(doc: dict[str, Any], flow: list[str], brief_sha256: str | None) -> dict[str, Any]:
    """Re-order/trim/extend the skeleton onboarding to the brief's onboarding.flow (kinds in order).

    Each slot takes the next unused skeleton screen of that kind; kinds the skeleton runs out of get a
    stub the design stage must fill in. The result is structure only — copy, options and the look are
    authored from the brief."""
    pool: dict[str, list[dict[str, Any]]] = {}
    for s in doc["onboarding"]:
        pool.setdefault(s["kind"], []).append(s)
    out, n = [], 0
    for kind in flow:
        if pool.get(kind):
            out.append(pool[kind].pop(0))
            continue
        n += 1
        out.append({"id": f"{kind}_{n}", "kind": kind, "section": "Brief", "title": f"TODO {kind} {n}",
                    "motion": "TODO: motion moment from the brief", "key": f"onb.{kind}_{n}"})
    return {**doc, "onboarding": out, "brief_sha256": brief_sha256}
