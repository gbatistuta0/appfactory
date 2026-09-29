# tests/test_session.py
from __future__ import annotations

import datetime as dt

from appfactory import config


def _blob(created_at: dt.datetime, max_age: int = 2592000) -> str:
    ts = created_at.strftime("%Y-%m-%d %H:%M:%S") + ".000000000 +00:00"
    return ("--- \n- !ruby/object:HTTP::Cookie\n"
            "  name: DESabc\n  domain: idmsa.apple.com\n"
            f"  max_age: {max_age}\n  created_at: {ts}\n")


def test_session_fresh():
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    r = config.session_status(_blob(created))
    assert r["present"] is True
    assert r["stale"] is False
    assert r["hours_left"] > 24


def test_session_stale_when_expired():
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)
    r = config.session_status(_blob(created))
    assert r["present"] is True
    assert r["stale"] is True


def test_session_stale_within_24h_margin():
    # 30-day cookie, created 29.5 days ago → ~12h left → stale
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=29, hours=12)
    r = config.session_status(_blob(created))
    assert r["stale"] is True


def test_session_absent():
    r = config.session_status("")
    assert r["present"] is False
    assert r["stale"] is True


import asyncio
from fastmcp import Client
from appfactory.server import mcp


def test_config_doctor_includes_session():
    async def _call():
        async with Client(mcp) as c:
            r = await c.call_tool("config_doctor", {})
            return r.data if hasattr(r, "data") else r

    d = asyncio.run(_call())
    assert "session" in d
    assert "stale" in d["session"]
