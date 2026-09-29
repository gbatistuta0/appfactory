"""aso_* — ASO support tools (competitor/top-grossing data, outputs skeleton).

Claude runs the ASO skills; this module provides the helpers that feed them
(competitor data, output skeleton) and validate them (metadata). ASO is a
required step in the pipeline (see the gates in pipeline.py).
"""

from __future__ import annotations

import json as _json
import plistlib
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import config as cfg
from . import metadata as meta

ITUNES_SEARCH = "https://itunes.apple.com/search"
# GOTCHA: the modern rss.marketingtools.apple.com feed has NO top-grossing and NO genre filter (404).
# Revenue proxying REQUIRES this legacy feed. limit is silently capped at 100.
ITUNES_RSS_TOP_GROSSING = "https://itunes.apple.com/{country}/rss/topgrossingapplications/limit={limit}/json"
ITUNES_RSS_TOP_GROSSING_GENRE = (
    "https://itunes.apple.com/{country}/rss/topgrossingapplications/limit={limit}/genre={genre}/json")

# App Store search autocomplete — REAL App Store search demand (not a web proxy).
# GOTCHA: without the X-Apple-Store-Front header Apple returns ZERO hints. Response is plist XML.
SEARCH_HINTS = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
# Storefront IDs for our top-11 locales (bare numeric ID is enough).
STOREFRONTS = {"us": 143441, "gb": 143444, "de": 143443, "fr": 143442, "tr": 143480,
               "jp": 143462, "es": 143454, "it": 143450, "br": 143503, "in": 143467, "kr": 143466}
ITUNES_RSS_TOP_FREE_GENRE = (
    "https://itunes.apple.com/{country}/rss/topfreeapplications/limit={limit}/genre={genre}/json")
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
# Every App Store app category with its genre id (verified against the legacy RSS 2026-09-27: each id
# returns a chart whose entries carry that category). AppFactory ideas are NOT limited to AI or
# photo→AI apps: any category is in scope.
# GOTCHA: an unknown genre id is silently IGNORED by the RSS and returns the overall chart — _fetch_chart
# rejects a chart whose entries do not carry the requested genre (ok:False, never "these are the apps").
GENRES = {
    "books": 6018, "business": 6000, "developer_tools": 6026, "education": 6017,
    "entertainment": 6016, "finance": 6015, "food_drink": 6023, "games": 6014,
    "graphics_design": 6027, "health": 6013, "lifestyle": 6012, "medical": 6020, "music": 6011, "navigation": 6010, "news": 6009, "photo_video": 6008,
    "productivity": 6007, "reference": 6006, "shopping": 6024, "social": 6005, "sports": 6004,
    "travel": 6003, "utilities": 6002, "weather": 6001,
}
# Categories that exist but have no genre chart in the legacy RSS: Kids is an age-band section (no
# primary genre id), Stickers (6025) returns an empty chart, Magazines & Newspapers (6021) serves mostly
# News apps (live sweep 2026-09-28: 8–22/100 entries in 6021).
UNCHARTED_GENRES = {"kids": "age-band section, no RSS genre chart", "stickers": "6025 returns no entries",
                    "magazines_newspapers": "6021 chart is mostly News (6009) apps — not a genre chart"}
# Review/fit flags per genre: review_risk (App Review rejection risk for a solo newcomer) and fit (how
# well a solo SwiftUI subscription build fits the category's winners).
GENRE_FLAGS: dict[str, dict[str, str]] = {
    "medical": {"review_risk": "high", "why": "Guideline 1.4.1/5.1.3: medical claims need regulatory "
                "proof; health data rules"},
    "kids": {"review_risk": "high", "why": "Kids Category rules: no third-party analytics/ads, parental "
             "gates, COPPA — the template's Firebase/RevenueCat setup conflicts"},
    "finance": {"review_risk": "medium", "why": "Guideline 3.1.1/5.1: lending, crypto and trading apps "
                "need licensed entities"},
    "health": {"review_risk": "medium", "why": "health/medical claims and HealthKit data review"},
    "social": {"review_risk": "medium", "why": "UGC moderation, report/block requirements (1.2)",
               "fit": "low"},
    "games": {"review_risk": "low", "why": "games monetize through gameplay, not a SwiftUI subscription "
              "skeleton", "fit": "low"},
    "news": {"review_risk": "low", "why": "content operations, not a product build", "fit": "low"},
    "navigation": {"review_risk": "low", "why": "maps/data licensing + background location", "fit": "low"},
    "music": {"review_risk": "medium", "why": "music licensing", "fit": "low"},
}


