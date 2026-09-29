"""preview_* — the App Store App Preview video.

Claude authors the preview itself (the `hyperframes` skill workflow, a BRIEF.md with
`destination: app-store-preview`) from REAL simulator recordings of the app: Apple's rule is that
the content is real app footage, motion graphics only frame and highlight it. The old Remotion
template path is gone.

Layout inside the app:
  marketing/preview/BRIEF.md                 the HyperFrames brief (preview_brief writes the skeleton)
  marketing/preview/recordings/<locale>/     raw `xcrun simctl io <udid> recordVideo` captures
  fastlane/app_previews/<locale>/*.mp4|.mov  the finished previews, up to 3 per locale, name order

Apple's iPhone 6.9" preview spec: 886 x 1920 portrait, at most
30 fps, H.264, 15–30 s, at most 500 MB, stereo AAC or no audio track. One preview per store locale,
or a documented share (spec.preview.shared: en-GB → en-US uploads the en-US file into the en-GB set).
Uploads go through the asc CLI (`asc video-previews upload` into the IPHONE_67 set: reserve → upload →
commit with the MD5, then `asc video-previews set-poster-frame`); a dry run is the default, a write
needs confirm=<bundle id> (the preview_upload tool passes it only after human approval).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import spec as spec_mod

PREVIEW_TYPE = "IPHONE_67"   # the 6.9" set (ASC names it after the 6.7" size)
MIME = {".mp4": "video/mp4", ".mov": "video/quicktime"}
MAX_PER_SET = 3
MAX_BYTES = 500 * 1024 * 1024
PREVIEWS_REL = Path("fastlane") / "app_previews"
PREVIEW_DIR_REL = Path("marketing") / "preview"
RECORDINGS_REL = PREVIEW_DIR_REL / "recordings"
BRIEF_REL = PREVIEW_DIR_REL / "BRIEF.md"
EDITABLE = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY",
            "READY_FOR_REVIEW"}


# ---------------------------------------------------------------------------------------------
# What must exist
# ---------------------------------------------------------------------------------------------

def rules(spec: dict[str, Any]) -> dict[str, Any]:
    """spec.preview over the defaults; `locales` None = every store locale."""
    p = spec_mod.preview(spec)
    locs = p["locales"] or list(spec["locales"]["store"])
    return {**p, "locales": locs}


def source_locale(r: dict[str, Any], loc: str) -> str:
    """The locale whose video `loc` shows (itself unless spec.preview.shared maps it)."""
    return (r.get("shared") or {}).get(loc, loc)


def local_previews(app: Path) -> dict[str, list[Path]]:
    root = app / PREVIEWS_REL
    out: dict[str, list[Path]] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in MIME)
        if files:
            out[d.name] = files
    return out


def probe(path: Path) -> dict[str, Any] | None:
    """ffprobe facts of a video, or None without ffprobe."""
    if not shutil.which("ffprobe"):
        return None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,channels:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[-200:]}
    info = json.loads(r.stdout or "{}")
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    num, _, den = str(video.get("r_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {"width": video.get("width"), "height": video.get("height"), "codec": video.get("codec_name"),
            "fps": round(fps, 2), "duration": float((info.get("format") or {}).get("duration") or 0),
            "audio": [(a.get("codec_name"), a.get("channels")) for a in audio]}


def video_problems(path: Path, facts: dict[str, Any] | None, r: dict[str, Any]) -> list[str]:
    name = f"{path.parent.name}/{path.name}"
    errs = []
    if path.stat().st_size > MAX_BYTES:
        errs.append(f"{name}: over 500 MB")
    if facts is None:
        return errs + [f"{name}: not probed — install ffmpeg (ffprobe) to check the ASC spec"]
    if facts.get("error"):
        return errs + [f"{name}: unreadable ({facts['error']})"]
    w, h = r["size"]
    if (facts.get("width"), facts.get("height")) != (w, h):
        errs.append(f"{name}: {facts.get('width')}x{facts.get('height')}, ASC wants {w}x{h} portrait")
    if not r["min_s"] <= facts.get("duration", 0) <= r["max_s"]:
        errs.append(f"{name}: {facts.get('duration', 0):.1f} s, ASC wants {r['min_s']}–{r['max_s']} s")
    if facts.get("fps", 0) > r["fps"] + 0.01:
        errs.append(f"{name}: {facts.get('fps')} fps, at most {r['fps']}")
    if facts.get("codec") != "h264":
        errs.append(f"{name}: video codec {facts.get('codec')}, ASC wants H.264")
    for codec, channels in facts.get("audio", []):
        if codec != "aac" or channels != 2:
            errs.append(f"{name}: audio {codec}/{channels} ch — stereo AAC or no audio track")
    return errs


def check(app_dir: str | Path, probe_fn: Callable[[Path], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Offline readiness: BRIEF, real recordings, one preview per locale (or a documented share), and
    every file inside Apple's spec. {ok, problems, plan: {locale: [files]}}."""
    probe_fn = probe_fn or probe
    app = Path(app_dir).expanduser()
    sp = spec_mod.load(app)
    r = rules(sp)
    problems: list[str] = []
    brief = app / BRIEF_REL
    if not brief.exists():
        problems.append(f"{BRIEF_REL} missing — preview_brief, then author it with the hyperframes skill")
    elif "destination: app-store-preview" not in brief.read_text(encoding="utf-8"):
        problems.append(f"{BRIEF_REL} must declare `destination: app-store-preview`")
    have = local_previews(app)
    plan: dict[str, list[str]] = {}
    store = set(sp["locales"]["store"])
    for loc in r["locales"]:
        src = source_locale(r, loc)
        if loc not in store:
            problems.append(f"{loc}: not a store locale (spec.locales.store)")
            continue
        files = have.get(src, [])
        if not files:
            problems.append(f"{loc}: no preview in {PREVIEWS_REL}/{src}/"
                            + ("" if src == loc else f" (shared from {src})"))
            continue
        if len(files) > MAX_PER_SET:
            problems.append(f"{src}: {len(files)} previews, ASC takes {MAX_PER_SET}")
        plan[loc] = [str(f.relative_to(app)) for f in files[:MAX_PER_SET]]
    for src in sorted({source_locale(r, loc) for loc in plan}):
        rec = app / RECORDINGS_REL / src
        if not rec.exists() or not any(p.suffix.lower() in MIME for p in rec.iterdir()):
            problems.append(f"{src}: no real app footage in {RECORDINGS_REL}/{src}/ "
                            "(xcrun simctl io <udid> recordVideo) — a preview shows the real app only")
        for f in have.get(src, [])[:MAX_PER_SET]:
            problems += video_problems(f, probe_fn(f), r)
    extra = sorted(set(have) - {source_locale(r, loc) for loc in r["locales"]})
    if extra:
        problems.append(f"previews for locales outside spec.preview: {extra}")
    return {"ok": not problems, "problems": problems, "plan": plan}


