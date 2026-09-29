"""design_research: reference collection, the brief, anti-sameness, brief-derived design + the new gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appfactory import design, gates, pipeline, spec
from appfactory.design import receipt, research, rules, screens
from design_fixtures import (BRIEF_TOKENS, REF_NAMES, author, brief_doc, design_ready, make_app, png,
                             write_brief, write_research)


def _flow() -> list[str]:
    return [s["kind"] for s in screens.skeleton()["onboarding"]]


# ---------------------------------------------------------------- collect

def test_collect_downloads_leaders_across_storefronts(tmp_path: Path, monkeypatch):
    def app_json(i: int, genre: int = 6012) -> dict:
        return {"trackId": 500 + i, "trackName": f"Leader {i}", "sellerName": f"S{i}", "primaryGenreName": "Lifestyle",
                "primaryGenreId": genre, "averageUserRating": 4.5, "userRatingCount": 1000 * i,
                "trackViewUrl": f"https://apps.apple.com/app/id{500 + i}",
                "screenshotUrls": [f"https://img/{i}/{j}.jpg" for j in range(4)], "artworkUrl512": f"https://img/{i}/icon.png"}

    seen = []

    def fake_get(url, params=None):
        seen.append(url)
        if url == research.ITUNES_SEARCH:
            base = 0 if params["country"] == "us" else 3
            return {"results": [app_json(i) for i in range(base, base + 5)]}
        if "rss" in url:
            assert "genre=6012" in url
            return {"feed": {"entry": [{"id": {"attributes": {"im:id": "520"}}}]}}
        if url == research.ITUNES_LOOKUP:
            return {"results": [app_json(20)]}
        raise AssertionError(url)

    monkeypatch.setattr(research, "_get_json", fake_get)
    monkeypatch.setattr(research, "_download", lambda url, dest: (dest.parent.mkdir(parents=True, exist_ok=True),
                                                                  dest.write_bytes(b"img"))[-1] is None or True)
    r = research.collect(tmp_path, ["plant care"], countries=["us", "gb"], max_apps=10, screenshots_per_app=3)
    assert r["ok"], r
    refs = json.loads((tmp_path / research.REFS_REL).read_text())
    ids = [a["id"] for a in refs["apps"]]
    assert "520" in ids  # top chart app looked up
    shared = next(a for a in refs["apps"] if a["id"] == "503")
    assert shared["countries"] == ["gb", "us"] and ids.index("503") < ids.index("500")  # multi-storefront ranks first
    assert len(shared["screenshots"]) == 3 and (tmp_path / shared["icon"]).exists()
    assert any("topgrossing" in u for u in seen) and any("topfree" in u for u in seen)


def test_collect_needs_terms(tmp_path: Path):
    assert research.collect(tmp_path, [])["ok"] is False


def test_references_need_enough_apps_on_disk(tmp_path: Path):
    write_research(tmp_path, n=4)
    r = research.check_references(tmp_path)
    assert r["ok"] is False and "4 reference apps" in r["reason"]


# ---------------------------------------------------------------- brief

def _brief_app(tmp_path: Path, **over) -> tuple[Path, dict]:
    ids = write_research(tmp_path)
    doc = brief_doc(ids, _flow())
    for k, v in over.items():
        doc[k] = v
    write_brief(tmp_path, doc)
    return tmp_path, doc


def test_valid_brief_passes(tmp_path: Path):
    app, _ = _brief_app(tmp_path)
    assert research.validate_brief(app) == []
    assert research.check(app)["ok"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["direction"].pop("paywall"), "direction.paywall missing"),
    (lambda d: d["direction"]["palette"].update(borrows=["999"]), "palette.borrows"),
    (lambda d: d["direction"]["density"].update(differs=""), "density.differs"),
    (lambda d: d.update(no_copy=False), "no_copy"),
    (lambda d: d.update(references=d["references"][:3]), "reference apps < 6"),
    (lambda d: d["direction"]["screenshots"]["analysis"].pop("frame1_hook"), "frame1_hook"),
    (lambda d: d["direction"]["screenshots"].update(borrows=d["references"][:2]), "screenshot sets < 4"),
    (lambda d: d["direction"]["screenshots"].update(boards=[{"shot": "paywall", "message": "x"}]), "3..10 boards"),
    (lambda d: d["direction"]["screenshots"]["boards"].append({"shot": "result", "message": "dup"}), "distinct"),
    (lambda d: d["direction"]["onboarding"].update(flow=["welcome", "offer", "paywall"]), "paywall followed"),
    (lambda d: d["direction"]["palette"]["tokens"].update(background="#FFFFFF", ink="#DDDDDD"), "WCAG AA"),
])
def test_brief_problems(tmp_path: Path, mutate, needle):
    ids = write_research(tmp_path)
    doc = brief_doc(ids, _flow())
    mutate(doc)
    write_brief(tmp_path, doc)
    errs = research.validate_brief(tmp_path)
    assert any(needle in e for e in errs), errs


def test_brief_md_must_name_cited_references(tmp_path: Path):
    app, _ = _brief_app(tmp_path)
    (app / research.BRIEF_MD_REL).write_text("# brief without names\n")
    assert any("does not name cited references" in e for e in research.validate_brief(app))


def test_anti_sameness_template_defaults(tmp_path: Path):
    ids = write_research(tmp_path)
    write_brief(tmp_path, brief_doc(ids, _flow(), tokens=dict(spec.DEFAULTS["design"]["tokens"])))
    assert any("template defaults" in e for e in research.validate_brief(tmp_path))


def test_anti_sameness_other_factory_app(tmp_path: Path):
    other = tmp_path / "Leaf"
    other.mkdir()
    spec.save(other, spec.build("Leaf", "com.example.leaf", design={"tokens": dict(BRIEF_TOKENS),
                                                                      "fonts": {"display": "Fraunces", "body": "Inter"}}))
    app, _ = make_app(tmp_path)  # Hue, same palette + type as Leaf
    errs = research.validate_brief(app)
    assert any("identical to Leaf" in e for e in errs), errs


def test_brief_template_lists_references_and_rules(tmp_path: Path):
    write_research(tmp_path)
    t = research.brief_template(tmp_path)
    assert len(t["references"]) == len(REF_NAMES)
    assert set(t["direction"]) == set(research.SECTIONS)
    assert set(t["direction"]["screenshots"]["analysis"]) == set(research.SCREENSHOT_ANALYSIS)
    assert t["rules"]["app"] == rules.APP_RULES and t["rules"]["store"] == rules.STORE_RULES


# ---------------------------------------------------------------- stage + gates

def test_design_research_stage_precedes_design():
    assert pipeline.STAGES.index("design_research") == pipeline.STAGES.index("design") - 1
    assert "design_research_collect" in pipeline.STAGE_INSTRUCTIONS["design_research"]


def test_legacy_manifest_with_design_done_skips_research(tmp_path: Path):
    p = tmp_path / ".appfactory"
    p.mkdir()
    stages = {s: "done" for s in pipeline.STAGES if s != "design_research"}
    (p / "state.json").write_text(json.dumps({"app": "Old", "bundle_id": "x", "stages": stages}))
    assert pipeline.load(tmp_path)["stages"]["design_research"] == "done"


def test_design_research_gate(tmp_path: Path):
    assert gates.validate_stage(tmp_path, "design_research")["ok"] is False
    app, _ = _brief_app(tmp_path)
    assert gates.validate_stage(app, "design_research")["ok"] is True


def test_generate_refuses_without_research(tmp_path: Path):
    sp = spec.build("Hue", "com.example.hue")
    spec.save(tmp_path, sp)
    screens.save(tmp_path, screens.skeleton(sp))
    r = design.generate(tmp_path)
    assert r["ok"] is False and "design research first" in r["error"]


def test_generate_refuses_tokens_not_from_brief(tmp_path: Path):
    app, sp = make_app(tmp_path)
    sp["design"]["tokens"]["accent"] = "#FF0000"
    spec.save(app, sp)
    r = design.generate(app)
    assert r["ok"] is False and any("differ from the brief palette" in p for p in r["problems"])


def test_generate_refuses_screens_not_from_brief(tmp_path: Path):
    app, sp = make_app(tmp_path)
    screens.save(app, screens.skeleton(sp))  # no brief_sha256
    r = design.generate(app)
    assert r["ok"] is False and any("not derived from the current brief" in p for p in r["problems"])


def test_skeleton_follows_brief_flow(tmp_path: Path):
    ids = write_research(tmp_path)
    flow = ["welcome", "question", "question", "emotional", "loading", "plan_ready", "paywall", "offer"]
    write_brief(tmp_path, brief_doc(ids, flow))
    doc = design.skeleton(spec.build("Hue", "com.example.hue"), tmp_path)
    assert [s["kind"] for s in doc["onboarding"]] == flow and doc["brief_sha256"] == research.brief_sha(tmp_path)


def test_design_gate_rejects_unauthored_scaffold_upload(tmp_path: Path):
    app, _ = make_app(tmp_path)
    design.generate(app)
    for f in json.loads((app / receipt.PLAN_REL).read_text())["authored"]:  # uploads the scaffolds as-is
        (app / design.PROJECT_REL / f).write_text((app / design.SCAFFOLD_REL / f).read_text())
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "still the generated scaffold" in r["reason"]


def test_design_gate_rejects_emoji_in_authored_board(tmp_path: Path):
    app = design_ready(tmp_path)
    board = app / design.PROJECT_REL / "S01-Welcome.dc.html"
    board.write_text(board.read_text().replace("</x-dc>", "<p>Grow 🌱</p></x-dc>"))
    receipt.record(app, "p", "https://claude.ai/design/p/x")
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "SF Symbols" in r["reason"]


def test_design_gate_requires_platform_rules_review(tmp_path: Path):
    app = design_ready(tmp_path)
    (app / ".appfactory" / "verify" / "design_review.json").write_text('{"fidelity_ok": true}')
    r = gates.validate_stage(app, "design")
    assert r["ok"] is False and "platform_rules_ok" in r["reason"] and "opaque background" in r["reason"]


def test_upload_must_follow_current_brief(tmp_path: Path):
    app = design_ready(tmp_path)
    assert receipt.check_after_brief(app)["ok"]
    p = app / research.BRIEF_JSON_REL
    p.write_text(p.read_text() + "\n")  # brief revised after the upload
    r = receipt.check_after_brief(app)
    assert r["ok"] is False and "before the current design brief" in r["reason"]


def test_screenshots_need_fresh_research(tmp_path: Path):
    app, _ = make_app(tmp_path)
    write_research(app, collected_at="2020-01-01T00:00:00Z")
    r = research.check_screenshot_concept(app)
    assert r["ok"] is False and "older than" in r["reason"]


# ---------------------------------------------------------------- rules

def test_rules_contrast_and_emoji():
    assert rules.contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert rules.contrast_problems({"ink": "#777777", "background": "#FFFFFF"})  # 4.48 < 4.5
    assert not rules.contrast_problems({"ink": "#10231A", "background": "#F4FBF6"})
    assert rules.has_emoji("Great job 🎉") and not rules.has_emoji("Great job")


def test_rating_copy_allowed_in_app_but_never_in_onboarding():
    doc = screens.skeleton()
    doc["main"][0]["subtitle"] = "Enjoying it? Rate us"
    assert not any("rating prompt" in e for e in screens.validate(doc))
    doc["onboarding"][2]["subtitle"] = "Rate us"
    assert any("rating prompt" in e for e in screens.validate(doc))