def genre_id(genre: str | int | None) -> int | None:
    """GENRES name (or a numeric id) → genre id; None for unknown/None."""
    if genre is None:
        return None
    if isinstance(genre, int) or str(genre).isdigit():
        gid = int(genre)
        return gid if gid in GENRES.values() else None
    return GENRES.get(str(genre).lower().replace("&", "").replace(" ", "_").replace("__", "_"))


def genre_name(gid: int | None) -> str | None:
    return next((k for k, v in GENRES.items() if v == gid), None)


_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def search_hints(term: str, country: str = "us", expand: bool = False) -> dict[str, Any]:
    """App Store search autocomplete = REAL search demand (free, no auth). Idea-stage HARD GATE.

    Returns hints ordered by Apple's own popularity ranking. 0 hints for a real-word term = no demand
    → reject the idea. expand=True also appends a–z to the seed to harvest the keyword universe.
    IMPORTANT: an endpoint failure returns ok:False (NOT an empty list) — a broken endpoint must never
    read as "no competition" and greenlight every idea.
    """
    sf = STOREFRONTS.get(country.lower())
    if not sf:
        return {"ok": False, "error": f"bilinmeyen storefront '{country}' ({sorted(STOREFRONTS)})"}

    def _hints(t: str) -> list[str] | None:
        try:
            r = httpx.get(SEARCH_HINTS, params={"clientApplication": "Software", "term": t},
                          headers={"X-Apple-Store-Front": str(sf)}, timeout=20)
        except httpx.HTTPError:
            return None
        if not r.is_success:
            return None
        try:
            d = plistlib.loads(r.content)
        except Exception:  # noqa: BLE001 — malformed plist = endpoint change
            return None
        return [h.get("term") for h in d.get("hints", []) if h.get("term")]

    base = _hints(term)
    if base is None:
        return {"ok": False, "error": "search hints endpoint failed/changed (undocumented); "
                                      "do not confuse this with ZERO results, fix it before scoring the idea"}
    out = {"ok": True, "term": term, "country": country, "hints": base, "count": len(base),
           "demand": "none" if not base else ("weak" if len(base) < 5 else "strong")}
    if expand:
        seen = list(base)
        for ch in "abcdefghijklmnopqrstuvwxyz":
            more = _hints(f"{term} {ch}")
            if more:
                seen.extend(t for t in more if t not in seen)
        out["expanded"] = seen
        out["expanded_count"] = len(seen)
    return out


def competitor_iap(app_id: str | int, country: str = "us") -> dict[str, Any]:
    """Competitor subscription/IAP price ladder (App Store product page serialized-server-data).

    iTunes lookup does not return IAPs; the product page embeds them. FRAGILE (undocumented JSON shape): if it
    breaks it returns ok:False + prices:None; ABSENCE means 'unknown', NOT 'free'. Input to the two-product offer
    funnel pricing. Plain curl returns 0 bytes, so a browser UA + gzip are required.
    """
    url = f"https://apps.apple.com/{country}/app/id{app_id}"
    try:
        r = httpx.get(url, headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
                      timeout=25, follow_redirects=True)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"network: {e}", "prices": None}
    if not r.is_success:
        return {"ok": False, "status": r.status_code, "prices": None}
    m = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return {"ok": False, "error": "serialized-server-data not found (the page shape may have changed)",
                "prices": None}
    try:
        data = _json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"JSON parse: {e}", "prices": None}

    prices: list[dict[str, str]] = []

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("$kind") == "textPair" and n.get("leadingText") and n.get("trailingText"):
                prices.append({"name": str(n["leadingText"]), "price": str(n["trailingText"])})
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)

    _walk(data)
    # de-dup, keep order
    seen: set[tuple] = set()
    uniq = [p for p in prices if not (tuple(p.items()) in seen or seen.add(tuple(p.items())))]
    return {"ok": True, "app_id": str(app_id), "country": country,
            "prices": uniq, "count": len(uniq)}


