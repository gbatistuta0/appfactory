"""Idea phase across every category: genre map, genre-aware charts, idea_harvest, idea_evaluate.
All HTTP is mocked (no network)."""

from __future__ import annotations

import asyncio
import plistlib
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastmcp import Client

from appfactory import aso, ideas
from appfactory.server import mcp

NOW = datetime.now(timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry(app_id: str, name: str, genre: int, released_days: int, seller: str = "Indie Co") -> dict:
    return {"id": {"attributes": {"im:id": app_id}}, "im:name": {"label": name},
            "im:artist": {"label": seller},
            "category": {"attributes": {"im:id": str(genre), "label": aso.genre_name(genre) or "?"}},
            "im:releaseDate": {"label": _iso(released_days)},
            "link": {"attributes": {"href": f"https://apps.apple.com/app/id{app_id}"}}}


class Router:
    """Fake httpx.get: routes by URL; records calls."""

    def __init__(self, charts=None, lookup=None, fail=(), hints=None, search=None, page=None):
        self.charts = charts or {}   # (country, feed, genre) -> list of entries
        self.lookup = lookup or {}   # id -> result dict
        self.fail = set(fail)        # (country, feed, genre) that 500
        self.hints = hints or []
        self.search = search or []
        self.page = page
        self.calls: list[str] = []

    def __call__(self, url, params=None, headers=None, timeout=None, follow_redirects=None):
        self.calls.append(url)
        req = httpx.Request("GET", url)
        m = re.match(r"https://itunes.apple.com/(\w+)/rss/top(grossing|free)applications/limit=\d+(?:/genre=(\d+))?/json", url)
        if m:
            key = (m.group(1), "grossing" if m.group(2) == "grossing" else "free", int(m.group(3) or 0))
            if key in self.fail:
                return httpx.Response(500, request=req, text="boom")
            entries = self.charts.get(key, [])
            return httpx.Response(200, request=req, json={"feed": {"entry": entries} if entries else {}})
        if url == aso.ITUNES_LOOKUP:
            ids = params["id"].split(",")
            return httpx.Response(200, request=req, json={"results": [self.lookup[i] for i in ids if i in self.lookup]})
        if url == aso.SEARCH_HINTS:
            return httpx.Response(200, request=req,
                                  content=plistlib.dumps({"hints": [{"term": h} for h in self.hints]}))
        if url == aso.ITUNES_SEARCH:
            return httpx.Response(200, request=req, json={"results": self.search})
        if url.startswith("https://apps.apple.com/"):
            if self.page is None:
                return httpx.Response(404, request=req)
            return httpx.Response(200, request=req, text=self.page)
        return httpx.Response(404, request=req)


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(aso.httpx, "get", r)
    monkeypatch.setattr(aso.time, "sleep", lambda s: None)
    return r


# ---- genre map ----

def test_genre_map_covers_every_category():
    assert len(aso.GENRES) == 24 and len(set(aso.GENRES.values())) == 24
    for name, gid in {"books": 6018, "business": 6000, "education": 6017, "entertainment": 6016,
                      "finance": 6015, "food_drink": 6023, "graphics_design": 6027, "health": 6013,
                      "lifestyle": 6012, "medical": 6020, "music": 6011, "navigation": 6010, "news": 6009,
                      "photo_video": 6008, "productivity": 6007, "reference": 6006, "shopping": 6024,
                      "social": 6005, "sports": 6004, "travel": 6003, "utilities": 6002, "weather": 6001,
                      "developer_tools": 6026, "games": 6014}.items():
        assert aso.GENRES[name] == gid
    assert {"kids", "stickers", "magazines_newspapers"} <= set(aso.UNCHARTED_GENRES)
    assert not set(aso.UNCHARTED_GENRES) & set(aso.GENRES)
    assert aso.GENRE_FLAGS["medical"]["review_risk"] == "high"
    assert aso.GENRE_FLAGS["kids"]["review_risk"] == "high"
    assert aso.genre_id("Food & Drink") == 6023 and aso.genre_id(6007) == 6007 and aso.genre_id("6015") == 6015
    assert aso.genre_id("nope") is None and aso.genre_id(1234) is None


def test_top_grossing_genre(router):
    router.charts[("us", "grossing", 6015)] = [_entry("1", "Budget Pro", 6015, 400)]
    r = aso.top_grossing("us", 10, genre="finance")
    assert r["ok"] and r["genre"] == "finance" and r["top_grossing"][0]["name"] == "Budget Pro"
    assert "/genre=6015/" in router.calls[-1]
    assert aso.top_grossing("us", genre="kids")["ok"] is False          # uncharted, never the overall chart


def test_ignored_genre_filter_is_a_failure(router):
    # Apple ignores an unknown genre id and serves the overall chart: must not pass as the genre chart.
    router.charts[("us", "grossing", 6015)] = [_entry(str(i), f"App{i}", 6007, 400) for i in range(4)]
    r = aso.top_grossing("us", genre="finance")
    assert r["ok"] is False and "ignored" in r["error"]


def test_genre_ai_density_is_informational(router):
    router.charts[("us", "grossing", 6002)] = [_entry("1", "Cleaner AI", 6002, 900), _entry("2", "Files", 6002, 900)]
    d = aso._genre_ai_density("us", 6002)
    assert d["ok"] and d["informational"] and d["ai_apps"] == 1 and d["total"] == 2


# ---- idea_harvest ----

def _harvest_router(router):
    g = 6015
    router.charts[("us", "grossing", g)] = [_entry("10", "Old Bank", g, 2000, "BigBank"),
                                            _entry("11", "New Budget", g, 100), _entry("12", "Fresh Tax", g, 60)]
    router.charts[("us", "free", g)] = [_entry("11", "New Budget", g, 100), _entry("13", "My Own App", g, 30, "Founder")]
    router.charts[("gb", "grossing", g)] = [_entry("11", "New Budget", g, 100)]
    router.fail.add(("gb", "free", g))
    router.lookup.update({
        "10": {"trackId": 10, "userRatingCount": 90000, "releaseDate": _iso(2000), "formattedPrice": "Free"},
        "11": {"trackId": 11, "userRatingCount": 1000, "releaseDate": _iso(100), "formattedPrice": "Free"},
        "12": {"trackId": 12, "userRatingCount": 900, "releaseDate": _iso(60), "formattedPrice": "Free"},
    })


def test_idea_harvest_proven_newcomers_clusters(router):
    _harvest_router(router)
    r = ideas.harvest(countries=["us", "gb"], genres=["finance"], exclude_terms=["founder"], delay=0, workers=1)
    assert r["ok"] and r["partial"] and r["feeds_ok"] == 3 and r["feeds_failed"] == 1
    assert r["failed_feeds"][0] == {"genre": "finance", "country": "gb", "feed": "free", "ok": False,
                                    "error": "HTTP 500"}
    assert r["excluded"] == ["My Own App"]
    proven = [a["name"] for a in r["chart_proven"]]
    assert proven[0] == "New Budget"                                    # charts in 2 grossing feeds
    assert set(proven) == {"New Budget", "Old Bank", "Fresh Tax"}
    rising = r["rising_newcomers"]
    assert [a["name"] for a in rising] == ["Fresh Tax", "New Budget"]   # 900/60 = 15/day > 1000/100
    assert rising[0]["ratings"] == 900 and rising[0]["ratings_per_day"] == 15.0
    c = r["clusters"][0]
    assert c["genre"] == "finance" and c["newcomers_in_grossing"] == 2 and c["grossing_apps"] == 3
    assert c["open_niche"] == "some"                                    # < 3 newcomers in grossing
    assert c["review_risk"] == "medium"


def test_idea_harvest_all_feeds_failed_is_not_empty(router):
    router.fail.update({("us", "grossing", 6015), ("us", "free", 6015)})
    r = ideas.harvest(countries=["us"], genres=["finance"], delay=0, workers=1)
    assert r["ok"] is False and "NOT 'no apps'" in r["error"]


def test_idea_harvest_defaults_to_all_genres(router):
    r = ideas.harvest(countries=["us"], feeds=["grossing"], delay=0, workers=2)
    assert r["ok"] and r["swept"]["genres"] == list(aso.GENRES) and r["feeds_ok"] == 24
    assert all(c["open_niche"] == "closed" for c in r["clusters"])     # empty charts measured, no newcomers
    assert ideas.harvest(genres=["kids"], delay=0)["ok"] is False


def test_idea_harvest_unlooked_ratings_are_none(router):
    _harvest_router(router)
    router.lookup.clear()
    r = ideas.harvest(countries=["us"], genres=["finance"], feeds=["grossing"], delay=0, workers=1)
    assert all(a["ratings"] is None for a in r["rising_newcomers"])    # unknown, not 0


# ---- idea_evaluate ----

PAGE = ('<script type="application/json" id="serialized-server-data">'
        '[{"$kind":"textPair","leadingText":"Pro Yearly","trailingText":"$39.99"}]</script>')


def _search(n=12):
    out = []
    for i in range(n):
        out.append({"trackName": f"Budget {i}", "trackId": 100 + i, "sellerName": "S",
                    "primaryGenreName": "Finance", "userRatingCount": 300 * (i + 1),
                    "releaseDate": _iso(40 + i * 10), "currentVersionReleaseDate": _iso(10),
                    "formattedPrice": "Free", "averageUserRating": 4.5})
    return out


def test_idea_evaluate_bundle(router):
    router.hints = [f"budget planner {i}" for i in range(8)]
    router.search = _search()
    router.page = PAGE
    r = ideas.evaluate("budget planner", "us", name_candidates=["Budget 3", "Pennywise Q"], delay=0)
    assert r["ok"] and r["genre"] == "finance" and r["genre_inferred"]
    assert r["autocomplete"]["count"] == 8
    assert r["niche"]["verdict"] in {"GO", "MAYBE", "WEAK", "REJECT"}
    assert set(r["newcomer_traction"]) >= {"window_12mo", "window_6mo", "dead_zone"}
    assert len(r["leaders"]) == 3 and r["leaders"][0]["ratings"] == 3600
    assert r["leaders"][0]["price_ladder"] == [{"name": "Pro Yearly", "price": "$39.99"}]
    assert r["ai_needed"]["heuristic"] == "optional" and r["ai_needed"]["claude_assessment"] is None
    assert r["build_complexity"]["level"] == "medium"                  # "budget" = platform work beyond skeleton
    assert r["review_risk"]["level"] == "medium"                       # finance genre
    assert r["name_availability"]["available_name"] == "Pennywise Q"


def test_idea_evaluate_ai_and_risk_heuristics(router):
    router.hints = ["ai headshot generator"]
    router.search = [{**a, "primaryGenreName": "Medical"} for a in _search(3)]
    r = ideas.evaluate("ai headshot generator", "us", leaders=0, delay=0)
    assert r["ai_needed"]["heuristic"] == "yes" and r["build_complexity"]["level"] == "medium"
    assert r["review_risk"]["level"] == "high"                         # medical genre inferred
    router.hints = ["water reminder"]
    router.search = [{**a, "primaryGenreName": "Health & Fitness"} for a in _search(3)]
    r2 = ideas.evaluate("water reminder", "us", leaders=0, delay=0)
    assert r2["ai_needed"]["heuristic"] == "no"                        # not a minus: AI is optional


def test_idea_evaluate_failed_demand_is_error(router, monkeypatch):
    monkeypatch.setattr(aso, "search_hints", lambda t, c: {"ok": False, "error": "endpoint changed"})
    r = ideas.evaluate("anything", "us", delay=0)
    assert r["ok"] is False and r["stage"] == "demand"
    assert ideas.evaluate("x", genre="nope")["ok"] is False


def test_idea_tools_registered():
    async def _names():
        async with Client(mcp) as c:
            return {t.name for t in await c.list_tools()}
    names = asyncio.run(_names())
    assert {"idea_harvest", "idea_evaluate", "aso_top_grossing"} <= names


def test_idea_harvest_open_niche_signal(router):
    g = 6002
    router.charts[("us", "grossing", g)] = [_entry(str(i), f"New {i}", g, 50) for i in range(3)] + \
        [_entry("9", "Old", g, 3000)]
    r = ideas.harvest(countries=["us"], genres=["utilities"], feeds=["grossing"], delay=0, workers=1)
    c = r["clusters"][0]
    assert c["newcomer_grossing_share"] == 0.75 and c["open_niche"] == "open"
