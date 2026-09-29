"""Rasterize a Claude Design board to PNG with local headless Chrome.

Input is the short-lived `serve_url` returned by `mcp__claude-design__render_preview`. It embeds a
project-scoped token, so it is used once here and never returned, logged or written to disk. Claude in
Chrome is not used (factory rule); this is a plain headless Chrome process.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path
from typing import Any

from ..proc import run

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def chrome_binary() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def png_info(path: Path) -> dict[str, int] | None:
    """(width, height, color_type) from the PNG IHDR; None when not a PNG."""
    try:
        head = path.read_bytes()[:26]
    except OSError:
        return None
    if len(head) < 26 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return {"width": w, "height": h, "color_type": head[25]}


def export_png(serve_url: str, out_path: str | Path, width: int, height: int, scale: int = 1) -> dict[str, Any]:
    if not str(serve_url).startswith("https://"):
        return {"ok": False, "error": "serve_url must be the https serve_url from render_preview"}
    chrome = chrome_binary()
    if chrome is None:
        return {"ok": False, "error": "Google Chrome/Chromium not found for headless export"}
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    r = run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
             f"--window-size={width},{height}", f"--force-device-scale-factor={scale}",
             "--virtual-time-budget=5000", f"--screenshot={out}", serve_url], timeout=120)
    info = png_info(out) if out.exists() else None
    if not r.get("ok") or info is None:
        # never echo the command (it carries the tokenized URL)
        return {"ok": False, "error": "headless Chrome export failed", "stderr": str(r.get("stderr", ""))[-300:]}
    expect = (width * scale, height * scale)
    if (info["width"], info["height"]) != expect:
        return {"ok": False, "error": f"exported {info['width']}×{info['height']}, expected {expect[0]}×{expect[1]}",
                "path": str(out)}
    return {"ok": True, "path": str(out), "width": info["width"], "height": info["height"]}