def _genre_ai_density(country: str, genre: int, limit: int = 100) -> dict[str, Any]:
    """INFORMATIONAL: how many of the category's top-grossing apps are AI-branded. Context only — AI is
    an optional edge, never a requirement nor a penalty; not in the score."""
    chart = _fetch_chart(country, "grossing", genre, limit)
    if not chart.get("ok"):
        return {"ok": False, "error": chart.get("error"), "informational": True}
    names = [a.get("name") or "" for a in chart["apps"]]
    ai = [n for n in names if "ai" in re.findall(r"[a-z]+", n.lower())]
    return {"ok": True, "informational": True, "total": len(names), "ai_apps": len(ai), "examples": ai[:5],
            "note": "context only: AI presence neither raises nor lowers the score"}


def _newcomer_traction(apps: list[dict[str, Any]]) -> dict[str, Any]:
    """Can newcomers gain traction? The 'dead zone' test (iOS App Store, single storefront).

    weak_ratio alone is MISLEADING: a dead niche piles up tractionless apps, so weak_ratio
    rises and RAISES the score, the wrong sign. The real question: can newcomers hold on?

    TWO windows are REQUIRED. Looking at 12 months alone hides a closed door: hairstyle try-on
    (2026-07) showed 5 apps with traction over 12 months ("door open") but 12 entries in the last
    3 months with a best of 4 ratings; the door had closed in February and older success masked it.
    The NEAR window (6 months) is measured separately and can declare a dead zone on its own.

    The threshold depends on age: a 3-month-old app cannot collect 500 ratings (age effect), so in the
    near window 100 counts as enough; otherwise every fresh niche would wrongly look dead.
    """
    now = datetime.now(timezone.utc)
    far_cut, near_cut = now - timedelta(days=365), now - timedelta(days=180)
    far: list[int] = []
    near: list[int] = []
    for a in apps:
        d = a.get("released")
        if not d:
            continue
        try:
            rel = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            continue
        if rel < far_cut:
            continue
        rc = a.get("ratings_count") or 0
        far.append(rc)
        if rel >= near_cut:
            near.append(rc)

    if not apps:
        # NO apps at all = measurement failed (rate limit / empty response), NOT a "clean niche".
        # Treating it as OK reads as 'enterable' in a scan, i.e. approving an unmeasured niche.
        return {"window_12mo": {"count": 0, "best": 0, "traction_over_500": 0},
                "window_6mo": {"count": 0, "best": 0, "traction_over_100": 0},
                "dead_zone": False, "penalty": 0, "measured": False,
                "reason": "NOT MEASURED: competitor list is empty (rate limit?); result unusable"}
    if len(far) < 3:
        # Few samples = no evidence. Neither penalize nor mark as dead (normal for new/small niches).
        return {"window_12mo": {"count": len(far), "best": max(far, default=0), "traction_over_500": 0},
                "window_6mo": {"count": len(near), "best": max(near, default=0), "traction_over_100": 0},
                "dead_zone": False, "penalty": 0, "measured": True,
                "reason": "fewer than 3 entries in the last 12 months; insufficient evidence"}

    far_traction = sum(1 for c in far if c >= 500)
    far_best = max(far)
    near_traction = sum(1 for c in near if c >= 100)
    near_best = max(near, default=0)

    # Far window dead = the niche never opened.
    dead_far = far_traction == 0 and far_best < 200
    # Near window dead = the door has CLOSED (whatever the far window says). Enough samples are required,
    # otherwise "nobody tried" gets confused with "everyone tried and died".
    dead_near = len(near) >= 5 and near_traction == 0 and near_best < 100
    dead = dead_far or dead_near
    penalty = 0 if dead else (15 if far_traction == 1 else 0)

    if dead_near and not dead_far:
        reason = (f"DOOR CLOSED: {len(near)} entries in the last 6 months, best has {near_best} ratings; "
                  f"the 12-month window shows {far_traction} with traction but all are older than 6 months")
    elif dead_far:
        reason = f"DEAD ZONE: {len(far)} entries in the last 12 months, best has {far_best} ratings, none gained traction"
    else:
        reason = (f"entry possible: {len(far)} entries in the last 12 months / {far_traction} with 500+, "
                  f"{len(near)} entries in the last 6 months / {near_traction} with 100+")

    return {"window_12mo": {"count": len(far), "best": far_best, "traction_over_500": far_traction},
            "window_6mo": {"count": len(near), "best": near_best, "traction_over_100": near_traction},
            "dead_zone": dead, "penalty": penalty, "measured": True, "reason": reason}


