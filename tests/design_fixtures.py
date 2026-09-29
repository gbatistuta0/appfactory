"""Shared fixtures for the Claude Design tests: a Hue app with design research (reference apps on disk),
a cited brief, spec/screens derived from it, boards authored from the scaffolds, a recorded upload,
store creatives with real captions/captures, and a Claude Design icon. No network, no Chrome."""

from __future__ import annotations

import datetime
import json
import struct
import zlib
from pathlib import Path

from appfactory import design, spec
from appfactory.design import brand, receipt, research, screens

OPEN_URL = "https://claude.ai/design/p/hue-project"
PROJECT_ID = "proj-hue"
REF_NAMES = ["Leafy Plant Care", "Bloom Garden Journal", "Sprout Tracker", "Fern Watering Buddy",
             "Grove Plant ID", "Petal Care Coach", "Moss Daily"]
BRIEF_TOKENS = {"background": "#F4FBF6", "ink": "#10231A", "accent": "#2BB673", "cta": "#1F9D5C"}
BRIEF_FONTS = {"display": "Fraunces", "body": "Inter"}
STORE_SHOTS = ["result", "onboarding", "paywall", "create"]


def png(w: int, h: int, color_type: int = 2, seed: int = 0) -> bytes:
    """A valid PNG (RGB by default, no alpha) — enough for IHDR checks and hashing."""
    channels = {2: 3, 6: 4}[color_type]
    row = b"\x00" + bytes([seed % 256]) * (w * channels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


def write_research(app: Path, n: int = len(REF_NAMES), collected_at: str | None = None) -> list[str]:
    apps = []
    for i, name in enumerate(REF_NAMES[:n]):
        rid = str(1000 + i)
        folder = f"{research.APPS_REL}/{rid}-{research._slug(name)}"
        (app / folder).mkdir(parents=True, exist_ok=True)
        (app / folder / "icon.png").write_bytes(png(4, 4, seed=i))
        shots = []
        for j in range(3):
            rel = f"{folder}/screenshot-{j + 1:02d}.png"
            (app / rel).write_bytes(png(4, 8, seed=i * 10 + j))
            shots.append(rel)
        apps.append({"id": rid, "name": name, "seller": f"Seller {i}", "genre": "Lifestyle", "rating": 4.6,
                     "ratings_count": 1000 * (n - i), "countries": ["us", "gb"], "sources": ["search:plant care"],
                     "store_url": f"https://apps.apple.com/app/id{rid}", "icon": f"{folder}/icon.png", "screenshots": shots})
    now = collected_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (app / research.REFS_REL).write_text(json.dumps({"collected_at": now, "terms": ["plant care"],
                                                     "countries": ["us", "gb", "de"], "apps": apps}))
    return [a["id"] for a in apps]


def brief_doc(ids: list[str], flow: list[str], tokens: dict | None = None, fonts: dict | None = None) -> dict:
    def cite(k: int = 2) -> dict:
        return {"borrows": ids[:k], "differs": "warmer, calmer and less clinical than the leaders"}

    return {
        "version": 1, "app": "Hue", "purpose": "Plant owners who keep forgetting care routines", "references": ids,
        "analysis": {"shared_patterns": ["green palettes, photo-led"], "differentiators": ["journal vs tracker"],
                     "gaps": ["no playful guide"]},
        "direction": {
            "palette": {"tokens": dict(tokens or BRIEF_TOKENS), **cite()},
            "typography": {**(fonts or BRIEF_FONTS), **cite()},
            "components": {"style": "soft cards, pill buttons", **cite()},
            "density": {"level": "airy", **cite()},
            "illustration": {"style": "chameleon mascot, flat", **cite()},
            "onboarding": {"flow": flow, "rationale": "personalize first", **cite()},
            "paywall": {"style": "plan cards + offer anchor", **cite()},
            "screenshots": {
                "analysis": {k: f"{k} observations across the leaders" for k in research.SCREENSHOT_ANALYSIS},
                "concept": "the plant's week told in four frames",
                "boards": [{"shot": s, "message": f"{s} message", "layout": "device right, headline left"}
                           for s in STORE_SHOTS],
                "layout": {"brandColorTop": "#2BB673", "brandColorBottom": "#12402A", "headlineColor": "#FFFFFF"},
                **cite(4)},
        },
        "no_copy": True,
    }


def write_brief(app: Path, doc: dict) -> None:
    (app / research.BRIEF_JSON_REL).write_text(json.dumps(doc, indent=2))
    (app / research.BRIEF_MD_REL).write_text("# Hue design brief\n\nReferences: " + ", ".join(REF_NAMES) + "\n")


def make_app(tmp: Path, name: str = "Hue") -> tuple[Path, dict]:
    """The app lives in <tmp>/<name> so sibling apps (anti-sameness check) are only this test's."""
    tmp = tmp / name
    (tmp / research.RESEARCH_REL).mkdir(parents=True, exist_ok=True)
    ids = write_research(tmp)
    flow = [s["kind"] for s in screens.skeleton()["onboarding"]]
    write_brief(tmp, brief_doc(ids, flow))
    sp = spec.build("Hue", "com.example.hue", design={"tokens": dict(BRIEF_TOKENS), "fonts": dict(BRIEF_FONTS),
                                                        "mascot": {"name": "Kami", "species": "chameleon",
                                                                   "states": spec.MASCOT_STATES}})
    spec.save(tmp, sp)
    screens.save(tmp, design.skeleton(sp, tmp))
    return tmp, sp


def author(app: Path) -> None:
    """Stand-in for Claude authoring each board in Claude Design from the brief and syncing it back."""
    plan = json.loads((app / receipt.PLAN_REL).read_text())
    for f in plan["authored"]:
        txt = (app / design.SCAFFOLD_REL / f).read_text().replace(brand.SCAFFOLD_MARK, 'data-authored="brief"')
        (app / design.PROJECT_REL / f).write_text(txt + "<!-- authored in Claude Design from the brief -->\n")


def upload(app: Path) -> dict:
    """design_generate → author → a recorded upload of every planned file."""
    r = design.generate(app)
    assert r["ok"], r
    author(app)
    rec = receipt.record(app, PROJECT_ID, OPEN_URL)
    assert rec["ok"], rec
    return r


def design_ready(tmp: Path) -> Path:
    """Everything the design gate needs."""
    app, _ = make_app(tmp)
    upload(app)
    (app / "Sources").mkdir(exist_ok=True)
    (app / "Sources" / "DesignSystem.swift").write_text("// ds")
    v = app / ".appfactory" / "verify"
    v.mkdir(parents=True, exist_ok=True)
    (v / "design_review.json").write_text(json.dumps({"fidelity_ok": True, "platform_rules_ok": True}))
    return app


def store_ready(app: Path) -> None:
    """ASO captions + en-US raw captures per concept board → regenerated, re-authored, uploaded, applied."""
    md = app / "marketing" / "screenshots"
    (md / "copy").mkdir(parents=True, exist_ok=True)
    (md / "copy" / "en-US.json").write_text(json.dumps(
        [{"headline": f"Hue headline {i}", "subhead": f"Hue subhead {i}"} for i in range(len(STORE_SHOTS))]))
    (md / "raw" / "en-US").mkdir(parents=True, exist_ok=True)
    for i, shot in enumerate(STORE_SHOTS, 1):
        (md / "raw" / "en-US" / f"{brand.capture_name(i, shot)}.png").write_bytes(png(4, 8, seed=i))
    upload(app)
    assert brand.apply_layout(app)["ok"]


def icon_master(app: Path, color_type: int = 2) -> Path:
    p = app / "design" / "icon.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(png(1024, 1024, color_type))
    return p
