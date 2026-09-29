"""design — brief-driven Claude Design project: structural scaffolds + the authoring/upload plan.

Input:  <app>/app.spec.json (design tokens/fonts derived from the brief, onboarding_screens, mascot)
        <app>/design/research/brief.json (design_research: the per-app direction, cites competitors)
        <app>/design/screens.json (every screen described individually; onboarding follows brief.flow)
        <app>/design/mascot/<state>.png (+ <state>-blink.png) approved poses, optional
Output: <app>/design/scaffold/*.dc.html — STRUCTURE ONLY (screen list, slots, funnel rules such as
        kg/lb pickers, honest copy, paywall prices from the spec). Never the shipped look.
        <app>/design/project/ — the Claude Design project: the AUTHORED boards (same file names as
        the scaffolds, written by Claude in Claude Design from the brief with the hifi-design skill and
        synced back), generated mascot motion boards, canvas.json (pages onboarding, app, mascot,
        brand, store), store_layout.json and upload_plan.json (exact claude-design MCP calls).

Claude Design is the ONLY design tool and the brief is the only source of the look: the gates reject
missing research, boards identical to their scaffold, and uploads recorded before the current brief.
This package never calls the claude-design MCP.
"""

from __future__ import annotations

import base64
import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .. import spec as spec_mod
from . import brand, mascot_boards, receipt, research, rules, screens
from .dc import Ctx
from .main_app import RENDERERS as MAIN_RENDERERS
from .onboarding import RENDERERS as ONB_RENDERERS
from .theme import H, W, from_spec

PROJECT_REL = "design/project"
SCAFFOLD_REL = "design/scaffold"
MASCOT_REL = "design/mascot"
COL, ROW = 470, 1250  # canvas grid for 390×844 boards

__all__ = ["generate", "skeleton", "validate_screens", "canvas", "authored_problems", "PROJECT_REL", "SCAFFOLD_REL",
           "MASCOT_REL"]


def skeleton(spec: dict[str, Any] | None = None, app_dir: str | Path | None = None) -> dict[str, Any]:
    """Structural skeleton; with an app whose brief exists, onboarding follows the brief's flow."""
    doc = screens.skeleton(spec)
    if app_dir is not None:
        brief = research.load_brief(app_dir)
        flow = (((brief or {}).get("direction") or {}).get("onboarding") or {}).get("flow")
        if flow:
            doc = screens.from_brief(doc, flow, research.brief_sha(app_dir))
    return doc


def validate_screens(doc: Any, spec: dict[str, Any] | None = None) -> list[str]:
    n = ((spec or {}).get("design") or {}).get("onboarding_screens", spec_mod.DEFAULTS["design"]["onboarding_screens"])
    return screens.validate(doc, min_onboarding=n, spec=spec)


def mascot_states(spec: dict[str, Any]) -> list[str]:
    m = (spec.get("design") or {}).get("mascot") or {}
    return [s for s in (m.get("states") or spec_mod.MASCOT_STATES) if s in spec_mod.MASCOT_STATES]


