"""preview.py — the Claude-authored App Preview: spec rules, readiness check, self-review log,
deterministic composition, ASC upload and the stage gate (fake ffprobe and ASC, no network)."""
import json
from pathlib import Path

import pytest

from appfactory import gates, preview, spec

GOOD = {"width": 886, "height": 1920, "codec": "h264", "fps": 30.0, "duration": 24.0, "audio": [("aac", 2)]}
SCORES = {k: 9 for k in preview.REVIEW_CRITERIA}


class FakeASC:
    def __init__(self, routes=None):
        self.calls = []
        self.routes = routes or {}
        self._n = 0

    def request(self, method, path, json=None, params=None):
        self.calls.append((method, path))
        self._n += 1
        if method == "GET":
            return {"ok": True, "data": {"data": self.routes.get(path, [])}}
        return {"ok": True, "data": {"data": {"id": f"id{self._n}", "attributes": {}}}}

    # first-class asc commands (ASCClient methods)
    def upload_preview(self, localization_id, path, preview_type):
        self.calls.append(("upload_preview", f"{localization_id}/{preview_type}/{Path(path).name}"))
        return {"ok": True, "id": f"pv{len(self.calls)}"}

    def set_preview_poster(self, preview_id, time_code):
        self.calls.append(("poster", f"{preview_id}@{time_code}"))
        return {"ok": True}

    def delete_preview(self, preview_id):
        self.calls.append(("delete_preview", preview_id))
        return {"ok": True}


def _app(tmp_path: Path, **over) -> Path:
    app = tmp_path / "Hue"
    app.mkdir()
    spec.save(app, spec.build("Hue", "com.x.hue", **over))
    return app


def _ready(app: Path, locales=("en-US",)) -> list[Path]:
    preview.brief(app)
    files = []
    for loc in locales:
        rec = app / preview.RECORDINGS_REL / loc
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "seg1_result.mp4").write_bytes(b"raw")
        d = app / preview.PREVIEWS_REL / loc
        d.mkdir(parents=True, exist_ok=True)
        f = d / "hue-preview.mp4"
        f.write_bytes(f"video-{loc}".encode())
        files.append(f)
    return files


def test_upload_one_preview_uploads_then_sets_the_poster(tmp_path):
    f = tmp_path / "preview.mp4"
    f.write_bytes(b"\x00\x01\x02fakevideo")
    c = FakeASC()
    res = preview.upload_one_preview(c, "LOC1", f, poster="00:00:05:00")
    assert res == {"ok": True, "id": "pv1"}
    assert c.calls == [("upload_preview", "LOC1/IPHONE_67/preview.mp4"), ("poster", "pv1@00:00:05:00")]


def test_spec_preview_rules():
    s = spec.build("Hue", "com.x.hue")
    assert spec.validate(s) == [] and spec.preview(s)["shared"]["en-GB"] == "en-US"
    for bad in ({"size": [1080, 1920]}, {"fps": 60}, {"max_s": 45}, {"poster": "5s"},
                {"locales": ["en-GB"]}, {"shared": {"es-MX": "en-GB"}}):
        assert spec.validate(spec.build("Hue", "com.x.hue", preview=bad)), bad
    own = spec.build("Hue", "com.x.hue", preview={"shared": {"en-GB": "en-GB"}})
    assert spec.validate(own) == [] and preview.source_locale(preview.rules(own), "en-GB") == "en-GB"


def test_brief_is_an_app_store_preview_brief(tmp_path):
    app = _app(tmp_path)
    r = preview.brief(app, "Snap a photo, get the answer.")
    text = (app / preview.BRIEF_REL).read_text()
    assert r["written"] and "destination: app-store-preview" in text and "aspect: 886x1920" in text
    assert "recordVideo" in text and "real app footage" in text.lower()
    assert "en-GB" not in r["locales"] and "en-US" in r["locales"]      # en-GB shares en-US
    assert preview.brief(app)["written"] is False


def test_check_needs_footage_coverage_and_the_apple_spec(tmp_path):
    app = _app(tmp_path, preview={"locales": ["en-US", "en-GB", "tr"]})
    files = _ready(app, ("en-US", "tr"))
    ok = preview.check(app, lambda f: GOOD)
    assert ok["ok"], ok["problems"]
    assert ok["plan"]["en-GB"] == ok["plan"]["en-US"] == ["fastlane/app_previews/en-US/hue-preview.mp4"]

    (app / preview.RECORDINGS_REL / "tr" / "seg1_result.mp4").unlink()
    assert any("real app footage" in p for p in preview.check(app, lambda f: GOOD)["problems"])
    (app / preview.RECORDINGS_REL / "tr" / "seg1_result.mp4").write_bytes(b"raw")

    bad = {**GOOD, "width": 1080, "fps": 60.0, "duration": 40.0, "codec": "hevc", "audio": [("aac", 1)]}
    text = " ".join(preview.check(app, lambda f: bad if f == files[1] else GOOD)["problems"])
    for want in ("1080x1920", "60.0 fps", "40.0 s", "hevc", "aac/1"):
        assert want in text, want
    files[1].unlink()
    assert any(p.startswith("tr: no preview") for p in preview.check(app, lambda f: GOOD)["problems"])


