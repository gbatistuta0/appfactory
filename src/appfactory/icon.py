"""icon_* — the app icon comes from Claude Design.

Flow: the `B01-AppIcon.dc.html` board of the app's Claude Design project (design_generate) is refined
in Claude Design → render_preview → `design_export_png` → design/icon.png → design_generate (copies it
into the project as icon.png) → upload + design_record_upload → `install()` writes AppIcon.appiconset
and the `.appfactory/verify/icon.json` proof the icon gate reads.

`generate()` (fal image model) is an explicit opt-in only: it writes a raster DRAFT to
design/icon_drafts/ as reference material for the Claude Design board, never into the appiconset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from . import config as cfg
from .proc import run


ICON_MASTER_REL = "design/icon.png"
APPICON_REL = "Resources/Assets.xcassets/AppIcon.appiconset"
VERIFY_REL = ".appfactory/verify/icon.json"


def generate(app_dir: str | Path, concept: str, extra: str = "", allow_external_generator: bool = False) -> dict[str, Any]:
    """OPT-IN raster draft (fal) → design/icon_drafts/. Never the shipped icon (that is Claude Design)."""
    if not allow_external_generator:
        return {"ok": False, "error": "the app icon is designed in Claude Design: refine B01-AppIcon.dc.html, "
                "design_export_png → design/icon.png → icon_install. Pass allow_external_generator=True only "
                "to get a raster reference draft (spend → approval)."}
    c = cfg.load_config()
    fal_key = c.get("fal_key")
    if not fal_key:
        return {"ok": False, "error": "fal_key missing"}
    prompt = (
        f"A premium iOS app icon for a {concept} app, full-bleed square with no border: "
        f"smooth diagonal gradient from teal #0F766E to deep blue #0369A1 filling the entire square, "
        f"a single bold elegant white centered symbol representing the app, minimal, flat, modern, "
        f"high contrast, no text, no letters. {extra}"
    ).strip()
    try:
        # Nano Banana (Gemini 2.5 Flash Image) — clean, brand-consistent icon.
        r = httpx.post("https://fal.run/fal-ai/nano-banana",
                       headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
                       json={"prompt": prompt, "num_images": 1, "output_format": "png", "aspect_ratio": "1:1"}, timeout=150)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"fal network error: {e}"}
    if not r.is_success:
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    url = (r.json().get("images") or [{}])[0].get("url")
    if not url:
        return {"ok": False, "error": "no fal image URL"}

    drafts = Path(app_dir).expanduser() / "design" / "icon_drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    raw = drafts / "_raw_icon"
    png = drafts / f"draft-{len(list(drafts.glob('draft-*.png'))) + 1:02d}.png"
    raw.write_bytes(httpx.get(url, timeout=120).content)
    run(["sips", "-s", "format", "png", str(raw), "--out", str(png)], timeout=60)
    raw.unlink(missing_ok=True)
    return {"ok": True, "draft": str(png), "prompt": prompt,
            "next": "reference only — upload it into the Claude Design project and redraw the icon on B01-AppIcon.dc.html"}


def install(app_dir: str | Path, source: str = ICON_MASTER_REL) -> dict[str, Any]:
    """Claude Design icon master (1024×1024 PNG exported from B01-AppIcon) → AppIcon.appiconset + verify/icon.json."""
    from .design import brand, receipt
    from .design.export import png_info

    app = Path(app_dir).expanduser()
    src = Path(source).expanduser()
    if not src.is_absolute():
        src = app / src
    info = png_info(src) if src.exists() else None
    if info is None:
        return {"ok": False, "error": f"{source} missing or not a PNG — export B01-AppIcon.dc.html with design_export_png"}
    if (info["width"], info["height"]) != (1024, 1024):
        return {"ok": False, "error": f"icon master is {info['width']}×{info['height']}, must be 1024×1024"}
    from . import config as cfg
    local = cfg.first_disabled(("design",)) is not None  # design service off: a locally authored master
    up = {"ok": True, "project_id": None} if local else receipt.check(app, required=[brand.ICON_BOARD, "icon.png"])
    if not up["ok"]:
        return {"ok": False, "error": "the icon is not current in Claude Design (design_generate copies design/icon.png "
                "into the project → upload → design_record_upload): " + up["reason"]}
    if not local and (receipt.load(app) or {}).get("files", {}).get("icon.png") != receipt.sha256(src):
        return {"ok": False, "error": "the uploaded Claude Design icon.png is not this master — re-run design_generate, "
                "upload, design_record_upload"}
    appicon = app / APPICON_REL
    appicon.mkdir(parents=True, exist_ok=True)
    png = appicon / "icon_1024.png"
    if info["color_type"] in (4, 6):  # App Store icons must not carry alpha → flatten through JPEG
        tmp = appicon / "_flat.jpg"
        a = run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100", str(src), "--out", str(tmp)], timeout=60)
        b = run(["sips", "-s", "format", "png", str(tmp), "--out", str(png)], timeout=60)
        tmp.unlink(missing_ok=True)
        if not (a.get("ok") and b.get("ok")):
            return {"ok": False, "error": "could not flatten the icon alpha channel (sips)"}
    else:
        png.write_bytes(src.read_bytes())
    (appicon / "Contents.json").write_text(json.dumps({
        "images": [{"filename": "icon_1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
        "info": {"author": "xcode", "version": 1},
    }, indent=2), encoding="utf-8")
    marker = {"source": "local", "board": None, "project_id": None} if local else \
        {"source": "claude_design", "board": brand.ICON_BOARD, "project_id": up["project_id"]}
    marker |= {"master": str(src.relative_to(app)) if src.is_relative_to(app) else str(src),
               "master_sha256": receipt.sha256(src), "installed_sha256": receipt.sha256(png)}
    vp = app / VERIFY_REL
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "icon": str(png), "marker": str(vp)}