def niche_score(term: str, country: str = "us", genre: str | None = None, *,
                _demand: dict[str, Any] | None = None, _comp: dict[str, Any] | None = None) -> dict[str, Any]:
    """Idea go/no-go score: demand (autocomplete) + competitor weakness + monetization.

    HARD GATE: autocomplete 0 hint = reject (no demand). Otherwise a 0-100 score.
    Competitor metrics use iTunes Search limit=50 (country PINNED: userRatingCount is per storefront,
    so comparisons are meaningless without a fixed country). limit>100 is silently clamped to 100.
    """
    demand = _demand if _demand is not None else search_hints(term, country)
    if not demand.get("ok"):
        return {"ok": False, "error": demand.get("error"), "stage": "demand"}
    hint_count = demand["count"]
    if hint_count == 0:
        return {"ok": True, "verdict": "REJECT", "score": 0, "term": term,
                "reason": "no App Store autocomplete suggestions; no real search demand",
                "demand": demand}

    comp = _comp if _comp is not None else fetch_competitors(term, country=country, limit=50)
    if not comp.get("ok"):
        return {"ok": False, "error": comp.get("error"), "stage": "competitors"}
    apps = comp["competitors"]
    counts = [a.get("ratings_count") or 0 for a in apps]
    median = statistics.median(counts) if counts else 0
    weak = sum(1 for c in counts if c < 1000)
    ceiling = max(counts) if counts else 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    stale = 0
    for a in apps:
        d = a.get("updated")
        if not d:
            continue
        try:
            if datetime.fromisoformat(d.replace("Z", "+00:00")) < cutoff:
                stale += 1
        except ValueError:
            continue

    n = len(apps) or 1
    weak_ratio, stale_ratio = weak / n, stale / n
    gid = genre_id(genre)
    density = (_genre_ai_density(country, gid) if gid else
               ({"ok": False, "error": f"unknown genre '{genre}' ({sorted(GENRES)})"} if genre else None))
    entrants = _newcomer_traction(apps)

    # Demand 40 / competition-softness 40 / monetization 20, MINUS a saturation penalty.
    s_demand = min(hint_count / 10, 1.0) * 40
    s_soft = (min(weak_ratio / 0.5, 1.0) * 30) + (min(stale_ratio / 0.3, 1.0) * 10)
    s_money = 20 if ceiling >= 100_000 else (12 if ceiling >= 10_000 else (5 if ceiling >= 1_000 else 0))
    # Saturation penalty: the stronger the median competitor, the harder the entry. weak_ratio alone misleads
    # (every niche has lots of dead apps); the real question is how entrenched the MEDIAN competitor is.
    if median >= 10_000:
        penalty = 45
    elif median >= 2_000:
        penalty = 30
    elif median >= 500:
        penalty = 15
    elif median >= 100:
        penalty = 5
    else:
        penalty = 0
    score = max(0, round(s_demand + s_soft + s_money - penalty))
    score = max(0, score - entrants["penalty"])
    if median > 50_000:
        verdict = "REJECT"          # saturated beyond recovery
    elif entrants["dead_zone"]:
        verdict = "REJECT"          # newcomers cannot hold on: a niche that LOOKS soft but cannot be entered
    elif score >= 60:
        verdict = "GO"
    elif score >= 40:
        verdict = "MAYBE"
    else:
        verdict = "WEAK"
    return {
        "ok": True, "term": term, "country": country, "score": score, "verdict": verdict,
        "demand": {"hints": hint_count, "top_terms": demand["hints"][:5]},
        "competition": {"sampled": n, "median_ratings": median, "weak_under_1k": weak,
                        "weak_ratio": round(weak_ratio, 2), "stale_180d": stale,
                        "stale_ratio": round(stale_ratio, 2), "ceiling_ratings": ceiling,
                        "saturation_penalty": penalty},
        "newcomers": entrants,
        "monetization": density,
        "note": "median>50k = saturated; ceiling>=100k = proven demand; high weak_ratio = easy entry; "
                "newcomers.dead_zone = entrants in the last 12 months failed to gain traction (LOOKS soft, cannot be entered)",
    }