def _collect_mascot(app: Path, out: Path, states: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Copy approved poses (+ closed-eye copies) into the project; state -> project-relative path."""
    src = app / MASCOT_REL
    poses, blinks = {}, {}
    if not src.is_dir():
        return poses, blinks
    (out / "mascot").mkdir(parents=True, exist_ok=True)
    from ..mascot import _resolve  # same pose fallback as the imported assets
    for st in states:
        pose = _resolve(src, st)
        if pose is None:
            continue
        for suffix, table, f in (("", poses, pose), ("-blink", blinks, pose.with_name(pose.stem + "-blink.png"))):
            if f.exists():
                shutil.copy2(f, out / "mascot" / f"{st}{suffix}.png")
                table[st] = f"mascot/{st}{suffix}.png"
    return poses, blinks


def _app_icon(app: Path, out: Path) -> str | None:
    cands = [app / "design" / "icon.png"]
    iconset = app / "Resources" / "Assets.xcassets" / "AppIcon.appiconset"
    if iconset.is_dir():
        cands += sorted(iconset.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    for c in cands:
        if c.exists():
            shutil.copy2(c, out / "icon.png")
            return "icon.png"
    return None


def canvas(title: str, rows: list[tuple[str, str, list[tuple[str, str, int, int]]]]) -> dict[str, Any]:
    """rows: (page id, row label, [(file, board title, w, h)]) → Claude Design canvas.json (v3)."""
    pages = {"onboarding": "Onboarding", "app": "Main app", "mascot": "Mascot motion",
             "brand": "Brand & app icon", "store": "App Store creatives"}
    boards, order, notes = {}, [], {}
    y_by_page: dict[str, int] = {}
    for n, (page_id, label, items) in enumerate(rows):
        y = y_by_page.get(page_id, 0)
        col = max((w for _, _, w, _ in items), default=390) + 80
        notes[f"{page_id}_row{n + 1}"] = {"x": 0, "y": y - 250, "text": label, "kind": "title1",
                                          "maxW": len(items) * col - 80, "page": page_id}
        for c, (f, board_title, w, h) in enumerate(items):
            boards[f] = {"x": c * col, "y": y, "w": w, "h": h, "title": board_title, "is_interactive": True, "page": page_id}
            order.append(f)
        y_by_page[page_id] = y + max((h for _, _, _, h in items), default=H) + 406
    used = [p for p in pages if p in y_by_page]
    return {"v": 3, "createdOnFiles": {"v": 1, "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "title": title, "launch": {"view": "canvas"}, "pages": [{"id": p, "name": pages[p]} for p in used],
            "boards": boards, "order": order, "notes": notes, "designSystems": []}


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def upload_calls(project_name: str, files: list[str], binary: list[str]) -> list[dict[str, Any]]:
    """The exact claude-design MCP sequence the orchestrating agent runs (this code never calls it)."""
    text = [f for f in files if f not in binary]
    calls: list[dict[str, Any]] = [
        {"tool": "mcp__claude-design__list_design_systems", "args": {},
         "note": "pick the app's design system if one exists (else the default)"},
        {"tool": "mcp__claude-design__get_claude_design_prompt", "args": {"design_system_id": "<optional>"},
         "note": "REQUIRED before any write_files; read_design_skill('hifi-design') before editing boards by hand"},
        {"tool": "mcp__claude-design__create_project", "args": {"name": project_name},
         "note": "skip when the app already has a project (reuse its project_id from design/project/upload_plan.json)"},
        {"tool": "mcp__claude-design__create_support_js", "args": {"project_id": "<project_id>", "path": "support.js"},
         "note": "once per directory that holds .dc.html files, before writing them"},
    ]
    for batch in _chunks(text, 8):
        calls.append({"tool": "mcp__claude-design__write_files",
                      "args": {"project_id": "<project_id>", "files": [{"path": f, "data": f"<utf-8 contents of design/project/{f}>"} for f in batch]}})
    for batch in _chunks(binary, 4):
        calls.append({"tool": "mcp__claude-design__write_files",
                      "args": {"project_id": "<project_id>", "files": [{"path": f, "encoding": "base64",
                                                                        "data": f"<base64 of design/project/{f}>"} for f in batch]}})
    first = next((f for f in text if f.endswith(".dc.html")), None)
    if first:
        calls.append({"tool": "mcp__claude-design__render_preview", "args": {"project_id": "<project_id>", "path": first},
                      "note": "open_url is the link for the founder; never share or persist serve_url"})
    calls.append({"tool": "mcp__appfactory__design_record_upload",
                  "args": {"app_dir": "<app_dir>", "project_id": "<project_id>", "open_url": "<open_url>"},
                  "note": "records the SHA-256 of every uploaded file; the design/icon/screenshots gates require it"})
    return calls


def generate(app_dir: str | Path) -> dict[str, Any]:
    """Write the scaffolds, mascot boards, canvas.json, store_layout.json and the authoring/upload plan."""
    app = Path(app_dir).expanduser()
    sp = spec_mod.path(app)
    if not sp.exists():
        return {"ok": False, "error": f"{spec_mod.SPEC_FILE} missing — create it first (spec.build/save)"}
    rc = research.check(app)
    if not rc["ok"]:
        return {"ok": False, "error": "design research first (design_research stage): " + rc["reason"],
                "problems": rc.get("problems", [])}
    brief = research.load_brief(app) or {}
    bsha = research.brief_sha(app)
    spec = spec_mod.load(app)
    if not screens.path(app).exists():
        return {"ok": False, "error": f"{screens.SCREENS_REL} missing — start from design_screens_skeleton and adapt every screen"}
    doc = screens.load(app)
    errs = validate_screens(doc, spec) + research.derive_problems(app, spec, doc)
    if errs:
        return {"ok": False, "error": "screens.json / spec are not valid or not derived from the brief", "problems": errs}

    theme = from_spec(spec)
    out = app / PROJECT_REL
    scaffold = app / SCAFFOLD_REL
    out.mkdir(parents=True, exist_ok=True)
    if scaffold.exists():
        shutil.rmtree(scaffold)
    scaffold.mkdir(parents=True)
    # generated project files only; authored boards are never touched
    for stale in list(out.glob("M[0-9][0-9]-*.dc.html")) + list((out / "mascot").glob("*.png")):
        stale.unlink()
    states = mascot_states(spec)
    poses, blinks = _collect_mascot(app, out, states)
    icon = _app_icon(app, out)
    files = screens.files(doc)
    first_main = files[doc["main"][0]["id"]] if doc["main"] else "#"
    ctx = Ctx(theme=theme, spec=spec, mascot=poses, blink=blinks, app_icon=icon, files=files, first_main=first_main, doc=doc)

    authored: list[str] = []
    onb = doc["onboarding"]
    n = len(onb)
    for i, s in enumerate(onb):
        nav = {"prev": files[onb[i - 1]["id"]] if i else "#",
               "next": files[onb[i + 1]["id"]] if i + 1 < n else first_main,
               "frac": min(1.0, i / max(1, n - 3)), "prev_frac": min(1.0, max(0, i - 1) / max(1, n - 3)), "index": i}
        html = brand.mark_scaffold(ONB_RENDERERS[s["kind"]](ctx, s, nav))
        (scaffold / files[s["id"]]).write_text(html, encoding="utf-8")
        authored.append(files[s["id"]])
    for s in doc["main"]:
        html = brand.mark_scaffold(MAIN_RENDERERS[s["kind"]](ctx, s))
        (scaffold / files[s["id"]]).write_text(html, encoding="utf-8")
        authored.append(files[s["id"]])
    generated: list[str] = []
    mascot_files = []
    for i, st in enumerate(states, 1):
        f = mascot_boards.file_name(i, st)
        (out / f).write_text(mascot_boards.board(ctx, st), encoding="utf-8")
        mascot_files.append((f, st))
        generated.append(f)

    (scaffold / brand.ICON_BOARD).write_text(brand.icon_board(ctx), encoding="utf-8")
    authored.append(brand.ICON_BOARD)
    store_written, store_warnings = brand.write_store(ctx, app, scaffold, out, brief, bsha)
    authored += store_written
    store_meta = brand.store_boards(brief)

    rows: list[tuple[str, str, list[tuple[str, str, int, int]]]] = []
    sections: dict[str, list] = {}
    for i, s in enumerate(onb, 1):
        sections.setdefault(s.get("section") or "Onboarding", []).append((files[s["id"]], f"{i:02d} · {s['title']}"[:80], W, H))
    rows += [("onboarding", label, items) for label, items in sections.items()]
    main_items = [(files[s["id"]], f"A{i:02d} · {s['title']}"[:80], W, H) for i, s in enumerate(doc["main"], 1)]
    rows += [("app", f"{6 + r} · Main app", chunk) for r, chunk in enumerate(_chunks(main_items, 5))]
    rows.append(("mascot", f"{theme.mascot_name or theme.display_name} · motion states (animate the approved poses)",
                 [(f, f"{mascot_boards.STATES[st][0]} — {mascot_boards.STATES[st][1]}", mascot_boards.W, mascot_boards.H) for f, st in mascot_files]))
    rows.append(("brand", "App icon master (1024×1024) — authored from the brief, exported with design_export_png → design/icon.png",
                 [(brand.ICON_BOARD, f"{theme.display_name} · App icon", brand.ICON_W, brand.ICON_H)]))
    rows.append(("store", "App Store screenshots — the brief's concept (440×956 @3× = 1320×2868), compositor renders it per locale",
                 [(b["file"], f"{i:02d} · {b['message'] or b['shot']}"[:80], brand.STORE_W, brand.STORE_H)
                  for i, b in enumerate(store_meta, 1)]))
    cv = canvas(f"{theme.display_name} Design", rows)
    (out / "canvas.json").write_text(json.dumps(cv, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    binary = sorted([f"mascot/{p.name}" for p in (out / "mascot").glob("*.png")]
                    + [f"store/raw/{p.name}" for p in (out / "store" / "raw").glob("*.png")]
                    + (["icon.png"] if icon else []))
    upload = sorted(authored + generated) + ["canvas.json", brand.STORE_LAYOUT]
    project_name = f"{theme.display_name} Design"
    plan_path = out / "upload_plan.json"
    prev_plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    plan = {"project_name": project_name, "project_id": prev_plan.get("project_id"), "brief_sha256": bsha,
            "files": upload, "binary_files": binary, "authored": sorted(authored), "scaffold_dir": SCAFFOLD_REL,
            "calls": upload_calls(project_name, upload, binary)}
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    missing_poses = [st for st in states if st not in poses]
    warnings = []
    if missing_poses:
        warnings.append(f"no approved pose PNG for {', '.join(missing_poses)} in {MASCOT_REL}/ — boards use "
                        f"{'the idle pose' if 'idle' in poses else 'the token-tinted placeholder'}")
    warnings += store_warnings
    todo = authored_problems(app)
    return {"ok": True, "dir": str(out), "scaffold_dir": str(scaffold), "onboarding": n, "main": len(doc["main"]),
            "mascot_boards": len(mascot_files), "authored": sorted(authored), "authoring_todo": todo[:10],
            "files": upload, "binary_files": binary, "canvas": str(out / "canvas.json"), "upload_plan": str(plan_path),
            "mcp_calls": plan["calls"], "warnings": warnings, "rules": rules.APP_RULES,
            "uploaded_current": receipt.check(app)["ok"],
            "next": ("AUTHOR every board in plan.authored in Claude Design from design/research/brief.json "
                     "(get_claude_design_prompt + read_design_skill('hifi-design')): the scaffold of the same name in "
                     f"{SCAFFOLD_REL}/ gives structure, rules and real copy/prices only — the look comes from the brief. "
                     "Sync each authored board to design/project/<file>, upload the rest (calls above), then "
                     "design_record_upload(app_dir, project_id, open_url) and have the founder review via open_url.")}


_TAGS = re.compile(r"<[^>]+>")
_NON_TEXT = re.compile(r"<(style|script|helmet|svg)\b.*?</\1>", re.S | re.I)


def visible_text(html: str) -> str:
    """Board copy only (no CSS/JS/SVG), for the copy rules on authored boards."""
    return _TAGS.sub(" ", _NON_TEXT.sub(" ", html))


def authored_problems(app_dir: str | Path) -> list[str]:
    """Authored boards exist, are not the scaffold, and keep the funnel rules (kg/lb, no dark patterns)."""
    app = Path(app_dir).expanduser()
    plan_p = app / PROJECT_REL / "upload_plan.json"
    if not plan_p.exists():
        return ["upload_plan.json missing — run design_generate"]
    plan = json.loads(plan_p.read_text(encoding="utf-8"))
    out, scaffold = app / PROJECT_REL, app / SCAFFOLD_REL
    errs: list[str] = []
    for f in plan.get("authored") or []:
        p = out / f
        if not p.exists():
            errs.append(f"{f}: not authored yet (design it in Claude Design from the brief, sync to design/project/)")
            continue
        txt = p.read_text(encoding="utf-8")
        sc = scaffold / f
        if brand.SCAFFOLD_MARK in txt or (sc.exists() and sc.read_text(encoding="utf-8") == txt):
            errs.append(f"{f}: still the generated scaffold — author the look from the brief in Claude Design")
    if errs:
        return errs
    doc = screens.load(app) if screens.path(app).exists() else {"onboarding": [], "main": []}
    files = screens.files(doc)
    for s in doc.get("onboarding", []) + doc.get("main", []):
        f = files.get(s["id"])
        if not f or not (out / f).exists():
            continue
        text = visible_text((out / f).read_text(encoding="utf-8"))
        if rules.has_emoji(text):
            errs.append(f"{f}: emoji in the UI — use SF Symbols (emoji render as boxes)")
        picker = s.get("picker") or {}
        if picker and screens.is_weight_picker(picker) and not (re.search(r"\bkg\b", text) and re.search(r"\blb\b", text)):
            errs.append(f"{f}: weight picker without the kg/lb toggle")
        is_onb = s in doc.get("onboarding", [])
        for rx, what in screens.BANNED_COPY:
            if what == "rating prompt" and not is_onb:
                continue  # success-moment rating prompts are required in the app, never in onboarding
            if rx.search(text):
                errs.append(f"{f}: {what} in the authored board")
                break
    return errs


def read_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
