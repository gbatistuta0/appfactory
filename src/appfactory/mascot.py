"""mascot_* — animate the APPROVED mascot poses; never rig from a parts sheet.

LESSON: a separately generated layered "parts sheet" drifts off-model. The pipeline is:
1. the founder approves one PNG per state (idle, wave, cheer, think, love, snap, trophy, sleep)
   → `<app>/design/mascot/<state>.png`;
2. `mascot_blink` makes a pixel-aligned closed-eye copy of each pose (`<state>-blink.png`);
3. `mascot_assets` imports poses + blinks into `Resources/Assets.xcassets/Mascot/` for MascotView;
4. `design_generate` renders the motion boards (canvas page "mascot") from the same PNGs.

The blink step needs OpenCV/NumPy/Pillow (`uv sync --extra mascot`); everything else is stdlib.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import spec as spec_mod

MASCOT_DIR = "design/mascot"
ASSETS_DIR = "Resources/Assets.xcassets/Mascot"
INK = (58, 36, 24, 255)  # closed-lid line color (dark warm brown reads on any fur)
_MISSING = ("mascot_blink needs the optional extra: `uv sync --extra mascot` "
            "(opencv-python-headless, numpy, pillow)")
# A state without its own approved pose borrows another (e.g. `think` for `sleep`).
FALLBACK = {"sleep": "think", "love": "idle", "snap": "idle", "trophy": "cheer", "cheer": "idle",
            "think": "idle", "wave": "idle"}


def _deps() -> tuple[Any, Any, Any, Any] | None:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        return None
    return cv2, np, Image, ImageDraw


def available() -> bool:
    return _deps() is not None


def _eye_masks(rgba: Any, cv2: Any, np: Any) -> list[tuple[Any, tuple[int, int, int, int]]]:
    """Iris blobs in the upper 55 %, grown into the whole eye (white + outline)."""
    rgb, a = rgba[..., :3].astype(int), rgba[..., 3]
    h, w = a.shape
    dark = (rgb[..., 0] < 90) & (rgb[..., 1] < 60) & (rgb[..., 2] < 50) & (a > 200)
    dark[int(h * 0.55):] = False
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8), 8)
    area = w * h
    cands = []
    for i in range(1, n):
        x, y, bw, bh, ar = stats[i]
        # Iris blobs are compact (not the long outline) and sizeable.
        if ar > area * 0.004 and 0.6 < bw / bh < 1.6 and bw < w * 0.2:
            cands.append((ar, i, x, y, bw, bh))
    cands = sorted(cands, reverse=True)[:2]
    white = (rgb.min(axis=2) > 222) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 16) & (a > 200)
    eyeish = (white | ((rgb.sum(axis=2) < 260) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 70))) & (a > 200)
    masks = []
    for _, i, x, y, bw, bh in cands:
        seed = (lab == i).astype(np.uint8)
        pad = int(max(bw, bh) * 0.42)
        box = np.zeros_like(seed)
        cv2.ellipse(box, (int(x + bw // 2), int(y + bh // 2)), (int(bw // 2 + pad), int(bh // 2 + pad)), 0, 0, 360, 1, -1)
        region = (eyeish & box.astype(bool)).astype(np.uint8)
        grown = seed.copy()
        k = np.ones((3, 3), np.uint8)
        for _ in range(pad):
            grown = cv2.dilate(grown, k) & region | seed
        grown = cv2.morphologyEx(grown, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        grown = cv2.dilate(grown, np.ones((7, 7), np.uint8))
        # Fill interior holes so no iris fragment survives to seed the inpaint.
        cs, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        grown = cv2.drawContours(np.zeros_like(grown), cs, -1, 1, -1)
        # Swallow dark outline/lash pixels hugging the edge, then pad.
        darkish = ((rgb.sum(axis=2) < 420) & (a > 200)).astype(np.uint8)
        for _ in range(4):
            grown = grown | (cv2.dilate(grown, np.ones((5, 5), np.uint8)) & darkish)
        grown = cv2.dilate(grown, np.ones((5, 5), np.uint8))
        masks.append((grown, (int(x), int(y), int(bw), int(bh))))
    return masks


def blink_one(path: str | Path) -> dict[str, Any]:
    """Write `<name>-blink.png` next to `path`: eyes inpainted with the surrounding color + closed-lid arcs."""
    deps = _deps()
    if deps is None:
        return {"ok": False, "error": _MISSING}
    cv2, np, Image, ImageDraw = deps
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"not found: {p}"}
    im = Image.open(p).convert("RGBA")
    rgba = np.array(im)
    masks = _eye_masks(rgba, cv2, np)
    if len(masks) != 2:
        return {"ok": False, "path": str(p), "error": f"found {len(masks)} eye(s), need 2 — pose gets no blink "
                "(MascotView then shows it without blinking)"}
    out = rgba.copy()
    bgr = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2BGR)
    full = np.zeros(rgba.shape[:2], np.uint8)
    for m, _ in masks:
        full |= m
    radius = max(3, int(rgba.shape[1] * 0.012))
    fill = cv2.inpaint(bgr, full * 255, radius, cv2.INPAINT_TELEA)
    out[..., :3] = np.where(full[..., None] > 0, cv2.cvtColor(fill, cv2.COLOR_BGR2RGB), rgba[..., :3])
    res = Image.fromarray(out)
    s = 4  # draw the lids at 4x for anti-aliasing
    layer = Image.new("RGBA", (res.width * s, res.height * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for m, _ in masks:
        ys, xs = np.where(m > 0)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        cx, cy, ew = (x0 + x1) / 2, y0 + (y1 - y0) * 0.55, (x1 - x0) * 0.78
        sag = ew * 0.28
        lw = max(2, round(res.width * 0.011))
        d.arc([(cx - ew / 2) * s, (cy - sag) * s, (cx + ew / 2) * s, (cy + sag) * s], 15, 165, fill=INK, width=lw * s)
    res.alpha_composite(layer.resize(res.size, Image.LANCZOS))
    dst = p.with_name(p.stem + "-blink.png")
    res.save(dst)
    return {"ok": True, "path": str(p), "blink": str(dst), "eyes": [b for _, b in masks]}


def blink(app_dir: str | Path, states: list[str] | None = None, paths: list[str] | None = None) -> dict[str, Any]:
    """Blink variants for explicit `paths`, or for every `<app>/design/mascot/<state>.png`."""
    if not available():
        return {"ok": False, "error": _MISSING}
    if not paths:
        base = Path(app_dir).expanduser() / MASCOT_DIR
        wanted = states or spec_mod.MASCOT_STATES
        paths = [str(base / f"{s}.png") for s in wanted if (base / f"{s}.png").exists()]
    if not paths:
        return {"ok": False, "error": f"no approved poses found in {MASCOT_DIR}/<state>.png"}
    results = [blink_one(p) for p in paths]
    return {"ok": any(r["ok"] for r in results), "results": results,
            "made": sum(r["ok"] for r in results), "skipped": [r["path"] for r in results if not r["ok"]]}


def _contents(filename: str) -> dict[str, Any]:
    return {"images": [{"filename": filename, "idiom": "universal", "scale": "1x"},
                       {"idiom": "universal", "scale": "2x"}, {"idiom": "universal", "scale": "3x"}],
            "info": {"author": "xcode", "version": 1}}


def _resolve(src: Path, state: str) -> Path | None:
    seen = set()
    cur: str | None = state
    while cur and cur not in seen:
        if (src / f"{cur}.png").exists():
            return src / f"{cur}.png"
        seen.add(cur)
        cur = FALLBACK.get(cur)
    return None


def assets(app_dir: str | Path, source_dir: str | None = None, states: list[str] | None = None) -> dict[str, Any]:
    """Import approved poses (+ blinks) into Assets.xcassets/Mascot/<state>{,-blink}.imageset.

    The Mascot folder provides a namespace, so SwiftUI loads them as "Mascot/<state>".
    A state without its own pose borrows its FALLBACK pose so every MascotState resolves.
    """
    app = Path(app_dir).expanduser()
    src = Path(source_dir).expanduser() if source_dir else app / MASCOT_DIR
    if not src.is_dir():
        return {"ok": False, "error": f"pose folder not found: {src}"}
    if states is None:
        try:
            m = (spec_mod.load(app).get("design") or {}).get("mascot") or {}
            states = m.get("states") or spec_mod.MASCOT_STATES
        except FileNotFoundError:
            states = spec_mod.MASCOT_STATES
    bad = [s for s in states if s not in spec_mod.MASCOT_STATES]
    if bad:
        return {"ok": False, "error": f"unknown mascot states: {bad}"}
    root = app / ASSETS_DIR
    root.mkdir(parents=True, exist_ok=True)
    (root / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1},
                                                    "properties": {"provides-namespace": True}}, indent=2) + "\n", encoding="utf-8")
    imported, borrowed, missing = [], {}, []
    for st in states:
        pose = _resolve(src, st)
        if pose is None:
            missing.append(st)
            continue
        if pose.stem != st:
            borrowed[st] = pose.stem
        for suffix, file in (("", pose), ("-blink", pose.with_name(pose.stem + "-blink.png"))):
            if not file.exists():
                continue
            ims = root / f"{st}{suffix}.imageset"
            if ims.exists():
                shutil.rmtree(ims)
            ims.mkdir(parents=True)
            shutil.copy2(file, ims / f"{st}{suffix}.png")
            (ims / "Contents.json").write_text(json.dumps(_contents(f"{st}{suffix}.png"), indent=2) + "\n", encoding="utf-8")
            imported.append(f"Mascot/{st}{suffix}")
    return {"ok": not missing, "imported": imported, "borrowed": borrowed, "missing": missing, "dir": str(root)}