def unit_economics(weekly_price: float = 7.99, yearly_price: float = 49.99,
                   weekly_credits: int = 10, yearly_monthly_credits: int = 60,
                   ai_cost_per_credit: float = 0.003, apple_cut: float = 0.15) -> dict[str, Any]:
    """Credit/cost/margin calculation; ties the price and credit-count decision to data.

    Until now the credit count (app.py default 15/10) was not tied to AI cost.
    apple_cut: Small Business Program 15% (under $1M/year); pass 0.30 for the standard 30% after the first year.
    """
    def _plan(price: float, credits_per_period: int, periods_per_year: float, label: str) -> dict[str, Any]:
        net = price * (1 - apple_cut)
        cost = credits_per_period * ai_cost_per_credit
        margin = net - cost
        return {
            "plan": label, "price": round(price, 2), "net_after_apple": round(net, 2),
            "credits_per_period": credits_per_period, "ai_cost_per_period": round(cost, 4),
            "margin_per_period": round(margin, 2),
            "margin_pct": round((margin / net * 100) if net else 0, 1),
            "annual_net_per_subscriber": round(margin * periods_per_year, 2),
            "breakeven_credits": int(net / ai_cost_per_credit) if ai_cost_per_credit else None,
        }

    weekly = _plan(weekly_price, weekly_credits, 52, "weekly")
    # yearly grants credits monthly → 12 periods, but is paid once a year
    yearly_net = yearly_price * (1 - apple_cut)
    yearly_cost = yearly_monthly_credits * ai_cost_per_credit * 12
    yearly = {
        "plan": "yearly", "price": round(yearly_price, 2), "net_after_apple": round(yearly_net, 2),
        "credits_per_period": yearly_monthly_credits, "ai_cost_per_year": round(yearly_cost, 4),
        "margin_per_year": round(yearly_net - yearly_cost, 2),
        "margin_pct": round(((yearly_net - yearly_cost) / yearly_net * 100) if yearly_net else 0, 1),
        "breakeven_credits_per_year": int(yearly_net / ai_cost_per_credit) if ai_cost_per_credit else None,
    }
    # Ladder sanity: yearly credits are PER MONTH, weekly credits PER WEEK — compare monthly-equivalents.
    weekly_monthly_equiv = weekly_credits * 52 / 12
    credit_ratio = (yearly_monthly_credits / weekly_monthly_equiv) if weekly_monthly_equiv else 0
    warnings = []
    if weekly["margin_pct"] < 80:
        warnings.append(f"weekly margin {weekly['margin_pct']}%; lower the credit count or raise the price")
    if yearly["margin_pct"] < 80:
        warnings.append(f"yearly margin {yearly['margin_pct']}%; the monthly credit allowance is too generous")
    if credit_ratio < 1.0:
        warnings.append(
            f"INVERTED LADDER: weekly monthly-equivalent {weekly_monthly_equiv:.0f} credits > yearly "
            f"{yearly_monthly_credits} credits/month; no reason to upgrade to yearly, raise the yearly credits")
    elif credit_ratio < 1.25:
        warnings.append(
            f"yearly gives only {credit_ratio:.2f}x credits; yearly is already much cheaper, "
            "the credit advantage should be clear too (target >=1.25x)")
    return {"ok": True, "weekly": weekly, "yearly": yearly,
            "ladder": {"weekly_monthly_equivalent_credits": round(weekly_monthly_equiv, 1),
                       "yearly_monthly_credits": yearly_monthly_credits,
                       "credit_ratio": round(credit_ratio, 2)},
            "ai_cost_per_credit": ai_cost_per_credit, "apple_cut": apple_cut,
            "warnings": warnings or ["margins and credit ladder are healthy"]}