def test_self_review_must_pass_on_the_final_file(tmp_path):
    app = _app(tmp_path, preview={"locales": ["en-US"]})
    (f,) = _ready(app)
    rel = str(f.relative_to(app))
    assert "no self-review" in preview.review_status(app)["problems"][0]
    low = {**SCORES, "hook": 6}
    assert preview.log_review(app, rel, low, [{"t": "00:01.0", "issue": "slow open"}])["ok"] is False
    probs = [{"t": "00:00.5", "issue": "logo first"}, {"t": "00:09.0", "issue": "caption overlaps"},
             {"t": "00:17.2", "issue": "dead beat"}]
    assert preview.log_review(app, rel, low, probs)["pass"] is False
    assert "every criterion needs 8+" in preview.review_status(app)["problems"][0]
    assert preview.log_review(app, rel, {**SCORES, "extra": 9}, [])["ok"] is False
    assert preview.log_review(app, rel, SCORES, [])["round"] == 2
    assert preview.review_status(app)["ok"] is True
    f.write_bytes(b"re-rendered")                                     # not the reviewed file any more
    assert "changed since its last review" in preview.review_status(app)["problems"][0]
    log = json.loads((app / preview.REVIEW_LOG_REL).read_text())
    assert [e["round"] for e in log] == [1, 2] and log[0]["problems"][0]["t"] == "00:00.5"


def test_composition_must_render_deterministically(tmp_path):
    app = _app(tmp_path, preview={"locales": ["en-US"]})
    _ready(app)
    comp = app / preview.PREVIEW_DIR_REL / "index.html"
    comp.write_text("<script>tl.to('.a', {x: 10})</script>")
    (app / preview.PREVIEW_DIR_REL / "assets").mkdir(exist_ok=True)
    (app / preview.PREVIEW_DIR_REL / "assets" / "gsap.js").write_text("setTimeout(f)")   # vendored: ignored
    assert preview.determinism_problems(app) == []
    comp.write_text("<script>const x = Math.random(); setTimeout(go, 100)</script>")
    assert "Math.random" in preview.determinism_problems(app)[0]


def test_upload_is_a_dry_run_until_confirmed_and_resolves_shares(tmp_path, monkeypatch):
    app = _app(tmp_path, preview={"locales": ["en-US", "en-GB"]})
    (f,) = _ready(app)
    monkeypatch.setattr(preview, "probe", lambda p: GOOD)
    assert preview.upload(app, confirm="com.x.hue")["mode"] == "refused"     # not self-reviewed yet
    preview.log_review(app, str(f.relative_to(app)), SCORES, [])
    dry = preview.upload(app)
    assert dry["mode"] == "dry-run" and set(dry["plan"]) == {"en-US", "en-GB"}
    routes = {"/v1/apps": [{"id": "a1"}],
              "/v1/apps/a1/appStoreVersions": [{"id": "v1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION",
                                                                          "versionString": "1.0"}}],
              "/v1/appStoreVersions/v1/appStoreVersionLocalizations": [
                  {"id": "l-us", "attributes": {"locale": "en-US"}}, {"id": "l-gb", "attributes": {"locale": "en-GB"}}],
              "/v1/appStoreVersionLocalizations/l-us/appPreviewSets": [{"id": "s-us", "attributes": {"previewType": "IPHONE_67"}}],
              "/v1/appPreviewSets/s-us/appPreviews": [{"id": "p1", "attributes": {"fileName": f.name,
                                                                                   "sourceFileChecksum": preview._md5(f)}}]}
    c = FakeASC(routes)
    r = preview.upload(app, confirm="com.x.hue", client=c)
    assert r["ok"] is True, r
    assert r["done"] == {"en-US": ["hue-preview.mp4: unchanged"], "en-GB": ["hue-preview.mp4: uploaded"]}
    assert ("upload_preview", "l-gb/IPHONE_67/hue-preview.mp4") in c.calls   # asc creates en-GB's set
    assert not any(m == "POST" for m, _ in c.calls)


def test_gate_requires_check_review_and_the_upload_marker(tmp_path, monkeypatch):
    app = _app(tmp_path, preview={"locales": ["en-US"]})
    monkeypatch.setattr(preview, "probe", lambda p: GOOD)
    assert "BRIEF" in gates._gate_app_preview(app)["reason"]
    (f,) = _ready(app)
    assert "self-review" in gates._gate_app_preview(app)["reason"]
    preview.log_review(app, str(f.relative_to(app)), SCORES, [])
    assert "marker" in gates._gate_app_preview(app)["reason"]
    mk = app / ".appfactory" / "verify" / "app_preview.json"
    mk.parent.mkdir(parents=True)
    mk.write_text(json.dumps({"uploaded": True}))
    assert gates._gate_app_preview(app)["ok"] is True


@pytest.mark.parametrize("cut", [None, 3.5])
def test_review_sheet_commands(tmp_path, cut):
    cmds = preview.sheet_cmds(tmp_path / "hue-preview.mp4", tmp_path, cut)
    assert "fps=2,scale=270:-1,tile=6x5" in cmds["contact"] and "fps=1,scale=360:-1,tile=5x3" in cmds["phone"]
    assert ("transition" in cmds) == (cut is not None)
    if cut:
        assert cmds["transition"][cmds["transition"].index("-ss") + 1] == "2.50"
