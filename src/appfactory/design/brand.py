"""Brand + App Store creative boards (canvas pages "brand" and "store") — scaffolds only.

The look is authored in Claude Design from design/research/brief.json; this module writes STRUCTURAL
scaffolds to design/scaffold/ (sizes, slots, the real captions/captures to place) and the machine layout:

- `B01-AppIcon.dc.html` — 1024×1024 icon master slot. The authored board (design/project/) is refined in
  Claude Design from the brief's illustration/palette direction, exported with `design_export_png` →
  design/icon.png → `icon_install`.
- `ST0N-<Shot>.dc.html` — one App Store board per entry of the brief's screenshots.boards (3–10, the
  brief's order and shots; 440×956 CSS px, exported at 3× = 1320×2868). Captions come from
  marketing/screenshots/copy/en-US.json, frames show marketing/screenshots/raw/en-US/<NN_shot>.png;
  missing ones are `data-placeholder` markers the screenshots gate rejects on the authored boards.
- `store_layout.json` (project) — the brief's screenshot layout colors, fonts, shot order and brief hash;
  `apply_layout()` merges it into marketing/screenshots/config.json for the per-locale compositor.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .dc import Ctx, page
from .theme import Theme, mix, rgba

ICON_BOARD = "B01-AppIcon.dc.html"
ICON_W = ICON_H = 1024
STORE_W, STORE_H, STORE_SCALE = 440, 956, 3
STORE_LAYOUT = "store_layout.json"
SCAFFOLD_MARK = 'data-scaffold="true"'
CAPTION_PLACEHOLDER = 'data-placeholder="caption"'
CAPTURE_PLACEHOLDER = 'data-placeholder="capture"'


def mark_scaffold(html: str) -> str:
    """Tag a generated board as scaffold — an authored board must not carry this marker."""
    return html.replace("<x-dc>", f"<x-dc {SCAFFOLD_MARK}>", 1)


def store_file(i: int, shot: str) -> str:
    return f"ST{i:02d}-{shot.capitalize()}.dc.html"


def capture_name(i: int, shot: str) -> str:
    return f"{i:02d}_{shot}"


def store_boards(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """The brief's screenshot boards → [{file, capture, shot, message, layout}] in the brief's order."""
    boards = (((brief.get("direction") or {}).get("screenshots") or {}).get("boards")) or []
    return [{"file": store_file(i, b["shot"]), "capture": capture_name(i, b["shot"]), "shot": b["shot"],
             "message": b.get("message", ""), "layout": b.get("layout", "")} for i, b in enumerate(boards, 1)]


def store_files(brief: dict[str, Any]) -> list[str]:
    return [b["file"] for b in store_boards(brief)]


def gradient(t: Theme, brief: dict[str, Any] | None = None) -> tuple[str, str]:
    lay = ((((brief or {}).get("direction") or {}).get("screenshots") or {}).get("layout")) or {}
    return lay.get("brandColorTop") or t.accent, lay.get("brandColorBottom") or mix(t.accent, t.ink, 0.35)


# ------------------------------------------------------------ icon

def icon_board(ctx: Ctx) -> str:
    t = ctx.theme
    top, bottom = gradient(t)
    pose = ctx.mascot.get("idle")
    art = (f'<img src="{pose}" alt="" style="width: 720px; height: 720px; object-fit: contain; display: block">' if pose else
           f'<span style="font-family: {t.display_css}; font-weight: 800; font-size: 560px; line-height: 1; color: #FFFFFF; '
           f'letter-spacing: -20px">{t.text(t.display_name[:1])}</span>')
    body = (f'<div data-icon-master="true" style="width: {ICON_W}px; height: {ICON_H}px; display: flex; align-items: center; '
            f'justify-content: center; background: linear-gradient(160deg, {top} 0%, {bottom} 100%); overflow: hidden">'
            f'{art}</div>')
    return mark_scaffold(page(t, f"{t.display_name} · App icon master", body, w=ICON_W, h=ICON_H, frame=False,
                              css="body{background:transparent}"))


# ------------------------------------------------------------ store creatives

def _captions(app: Path) -> list[dict[str, str]]:
    p = app / "marketing" / "screenshots" / "copy" / "en-US.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except Exception:  # noqa: BLE001
        data = []
    return data if isinstance(data, list) else []


def collect_captures(app: Path, out: Path, names: list[str]) -> dict[str, str]:
    """Copy en-US raw captures into the project (store/raw/<NN_shot>.png) → {capture name: project path}."""
    raw = app / "marketing" / "screenshots" / "raw" / "en-US"
    dest = out / "store" / "raw"
    if dest.exists():
        shutil.rmtree(dest)
    found: dict[str, str] = {}
    for name in names:
        src = raw / f"{name}.png"
        if src.exists():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / src.name)
            found[name] = f"store/raw/{src.name}"
    return found


def store_board(ctx: Ctx, i: int, shot: str, caption: dict[str, str] | None, capture: str | None,
                brief: dict[str, Any] | None = None, note: str = "") -> str:
    t = ctx.theme
    top, bottom = gradient(t, brief)
    if caption and caption.get("headline"):
        head = (f'<h1 style="margin: 0; font-family: {t.display_css}; font-weight: 800; font-size: 38px; line-height: 1.08; '
                f'letter-spacing: -0.5px; color: #FFFFFF">{t.text(caption["headline"])}</h1>'
                f'<p style="margin: 0; font-size: 18px; line-height: 1.35; color: {rgba("#FFFFFF", .9)}">'
                f'{t.text(caption.get("subhead", ""))}</p>')
    else:
        head = (f'<h1 {CAPTION_PLACEHOLDER} style="margin: 0; font-family: {t.display_css}; font-weight: 800; font-size: 38px; '
                f'line-height: 1.08; color: #FFFFFF; opacity: .55">Caption {i} from ASO copy</h1>')
    screen = (f'<img src="{capture}" alt="" style="width: 100%; height: 100%; object-fit: cover; display: block">' if capture else
              f'<div {CAPTURE_PLACEHOLDER} style="width: 100%; height: 100%; display: flex; align-items: center; '
              f'justify-content: center; background: {t.bg}; color: {t.muted}; font-size: 15px">{shot} capture</div>')
    body = (f'<div style="width: {STORE_W}px; height: {STORE_H}px; box-sizing: border-box; padding: 64px 32px 0; display: flex; '
            f'flex-direction: column; align-items: center; gap: 36px; overflow: hidden; '
            f'background: linear-gradient(180deg, {top} 0%, {bottom} 100%)">'
            f'<div style="display: flex; flex-direction: column; gap: 12px; text-align: center; animation: rise .6s both">{head}</div>'
            f'<div style="width: 340px; height: 736px; flex-shrink: 0; border-radius: 52px; padding: 10px; box-sizing: border-box; '
            f'background: {t.ink}; box-shadow: 0 30px 60px {rgba(t.ink, .35)}; animation: rise .7s .1s both">'
            f'<div style="width: 100%; height: 100%; border-radius: 42px; overflow: hidden">{screen}</div></div></div>')
    if note:
        body += f'<!-- brief layout: {note.replace("--", "-")} -->'
    return mark_scaffold(page(t, f"{t.display_name} · App Store {i:02d} {shot}", body, w=STORE_W, h=STORE_H, frame=False))


def layout(t: Theme, brief: dict[str, Any], brief_sha256: str | None) -> dict[str, Any]:
    ss = ((brief.get("direction") or {}).get("screenshots")) or {}
    lay = ss.get("layout") or {}
    top, bottom = gradient(t, brief)
    boards = store_boards(brief)
    return {"brandColorTop": top, "brandColorBottom": bottom, "headlineColor": lay.get("headlineColor", "#FFFFFF"),
            "headlineFont": t.display_font, "bodyFont": t.body_font,
            "canvas": {"w": STORE_W * STORE_SCALE, "h": STORE_H * STORE_SCALE},
            "concept": ss.get("concept", ""), "boards": [b["file"] for b in boards],
            "shots": [b["capture"] for b in boards], "brief_sha256": brief_sha256, "rules": _store_rules()}


def _store_rules() -> list[str]:
    from .rules import STORE_RULES
    return STORE_RULES


def write_store(ctx: Ctx, app: Path, scaffold: Path, out: Path, brief: dict[str, Any],
                brief_sha256: str | None) -> tuple[list[str], list[str]]:
    """Scaffold every store board of the brief's concept + write store_layout.json. → (board files, warnings)."""
    caps = _captions(app)
    boards = store_boards(brief)
    captures = collect_captures(app, out, [b["capture"] for b in boards])
    written = []
    for i, bd in enumerate(boards, 1):
        cap = caps[i - 1] if i - 1 < len(caps) and isinstance(caps[i - 1], dict) else None
        html = store_board(ctx, i, bd["shot"], cap, captures.get(bd["capture"]), brief,
                           f'{bd["message"]} | {bd["layout"]}')
        (scaffold / bd["file"]).write_text(html, encoding="utf-8")
        written.append(bd["file"])
    (out / STORE_LAYOUT).write_text(json.dumps(layout(ctx.theme, brief, brief_sha256), indent=2) + "\n", encoding="utf-8")
    warnings = []
    if len(caps) < len(boards):
        warnings.append("store boards use caption placeholders — write marketing/screenshots/copy/en-US.json (ASO) "
                        "and re-run design_generate before the screenshots stage")
    if len(captures) < len(boards):
        warnings.append("store boards use capture placeholders until marketing/screenshots/raw/en-US/*.png exist")
    return written, warnings