# ---------------------------------------------------------------------------------------------
# Brief (Claude authors the video with the hyperframes skill)
# ---------------------------------------------------------------------------------------------

def brief(app_dir: str | Path, message: str = "", overwrite: bool = False) -> dict[str, Any]:
    """Write marketing/preview/BRIEF.md: the HyperFrames brief for an App Store preview, from the spec."""
    app = Path(app_dir).expanduser()
    sp = spec_mod.load(app)
    r = rules(sp)
    out = app / BRIEF_REL
    if out.exists() and not overwrite:
        return {"ok": True, "path": str(out), "written": False, "note": "exists; pass overwrite=true to replace"}
    name = sp.get("display_name") or sp["name"]
    w, h = r["size"]
    sources = sorted({source_locale(r, loc) for loc in r["locales"]})
    shared = ", ".join(f"{k} uses {v}" for k, v in sorted((r.get("shared") or {}).items())) or "none"
    text = f"""---
workflow: general-video
flow: companion
storyboard: no
message: "{message or f'What {name} does, shown in the real app.'}"
destination: app-store-preview
aspect: {w}x{h}
language: {sources[0] if sources else 'en-US'}
audience: "App Store visitors deciding whether to download {name}"
length: {max(r['min_s'], min(r['max_s'], 24))}s
angle: product-demo
---

## Intent

App Store Connect App Preview for {name}. Apple's rule: the content is REAL app footage; motion
graphics may frame and highlight it (a subtly animated phone frame on the app's own background,
kinetic captions in a top band that never covers the UI, punch-ins on the moments that matter,
crossfades or whips between segments), never replace it. Open on the single most striking,
believable moment: the first frame is the autoplay poster (poster time code {r['poster']}).

## Assets

Fresh simulator recordings of this app only, per language, in {RECORDINGS_REL}/<locale>/:

    Scripts/sim_store_prep.sh <udid> <lang> <region>     # language, region, 9:41 status bar, clean install
    xcrun simctl io <udid> recordVideo --codec=h264 --force {RECORDINGS_REL}/<locale>/segN_<moment>.mp4

Seed the screens with the app's DEBUG launch flags (-uiTest, seeded results), never a real AI spend.
No hands, no people, no device in hand, no screens from other apps, no prices beyond what the app
shows. The end card (icon + name) is the only non-footage beat.

## Spec (checked by preview_check)

- {w}x{h} portrait, at most {r['fps']} fps, H.264, {r['min_s']}–{r['max_s']} s, at most 500 MB
- stereo AAC music or no audio track (it autoplays muted: the story works without sound)
- one preview per locale: {', '.join(sources)}; shared: {shared}
- captions per language, at most ~28 characters, from the app's own terms

## Output

Render to fastlane/app_previews/<locale>/{sp['name'].lower()}-preview.mp4, then preview_check and,
with the founder's go, preview_upload(dry_run=False) + `appfactory approve <id>`.
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    for src in sources:
        (app / RECORDINGS_REL / src).mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(out), "written": True, "locales": sources,
            "record": f"xcrun simctl io <udid> recordVideo --codec=h264 --force {RECORDINGS_REL}/<locale>/segN.mp4"}


# ---------------------------------------------------------------------------------------------
# Self-review before the upload (score every final file, fix, re-render, until all >= 8)
# ---------------------------------------------------------------------------------------------

REVIEW_REL = PREVIEW_DIR_REL / "review"
REVIEW_LOG_REL = REVIEW_REL / "log.json"
REVIEW_CRITERIA = {
    "hook": "the first 2 s / poster frame make someone stop scrolling",
    "readability": "every overlay reads at 360 px wide (the phone-size sheet)",
    "motion": "no dead beats, no text overlapping during swaps",
    "variety": "something new every 2–4 s",
    "brand": "the app's colors, type and wording; the real app on screen",
    "music": "cuts land on the beat (or the silent cut still reads)",
}
REVIEW_MIN = 8
# A composition must render the same every time: no randomness or wall-clock timers.
_NONDETERMINISTIC = re.compile(r"Math\.random|setTimeout|setInterval|Date\.now|performance\.now|new Date\(")


def final_files(app: Path, sp: dict[str, Any] | None = None) -> list[Path]:
    """The preview files that will be uploaded (one set per source locale)."""
    sp = sp or spec_mod.load(app)
    r = rules(sp)
    have = local_previews(app)
    out: list[Path] = []
    for src in sorted({source_locale(r, loc) for loc in r["locales"]}):
        out += have.get(src, [])[:MAX_PER_SET]
    return out


def fastest_transition(video: Path) -> float | None:
    """Time of the strongest scene change (ffmpeg scene score), for the transition strip."""
    if not shutil.which("ffmpeg"):
        return None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf",
                        "select='gt(scene,0.15)',metadata=print:file=-", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    best: tuple[float, float] | None = None
    t = None
    for line in r.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None and (best is None or float(m.group(1)) > best[1]):
            best = (t, float(m.group(1)))
    return best[0] if best else None


def sheet_cmds(video: Path, out_dir: Path, cut_at: float | None) -> dict[str, list[str]]:
    """ffmpeg commands: a contact sheet (2 fps, 270 px, 6x5), a phone-size sheet (1 fps, 360 px, 5x3)
    and a 12-frame strip around the fastest transition."""
    stem = video.stem
    cmds = {
        "contact": ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", "fps=2,scale=270:-1,tile=6x5",
                    "-frames:v", "1", str(out_dir / f"{stem}-contact.png")],
        "phone": ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", "fps=1,scale=360:-1,tile=5x3",
                  "-frames:v", "1", str(out_dir / f"{stem}-phone.png")],
    }
    if cut_at is not None:
        cmds["transition"] = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, cut_at - 1):.2f}", "-t", "2",
                              "-i", str(video), "-vf", "fps=6,scale=270:-1,tile=12x1", "-frames:v", "1",
                              str(out_dir / f"{stem}-transition.png")]
    return cmds


def review_sheets(app_dir: str | Path) -> dict[str, Any]:
    """Render the review sheets of every final preview into marketing/preview/review/<locale>/. Open
    them, score the file against REVIEW_CRITERIA with preview_review_log, fix and re-render until
    every score is >= 8."""
    app = Path(app_dir).expanduser()
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "ffmpeg not installed (brew install ffmpeg)"}
    made, errors = {}, []
    for f in final_files(app):
        out = app / REVIEW_REL / f.parent.name
        out.mkdir(parents=True, exist_ok=True)
        for kind, cmd in sheet_cmds(f, out, fastest_transition(f)).items():
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                made.setdefault(str(f.relative_to(app)), []).append(str(Path(cmd[-1]).relative_to(app)))
            else:
                errors.append({"file": f.name, "sheet": kind, "error": r.stderr.strip()[-200:]})
    return {"ok": not errors, "sheets": made, "errors": errors, "criteria": REVIEW_CRITERIA, "min_score": REVIEW_MIN}


def _load_log(app: Path) -> list[dict[str, Any]]:
    p = app / REVIEW_LOG_REL
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def log_review(app_dir: str | Path, file: str, scores: dict[str, int], problems: list[dict[str, str]]) -> dict[str, Any]:
    """Append one review round for `file` (relative to the app): a 1–10 score per criterion and, while
    any score is under 8, the 3 worst problems with timestamps ({"t": "00:03.2", "issue": "…"})."""
    app = Path(app_dir).expanduser()
    f = app / file
    if not f.exists():
        return {"ok": False, "error": f"{file} not found"}
    bad = [k for k in REVIEW_CRITERIA if not isinstance(scores.get(k), int) or not 1 <= scores[k] <= 10]
    if bad or set(scores) - set(REVIEW_CRITERIA):
        return {"ok": False, "error": f"score every criterion 1–10: {sorted(REVIEW_CRITERIA)}"}
    passing = all(scores[k] >= REVIEW_MIN for k in REVIEW_CRITERIA)
    if not passing and (len(problems) != 3 or not all(p.get("t") and p.get("issue") for p in problems)):
        return {"ok": False, "error": "a failing round logs exactly the 3 worst problems, each with t and issue"}
    log = _load_log(app)
    rnd = 1 + sum(1 for e in log if e.get("file") == file)
    log.append({"file": file, "md5": _md5(f), "round": rnd, "scores": scores, "problems": problems, "pass": passing})
    (app / REVIEW_LOG_REL).parent.mkdir(parents=True, exist_ok=True)
    (app / REVIEW_LOG_REL).write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "round": rnd, "pass": passing,
            "next": "upload after preview_check" if passing else "fix the 3 problems, re-render, run preview_review_sheets again"}


def review_status(app_dir: str | Path) -> dict[str, Any]:
    """Every final file's LAST review round matches the file on disk (MD5) and scores >= 8 everywhere;
    the composition renders deterministically."""
    app = Path(app_dir).expanduser()
    log = _load_log(app)
    problems = []
    for f in final_files(app):
        rel = str(f.relative_to(app))
        rounds = [e for e in log if e.get("file") == rel]
        if not rounds:
            problems.append(f"{rel}: no self-review in {REVIEW_LOG_REL} (preview_review_sheets → preview_review_log)")
        elif rounds[-1].get("md5") != _md5(f):
            problems.append(f"{rel}: changed since its last review — review the final render")
        elif not rounds[-1].get("pass") or min(rounds[-1]["scores"].values()) < REVIEW_MIN:
            problems.append(f"{rel}: last review scores {rounds[-1]['scores']} — every criterion needs {REVIEW_MIN}+")
    problems += determinism_problems(app)
    return {"ok": not problems, "problems": problems}


def determinism_problems(app: Path) -> list[str]:
    """Composition sources (marketing/preview, not the recordings, vendored libraries or renders) must not
    use randomness or wall-clock timers: a re-render must reproduce the reviewed file."""
    root = app / PREVIEW_DIR_REL
    out = []
    for f in sorted(root.rglob("*")) if root.exists() else []:
        rel = f.relative_to(root)
        if not f.is_file() or f.suffix not in (".html", ".js", ".mjs", ".ts", ".css") or f.name.endswith(".min.js"):
            continue
        if {"node_modules", "recordings", "review", "assets", "renders", "dist"} & set(rel.parts):
            continue
        hits = sorted(set(_NONDETERMINISTIC.findall(f.read_text(encoding="utf-8", errors="ignore"))))
        if hits:
            out.append(f"{PREVIEW_DIR_REL / rel}: {', '.join(hits)} — use the paused timeline and seeded values only")
    return out


# ---------------------------------------------------------------------------------------------
# Upload (ASC API)
# ---------------------------------------------------------------------------------------------

def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def upload_one_preview(c, localization_id: str, p: Path, poster: str | None = None) -> dict[str, Any]:
    """Single video into the localization's IPHONE_67 set (asc creates the set if needed), then the
    poster time code."""
    res = c.upload_preview(localization_id, p, PREVIEW_TYPE)
    if not res.get("ok"):
        return {"ok": False, "step": "upload", "error": res.get("error"), **({"id": res["id"]} if res.get("id") else {})}
    pid = res.get("id")
    if poster and pid:
        pr = c.set_preview_poster(pid, poster)
        if not pr.get("ok"):
            return {"ok": False, "step": "poster", "error": pr.get("error"), "id": pid}
    return {"ok": True, "id": pid}


def upload(app_dir: str | Path, confirm: str = "", replace: bool = False, locales: list[str] | None = None,
           client: Any = None, probe_fn: Callable[[Path], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Dry run unless confirm == bundle id. Per locale (shares resolved): the IPHONE_67 set of the
    editable version; a file already there with the same name and MD5 is kept; a different one is
    replaced only with replace=true."""
    app = Path(app_dir).expanduser()
    sp = spec_mod.load(app)
    chk = check(app, probe_fn)
    plan = {loc: files for loc, files in chk["plan"].items() if not locales or loc in locales}
    review = review_status(app)
    if not chk["ok"] or not review["ok"]:
        return {"ok": False, "mode": "refused", "problems": chk["problems"] + review["problems"], "plan": plan}
    if confirm != sp["bundle_id"]:
        return {"ok": True, "mode": "dry-run", "plan": plan,
                "note": "nothing sent; upload with dry_run=False after the founder's go (appfactory approve)"}
    from .asc import ASCClient
    c = client or ASCClient()
    r = rules(sp)
    apps = c.request("GET", "/v1/apps", params={"filter[bundleId]": sp["bundle_id"]}).get("data", {}).get("data", [])
    if not apps:
        return {"ok": False, "error": f"app not found: {sp['bundle_id']}"}
    versions = c.request("GET", f"/v1/apps/{apps[0]['id']}/appStoreVersions",
                         params={"filter[platform]": "IOS", "limit": "10"}).get("data", {}).get("data", [])
    state = lambda v: v["attributes"].get("appVersionState") or v["attributes"].get("appStoreState")  # noqa: E731
    version = next((v for v in versions if state(v) in EDITABLE), None)
    if version is None:
        return {"ok": False, "error": "no editable iOS version in App Store Connect"}
    locs = {x["attributes"]["locale"]: x["id"] for x in c.request(
        "GET", f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations",
        params={"limit": "50"}).get("data", {}).get("data", [])}
    done: dict[str, list[str]] = {}
    errors: list[dict[str, Any]] = []
    for loc, rels in plan.items():
        lid = locs.get(loc)
        if not lid:
            errors.append({"locale": loc, "error": "no such localization on the editable version"})
            continue
        sets = c.request("GET", f"/v1/appStoreVersionLocalizations/{lid}/appPreviewSets").get("data", {}).get("data", [])
        pset = next((s["id"] for s in sets if s["attributes"].get("previewType") == PREVIEW_TYPE), None)
        # no set yet → `asc video-previews upload` creates it
        existing = c.request("GET", f"/v1/appPreviewSets/{pset}/appPreviews").get("data", {}).get("data", []) if pset else []
        by_name = {e["attributes"].get("fileName"): e for e in existing}
        for rel in rels:
            f = app / rel
            cur = by_name.get(f.name)
            if cur and (cur["attributes"].get("sourceFileChecksum") == _md5(f)):
                done.setdefault(loc, []).append(f"{f.name}: unchanged")
                continue
            if cur and not replace:
                errors.append({"locale": loc, "file": f.name, "error": "a different file with this name is in the set "
                               "(replace=true swaps it)"})
                continue
            if cur:
                c.delete_preview(cur["id"])
            res = upload_one_preview(c, lid, f, r["poster"])
            if res.get("ok"):
                done.setdefault(loc, []).append(f"{f.name}: uploaded")
            else:
                errors.append({"locale": loc, "file": f.name, **res})
    return {"ok": not errors, "mode": "upload", "version": version["attributes"].get("versionString"),
            "done": done, "errors": errors}
