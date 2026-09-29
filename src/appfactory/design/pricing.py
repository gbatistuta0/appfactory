"""Paywall numbers straight from the spec products (never typed into a board by hand)."""

from __future__ import annotations

import re
from typing import Any

from .. import spec as spec_mod

_PERIOD = re.compile(r"^P(\d+)([DWMY])$")
_UNIT_WEEKS = {"D": 1 / 7, "W": 1.0, "M": 52 / 12, "Y": 52.0}
_NAMES = {("W", 1): ("Weekly", "week"), ("M", 1): ("Monthly", "month"), ("Y", 1): ("Yearly", "year")}


def weeks(period: str) -> float:
    m = _PERIOD.match(period)
    if not m:
        raise ValueError(f"bad ISO period {period!r}")
    return int(m.group(1)) * _UNIT_WEEKS[m.group(2)]


def period_name(period: str) -> tuple[str, str]:
    """('Yearly', 'year') for P1Y, ('3 months', '3 months') for P3M."""
    m = _PERIOD.match(period)
    n, u = int(m.group(1)), m.group(2)
    if (u, n) in _NAMES:
        return _NAMES[(u, n)]
    word = {"D": "day", "W": "week", "M": "month", "Y": "year"}[u]
    label = f"{n} {word}s"
    return label[:1].upper() + label[1:], label


def duration_text(iso: str) -> str:
    m = _PERIOD.match(iso)
    n, u = int(m.group(1)), m.group(2)
    word = {"D": "day", "W": "week", "M": "month", "Y": "year"}[u]
    return f"{n} {word}{'s' if n != 1 else ''}"


def money(usd: float) -> str:
    return f"${usd:,.2f}"


def plans(spec: dict[str, Any], offering: str = "default") -> list[dict[str, Any]]:
    """Products of one offering with display strings, shortest period first."""
    out = []
    for p in spec_mod.products(spec):
        if p.get("offering") != offering:
            continue
        name, unit = period_name(p["period"])
        per_week = p["usd"] / weeks(p["period"])
        intro = p.get("intro") or None
        trial = f"{duration_text(intro['duration'])} free" if intro and intro.get("type") == "free" else None
        out.append({**p, "name": name, "unit": unit, "price": money(p["usd"]), "per_week": per_week,
                    "per_week_text": money(per_week) + " / week", "per_month_text": money(p["usd"] / (weeks(p["period"]) / (52 / 12))),
                    "trial": trial})
    out.sort(key=lambda x: weeks(x["period"]))
    if len(out) > 1:
        top = max(x["per_week"] for x in out)
        best = min(out, key=lambda x: x["per_week"])
        save = round((1 - best["per_week"] / top) * 100)
        for x in out:
            x["badge"] = f"SAVE {save}%" if x is best and save > 0 else None
            x["preselected"] = x is best
    elif out:
        out[0]["badge"], out[0]["preselected"] = None, True
    return out


def offer(spec: dict[str, Any]) -> dict[str, Any] | None:
    """The offer product vs the regular product of the same period (strike price, % off)."""
    offers = plans(spec, "offer")
    if not offers:
        return None
    o = offers[0]
    regular = next((p for p in plans(spec, "default") if p["period"] == o["period"]), None)
    off = round((1 - o["usd"] / regular["usd"]) * 100) if regular and regular["usd"] > o["usd"] else 0
    anchor = spec.get("offer_anchor") or {}
    return {**o, "regular": regular, "off": off, "anchor_item": anchor.get("item", "coffee"),
            "anchor_key": anchor.get("label_key")}