def placeholders(out: Path, files: list[str]) -> list[str]:
    """Authored store boards that are missing or still show a caption/capture placeholder."""
    bad = []
    for f in files:
        p = out / f
        txt = p.read_text(encoding="utf-8") if p.exists() else CAPTION_PLACEHOLDER
        if CAPTION_PLACEHOLDER in txt or CAPTURE_PLACEHOLDER in txt:
            bad.append(f)
    return bad


def apply_layout(app_dir: str | Path) -> dict[str, Any]:
    """Merge design/project/store_layout.json into marketing/screenshots/config.json (compositor input)."""
    app = Path(app_dir).expanduser()
    src = app / "design" / "project" / STORE_LAYOUT
    if not src.exists():
        return {"ok": False, "error": f"design/project/{STORE_LAYOUT} missing — run design_generate"}
    lay = json.loads(src.read_text(encoding="utf-8"))
    cfg_p = app / "marketing" / "screenshots" / "config.json"
    cfg_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    for k in ("brandColorTop", "brandColorBottom", "headlineColor", "headlineFont", "bodyFont", "canvas", "shots"):
        cfg[k] = lay[k]
    cfg_p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "config": str(cfg_p)}


def layout_matches(app: Path) -> dict[str, Any]:
    """The compositor config carries the Claude Design store layout values."""
    src = app / "design" / "project" / STORE_LAYOUT
    cfg_p = app / "marketing" / "screenshots" / "config.json"
    if not src.exists() or not cfg_p.exists():
        return {"ok": False, "reason": f"design/project/{STORE_LAYOUT} or marketing/screenshots/config.json missing"}
    try:
        lay = json.loads(src.read_text(encoding="utf-8"))
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"store layout unreadable: {e}"}
    off = [k for k in ("brandColorTop", "brandColorBottom", "headlineColor") if str(cfg.get(k, "")).upper() != str(lay[k]).upper()]
    if off:
        return {"ok": False, "reason": f"marketing/screenshots/config.json differs from the Claude Design store layout "
                f"({', '.join(off)}) — run apply_store_layout / screenshot_build_all"}
    return {"ok": True}