def fetch_competitors(term: str, country: str = "us", limit: int = 10) -> dict[str, Any]:
    """Fetch competitor apps via the iTunes Search API (live, read-only)."""
    try:
        r = httpx.get(ITUNES_SEARCH, params={
            "term": term, "entity": "software", "country": country, "limit": limit,
        }, timeout=25)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"network: {e}"}
    if not r.is_success:
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    apps = []
    for a in r.json().get("results", []):
        apps.append({
            "name": a.get("trackName"),
            "bundleId": a.get("bundleId"),
            "seller": a.get("sellerName"),
            "genre": a.get("primaryGenreName"),
            "rating": a.get("averageUserRating"),
            "ratings_count": a.get("userRatingCount"),
            "price": a.get("formattedPrice"),
            "url": a.get("trackViewUrl"),
            # REQUIRED for the niche_score staleness signal (otherwise stale is always 0):
            "updated": a.get("currentVersionReleaseDate"),
            # REQUIRED for the dead-zone test: when the app was FIRST released (updated = last update, a different thing)
            "released": a.get("releaseDate"),
            "track_id": a.get("trackId"),
        })
    return {"ok": True, "count": len(apps), "competitors": apps}


def _get_json(url: str, params: dict[str, Any] | None = None, *, retries: int = 1,
              backoff: float = 2.0) -> tuple[Any, str | None]:
    """GET → (json, None) or (None, error). One polite retry on 403/429/5xx (Apple throttles bursts)."""
    last = ""
    for attempt in range(retries + 1):
        try:
            r = httpx.get(url, params=params, timeout=25)
        except httpx.HTTPError as e:
            last = f"network: {e}"
        else:
            if r.is_success:
                try:
                    return r.json(), None
                except Exception as e:  # noqa: BLE001
                    return None, f"JSON parse: {e}"
            last = f"HTTP {r.status_code}"
            if r.status_code not in (403, 429) and r.status_code < 500:
                break
        if attempt < retries and backoff:
            time.sleep(backoff * (attempt + 1))
    return None, last


def _fetch_chart(country: str, feed: str, genre: int | None, limit: int = 100) -> dict[str, Any]:
    """One legacy-RSS chart (feed: grossing|free). ok:False on ANY failure — never an empty list, and
    never the overall chart served in place of an ignored genre filter."""
    limit = max(1, min(int(limit), 100))  # the legacy RSS silently caps at 100
    if feed == "grossing":
        url = (ITUNES_RSS_TOP_GROSSING_GENRE.format(country=country, limit=limit, genre=genre) if genre
               else ITUNES_RSS_TOP_GROSSING.format(country=country, limit=limit))
    elif feed == "free":
        url = ITUNES_RSS_TOP_FREE_GENRE.format(country=country, limit=limit, genre=genre) if genre else \
            f"https://itunes.apple.com/{country}/rss/topfreeapplications/limit={limit}/json"
    else:
        return {"ok": False, "error": f"unknown feed '{feed}' (grossing|free)"}
    data, err = _get_json(url)
    if err:
        return {"ok": False, "error": err, "country": country, "feed": feed, "genre": genre}
    feed_obj = (data or {}).get("feed") if isinstance(data, dict) else None
    if not isinstance(feed_obj, dict):
        return {"ok": False, "error": "unexpected RSS shape (no feed object)", "country": country,
                "feed": feed, "genre": genre}
    entries = feed_obj.get("entry", [])
    if isinstance(entries, dict):  # a single-entry feed is an object, not a list
        entries = [entries]
    apps = []
    for rank, e in enumerate(entries, 1):
        cat = e.get("category", {}).get("attributes", {})
        apps.append({
            "id": str(e.get("id", {}).get("attributes", {}).get("im:id") or ""),
            "name": e.get("im:name", {}).get("label"),
            "seller": e.get("im:artist", {}).get("label"),
            "category": cat.get("label"),
            "genre_id": int(cat["im:id"]) if str(cat.get("im:id", "")).isdigit() else None,
            "released": e.get("im:releaseDate", {}).get("label"),
            "rank": rank,
            "url": next((l.get("attributes", {}).get("href") for l in
                         (e.get("link") if isinstance(e.get("link"), list) else [e.get("link") or {}])
                         if isinstance(l, dict)), None),
        })
    if genre and apps:
        matching = sum(1 for a in apps if a["genre_id"] == genre)
        if matching * 2 < len(apps):
            return {"ok": False, "country": country, "feed": feed, "genre": genre,
                    "error": f"genre filter ignored by the RSS ({matching}/{len(apps)} entries in genre "
                             f"{genre}) — this is not the genre chart"}
    return {"ok": True, "country": country, "feed": feed, "genre": genre, "count": len(apps),
            "empty": not apps, "apps": apps}


