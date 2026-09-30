"""legal_* — privacy policy / terms / support pages served by the app's Supabase `legal` function.

Replaces the old GitHub-gist legal links. Source: store/privacy/{privacy-policy,terms,support}.<lang>.md
(templates ship in English; the localize stage translates). Pipeline:

  legal_render   fill factory placeholders + resolve <!-- if:consent.health --> blocks (spec-driven)
  legal_check    list what still blocks publication (placeholders, unrendered blocks, missing languages)
  backend/legal/build.ts  (deno) → supabase/functions/legal/content.gen.ts, run by backend_deploy
  legal_verify   read-only GETs of every live URL per language (200, right language, support email)

URL shape (App Store Connect privacy/support URLs and the in-app links):
  https://<ref>.supabase.co/functions/v1/legal/{privacy,terms,support}[?lang=<app language>]
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Callable

from . import config as cfg
from . import spec as spec_mod

DOCS = {"privacy": "privacy-policy", "terms": "terms", "support": "support"}
LEGAL_URL_RE = re.compile(
    r"^https://[a-z0-9]{20}\.supabase\.co/functions/v1/legal/(privacy|terms|support)(\?lang=[A-Za-z]{2,3}(-[A-Za-z0-9]{2,4})?)?$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_BLOCK_RE = re.compile(r"<!--\s*if:([\w.]+)\s*-->\n?(.*?)<!--\s*endif\s*-->\n?", re.S)
_MARKER_RE = re.compile(r"<!--\s*(?:if:[\w.]+|endif)\s*-->")


def base_url(supabase_url: str) -> str:
    return supabase_url.rstrip("/") + "/functions/v1/legal"


def url(supabase_url: str, doc: str, lang: str | None = None) -> str:
    u = f"{base_url(supabase_url)}/{doc}"
    return f"{u}?lang={lang}" if lang else u


def is_legal_url(value: str, doc: str | None = None) -> bool:
    m = LEGAL_URL_RE.match(value or "")
    return bool(m) and (doc is None or m.group(1) == doc)


def app_language(store_locale: str, app_locales: list[str]) -> str:
    """Store locale → the app language its legal page is served in ("es-MX" → "es", "tr" → "tr")."""
    low = {loc.lower(): loc for loc in app_locales}
    if store_locale.lower() in low:
        return low[store_locale.lower()]
    lang = store_locale.split("-")[0].lower()
    if lang in low:
        return low[lang]
    for loc in app_locales:
        if loc.split("-")[0].lower() == lang:
            return loc
    return app_locales[0]


def _flag(spec: dict[str, Any], dotted: str) -> bool:
    cur: Any = spec
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return False
        cur = cur.get(part)
    return bool(cur)


def resolve_blocks(text: str, spec: dict[str, Any]) -> str:
    """Keep <!-- if:<spec path> --> … <!-- endif --> bodies whose spec flag is truthy, drop the rest."""
    return _BLOCK_RE.sub(lambda m: m.group(2) if _flag(spec, m.group(1)) else "", text)


def _plans_sentence(spec: dict[str, Any]) -> str:
    names = {"P1W": "weekly", "P1M": "monthly", "P3M": "quarterly", "P6M": "six-monthly", "P1Y": "yearly"}
    periods = []
    for p in spec["subscription"]["products"]:
        if p.get("offering") == "offer":
            continue
        n = names.get(p["period"], p["period"])
        if n not in periods:
            periods.append(n)
    return (" and ".join(periods) if len(periods) <= 2 else ", ".join(periods[:-1]) + " and " + periods[-1]) + " plans"


def _trial_sentence(spec: dict[str, Any]) -> str:
    trials = sorted({spec_mod.intro_duration(p["intro"]["duration"]) for p in spec["subscription"]["products"]
                     if p.get("intro") and p["intro"].get("type") == "free"})
    if not trials:
        return "there is no free trial."
    days = {"P3D": "3-day", "P1W": "1-week", "P2W": "2-week", "P1M": "1-month", "P2M": "2-month",
            "P3M": "3-month", "P6M": "6-month", "P1Y": "1-year"}
    t = " or ".join(days.get(d, d) for d in trials)
    return (f"some plans include a {t} free trial for eligible new subscribers. Apple gives one introductory "
            "offer per Apple Account in the subscription group. If you do not cancel at least 24 hours before "
            "the trial ends, the subscription starts and you are charged the plan price.")


def _free_use_sentence(spec: dict[str, Any]) -> str:
    n = spec.get("usage", {}).get("free_lifetime_scans", 0)
    return "without a subscription you can try one analysis for free." if n else \
        "the app's analyses need a subscription."


def factory_values(spec: dict[str, Any], config: dict[str, Any] | None = None,
                   supabase_url: str | None = None, today: _dt.date | None = None) -> dict[str, str]:
    """Placeholders the factory can fill. Product wording (APP_PURPOSE, ANALYSIS_PURPOSE, …) is left
    for the store stage, so publication stays blocked until someone writes it."""
    c = config if config is not None else cfg.load_config()
    d = today or _dt.date.today()
    values = {
        "APP_NAME": spec.get("display_name") or spec.get("name", ""),
        "EFFECTIVE_DATE": f"{d.day} {d.strftime('%B')} {d.year}",
        "PLANS_SENTENCE": _plans_sentence(spec),
        "TRIAL_SENTENCE": _trial_sentence(spec),
        "FREE_USE_SENTENCE": _free_use_sentence(spec),
        "APPLE_HEALTH_SUFFIX": ", Apple Health on your device" if spec.get("consent", {}).get("health") else "",
        "MIN_AGE": "16",
    }
    if c.get("support_email"):
        values["SUPPORT_EMAIL"] = c["support_email"]
    if c.get("legal_controller"):
        values["CONTROLLER"] = c["legal_controller"]
    if supabase_url:
        values["PRIVACY_URL"] = url(supabase_url, "privacy")
        values["TERMS_URL"] = url(supabase_url, "terms")
    return values


def fill(text: str, values: dict[str, str]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def source_files(app_dir: str | Path) -> list[Path]:
    app = Path(app_dir).expanduser()
    files = sorted((app / "store" / "privacy").glob("*.md"))
    priv = app / "backend" / "PRIVACY.md"
    return files + ([priv] if priv.exists() else [])


def render(app_dir: str | Path, spec: dict[str, Any], values: dict[str, str] | None = None,
           config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve conditional blocks and fill the factory placeholders in store/privacy/*.md and
    backend/PRIVACY.md (in place, idempotent). Remaining placeholders are reported."""
    app = Path(app_dir).expanduser()
    outs = cfg.app_outputs(app)
    vals = factory_values(spec, config, outs.get("supabase_url"))
    vals.update(values or {})
    changed, remaining = [], {}
    for f in source_files(app):
        text = f.read_text(encoding="utf-8")
        new = fill(resolve_blocks(text, spec), vals)
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(str(f.relative_to(app)))
        body = re.sub(r"<!--.*?-->", "", new, flags=re.S)
        left = sorted(set(PLACEHOLDER_RE.findall(body)))
        if left:
            remaining[str(f.relative_to(app))] = left
    return {"ok": True, "changed": changed, "remaining_placeholders": remaining}


