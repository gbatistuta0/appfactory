"""idea_* — Phase 0 idea discovery across EVERY App Store category.

AppFactory ideas are not limited to AI or photo→AI apps. Any iOS subscription idea is in scope when its
market is rising, revenue-proven, open to newcomers and fits a solo SwiftUI subscription build; AI is an
optional edge (spec.ai.enabled), never a requirement.

- harvest(): sweeps the legacy top-grossing + top-free charts per genre × storefront, dedupes, enriches
  via iTunes lookup and returns chart-proven apps, rising newcomers and per-genre "open niche" clusters.
- evaluate(): the evidence bundle used to rank one idea (demand, niche score, two-window newcomer
  traction, leaders' price ladders, ai_needed, build complexity, review risk, name availability).

Read-only, free endpoints, polite pacing. A failed feed is reported as ok:False — never as "no apps".
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from . import aso

DEFAULT_COUNTRIES = ["us", "gb", "de", "br", "tr", "jp", "fr"]
FEEDS = ("grossing", "free")
LOOKUP_BATCH = 100
# open_niche thresholds: share of a genre's top-grossing apps released within newcomer_months.
OPEN_SHARE = 0.20  # live sweep 2026-09-28: genre shares ranged 0.06–0.43, median ~0.16
_DAYS_PER_MONTH = 30.44

# primaryGenreName (iTunes lookup/search) → GENRES key.
GENRE_LABELS = {
    "Books": "books", "Business": "business", "Developer Tools": "developer_tools", "Education": "education",
    "Entertainment": "entertainment", "Finance": "finance", "Food & Drink": "food_drink", "Games": "games",
    "Graphics & Design": "graphics_design", "Health & Fitness": "health", "Lifestyle": "lifestyle",
"Medical": "medical", "Music": "music",
    "Navigation": "navigation", "News": "news", "Photo & Video": "photo_video", "Productivity": "productivity",
    "Reference": "reference", "Shopping": "shopping", "Social Networking": "social", "Sports": "sports",
    "Travel": "travel", "Utilities": "utilities", "Weather": "weather",
}


def _parse_date(d: str | None) -> datetime | None:
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_days(d: str | None, now: datetime) -> int | None:
    dt = _parse_date(d)
    return None if dt is None else max(0, (now - dt).days)


def _lookup(ids: list[str], country: str) -> tuple[dict[str, dict[str, Any]], str | None]:
    """iTunes lookup for up to LOOKUP_BATCH ids in one storefront (ratings counts are per storefront)."""
    data, err = aso._get_json(aso.ITUNES_LOOKUP, {"id": ",".join(ids), "country": country})
    if err:
        return {}, err
    out = {}
    for r in (data or {}).get("results", []):
        if r.get("trackId"):
            out[str(r["trackId"])] = r
    return out, None


def _pmap(fn: Any, items: list[Any], workers: int) -> list[Any]:
    """Ordered map with a small thread pool (polite: `workers` requests in flight at most)."""
    if workers <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def _matches(app: dict[str, Any], terms: list[str]) -> bool:
    hay = f"{app.get('name') or ''} {app.get('seller') or ''}".lower()
    return any(t.lower() in hay for t in terms if t)


def harvest(countries: list[str] | None = None, genres: list[str] | None = None, limit: int = 100,
            newcomer_months: int = 12, exclude_terms: list[str] | None = None,
            feeds: list[str] | None = None, max_results: int = 50, delay: float = 0.3,
            workers: int = 4) -> dict[str, Any]:
    """Sweep top-grossing (+ top-free) per genre × storefront → chart-proven apps, rising newcomers and
    per-genre clusters. genres None = every charted App Store category (aso.GENRES)."""
    countries = [c.lower() for c in (countries or DEFAULT_COUNTRIES)]
    feeds = list(feeds or FEEDS)
    bad_feeds = [f for f in feeds if f not in FEEDS]
    if bad_feeds:
        return {"ok": False, "error": f"unknown feed(s) {bad_feeds} (grossing|free)"}
    if genres is None:
        genre_keys = list(aso.GENRES)
    else:
        genre_keys, unknown = [], []
        for g in genres:
            gid = aso.genre_id(g)
            if gid:
                genre_keys.append(aso.genre_name(gid))
            else:
                unknown.append(g)
        if unknown:
            return {"ok": False, "error": f"unknown genre(s) {unknown} (one of {sorted(aso.GENRES)}; "
                                          f"uncharted: {aso.UNCHARTED_GENRES})"}
    now = datetime.now(timezone.utc)
    workers = max(1, min(int(workers), 8))
    newcomer_days = int(newcomer_months * _DAYS_PER_MONTH)

    # 1) charts
    feed_log: list[dict[str, Any]] = []
    apps: dict[str, dict[str, Any]] = {}
    tasks = [(g, c, f) for g in genre_keys for c in countries for f in feeds]

    def _one(t: tuple[str, str, str]) -> dict[str, Any]:
        if delay:
            time.sleep(delay)  # per-worker pacing: at most `workers` requests in flight
        return aso._fetch_chart(t[1], t[2], aso.GENRES[t[0]], limit)

    for (g, c, f), chart in zip(tasks, _pmap(_one, tasks, workers)):
        feed_log.append({"genre": g, "country": c, "feed": f, "ok": bool(chart.get("ok")),
                         **({"count": chart["count"]} if chart.get("ok") else {"error": chart.get("error")})})
        if not chart.get("ok"):
            continue
        for a in chart["apps"]:
            if not a["id"]:
                continue
            rec = apps.setdefault(a["id"], {
                "id": a["id"], "name": a["name"], "seller": a["seller"], "genre": g,
                "released": a["released"], "appearances": [], "ratings_by_country": {},
            })
            rec["appearances"].append({"genre": g, "country": c, "feed": f, "rank": a["rank"]})
    ok_feeds = [x for x in feed_log if x["ok"]]
    failed_feeds = [x for x in feed_log if not x["ok"]]
    if not ok_feeds:
        return {"ok": False, "error": "every chart feed failed — nothing measured (NOT 'no apps')",
                "failed_feeds": failed_feeds[:20], "failed_count": len(failed_feeds)}

    # 2) founder's own apps / explicit exclusions
    excluded = []
    if exclude_terms:
        for k in [k for k, a in apps.items() if _matches(a, exclude_terms)]:
            excluded.append(apps.pop(k)["name"])

    # 3) enrich: grossing apps + newcomers (by RSS release date), per storefront they charted in
    def _is_newcomer(a: dict[str, Any]) -> bool:
        age = _age_days(a.get("released"), now)
        return age is not None and age <= newcomer_days

    to_enrich: dict[str, list[str]] = {}
    for a in apps.values():
        if _is_newcomer(a) or any(x["feed"] == "grossing" for x in a["appearances"]):
            for c in sorted({x["country"] for x in a["appearances"]}):
                to_enrich.setdefault(c, []).append(a["id"])
    batches = [(c, ids[i:i + LOOKUP_BATCH]) for c, ids in to_enrich.items()
               for i in range(0, len(ids), LOOKUP_BATCH)]

    def _lk(b: tuple[str, list[str]]) -> tuple[dict[str, dict[str, Any]], str | None]:
        if delay:
            time.sleep(delay)
        return _lookup(b[1], b[0])

    lookup_log = []
    for (c, batch), (found, err) in zip(batches, _pmap(_lk, batches, workers)):
        lookup_log.append({"country": c, "requested": len(batch), "ok": err is None,
                           **({"found": len(found)} if err is None else {"error": err})})
        for tid, r in found.items():
            a = apps.get(tid)
            if a is None:
                continue
            a["ratings_by_country"][c] = r.get("userRatingCount") or 0
            a["released"] = r.get("releaseDate") or a.get("released")
            a["price"] = r.get("formattedPrice")
            a["rating"] = r.get("averageUserRating")
            a["primary_genre"] = r.get("primaryGenreName")
            a["url"] = r.get("trackViewUrl")
            a["enriched"] = True

    # 4) derive
    for a in apps.values():
        a["age_days"] = _age_days(a.get("released"), now)
        rbc = a["ratings_by_country"]
        a["ratings"] = max(rbc.values()) if rbc else None       # None = not looked up, not "0 ratings"
        a["ratings_per_day"] = (round(a["ratings"] / max(a["age_days"], 1), 2)
                                if a["ratings"] is not None and a["age_days"] is not None else None)
        gr = [x for x in a["appearances"] if x["feed"] == "grossing"]
        a["grossing_charts"] = len(gr)
        a["grossing_best_rank"] = min((x["rank"] for x in gr), default=None)
        a["grossing_countries"] = sorted({x["country"] for x in gr})
        a["newcomer"] = a["age_days"] is not None and a["age_days"] <= newcomer_days

    def _card(a: dict[str, Any]) -> dict[str, Any]:
        return {k: a.get(k) for k in ("id", "name", "seller", "genre", "released", "age_days", "ratings",
                                      "ratings_per_day", "price", "rating", "grossing_charts",
                                      "grossing_best_rank", "grossing_countries", "url")} | {
            "free_charts": sum(1 for x in a["appearances"] if x["feed"] == "free")}

    proven = sorted((a for a in apps.values() if a["grossing_charts"]),
                    key=lambda a: (-a["grossing_charts"], a["grossing_best_rank"] or 999))
    rising = sorted((a for a in apps.values() if a["newcomer"]),
                    key=lambda a: (a["ratings_per_day"] is None, -(a["ratings_per_day"] or 0),
                                   -a["grossing_charts"]))

    # 5) per-genre clusters: how many newcomers chart → "open niche" signal
    clusters = []
    for g in genre_keys:
        g_ok = [x for x in ok_feeds if x["genre"] == g]
        members = [a for a in apps.values() if any(x["genre"] == g for x in a["appearances"])]
        newc = [a for a in members if a["newcomer"]]
        newc_gross = [a for a in newc if a["grossing_charts"]]
        gross_members = [a for a in members if any(x["genre"] == g and x["feed"] == "grossing"
                                                   for x in a["appearances"])]
        share = len(newc_gross) / len(gross_members) if gross_members else 0.0
        # Relative, not absolute: over 7 storefronts × 100 ranks every genre has a few new big-brand apps.
        if not g_ok:
            signal = "unmeasured"
        elif share >= OPEN_SHARE and len(newc_gross) >= 3:
            signal = "open"
        elif newc:
            signal = "some"
        else:
            signal = "closed"
        flags = aso.GENRE_FLAGS.get(g, {})
        clusters.append({
            "genre": g, "feeds_ok": len(g_ok),
            "feeds_failed": sum(1 for x in failed_feeds if x["genre"] == g),
            "charted_apps": len(members), "newcomers": len(newc), "newcomers_in_grossing": len(newc_gross),
            "grossing_apps": len(gross_members),
            "newcomer_grossing_share": round(share, 3),
            "newcomer_share": round(len(newc) / len(members), 3) if members else None,
            "open_niche": signal,
            "top_newcomers": [a["name"] for a in sorted(newc, key=lambda a: -(a["ratings_per_day"] or 0))[:5]],
            "review_risk": flags.get("review_risk", "low"), "fit": flags.get("fit", "ok"),
        })
    order = {"open": 0, "some": 1, "closed": 2, "unmeasured": 3}
    clusters.sort(key=lambda c: (order[c["open_niche"]], -c["newcomer_grossing_share"], -c["newcomers"]))

    return {
        "ok": True, "partial": bool(failed_feeds),
        "swept": {"countries": countries, "genres": genre_keys, "feeds": feeds, "limit": min(limit, 100),
                  "newcomer_months": newcomer_months},
        "feeds_ok": len(ok_feeds), "feeds_failed": len(failed_feeds), "failed_feeds": failed_feeds[:30],
        "lookups": {"calls": len(lookup_log), "failed": [x for x in lookup_log if not x["ok"]][:20]},
        "unique_apps": len(apps), "excluded": excluded,
        "chart_proven": [_card(a) for a in proven[:max_results]],
        "rising_newcomers": [_card(a) for a in rising[:max_results]],
        "clusters": clusters,
        "uncharted_genres": aso.UNCHARTED_GENRES,
        "note": ("Any category is in scope; AI is an optional edge. failed feeds are unmeasured, not empty. "
                 "open_niche: open = ≥20% of the genre's top-grossing apps (and ≥3) are newcomers (≤ newcomer_months); "
                 "some = newcomers chart but below that; closed = no newcomer charts. Newcomers include big-brand "
                 "launches — check the seller before reading a newcomer as an indie signal. ratings None = not looked up. "
                 "Next: idea_evaluate(term, country, genre) for each candidate."),
    }


# ---- idea_evaluate ----

# Terms that make the core feature itself AI (generation, recognition, language understanding).
AI_REQUIRED_TERMS = (
    "ai", "gpt", "chatbot", "chat bot", "generator", "generate", "identifier", "identify", "detector",
    "solver", "enhancer", "enhance", "headshot", "avatar", "translate", "translator", "transcribe",
    "transcription", "summarize", "summarizer", "recognize", "recognition", "try on", "try-on",
    "face swap", "voice changer", "photo to", "text to", "humanizer", "tutor", "homework",
)
# Terms where AI can differentiate but the core works without it.
AI_OPTIONAL_TERMS = (
    "scan", "scanner", "coach", "planner", "plan", "recipe", "meal", "calorie", "journal", "diary",
    "workout", "study", "flashcard", "resume", "caption", "editor", "writer", "writing", "dream",
)
HIGH_COMPLEXITY_TERMS = (
    "multiplayer", "social", "chat", "messenger", "stream", "streaming", "map", "gps", "navigation", "bank",
    "trading", "crypto", "stock", "vpn", "dating", "delivery", "marketplace", "sync", "collaborat",
    "video editor", "live", "radio", "podcast", "music player", "game", "browser", "keyboard",
)
MEDIUM_COMPLEXITY_TERMS = (
    "widget", "health", "sleep", "workout", "fitness", "watch", "camera", "scan", "ocr", "offline",
    "calendar", "budget", "expense", "photo editor", "pdf", "voice", "audio", "recorder", "location",
)
REVIEW_RISK_TERMS = {
    "high": ("diagnos", "symptom", "medical", "prescription", "loan", "crypto", "trading", "gambl",
             "betting", "casino", "kids", "children", "vpn", "spy", "tracker phone"),
    "medium": ("dating", "therapy", "mental health", "blood", "pregnan", "fertility", "invest", "tax",
               "weight loss", "diet", "face swap", "deepfake"),
}


def _has(text: str, terms: tuple[str, ...]) -> list[str]:
    t = f" {text.lower()} "
    hits = []
    for term in terms:
        if " " in term or "-" in term or len(term) > 4:
            if term in t:
                hits.append(term)
        elif f" {term} " in t or f" {term}s " in t:
            hits.append(term)
    return hits


def _infer_genre(apps: list[dict[str, Any]]) -> str | None:
    labels = [GENRE_LABELS.get(a.get("genre") or "") for a in apps[:15]]
    labels = [x for x in labels if x]
    return Counter(labels).most_common(1)[0][0] if labels else None


def _ai_needed(term: str, leaders: list[dict[str, Any]]) -> dict[str, Any]:
    strong = _has(term, AI_REQUIRED_TERMS)
    optional = _has(term, AI_OPTIONAL_TERMS)
    leader_ai = [a.get("name") for a in leaders if _has(a.get("name") or "", ("ai", "gpt"))]
    signals = []
    if strong:
        heuristic = "yes"
        signals.append(f"term implies AI as the core feature: {strong}")
    elif optional or (leaders and len(leader_ai) * 3 >= len(leaders)):
        heuristic = "optional"
        if optional:
            signals.append(f"AI can differentiate (not required): {optional}")
        if leader_ai:
            signals.append(f"{len(leader_ai)}/{len(leaders)} leaders AI-branded: {leader_ai[:3]}")
    else:
        heuristic = "no"
        signals.append("core feature works without AI (no AI terms, leaders not AI-branded)")
    return {"heuristic": heuristic, "signals": signals, "claude_assessment": None,
            "note": "Claude sets claude_assessment (yes|optional|no) after reading the leaders; "
                    "yes/optional → spec.ai.enabled true, no → spec.ai.enabled false."}


def _build_complexity(term: str, genre: str | None, ai: str, leaders: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = []
    level = 0
    hi = _has(term, HIGH_COMPLEXITY_TERMS)
    if hi:
        level, reasons = 2, [f"term implies infrastructure beyond the template: {hi}"]
    fit = aso.GENRE_FLAGS.get(genre or "", {}).get("fit")
    if fit == "low":
        level = 2
        reasons.append(f"genre '{genre}' winners are not solo SwiftUI subscription builds "
                       f"({aso.GENRE_FLAGS[genre]['why']})")
    med = _has(term, MEDIUM_COMPLEXITY_TERMS)
    if med and level < 1:
        level = 1
        reasons.append(f"platform integration beyond the skeleton: {med}")
    if ai == "yes" and level < 1:
        level = 1
        reasons.append("AI core: analyze edge function prompt + schema + eval + unit economics")
    if not reasons:
        reasons.append("fits the template: subscription + onboarding funnel + on-device core feature")
    return {"level": ("low", "medium", "high")[level], "reasons": reasons,
            "template": "SwiftUI subscription skeleton (onboarding funnel, paywalls, Settings, Supabase "
                        "usage/delete-account/legal; analyze edge function only when spec.ai.enabled)"}


def _review_risk(term: str, genre: str | None, ai: str) -> dict[str, Any]:
    order = {"low": 0, "medium": 1, "high": 2}
    flags = aso.GENRE_FLAGS.get(genre or "", {})
    level = flags.get("review_risk", "low")
    reasons = [f"genre {genre}: {flags['why']}"] if flags.get("review_risk", "low") != "low" else []
    for lv in ("high", "medium"):
        hits = _has(term, REVIEW_RISK_TERMS[lv])
        if hits:
            reasons.append(f"term: {hits}")
            if order[lv] > order[level]:
                level = lv
    if ai == "yes":
        reasons.append("generative AI: China stays excluded (spec.store.excluded_territories CHN); "
                       "5.1.2 data-sharing disclosure for the AI provider")
    return {"level": level, "reasons": reasons or ["no category/term review flags"]}


def evaluate(term: str, country: str = "us", genre: str | None = None,
             name_candidates: list[str] | None = None, leaders: int = 3,
             delay: float = 0.3) -> dict[str, Any]:
    """Evidence bundle to rank one idea: autocomplete demand, niche score/verdict, two-window newcomer
    traction (12 + 6 months), leaders with price ladders, ai_needed, build complexity, review risk and
    (optional) the first available App Store name."""
    if genre is not None and aso.genre_id(genre) is None:
        return {"ok": False, "error": f"unknown genre '{genre}' (one of {sorted(aso.GENRES)})"}
    demand = aso.search_hints(term, country)
    if not demand.get("ok"):
        return {"ok": False, "stage": "demand", "error": demand.get("error")}
    comp = aso.fetch_competitors(term, country=country, limit=50)
    if not comp.get("ok"):
        return {"ok": False, "stage": "competitors", "error": comp.get("error") or comp.get("status")}
    apps = comp["competitors"]
    genre_key = aso.genre_name(aso.genre_id(genre)) if genre else _infer_genre(apps)
    niche = aso.niche_score(term, country, genre_key, _demand=demand, _comp=comp)

    top = sorted(apps, key=lambda a: -(a.get("ratings_count") or 0))[:max(0, leaders)]
    leader_rows = []
    for a in top:
        if delay:
            time.sleep(delay)
        iap = aso.competitor_iap(a["track_id"], country) if a.get("track_id") else {"ok": False, "prices": None}
        leader_rows.append({
            "name": a.get("name"), "seller": a.get("seller"), "ratings": a.get("ratings_count"),
            "rating": a.get("rating"), "released": a.get("released"), "price": a.get("price"),
            "track_id": a.get("track_id"),
            # prices None = UNKNOWN (page shape changed / network), never "free"
            "price_ladder": iap.get("prices") if iap.get("ok") else None,
            "price_ladder_ok": bool(iap.get("ok")),
        })

    ai = _ai_needed(term, apps[:10])
    complexity = _build_complexity(term, genre_key, ai["heuristic"], leader_rows)
    risk = _review_risk(term, genre_key, ai["heuristic"])
    name = aso.find_available_name(name_candidates, country) if name_candidates else None

    nc = niche.get("newcomers") or {}
    return {
        "ok": True, "term": term, "country": country, "genre": genre_key,
        "genre_inferred": genre is None,
        "autocomplete": {"count": demand["count"], "demand": demand["demand"], "top_terms": demand["hints"][:8]},
        "niche": {k: niche.get(k) for k in ("score", "verdict", "reason", "competition", "monetization")}
        if niche.get("ok") else {"ok": False, "error": niche.get("error")},
        "newcomer_traction": {"window_12mo": nc.get("window_12mo"), "window_6mo": nc.get("window_6mo"),
                              "dead_zone": nc.get("dead_zone"), "measured": nc.get("measured"),
                              "reason": nc.get("reason")},
        "leaders": leader_rows,
        "ai_needed": ai,
        "build_complexity": complexity,
        "review_risk": risk,
        "name_availability": name,
        "note": ("Rank on evidence: demand (autocomplete) + niche verdict + newcomers still gaining traction "
                 "in the 6-month window + leaders' price ladders (revenue-proven). AI is optional: "
                 "ai_needed=no is not a minus."),
    }