def top_grossing(country: str = "us", limit: int = 25, genre: str | int | None = None) -> dict[str, Any]:
    """Top-grossing apps (revenue proxy) — for hunting proven ideas. genre: a GENRES name or id (any
    App Store category); None = the overall chart."""
    gid = None
    if genre is not None:
        gid = genre_id(genre)
        if gid is None:
            return {"ok": False, "error": f"unknown genre '{genre}' (one of {sorted(GENRES)}; "
                                          f"uncharted: {sorted(UNCHARTED_GENRES)})"}
    chart = _fetch_chart(country, "grossing", gid, limit)
    if not chart.get("ok"):
        return {"ok": False, "error": chart.get("error")}
    apps = [{k: a[k] for k in ("name", "seller", "category", "url", "id", "rank")} for a in chart["apps"]]
    return {"ok": True, "count": len(apps), "genre": genre_name(gid) if gid else None, "top_grossing": apps}


def check_name_available(name: str, country: str = "us") -> dict[str, Any]:
    """App Store name must be globally UNIQUE — check for an exact-name conflict via iTunes Search.
    If available=False, that name is taken (submit will reject it)."""
    r = fetch_competitors(name, country=country, limit=25)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "iTunes search failed")}
    norm = name.strip().lower()
    conflicts = [a["name"] for a in r.get("competitors", [])
                 if a.get("name") and a["name"].strip().lower() == norm]
    return {"ok": True, "name": name, "available": not conflicts,
            "conflict": conflicts[0] if conflicts else None}


def find_available_name(candidates: list[str], country: str = "us") -> dict[str, Any]:
    """Pick the first AVAILABLE candidate name (not taken on the App Store). Call BEFORE asc_create_app."""
    checked = []
    for c in candidates:
        res = check_name_available(c, country)
        checked.append({"name": c, "available": res.get("available"), "conflict": res.get("conflict")})
        if res.get("ok") and res.get("available"):
            return {"ok": True, "available_name": c, "checked": checked}
    return {"ok": False, "available_name": None, "checked": checked,
            "error": "no candidate available — try new candidates"}


APPLE_METADATA_SKELETON = """# Apple App Store Metadata — {app}

Copy-paste ready. Languages: {locales}
Limits: App Name 30 · Subtitle 30 · Promotional Text 170 · Keyword Field 100 · Description 4000 · What's New 4000

{sections}
"""

_LOCALE_SECTION = """# {locale}
## App Name
```

```
## Subtitle
```

```
## Promotional Text
```

```
## Keyword Field
```

```
## Description
```

```
## What's New
```

```
"""


def scaffold_outputs(app_name: str, base_dir: str | Path, locales: list[str] | None = None) -> dict[str, Any]:
    """Set up the outputs/<App>/ skeleton (01-research, 02-metadata, 05/06)."""
    locs = locales or cfg.APP_STORE_LOCALES
    root = Path(base_dir).expanduser() / "outputs" / app_name
    for sub in ("01-research", "02-metadata", "05-optimization", "06-growth-roadmap"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    sections = "\n".join(_LOCALE_SECTION.format(locale=l) for l in locs)
    md = APPLE_METADATA_SKELETON.format(app=app_name, locales=", ".join(locs), sections=sections)
    (root / "02-metadata" / "apple-metadata.md").write_text(md, encoding="utf-8")
    (root / "01-research" / "keyword-list.md").write_text(f"# Keyword List — {app_name}\n\n(aso-research will fill this in)\n", encoding="utf-8")
    return {"ok": True, "outputs_dir": str(root), "locales": locs,
            "apple_metadata": str(root / "02-metadata" / "apple-metadata.md")}


def validate_metadata(app_name: str, base_dir: str | Path) -> dict[str, Any]:
    """Validate outputs/<App>/02-metadata/apple-metadata.md (metadata.check)."""
    src = Path(base_dir).expanduser() / "outputs" / app_name / "02-metadata" / "apple-metadata.md"
    return meta.check(src)
