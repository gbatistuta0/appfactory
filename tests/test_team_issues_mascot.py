"""team_brief, github issue tools (subprocess mocked — no live GitHub) and the mascot pipeline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from appfactory import github, issues, mascot, spec, team
from appfactory.design import screens

FAKE_TOKEN = "gho_fake_token_for_tests"


class FakeRun:
    """Stands in for subprocess.run; records every call (argv + env)."""

    def __init__(self):
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, cmd, capture_output=True, text=True, timeout=None, cwd=None, env=None):
        self.calls.append((cmd, env))
        out = FAKE_TOKEN if cmd[:3] == ["gh", "auth", "token"] else "https://github.com/octocat/hue/issues/7"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


@pytest.fixture(autouse=True)
def gh_account(monkeypatch):
    monkeypatch.setattr("appfactory.issues.gh_user", lambda: "octocat")


@pytest.fixture
def fake_run(monkeypatch):
    fr = FakeRun()
    monkeypatch.setattr("appfactory.proc.subprocess.run", fr)
    return fr


# ---------------------------------------------------------------- issues

def test_bootstrap_dry_run_returns_commands_without_running(fake_run):
    r = issues.bootstrap_labels("hue")
    assert r["ok"] and r["dry_run"] and fake_run.calls == []
    assert len(r["commands"]) == 8
    assert all(c.startswith("GH_TOKEN=$(gh auth token --user octocat) gh label create ") for c in r["commands"])
    assert any("ios --repo octocat/hue --color 1D76DB" in c for c in r["commands"])
    assert set(r["labels"]) == {"ios", "backend", "store", "lead", "founder", "next", "later", "other-project"}


def test_bootstrap_live_injects_token_per_command(fake_run):
    r = issues.bootstrap_labels("octocat/hue", dry_run=False)
    assert r["ok"]
    assert fake_run.calls[0][0] == ["gh", "auth", "token", "--user", "octocat"]
    label_calls = fake_run.calls[1:]
    assert len(label_calls) == 8 and all(env and env["GH_TOKEN"] == FAKE_TOKEN for _, env in label_calls)
    assert not any("switch" in " ".join(cmd) for cmd, _ in fake_run.calls)
    assert FAKE_TOKEN not in json.dumps(r)  # the token never leaves the env


def test_issue_create_dry_run_and_live(fake_run):
    r = issues.create_issue("hue", "Add kg/lb toggle to the desired weight picker", ["ios", "next"],
                            "What: toggle.\nWhy: founder asked.\nDone when: UI test passes.")
    assert r["ok"] and r["dry_run"] and fake_run.calls == []
    cmd = r["commands"][0]
    assert "gh issue create --repo octocat/hue --title 'Add kg/lb toggle" in cmd and "--label ios --label next" in cmd
    live = issues.create_issue("hue", "Add kg/lb toggle", ["ios"], "body", dry_run=False)
    assert live["ok"] and live["url"].endswith("/issues/7")
    assert fake_run.calls[-1][1]["GH_TOKEN"] == FAKE_TOKEN


@pytest.mark.parametrize("title, labels, body, needle", [
    ("Added a toggle", ["ios"], "b", "imperative"),
    ("Add a toggle.", ["ios"], "b", "period"),
    ("Add a toggle", ["next"], "b", "role label"),
    ("Add a toggle", ["ios", "bug"], "b", "unknown labels"),
    ("Add a toggle", ["ios", "next", "later"], "b", "next OR later"),
    ("Add a toggle", ["ios"], "  ", "body"),
])
def test_issue_rules(fake_run, title, labels, body, needle):
    r = issues.create_issue("hue", title, labels, body)
    assert r["ok"] is False and needle in r["error"] and fake_run.calls == []


def test_missing_token_is_reported(monkeypatch):
    def no_token(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no oauth token")
    monkeypatch.setattr("appfactory.proc.subprocess.run", no_token)
    r = issues.create_issue("hue", "Add a toggle", ["ios"], "b", dry_run=False)
    assert r["ok"] is False and "gh auth switch" in r["error"]


def test_create_repo_private_as_octocat(tmp_path: Path, fake_run):
    (tmp_path / ".git").mkdir()
    dry = github.create_private_repo(tmp_path, "hue", dry_run=True)
    assert dry["ok"] and "gh repo create octocat/hue --private" in dry["commands"][0] and fake_run.calls == []
    live = github.create_private_repo(tmp_path, "hue", dry_run=False)
    assert live["ok"] and live["repo"] == "octocat/hue"
    cmd, env = fake_run.calls[-1]
    assert "--private" in cmd and env["GH_TOKEN"] == FAKE_TOKEN


# ---------------------------------------------------------------- team

def test_team_brief_renders_everything(tmp_path: Path):
    sp = spec.build("Hue", "com.octocat.hue", design={"mascot": {"name": "Kami", "species": "chameleon",
                                                                  "states": ["idle", "wave"]}})
    spec.save(tmp_path, sp)
    screens.save(tmp_path, screens.skeleton(sp))
    r = team.brief(tmp_path, sessions={"ios": "hue-0d"})
    assert r["ok"] and len(r["written"]) == 7
    text = {rel: (tmp_path / rel).read_text() for rel in r["written"]}
    assert all("{{" not in t for t in text.values())
    t = text["docs/TEAM.md"]
    assert "`hue-0d`" in t and "com.octocat.hue.yearly" in t and "octocat/hue" in t and "Kami" in t
    assert "Claude in Chrome" in t and "Only the lead pushes" in t and "gh auth switch" in t
    plan = text["docs/onboarding-plan.md"]
    assert plan.count("\n| ") > 26 and "hue_onboarding_answer" in plan and "kg/lb" in plan
    assert "## 2. Method and data" in text["store/aso-research.md"]
    again = team.brief(tmp_path)
    assert again["written"] == [] and len(again["kept"]) == 7


def test_team_render_rejects_unknown_variables():
    with pytest.raises(KeyError):
        team.render_text("{{nope}}", {})


# ---------------------------------------------------------------- mascot

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_mascot_assets_import_with_blink_and_fallback(tmp_path: Path):
    m = tmp_path / "design" / "mascot"
    m.mkdir(parents=True)
    for name in ("idle.png", "idle-blink.png", "think.png", "wave.png"):
        (m / name).write_bytes(PNG)
    r = mascot.assets(tmp_path)
    assert r["ok"], r
    root = tmp_path / mascot.ASSETS_DIR
    assert json.loads((root / "Contents.json").read_text())["properties"]["provides-namespace"] is True
    assert "Mascot/idle-blink" in r["imported"] and "Mascot/wave" in r["imported"]
    assert r["borrowed"]["sleep"] == "think" and r["borrowed"]["love"] == "idle"
    c = json.loads((root / "sleep.imageset" / "Contents.json").read_text())
    assert c["images"][0]["filename"] == "sleep.png" and (root / "sleep.imageset" / "sleep.png").exists()


def test_mascot_assets_reports_missing(tmp_path: Path):
    (tmp_path / "design" / "mascot").mkdir(parents=True)
    r = mascot.assets(tmp_path)
    assert r["ok"] is False and "idle" in r["missing"]


def test_mascot_blink_without_extra_is_a_clear_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mascot, "_deps", lambda: None)
    r = mascot.blink(tmp_path)
    assert r["ok"] is False and "uv sync --extra mascot" in r["error"]


def test_mascot_blink_closes_the_eyes(tmp_path: Path):
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([60, 40, 340, 380], fill=(240, 140, 60, 255))           # body
    for cx in (150, 250):
        d.ellipse([cx - 32, 120, cx + 32, 184], fill=(250, 250, 250, 255))  # eye white
        d.ellipse([cx - 18, 134, cx + 18, 170], fill=(40, 25, 15, 255))     # iris
    p = tmp_path / "idle.png"
    im.save(p)
    r = mascot.blink_one(p)
    assert r["ok"], r
    out = np.array(Image.open(tmp_path / "idle-blink.png").convert("RGBA")).astype(int)
    iris = out[140:165, 138:162, :3]
    assert (iris.sum(axis=2) < 150).mean() < 0.3  # the iris is gone
    assert out.shape == np.array(im).shape