def check(app_dir: str | Path, spec: dict[str, Any]) -> dict[str, Any]:
    """What blocks publication: per doc × app language, missing file / placeholder / unrendered block.
    English must exist for privacy and terms (the fallback language)."""
    app = Path(app_dir).expanduser()
    src = app / "store" / "privacy"
    problems: dict[str, list[str]] = {}
    published: list[str] = []
    for doc, base in DOCS.items():
        for lang in spec["locales"]["app"]:
            cands = [src / f"{base}.{lang}.md"] + ([src / f"{base}.md"] if lang == "en" else [])
            f = next((p for p in cands if p.exists()), None)
            key = f"{doc}/{lang}"
            if f is None:
                problems[key] = ["missing"]
                continue
            text = f.read_text(encoding="utf-8")
            issues = [f"unrendered {m}" for m in sorted(set(_MARKER_RE.findall(text)))]
            body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            issues += [f"{{{{{p}}}}}" for p in sorted(set(PLACEHOLDER_RE.findall(body)))]
            if issues:
                problems[key] = issues
            else:
                published.append(key)
    fallback = spec["locales"]["app"][0]

    def blocks(key: str, issues: list[str]) -> bool:
        # The fallback language must exist for every doc; any unfilled/unrendered file blocks.
        return key.split("/")[1] == fallback or any(not i.startswith("missing") for i in issues)

    blocking = {k: v for k, v in problems.items() if blocks(k, v)}
    return {"ok": not blocking, "publishable": published, "blocking": blocking,
            "missing_translations": sorted(k for k, v in problems.items() if k not in blocking)}


def verify_live(supabase_url: str, support_email: str, languages: list[str],
                docs: tuple[str, ...] = ("privacy", "terms"),
                get: Callable[[str], tuple[int, dict[str, str], str]] | None = None) -> dict[str, Any]:
    """Read-only: every doc × language answers 200 in that language, with the support email and no
    placeholder. `get(url) -> (status, headers, text)` is injectable for tests."""
    if get is None:
        import httpx

        def get(u: str) -> tuple[int, dict[str, str], str]:
            r = httpx.get(u, timeout=20)
            return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.text
    checks = []
    for doc in docs:
        for lang in languages:
            u = url(supabase_url, doc, lang)
            try:
                status, headers, text = get(u)
            except Exception as e:  # noqa: BLE001
                checks.append({"url": u, "problems": [f"network error: {e}"]})
                continue
            headers = {k.lower(): v for k, v in headers.items()}
            probs = []
            if status != 200:
                probs.append(f"HTTP {status}")
            if headers.get("content-language") != lang:
                probs.append(f"served {headers.get('content-language')}")
            if support_email and support_email not in text:
                probs.append("support email missing")
            if PLACEHOLDER_RE.search(text):
                probs.append("placeholder left")
            checks.append({"url": u, "problems": probs})
    failed = [c for c in checks if c["problems"]]
    return {"ok": not failed, "checked": len(checks), "failed": failed}
