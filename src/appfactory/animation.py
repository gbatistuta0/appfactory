"""Cute Lottie animations for apps — fetch from LottieFiles free library + recolor to app palette.

Pipeline (headless, no npm): LottieFiles public GraphQL (no auth, Lottie Simple License = commercial,
no attribution) → pick top-viewed match by keyword → recolor JSON to the app's DS.Palette (dominant→primary,
second→accent, preserve near-black/near-white) → write Resources/Animations/<slot>.json. lottie-spm renders it.
Colors in Lottie JSON: fill/stroke items ("ty":"fl"/"st") have c.k=[r,g,b,a] normalized 0..1; gradients
("ty":"gf") have g.k.k=[stop,r,g,b,...]. We recurse shapes/groups.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

GRAPHQL = "https://graphql.lottiefiles.com/"
_SEARCH = """query Search($q: String!) {
  searchPublicAnimations(query: $q, first: 8, orderBy: { column: VIEWS_COUNT, order: DESC }) {
    edges { node { name slug jsonUrl lottieUrl bgColor } }
  }
}"""

# Default keyword per slot (app can override via keyword arg for on-theme cuteness).
SLOT_KEYWORDS = {
    "loading": "cute loading",
    "success": "success celebration confetti",
    "empty": "empty box cute",
    "onboarding_hero": "cute welcome hero",
}


_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def _post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (trusted host)
        return json.loads(r.read().decode())


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def search(keyword: str) -> list[dict[str, Any]]:
    """Top-viewed free animations for a keyword. Returns [{name, slug, jsonUrl, bgColor}]."""
    d = _post_json(GRAPHQL, {"query": _SEARCH, "variables": {"q": keyword}})
    edges = (((d.get("data") or {}).get("searchPublicAnimations") or {}).get("edges")) or []
    return [e["node"] for e in edges if e.get("node", {}).get("jsonUrl")]


def _hex_to_rgb01(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _is_neutral(rgb: tuple[float, float, float], eps: float = 0.14) -> bool:
    """Near-black / near-white / near-gray — DON'T recolor (backgrounds, outlines, eyes)."""
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    if mx <= eps or mn >= 1 - eps:      # near black / near white
        return True
    return (mx - mn) <= eps             # near gray (low saturation)


def _walk_colors(node: Any, apply):
    """Recurse Lottie tree, calling apply([r,g,b]) on every solid fill/stroke color array (in place)."""
    if isinstance(node, dict):
        ty = node.get("ty")
        if ty in ("fl", "st"):  # fill / stroke
            c = node.get("c")
            if isinstance(c, dict) and c.get("a") == 0 and isinstance(c.get("k"), list) and len(c["k"]) >= 3:
                apply(c["k"])
        # gradients: g.k.k = [stop,r,g,b, stop,r,g,b, ...] — recolor RGB triplets in place
        if ty == "gf" and isinstance(node.get("g"), dict):
            gk = node["g"].get("k", {})
            arr = gk.get("k") if isinstance(gk, dict) else None
            if isinstance(arr, list):
                for i in range(0, len(arr) - 3, 4):
                    apply(arr, i + 1)   # rgb starts at offset+1
        for v in node.values():
            _walk_colors(v, apply)
    elif isinstance(node, list):
        for v in node:
            _walk_colors(v, apply)


def recolor(anim: dict[str, Any], primary_hex: str, accent_hex: str) -> dict[str, Any]:
    """Recolor in place: dominant color → primary, everything else non-neutral → accent.
    Preserves near-black/white/gray. Simple + robust across arbitrary cute assets (no keypaths)."""
    prim = _hex_to_rgb01(primary_hex)
    acc = _hex_to_rgb01(accent_hex)

    # Pass 1: find the dominant non-neutral color (by frequency).
    freq: dict[tuple, int] = {}

    def _tally(arr, off=0):
        rgb = (round(arr[off], 3), round(arr[off + 1], 3), round(arr[off + 2], 3))
        if not _is_neutral(rgb):
            freq[rgb] = freq.get(rgb, 0) + 1

    _walk_colors(anim, _tally)
    dominant = max(freq, key=freq.get) if freq else None

    # Pass 2: apply.
    def _apply(arr, off=0):
        rgb = (round(arr[off], 3), round(arr[off + 1], 3), round(arr[off + 2], 3))
        if _is_neutral(rgb):
            return
        tgt = prim if (dominant and rgb == dominant) else acc
        arr[off], arr[off + 1], arr[off + 2] = tgt

    _walk_colors(anim, _apply)
    return anim


def fetch_recolor(app_dir: str, slot: str, primary_hex: str, accent_hex: str,
                  keyword: str | None = None) -> dict[str, Any]:
    """Fetch a cute free Lottie for `slot`, recolor to palette, write Resources/Animations/<slot>.json.

    slot: loading | success | empty | onboarding_hero. keyword: on-theme override (else slot default).
    primary_hex/accent_hex: app DS.Palette light hex (e.g. '006A63'). Returns {ok, path, source_name}.
    """
    if slot not in SLOT_KEYWORDS:
        return {"ok": False, "error": f"bilinmeyen slot '{slot}' (loading|success|empty|onboarding_hero)"}
    kw = keyword or SLOT_KEYWORDS[slot]
    try:
        hits = search(kw)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"LottieFiles search failed: {e}"}
    if not hits:
        return {"ok": False, "error": f"no results for '{kw}' — try a different keyword"}
    node = hits[0]
    try:
        anim = json.loads(_get(node["jsonUrl"]).decode())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"JSON indirilemedi ({node.get('name')}): {e}"}

    recolor(anim, primary_hex, accent_hex)

    out_dir = Path(app_dir) / "Resources" / "Animations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slot}.json"
    out.write_text(json.dumps(anim, separators=(",", ":")), encoding="utf-8")
    return {"ok": True, "path": str(out), "source_name": node.get("name"),
            "slug": node.get("slug"), "keyword": kw}


if __name__ == "__main__":  # self-check: recolor swaps non-neutral, preserves neutral
    demo = {"layers": [{"shapes": [
        {"ty": "fl", "c": {"a": 0, "k": [0.9, 0.1, 0.1, 1]}},   # red → dominant → primary
        {"ty": "st", "c": {"a": 0, "k": [0.02, 0.02, 0.02, 1]}},  # near-black → preserved
        {"ty": "fl", "c": {"a": 0, "k": [0.1, 0.1, 0.9, 1]}},   # blue → accent
    ]}]}
    recolor(demo, "006A63", "00649A")  # primary teal, accent blue
    fills = demo["layers"][0]["shapes"]
    assert fills[0]["c"]["k"][:3] == list(_hex_to_rgb01("006A63")), fills[0]["c"]["k"]
    assert fills[1]["c"]["k"][:3] == [0.02, 0.02, 0.02], "near-black must be preserved"
    assert fills[2]["c"]["k"][:3] == list(_hex_to_rgb01("00649A")), fills[2]["c"]["k"]
    print("recolor self-check OK")
