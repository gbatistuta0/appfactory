"""design_research — competitor + top-chart visual research and the per-app design brief.

The factory has no house look. Before any board is drawn, this step:

1. `collect()` finds the category's leading apps across key storefronts (iTunes Search for the app's
   terms + the genre's top-grossing and top-free charts, looked up for screenshotUrls/artwork) and
   downloads their App Store screenshots and icons into design/research/apps/<id>-<slug>/.
2. Claude studies them and writes design/research/brief.md + brief.json (`brief_template()` gives the
   shape): a blended, differentiated direction for THIS app — palette, type, components, density,
   illustration, onboarding flow, paywall, screenshot concept — each choice citing the references it
   borrows from and what it does differently. No competitor brand, asset or trade dress is copied.
3. `validate_brief()` / `check()` are what the design_research, design and screenshots gates run.

References are study material only: the downloaded files never enter the Claude Design project.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from .. import spec as spec_mod

RESEARCH_REL = "design/research"
REFS_REL = f"{RESEARCH_REL}/references.json"
BRIEF_JSON_REL = f"{RESEARCH_REL}/brief.json"
BRIEF_MD_REL = f"{RESEARCH_REL}/brief.md"
APPS_REL = f"{RESEARCH_REL}/apps"

DEFAULT_COUNTRIES = ["us", "gb", "de", "jp", "br"]
MIN_REFERENCES = 6          # apps with an icon + screenshots on disk
MIN_SCREENSHOTS = 2         # per reference app
MIN_STOREFRONTS = 2
SECTIONS = ["palette", "typography", "components", "density", "illustration", "onboarding", "paywall", "screenshots"]
REQUIRED_TOKENS = ["background", "ink", "accent", "cta"]
CAPTURE_KEYS = ["onboarding", "create", "result", "gallery", "paywall", "settings"]  # screenshot.CAPTURE_ARGS
STORE_BOARDS_RANGE = (3, 10)
MIN_SCREENSHOT_REFS = 4     # competitor screenshot sets the screenshot concept must cite
MAX_RESEARCH_AGE_DAYS = 45  # the screenshots stage refreshes older research
SCREENSHOT_ANALYSIS = ["frame1_hook", "caption_style", "framing", "backgrounds", "sequencing", "badges"]

ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
CHART_FEEDS = {
    "top_grossing": "https://itunes.apple.com/{country}/rss/topgrossingapplications/limit={limit}/genre={genre}/json",
    "top_free": "https://itunes.apple.com/{country}/rss/topfreeapplications/limit={limit}/genre={genre}/json",
}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ------------------------------------------------------------ network (patched in tests)

def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = httpx.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def _download(url: str, dest: Path) -> bool:
    try:
        r = httpx.get(url, timeout=60)
    except httpx.HTTPError:
        return False
    if not r.is_success or not r.content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return True


# ------------------------------------------------------------ collect

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "app").lower()).strip("-")[:40] or "app"


def _entry(a: dict[str, Any], country: str, source: str) -> dict[str, Any]:
    return {"id": str(a.get("trackId")), "name": a.get("trackName"), "seller": a.get("sellerName"),
            "genre": a.get("primaryGenreName"), "genre_id": a.get("primaryGenreId"),
            "rating": a.get("averageUserRating"), "ratings_count": a.get("userRatingCount") or 0,
            "store_url": a.get("trackViewUrl"), "countries": [country], "sources": [source],
            "_shots": list(a.get("screenshotUrls") or []), "_icon": a.get("artworkUrl512") or a.get("artworkUrl100")}


def _merge(pool: dict[str, dict[str, Any]], e: dict[str, Any]) -> None:
    if not e["id"] or e["id"] == "None":
        return
    cur = pool.get(e["id"])
    if cur is None:
        pool[e["id"]] = e
        return
    cur["countries"] = sorted(set(cur["countries"]) | set(e["countries"]))
    cur["sources"] = sorted(set(cur["sources"]) | set(e["sources"]))
    cur["ratings_count"] = max(cur["ratings_count"], e["ratings_count"])
    cur["_shots"] = cur["_shots"] or e["_shots"]
    cur["_icon"] = cur["_icon"] or e["_icon"]


def collect(app_dir: str | Path, terms: list[str], countries: list[str] | None = None, per_term: int = 10,
            chart_limit: int = 25, max_apps: int = 16, screenshots_per_app: int = 6,
            exclude_ids: list[str] | None = None) -> dict[str, Any]:
    """Search + top charts across storefronts → download screenshots/icons → references.json."""
    app = Path(app_dir).expanduser()
    countries = countries or DEFAULT_COUNTRIES
    terms = [t for t in (terms or []) if str(t).strip()]
    if not terms:
        return {"ok": False, "error": "terms missing — pass the app idea's category keywords (e.g. ['calorie counter'])"}
    pool: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for country in countries:
        for term in terms:
            try:
                res = _get_json(ITUNES_SEARCH, {"term": term, "entity": "software", "country": country, "limit": per_term})
            except Exception as e:  # noqa: BLE001
                errors.append(f"search {term}/{country}: {e}")
                continue
            for a in res.get("results", []):
                _merge(pool, _entry(a, country, f"search:{term}"))
    genres = Counter(e["genre_id"] for e in pool.values() if e.get("genre_id"))
    genre = genres.most_common(1)[0][0] if genres else None
    if genre:
        for country in countries[:3]:
            ids: dict[str, str] = {}
            for chart, url in CHART_FEEDS.items():
                try:
                    feed = _get_json(url.format(country=country, limit=chart_limit, genre=genre))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{chart}/{country}: {e}")
                    continue
                for it in feed.get("feed", {}).get("entry", []) or []:
                    tid = ((it.get("id") or {}).get("attributes") or {}).get("im:id")
                    if tid:
                        ids.setdefault(str(tid), chart)
            for chunk in [list(ids)[i:i + 50] for i in range(0, len(ids), 50)]:
                try:
                    res = _get_json(ITUNES_LOOKUP, {"id": ",".join(chunk), "country": country, "entity": "software"})
                except Exception as e:  # noqa: BLE001
                    errors.append(f"lookup/{country}: {e}")
                    continue
                for a in res.get("results", []):
                    _merge(pool, _entry(a, country, f"{ids.get(str(a.get('trackId')), 'chart')}:{country}"))
    skip = {str(x) for x in (exclude_ids or [])}
    ranked = sorted((e for e in pool.values() if e["_shots"] and e["id"] not in skip),
                    key=lambda e: (-len(e["countries"]), -e["ratings_count"]))[:max_apps]
    apps = []
    for e in ranked:
        folder = f"{APPS_REL}/{e['id']}-{_slug(e['name'])}"
        icon = f"{folder}/icon.png" if e["_icon"] and _download(e["_icon"], app / folder / "icon.png") else None
        shots = []
        for i, url in enumerate(e["_shots"][:screenshots_per_app], 1):
            rel = f"{folder}/screenshot-{i:02d}{Path(url.split('?')[0]).suffix or '.jpg'}"
            if _download(url, app / rel):
                shots.append(rel)
        apps.append({k: v for k, v in e.items() if not k.startswith("_")} | {"icon": icon, "screenshots": shots})
    doc = {"collected_at": _now(), "terms": terms, "countries": countries, "genre_id": genre, "apps": apps}
    p = app / REFS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    chk = check_references(app)
    return {"ok": chk["ok"], "references": str(p), "apps": len(apps),
            "with_screenshots": sum(1 for a in apps if len(a["screenshots"]) >= MIN_SCREENSHOTS),
            "errors": errors[:10], "reason": chk.get("reason"),
            "next": ("Study every downloaded screenshot + icon (Read the image files), then write "
                     f"{BRIEF_MD_REL} + {BRIEF_JSON_REL} (design_research_brief_template shows the shape).")}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_references(app_dir: str | Path) -> dict[str, Any] | None:
    p = Path(app_dir).expanduser() / REFS_REL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def usable_refs(app: Path, refs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for a in refs.get("apps") or []:
        shots = [s for s in a.get("screenshots") or [] if (app / s).is_file()]
        if a.get("icon") and (app / a["icon"]).is_file() and len(shots) >= MIN_SCREENSHOTS:
            out[str(a.get("id"))] = a
    return out


def check_references(app_dir: str | Path) -> dict[str, Any]:
    app = Path(app_dir).expanduser()
    refs = load_references(app)
    if refs is None:
        return {"ok": False, "reason": f"no design research ({REFS_REL}) — run design_research_collect"}
    usable = usable_refs(app, refs)
    if len(usable) < MIN_REFERENCES:
        return {"ok": False, "reason": f"design research has {len(usable)} reference apps with an icon + "
                f"≥{MIN_SCREENSHOTS} downloaded screenshots < {MIN_REFERENCES} — widen the terms/countries"}
    if len(refs.get("countries") or []) < MIN_STOREFRONTS:
        return {"ok": False, "reason": f"design research covers < {MIN_STOREFRONTS} storefronts"}
    return {"ok": True, "references": len(usable)}


# ------------------------------------------------------------ brief

def brief_template(app_dir: str | Path) -> dict[str, Any]:
    """The brief.json shape, pre-filled with the reference ids to analyze (values are instructions)."""
    app = Path(app_dir).expanduser()
    refs = load_references(app) or {}
    ids = list(usable_refs(app, refs)) if refs else []
    cite = {"borrows": ["<reference ids this choice learns from>"],
            "differs": "<what this app deliberately does differently, and why it fits its purpose>"}
    return {
        "version": 1,
        "app": "<display name>",
        "purpose": "<who it is for and the job it does — the lens for every choice below>",
        "references": ids,
        "analysis": {"shared_patterns": ["<what the top apps share: look, palette, type, layouts, onboarding, "
                                         "paywall, screenshot storytelling>"],
                     "differentiators": ["<how the leaders differ from each other>"],
                     "gaps": ["<what none of them does well — the opening for this app>"]},
        "direction": {
            "palette": {"tokens": {k: "#RRGGBB" for k in spec_mod.DEFAULTS["design"]["tokens"]}, **cite},
            "typography": {"display": "<Google font>", "body": "<Google font>", **cite},
            "components": {"style": "<corner radius, surfaces, buttons, pickers, iconography>", **cite},
            "density": {"level": "airy | balanced | dense", **cite},
            "illustration": {"style": "<mascot / illustration / photo language, motion character>", **cite},
            "onboarding": {"flow": ["<onboarding kinds in order, e.g. welcome, question, ..., paywall, offer>"],
                           "rationale": "<why this shape for this app>", **cite},
            "paywall": {"style": "<hard paywall + offer: layout, plan cards, trust, anchor>", **cite},
            "screenshots": {"analysis": {
                                "frame1_hook": "<how the leaders hook in the first frame>",
                                "caption_style": "<caption voice, length, case, placement>",
                                "framing": "<device frames vs full-bleed vs cut-outs>",
                                "backgrounds": "<solid / gradient / photo / illustrated, color use>",
                                "sequencing": "<how features are ordered across the set>",
                                "badges": "<awards/ratings/social proof usage — within Apple's rules>"},
                            "concept": "<the storytelling idea of THIS app's set, blending + differing>",
                            "boards": [{"shot": f"<one of {CAPTURE_KEYS}>", "message": "<headline angle>",
                                        "layout": "<device placement, crop, background, callouts>"}],
                            "layout": {"brandColorTop": "#RRGGBB", "brandColorBottom": "#RRGGBB",
                                       "headlineColor": "#RRGGBB"}, **cite},
        },
        "no_copy": "<set to true: no competitor brand, asset or distinctive trade dress is reused>",
        "rules": {"app": _rules().APP_RULES, "store": _rules().STORE_RULES,
                  "note": "structural constraints the look must respect (not part of the brief file)"},
        "brief_md": f"{BRIEF_MD_REL} — the human-readable version; name every cited reference app",
    }


def _rules():
    from . import rules
    return rules


def load_brief(app_dir: str | Path) -> dict[str, Any] | None:
    p = Path(app_dir).expanduser() / BRIEF_JSON_REL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def brief_sha(app_dir: str | Path) -> str | None:
    p = Path(app_dir).expanduser() / BRIEF_JSON_REL
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def palette_key(tokens: dict[str, Any], fonts: dict[str, Any] | None = None) -> tuple:
    t = {k: str(v).upper() for k, v in (tokens or {}).items()}
    f = fonts or {}
    return (t.get("accent"), t.get("background"), t.get("cta"), f.get("display"), f.get("body"))


def sibling_designs(app: Path) -> dict[str, tuple]:
    """Other factory apps next to this one (e.g. ~/Desktop/AppFactoryApps/*) → their palette key."""
    out: dict[str, tuple] = {}
    parent = app.resolve().parent
    for sp in parent.glob("*/app.spec.json"):
        if sp.parent.resolve() == app.resolve():
            continue
        try:
            d = (json.loads(sp.read_text(encoding="utf-8")).get("design") or {})
        except Exception:  # noqa: BLE001
            continue
        tokens = dict(spec_mod.DEFAULTS["design"]["tokens"]) | (d.get("tokens") or {})
        fonts = dict(spec_mod.DEFAULTS["design"]["fonts"]) | (d.get("fonts") or {})
        out[sp.parent.name] = palette_key(tokens, fonts)
    return out


def validate_brief(app_dir: str | Path) -> list[str]:
    app = Path(app_dir).expanduser()
    brief = load_brief(app)
    if brief is None:
        return [f"{BRIEF_JSON_REL} missing or unreadable — write the design brief from the research"]
    md_p = app / BRIEF_MD_REL
    if not md_p.exists():
        return [f"{BRIEF_MD_REL} missing — the human-readable brief with every reference cited"]
    md = md_p.read_text(encoding="utf-8").lower()
    usable = usable_refs(app, load_references(app) or {})
    errs: list[str] = []
    refs = [str(r) for r in brief.get("references") or []]
    unknown = [r for r in refs if r not in usable]
    if unknown:
        errs.append(f"brief cites references without downloaded screenshots: {', '.join(unknown[:5])}")
    if len(set(refs) & set(usable)) < MIN_REFERENCES:
        errs.append(f"brief analyzes {len(set(refs) & set(usable))} reference apps < {MIN_REFERENCES}")
    if not str(brief.get("purpose", "")).strip() or str(brief.get("purpose", "")).startswith("<"):
        errs.append("brief.purpose missing")
    an = brief.get("analysis") or {}
    for k in ("shared_patterns", "differentiators"):
        if not an.get(k) or any(str(x).startswith("<") for x in an[k]):
            errs.append(f"brief.analysis.{k} missing")
    if brief.get("no_copy") is not True:
        errs.append("brief.no_copy must be true (no competitor brand, asset or trade dress reused)")
    direction = brief.get("direction") or {}
    cited: set[str] = set()
    for sec in SECTIONS:
        d = direction.get(sec)
        if not isinstance(d, dict):
            errs.append(f"brief.direction.{sec} missing")
            continue
        borrows = [str(b) for b in d.get("borrows") or []]
        if not borrows or any(b not in refs for b in borrows):
            errs.append(f"brief.direction.{sec}.borrows must cite analyzed reference ids")
        cited |= set(borrows)
        if len(str(d.get("differs", "")).strip()) < 12 or str(d.get("differs", "")).startswith("<"):
            errs.append(f"brief.direction.{sec}.differs must say what this app does differently")
    tokens = ((direction.get("palette") or {}).get("tokens")) or {}
    bad = [k for k in REQUIRED_TOKENS if not _HEX.match(str(tokens.get(k, "")))]
    bad += [k for k, v in tokens.items() if not _HEX.match(str(v))]
    if bad:
        errs.append(f"brief palette tokens must be #RRGGBB (missing/invalid: {', '.join(sorted(set(bad)))})")
    typ = direction.get("typography") or {}
    if not str(typ.get("display", "")).strip() or not str(typ.get("body", "")).strip() or \
            str(typ.get("display", "")).startswith("<"):
        errs.append("brief typography needs display + body fonts")
    from . import screens as screens_mod
    flow = (direction.get("onboarding") or {}).get("flow") or []
    if not flow or any(k not in screens_mod.ONBOARDING_KINDS for k in flow):
        errs.append(f"brief onboarding.flow must list onboarding kinds from {sorted(screens_mod.ONBOARDING_KINDS)}")
    else:
        try:
            spec = spec_mod.load(app)
        except (OSError, ValueError):
            spec = None
        if spec_mod.option(spec, "hard_paywall") and spec_mod.offer_on(spec):
            if flow.count("paywall") != 1 or flow.count("offer") != 1 or flow.index("offer") < flow.index("paywall"):
                errs.append("brief onboarding.flow needs one paywall followed by one offer")
        else:
            from . import screens as _screens
            errs += ["brief onboarding.flow: " + e for e in _screens.funnel_problems(flow, spec)]
    ss = direction.get("screenshots") or {}
    boards = ss.get("boards") or []
    lo, hi = STORE_BOARDS_RANGE
    if not str(ss.get("concept", "")).strip() or str(ss.get("concept", "")).startswith("<"):
        errs.append("brief screenshots.concept missing")
    if not lo <= len(boards) <= hi:
        errs.append(f"brief screenshots.boards must have {lo}..{hi} boards")
    shots = [b.get("shot") for b in boards if isinstance(b, dict)]
    if any(s not in CAPTURE_KEYS for s in shots) or len(set(shots)) != len(shots):
        errs.append(f"brief screenshots.boards[].shot must be distinct values from {CAPTURE_KEYS}")
    if any(not str(b.get("message", "")).strip() for b in boards if isinstance(b, dict)):
        errs.append("every screenshot board needs its message")
    ss_an = ss.get("analysis") or {}
    thin = [k for k in SCREENSHOT_ANALYSIS if len(str(ss_an.get(k, "")).strip()) < 8 or str(ss_an.get(k, "")).startswith("<")]
    if thin:
        errs.append(f"brief screenshots.analysis missing: {', '.join(thin)} (study the competitors' screenshot sets)")
    ss_refs = {str(b) for b in ss.get("borrows") or []} & set(usable)
    if len(ss_refs) < MIN_SCREENSHOT_REFS:
        errs.append(f"brief screenshots concept cites {len(ss_refs)} competitor screenshot sets < {MIN_SCREENSHOT_REFS}")
    lay = ss.get("layout") or {}
    if any(not _HEX.match(str(lay.get(k, ""))) for k in ("brandColorTop", "brandColorBottom", "headlineColor")):
        errs.append("brief screenshots.layout needs brandColorTop/brandColorBottom/headlineColor as #RRGGBB")
    missing_names = [usable[r]["name"] for r in sorted(cited) if r in usable
                     and str(usable[r].get("name", "")).lower() not in md]
    if missing_names:
        errs.append(f"{BRIEF_MD_REL} does not name cited references: {', '.join(missing_names[:4])}")
    if not errs:
        from . import rules
        merged = dict(spec_mod.DEFAULTS["design"]["tokens"]) | tokens
        errs += [f"brief palette: {e}" for e in rules.contrast_problems(merged)]
    # anti-sameness: never the template defaults, never another factory app's palette + type
    if not errs:
        key = palette_key(tokens, typ)
        dflt = spec_mod.DEFAULTS["design"]
        if key[:3] == palette_key(dflt["tokens"])[:3]:
            errs.append("brief palette equals the factory template defaults — derive it from the research")
        for other, okey in sibling_designs(app).items():
            if okey == key:
                errs.append(f"brief palette + typography are identical to {other} — each app needs its own look")
    return errs


def check(app_dir: str | Path) -> dict[str, Any]:
    """design_research gate: references on disk + a valid, cited, differentiated brief."""
    ref = check_references(app_dir)
    if not ref["ok"]:
        return ref
    errs = validate_brief(app_dir)
    if errs:
        more = f" (+{len(errs) - 3} more)" if len(errs) > 3 else ""
        return {"ok": False, "reason": "design brief: " + "; ".join(errs[:3]) + more, "problems": errs}
    return {"ok": True, "reason": f"design research: {ref['references']} reference apps, brief valid",
            "brief_sha256": brief_sha(app_dir)}


def research_age_days(app_dir: str | Path) -> float | None:
    refs = load_references(app_dir) or {}
    try:
        at = datetime.datetime.strptime(refs["collected_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds() / 86400


def check_screenshot_concept(app_dir: str | Path) -> dict[str, Any]:
    """Screenshots stage: research fresh enough + brief valid (incl. the screenshot concept section)."""
    age = research_age_days(app_dir)
    if age is None or age > MAX_RESEARCH_AGE_DAYS:
        return {"ok": False, "reason": f"design research is older than {MAX_RESEARCH_AGE_DAYS} days (or undated) — "
                "re-run design_research_collect, re-study the competitors' screenshot sets, update the brief's "
                "screenshots section"}
    return check(app_dir)


def derive_problems(app_dir: str | Path, spec: dict[str, Any], doc: dict[str, Any]) -> list[str]:
    """screens.json + spec design tokens/fonts come from the current brief."""
    app = Path(app_dir).expanduser()
    brief = load_brief(app) or {}
    d = brief.get("direction") or {}
    errs = []
    if doc.get("brief_sha256") != brief_sha(app):
        errs.append("design/screens.json is not derived from the current brief (brief_sha256 mismatch) — "
                    "re-run design_screens_skeleton from the brief and re-adapt")
    flow = (d.get("onboarding") or {}).get("flow") or []
    kinds = [s.get("kind") for s in doc.get("onboarding") or []]
    if kinds != flow:
        errs.append("onboarding screen kinds differ from the brief's onboarding.flow")
    sd = spec.get("design") or {}
    tokens = dict(spec_mod.DEFAULTS["design"]["tokens"]) | (sd.get("tokens") or {})
    want = (d.get("palette") or {}).get("tokens") or {}
    off = [k for k, v in want.items() if str(tokens.get(k, "")).upper() != str(v).upper()]
    if off:
        errs.append(f"spec design.tokens differ from the brief palette ({', '.join(off[:4])}) — copy the brief tokens")
    fonts = dict(spec_mod.DEFAULTS["design"]["fonts"]) | (sd.get("fonts") or {})
    typ = d.get("typography") or {}
    if fonts.get("display") != typ.get("display") or fonts.get("body") != typ.get("body"):
        errs.append("spec design.fonts differ from the brief typography")
    return errs
