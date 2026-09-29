"""Design generators, screens.json validation and the Claude Design gate."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from appfactory import design, gates, icon, spec
from appfactory import screenshot as ss
from appfactory.design import brand, export, pricing, receipt, research, screens
from design_fixtures import (OPEN_URL, PROJECT_ID, STORE_SHOTS, author, brief_doc, design_ready, icon_master,
                             make_app, png, store_ready, upload, write_brief, write_research)

MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def _app(tmp_path: Path) -> tuple[Path, dict]:
    return make_app(tmp_path)


def _write_doc(app: Path, sp: dict) -> dict:
    doc = design.skeleton(sp, app)
    screens.save(app, doc)
    return doc


def test_skeleton_is_valid_cal_ai_funnel():
    sp = spec.build("Hue", "com.example.hue")
    doc = design.skeleton(sp)
    assert len(doc["onboarding"]) == 26
    assert design.validate_screens(doc, sp) == []
    kinds = [s["kind"] for s in doc["onboarding"]]
    assert kinds[-2:] == ["paywall", "offer"]
    assert {"rating", "notification", "spin_wheel"}.isdisjoint(kinds)
    assert all(s.get("motion") for s in doc["onboarding"] + doc["main"])
    assert all(s["key"].startswith(("onb.", "app.")) for s in doc["onboarding"] + doc["main"])


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["onboarding"].insert(3, {"id": "rate", "kind": "rating", "title": "Rate", "motion": "x"}), "rating"),
    (lambda d: d["onboarding"].insert(3, {"id": "notify", "kind": "notification_prompt", "title": "N", "motion": "x"}), "notification"),
    (lambda d: d["onboarding"].insert(3, {"id": "spin", "kind": "spin_wheel", "title": "S", "motion": "x"}), "spin"),
    (lambda d: d["onboarding"][4].update(footnote="Loved by 2M+ users"), "invented"),
    (lambda d: d["onboarding"][4].update(footnote="80% of people reach their goal"), "statistic"),
    (lambda d: d["onboarding"][1].update(subtitle="Rate us 5 stars"), "rating prompt"),
    (lambda d: d["onboarding"][2].update(motion=""), "motion"),
    (lambda d: d["onboarding"].append(copy.deepcopy(d["onboarding"][1]) | {"id": "about_copy"}), "duplicates"),
    (lambda d: d["onboarding"].pop(-1), "offer"),
    (lambda d: d["main"].__setitem__(slice(None), [s for s in d["main"] if s["kind"] != "settings"]), "settings"),
    (lambda d: d["onboarding"][7].update(picker={"type": "weight", "units": ["kg"]}), "kg/lb"),
])
def test_validation_rejects(mutate, needle):
    sp = spec.build("Hue", "com.example.hue")
    doc = design.skeleton(sp)
    mutate(doc)
    errs = design.validate_screens(doc, sp)
    assert errs and any(needle in e for e in errs), errs


def test_validation_enforces_spec_onboarding_count():
    sp = spec.build("Hue", "com.example.hue", design={"onboarding_screens": 30})
    errs = design.validate_screens(design.skeleton(sp), sp)
    assert any("26 screens < 30" in e for e in errs)


def test_generate_writes_every_board_and_canvas(tmp_path: Path):
    app, sp = _app(tmp_path)
    doc = _write_doc(app, sp)
    r = design.generate(app)
    assert r["ok"], r
    out, scaffold = app / design.PROJECT_REL, app / design.SCAFFOLD_REL
    brief = research.load_brief(app)
    scaffolds = sorted(p.name for p in scaffold.glob("*.dc.html"))
    assert len(scaffolds) == 26 + len(doc["main"]) + 1 + len(STORE_SHOTS)  # screens + icon + brief store boards
    assert sorted(p.name for p in out.glob("*.dc.html")) == [f"M{i:02d}-{s.capitalize()}.dc.html"
                                                              for i, s in enumerate(spec.MASCOT_STATES, 1)]
    plan = json.loads((out / "upload_plan.json").read_text())
    assert plan["authored"] == scaffolds and plan["brief_sha256"] == research.brief_sha(app)
    cv = json.loads((out / "canvas.json").read_text())
    assert {p["id"] for p in cv["pages"]} == {"onboarding", "app", "mascot", "brand", "store"}
    assert set(cv["boards"]) == set(scaffolds) | {p.name for p in out.glob("*.dc.html")}
    assert all(b["w"] == 390 and b["h"] == 844 for b in cv["boards"].values() if b["page"] in ("onboarding", "app"))
    assert cv["boards"][brand.ICON_BOARD]["page"] == "brand" and cv["boards"][brand.ICON_BOARD]["w"] == 1024
    store = brand.store_files(brief)
    assert store == ["ST01-Result.dc.html", "ST02-Onboarding.dc.html", "ST03-Paywall.dc.html", "ST04-Create.dc.html"]
    assert all(cv["boards"][f]["page"] == "store" and cv["boards"][f]["w"] == 440 for f in store)
    html = (scaffold / "S01-Welcome.dc.html").read_text()
    assert "@keyframes rise" in html and 'data-dc-script' in html and "./support.js" in html
    assert brand.SCAFFOLD_MARK in html
    assert "#1F9D5C" in html and "Fraunces" in html  # brief-derived tokens + fonts
    assert len(r["authoring_todo"]) == 10 and "not authored yet" in r["authoring_todo"][0]
    tools = [c["tool"] for c in r["mcp_calls"]]
    assert tools[:4] == ["mcp__claude-design__list_design_systems", "mcp__claude-design__get_claude_design_prompt",
                         "mcp__claude-design__create_project", "mcp__claude-design__create_support_js"]
    assert "mcp__claude-design__write_files" in tools and tools[-2] == "mcp__claude-design__render_preview"
    assert tools[-1] == "mcp__appfactory__design_record_upload"
    assert r["uploaded_current"] is False
    assert r["warnings"]  # no approved poses yet → placeholder


def test_generated_boards_are_individual(tmp_path: Path):
    app, sp = _app(tmp_path)
    _write_doc(app, sp)
    design.generate(app)
    bodies = [re.sub(r"<title>.*?</title>", "", p.read_text()) for p in (app / design.SCAFFOLD_REL).glob("S*.dc.html")]
    assert len(set(bodies)) == len(bodies)


def test_weight_pickers_always_have_kg_lb_toggle(tmp_path: Path):
    app, sp = _app(tmp_path)
    doc = design.skeleton(sp, app)
    doc["onboarding"][7] = {"id": "target_weight", "kind": "picker", "section": "x", "title": "Desired weight?",
                            "picker": {"type": "weight"}, "motion": "Ruler snaps", "key": "onb.target_weight"}
    doc["onboarding"][9]["picker"] = {"type": "slider", "measure": "weight", "min": 1, "max": 15, "default": 8,
                                      "unit": "kg / week"}
    screens.save(app, doc)
    assert design.generate(app)["ok"]
    for name in ("S08-TargetWeight.dc.html", "S10-Pace.dc.html"):
        html = (app / design.SCAFFOLD_REL / name).read_text()
        assert "{{toKg}}" in html and "{{toLb}}" in html and ">kg</button>" in html and ">lb</button>" in html


def test_paywall_prices_come_from_spec(tmp_path: Path):
    app, sp = _app(tmp_path)
    _write_doc(app, sp)
    design.generate(app)
    pw = (app / design.SCAFFOLD_REL / "S25-Paywall.dc.html").read_text()
    assert "$49.99" in pw and "$7.99" in pw and "SAVE 88%" in pw and "3 days free" in pw
    offer = (app / design.SCAFFOLD_REL / "S26-Offer.dc.html").read_text()
    assert "$29.99" in offer and "40% OFF" in offer and "burger" in offer


def test_pricing_badge_and_offer():
    sp = spec.build("Hue", "com.example.hue")
    plans = pricing.plans(sp)
    assert [p["name"] for p in plans] == ["Weekly", "Yearly"]
    assert plans[1]["badge"] == "SAVE 88%" and plans[1]["preselected"]
    o = pricing.offer(sp)
    assert o["off"] == 40 and o["per_month_text"] == "$2.50"


def test_generate_uses_approved_poses_with_fallback(tmp_path: Path):
    app, sp = _app(tmp_path)
    _write_doc(app, sp)
    m = app / "design" / "mascot"
    m.mkdir(parents=True)
    (m / "idle.png").write_bytes(MIN_PNG)
    (m / "idle-blink.png").write_bytes(MIN_PNG)
    (m / "think.png").write_bytes(MIN_PNG)
    r = design.generate(app)
    assert r["ok"]
    assert "mascot/sleep.png" in r["binary_files"]  # sleep borrows think
    board = (app / design.PROJECT_REL / "M08-Sleep.dc.html").read_text()
    assert 'src="mascot/sleep.png"' in board
    pose_warnings = [w for w in r["warnings"] if w.startswith("no approved pose")]
    assert not pose_warnings or "idle" not in pose_warnings[0].split("for ")[1].split(" in")[0]


def test_generate_refuses_invalid_screens(tmp_path: Path):
    app, sp = _app(tmp_path)
    doc = design.skeleton(sp, app)
    doc["onboarding"][3]["kind"] = "rating"
    screens.save(app, doc)
    r = design.generate(app)
    assert r["ok"] is False and any("rating" in p for p in r["problems"])


# ---------------------------------------------------------------- gate

def _review(app: Path, ok=True):
    v = app / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "design_review.json").write_text(json.dumps({"fidelity_ok": ok, "platform_rules_ok": True}))


def _ready(tmp_path: Path) -> Path:
    return design_ready(tmp_path)


def test_design_gate_claude_passes(tmp_path: Path):
    r = gates.validate_stage(_ready(tmp_path), "design")
    assert r["ok"] is True and "Claude Design" in r["reason"] and PROJECT_ID in r["reason"]


def test_design_gate_claude_needs_fidelity_review(tmp_path: Path):
    app = _ready(tmp_path)
    _review(app, ok=False)
    assert gates.validate_stage(app, "design")["ok"] is False


def test_design_gate_claude_rejects_stale_canvas(tmp_path: Path):
    app = _ready(tmp_path)
    doc = screens.load(app)
    doc["main"].append({"id": "extra_list", "kind": "list", "title": "Saved", "motion": "rise", "items": ["a"]})
    screens.save(app, doc)
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "stale" in r["reason"]


def test_design_gate_claude_rejects_dark_patterns(tmp_path: Path):
    app = _ready(tmp_path)
    doc = screens.load(app)
    doc["onboarding"][4]["footnote"] = "Join 1,000,000 users"
    screens.save(app, doc)
    assert gates.validate_stage(app, "design")["ok"] is False


def test_design_gate_claude_rejects_duplicate_screens(tmp_path: Path):
    app = _ready(tmp_path)
    doc = screens.load(app)
    dup = copy.deepcopy(doc["onboarding"][1])
    dup["id"] = "about_again"
    doc["onboarding"].insert(2, dup)
    screens.save(app, doc)
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "duplicates" in r["reason"]


def test_design_gate_without_any_design(tmp_path: Path):
    r = gates.validate_stage(tmp_path, "design")
    assert r["ok"] is False and "screens.json" in r["reason"] and "Claude Design" in r["reason"]


def test_design_gate_rejects_legacy_stitch_manifest(tmp_path: Path):
    d = tmp_path / ".appfactory" / "design"
    d.mkdir(parents=True)
    (d / "screens.json").write_text(json.dumps([{"screen": "welcome", "stitch_project_id": "p", "prompt": "x",
                                                 "html_path": "w.html"}]))
    r = gates.validate_stage(tmp_path, "design")
    assert r["ok"] is False and "Stitch" in r["reason"] and "no longer accepted" in r["reason"]


def test_design_gate_requires_recorded_upload(tmp_path: Path):
    app = _ready(tmp_path)
    (app / receipt.RECEIPT_REL).unlink()
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "design_record_upload" in r["reason"]


def test_design_gate_rejects_changes_after_upload(tmp_path: Path):
    app = _ready(tmp_path)
    board = app / design.PROJECT_REL / "S01-Welcome.dc.html"
    board.write_text(board.read_text() + "<!-- local edit -->")
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "changed since the Claude Design upload" in r["reason"]


def test_design_gate_rejects_partial_upload(tmp_path: Path):
    app = _ready(tmp_path)
    rec = json.loads((app / receipt.RECEIPT_REL).read_text())
    rec["files"].pop(brand.store_files(research.load_brief(app))[0])
    (app / receipt.RECEIPT_REL).write_text(json.dumps(rec))
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "not uploaded" in r["reason"]


# ---------------------------------------------------------------- receipt

@pytest.mark.parametrize("pid, url, needle", [
    ("", OPEN_URL, "project_id"),
    ("p1", "http://claude.ai/design/x", "open_url"),
    ("p1", "https://abc.claudeusercontent.com/serve?token=x", "serve_url"),
])
def test_record_upload_validates_inputs(tmp_path: Path, pid, url, needle):
    app = design_ready(tmp_path)
    r = receipt.record(app, pid, url)
    assert r["ok"] is False and needle in r["error"]


def test_record_upload_stores_project_id_in_plan(tmp_path: Path):
    app = design_ready(tmp_path)
    plan = json.loads((app / receipt.PLAN_REL).read_text())
    assert plan["project_id"] == PROJECT_ID
    # a regenerate keeps the project id so the next upload reuses the project
    design.generate(app)
    assert json.loads((app / receipt.PLAN_REL).read_text())["project_id"] == PROJECT_ID


# ---------------------------------------------------------------- icon (brand page)

def test_authored_boards_survive_regenerate(tmp_path: Path):
    app = design_ready(tmp_path)
    board = app / design.PROJECT_REL / brand.ICON_BOARD
    assert 'data-icon-master="true"' in board.read_text()
    board.write_text(board.read_text().replace("#2BB673", "#123456"))  # refined in Claude Design, synced back
    design.generate(app)
    assert "#123456" in board.read_text()
    assert brand.SCAFFOLD_MARK in (app / design.SCAFFOLD_REL / brand.ICON_BOARD).read_text()


def test_icon_generate_is_opt_in_and_never_installs(tmp_path: Path):
    r = icon.generate(tmp_path, "a plant app")
    assert r["ok"] is False and "Claude Design" in r["error"]
    assert not (tmp_path / icon.APPICON_REL).exists()


def _icon_installed(app: Path) -> dict:
    icon_master(app)
    upload(app)  # design_generate copies design/icon.png into the project → upload → record
    return icon.install(app)


def test_icon_install_and_gate(tmp_path: Path):
    app = design_ready(tmp_path)
    r = _icon_installed(app)
    assert r["ok"], r
    marker = json.loads((app / icon.VERIFY_REL).read_text())
    assert marker["source"] == "claude_design" and marker["board"] == brand.ICON_BOARD
    g = gates.validate_stage(app, "icon")
    assert g["ok"] is True and "Claude Design" in g["reason"]


def test_icon_install_requires_uploaded_master(tmp_path: Path):
    app = design_ready(tmp_path)
    icon_master(app)  # exported but never regenerated/uploaded
    r = icon.install(app)
    assert r["ok"] is False and "Claude Design" in r["error"]


def test_icon_install_rejects_wrong_size(tmp_path: Path):
    app = design_ready(tmp_path)
    (app / "design" / "icon.png").write_bytes(png(512, 512))
    r = icon.install(app)
    assert r["ok"] is False and "1024" in r["error"]


def test_icon_gate_rejects_non_claude_design_icon(tmp_path: Path):
    app = design_ready(tmp_path)
    ai = app / icon.APPICON_REL
    ai.mkdir(parents=True)
    (ai / "icon_1024.png").write_bytes(png(1024, 1024))
    (ai / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon_1024.png", "size": "1024x1024"}]}))
    r = gates.validate_stage(app, "icon")
    assert r["ok"] is False and "Claude Design" in r["reason"]


def test_icon_gate_rejects_swapped_appiconset(tmp_path: Path):
    app = design_ready(tmp_path)
    assert _icon_installed(app)["ok"]
    (app / icon.APPICON_REL / "icon_1024.png").write_bytes(png(1024, 1024, seed=9))
    r = gates.validate_stage(app, "icon")
    assert r["ok"] is False and "icon_install" in r["reason"]


# ---------------------------------------------------------------- store creatives

def test_store_boards_start_as_placeholders(tmp_path: Path):
    app = design_ready(tmp_path)
    out = app / design.PROJECT_REL
    files = brand.store_files(research.load_brief(app))
    assert brand.placeholders(out, files) == files
    lay = json.loads((out / brand.STORE_LAYOUT).read_text())
    assert lay["canvas"] == {"w": 1320, "h": 2868} and lay["brandColorBottom"] == "#12402A"  # brief layout
    assert lay["shots"] == ["01_result", "02_onboarding", "03_paywall", "04_create"]
    assert lay["brief_sha256"] == research.brief_sha(app) and lay["concept"]


def test_store_boards_use_captions_and_captures(tmp_path: Path):
    app = design_ready(tmp_path)
    store_ready(app)
    out = app / design.PROJECT_REL
    files = brand.store_files(research.load_brief(app))
    assert brand.placeholders(out, files) == []
    first = (out / files[0]).read_text()
    assert "Hue headline 0" in first and 'src="store/raw/01_result.png"' in first
    plan = json.loads((out / "upload_plan.json").read_text())
    assert "store/raw/01_result.png" in plan["binary_files"] and brand.STORE_LAYOUT in plan["files"]
    cfg = json.loads((app / "marketing" / "screenshots" / "config.json").read_text())
    assert cfg["brandColorTop"] == "#2BB673" and cfg["canvas"] == {"w": 1320, "h": 2868}
    assert ss.screens_for(cfg["shots"])[2] == ("03_paywall", ss.CAPTURE_ARGS["paywall"])


def test_capture_keys_match_screenshot_module():
    assert research.CAPTURE_KEYS == list(ss.CAPTURE_ARGS)


def test_build_all_refuses_without_claude_design_layout(tmp_path: Path):
    r = ss.build_all(tmp_path, "X.xcodeproj", "X", "com.x", "sample", "UDID")
    assert r["ok"] is False and r["step"] == "layout"


def test_onboarding_heroes_are_opt_in(tmp_path: Path):
    r = ss.generate_onboarding_heroes(tmp_path, "plants", count=2)
    assert r["ok"] is False and "Claude Design" in r["error"]


# ---------------------------------------------------------------- export

def test_export_png_uses_headless_chrome_and_checks_size(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(cmd, timeout=120, cwd=None, env=None):
        calls.append(cmd)
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--screenshot="))
        Path(out).write_bytes(png(1024, 1024))
        return {"ok": True, "stdout": "", "stderr": ""}

    monkeypatch.setattr(export, "chrome_binary", lambda: "/bin/chrome")
    monkeypatch.setattr(export, "run", fake_run)
    r = export.export_png("https://x.claudeusercontent.com/s?t=secret", tmp_path / "icon.png", 1024, 1024)
    assert r["ok"] and "--headless=new" in calls[0] and "secret" not in json.dumps(r)
    bad = export.export_png("https://x.claudeusercontent.com/s?t=secret", tmp_path / "st.png", 440, 956, scale=3)
    assert bad["ok"] is False and "expected 1320×2868" in bad["error"] and "secret" not in json.dumps(bad)
    assert export.export_png("file:///etc/passwd", tmp_path / "x.png", 1, 1)["ok"] is False


def test_claude_design_tools_registered():
    import asyncio

    from fastmcp import Client

    from appfactory.server import mcp

    async def _list():
        async with Client(mcp) as c:
            return {t.name for t in await c.list_tools()}

    names = asyncio.run(_list())
    for n in ("design_research_collect", "design_research_brief_template", "design_research_check",
              "design_screens_skeleton", "design_generate", "design_record_upload", "design_upload_status",
              "design_export_png", "icon_install", "screenshot_apply_layout"):
        assert n in names


def test_visual_stage_instructions_route_through_claude_design():
    from appfactory import pipeline
    for stage in ("design", "icon", "screenshots"):
        text = pipeline.STAGE_INSTRUCTIONS[stage]
        assert "Claude Design" in text and "design_record_upload" in text, stage
    assert "Stitch" not in pipeline.STAGE_INSTRUCTIONS["design"].replace("no Stitch", "")
    assert "Flux" not in pipeline.STAGE_INSTRUCTIONS["icon"]
