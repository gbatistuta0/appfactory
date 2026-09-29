"""screenshot_* — App Store screenshot generation (build.mjs compositor pattern).

Flow: capture (simctl, raw) → apply the Claude Design store layout (design/project/store_layout.json,
the ST0N boards) to the compositor config → brand (node compositor renders that layout per locale) →
sync (branded → fastlane/screenshots/<locale>/). The layout itself is designed in Claude Design.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from . import config as cfg
from .proc import run

from . import config as _cfg

# App Store locales (configured set, ASC codes). Screenshots are produced in ALL languages, equal count.
DEFAULT_LOCALES = _cfg.APP_STORE_LOCALES
# ASC code (ta-IN) → iOS bare language code (ta) — for the AppleLanguages launch-arg + captions.
_ASC_TO_BARE = {v: k for k, v in _cfg.IN_APP_TO_ASC.items()}

# Capturable screens (ScreenshotMode launch args). The brief's screenshot concept picks which ones,
# in which order (design/project/store_layout.json "shots" = "<NN>_<key>").
CAPTURE_ARGS = {
    "onboarding": ["-onboarding_completed", "NO"],
    "create": ["-onboarding_completed", "YES"],
    "result": ["-onboarding_completed", "YES", "-uiResult"],
    "gallery": ["-onboarding_completed", "YES", "-uiTab", "1", "-uiSeedGallery"],
    "paywall": ["-onboarding_completed", "YES", "-uiPaywall"],
    "settings": ["-onboarding_completed", "YES", "-uiTab", "2"],
}
DEFAULT_SCREENS = [(f"{i:02d}_{k}", a) for i, (k, a) in enumerate(CAPTURE_ARGS.items(), 1)]


def screens_for(shots: list[str]) -> list[tuple[str, list[str]]]:
    """store_layout shots ("03_paywall") → (capture name, launch args)."""
    return [(name, CAPTURE_ARGS[name.split("_", 1)[1]]) for name in shots if name.split("_", 1)[-1] in CAPTURE_ARGS]

# Caption headline/subhead FALLBACK keys (localized values pulled from the String Catalog).
# GOTCHA: these must be app-AGNOSTIC (previously one app's "headshot" text → it got
# wrongly copied to every app). The real captions are APP-SPECIFIC: each app provides a
# PRE-TRANSLATED marketing/screenshots/copy/<locale>.json → captions_from_catalog won't overwrite them (guard below).
CAPTION_KEYS = [
    ("Get Started", "Create something beautiful in seconds."),
    ("Create", "Bring your idea to life."),
    ("Your portrait is ready", "Save and share instantly."),
    ("Gallery", "All your creations in one place."),
    ("Unlock Premium", "Everything, unlimited."),
    ("Settings", "Your data stays private."),
]


def generate_sample(app_dir: str | Path, prompt: str) -> dict[str, Any]:
    """Sample AI OUTPUT (sample_headshot.jpg) that fills Result/Gallery — app content from the app's own AI
    model, not a design asset. An existing image is kept; fal is called only when it is missing."""
    out = Path(app_dir).expanduser() / "Resources" / "sample_headshot.jpg"
    if out.exists() and out.stat().st_size > 10_000:
        return {"ok": True, "path": str(out), "skipped": "existing image kept — did not call fal"}
    fal = cfg.load_config().get("fal_key")
    if not fal:
        return {"ok": False, "error": "fal_key not in config"}
    try:
        r = httpx.post("https://fal.run/fal-ai/flux/schnell",
                       headers={"Authorization": f"Key {fal}", "Content-Type": "application/json"},
                       json={"prompt": prompt, "image_size": "portrait_4_3", "num_images": 1},
                       timeout=180)
        url = r.json().get("images", [{}])[0].get("url")
        if not url:
            return {"ok": False, "error": "no image in fal response", "raw": r.text[:300]}
        img = httpx.get(url, timeout=120).content
        out = Path(app_dir).expanduser() / "Resources" / "sample_headshot.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(img)
        return {"ok": True, "path": str(out), "bytes": len(img)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _onboarding_prompts(concept: str, count: int = 11, prompts: list[str] | None = None) -> list[str]:
    """Onboarding hero prompts — APP-AGNOSTIC (no fixed headshot/persona/teal).
    If app-specific `prompts` are given, cycle through them by count; otherwise derive from concept.
    Each prompt is distinct (by step number) → the same image won't repeat."""
    concept = (concept or "modern mobile app").strip()
    if prompts:
        return [prompts[i % len(prompts)] for i in range(count)]
    angles = [
        "premium hero illustration of the core benefit",
        "aspirational lifestyle scene of a person using the app on a phone",
        "minimal abstract illustration with elegant glowing gradient accents",
        "close-up of the app's key visual elements in premium product style",
        "a transformation scene conveying the value",
    ]
    return [
        f"{angles[i % len(angles)]} for a {concept} app — onboarding step {i + 1}, "
        "modern, clean, vibrant, no text, no watermark, full frame"
        for i in range(count)
    ]


def generate_onboarding_heroes(app_dir: str | Path, concept: str, count: int = 11,
                               allow_external_generator: bool = False) -> dict[str, Any]:
    """LEGACY onboarding hero images (onb_step{i}.jpg). Onboarding visuals are designed in Claude Design
    (design/screens.json boards: mascot, motion, illustrations) — this fal generator is an explicit opt-in only.
    Existing images are never overwritten."""
    res = Path(app_dir).expanduser() / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    existing = [i for i in range(count) if (res / f"onb_step{i}.jpg").exists()
                and (res / f"onb_step{i}.jpg").stat().st_size > 10_000]
    if len(existing) >= count:
        return {"ok": True, "skipped": f"{len(existing)} existing heroes kept — did not call fal"}
    if not allow_external_generator:
        return {"ok": False, "error": "onboarding visuals come from the Claude Design boards; pass "
                "allow_external_generator=True only for a legacy hero-image onboarding (spend → approval)"}
    fal = cfg.load_config().get("fal_key")
    if not fal:
        return {"ok": False, "error": "fal_key missing"}
    step_prompts = _onboarding_prompts(concept, count)
    ok = 0
    for i, pr in enumerate(step_prompts):
        if i in existing:  # don't overwrite an existing image
            ok += 1
            continue
        try:
            r = httpx.post("https://fal.run/fal-ai/flux/schnell",
                           headers={"Authorization": f"Key {fal}", "Content-Type": "application/json"},
                           json={"prompt": pr, "image_size": "portrait_4_3"}, timeout=120)
            url = (r.json().get("images") or [{}])[0].get("url")
            if url:
                (res / f"onb_step{i}.jpg").write_bytes(httpx.get(url, timeout=120).content)
                ok += 1
        except Exception:  # noqa: BLE001
            pass
    return {"ok": ok == count, "generated": ok, "count": count}


def _find_catalog(app_dir: Path) -> Path | None:
    for p in app_dir.rglob("Localizable.xcstrings"):
        if "build" not in p.parts and ".git" not in p.parts:
            return p
    return None


def captions_from_catalog(app_dir: str | Path, locales: list[str] | None = None) -> dict[str, Any]:
    """Produce copy/<locale>.json files from the LOCALIZED values in the String Catalog (NO new translation)."""
    app = Path(app_dir).expanduser()
    cat_path = _find_catalog(app)
    if not cat_path:
        return {"ok": False, "error": "Localizable.xcstrings not found"}
    cat = json.loads(cat_path.read_text(encoding="utf-8")).get("strings", {})
    locales = locales or DEFAULT_LOCALES
    copy_dir = app / "marketing" / "screenshots" / "copy"
    copy_dir.mkdir(parents=True, exist_ok=True)

    def tr(key: str, loc: str) -> str:
        bare = _ASC_TO_BARE.get(loc, loc)  # catalog uses the BARE code
        locz = cat.get(key, {}).get("localizations", {})
        u = (locz.get(bare) or locz.get(loc) or {}).get("stringUnit", {})
        return u.get("value") or key

    written, skipped = [], []
    for loc in locales:
        dest = copy_dir / f"{loc}.json"
        # GUARD: if the app provided PRE-TRANSLATED captions (file exists + non-empty) DON'T OVERWRITE — app-specific wins.
        if dest.exists():
            try:
                existing = json.loads(dest.read_text(encoding="utf-8"))
                if isinstance(existing, list) and existing and all(
                        (e.get("headline") or e.get("subhead")) for e in existing):
                    skipped.append(loc); continue
            except Exception:  # noqa: BLE001
                pass
        data = [{"headline": tr(h, loc), "subhead": tr(s, loc)} for h, s in CAPTION_KEYS]
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(loc)
    return {"ok": True, "written": written, "skipped_app_provided": skipped, "count": len(written)}


def build_all(app_dir: str | Path, project: str, scheme: str, bundle_id: str,
              sample_prompt: str, udid: str, locales: list[str] | None = None) -> dict[str, Any]:
    """REQUIRED screenshot step (turnkey, all apps): sample AI output → xcodegen → sim build + install →
    captions from catalog → capture 32 languages × 6 screens → apply the Claude Design store layout →
    brand → sync. Result is ready in fastlane/screenshots; uploaded to ASC via deliver_screenshots."""
    from .design import brand as brand_layout

    app = Path(app_dir).expanduser()
    md = app / "marketing" / "screenshots"
    if not (app / "design" / "project" / brand_layout.STORE_LAYOUT).exists():
        return {"ok": False, "step": "layout", "error": "no Claude Design store layout — run design_generate "
                "(store page) and upload it before building screenshots"}
    # 1) sample AI output (BEFORE build → bundled into Resources)
    smp = generate_sample(app, sample_prompt)
    # 2) xcodegen (including new assets) + sim build
    if (app / "project.yml").exists():
        run(["xcodegen", "generate"], cwd=str(app), timeout=120)
    proj = str(app / project) if not project.startswith("/") else project
    b = run(["xcodebuild", "-project", proj, "-scheme", scheme,
             "-destination", f"platform=iOS Simulator,id={udid}",
             "-derivedDataPath", str(app / "build" / "dd"), "build"], timeout=1200)
    if not b.get("ok"):
        return {"ok": False, "step": "build", "detail": b}
    # 3) install
    apps = list((app / "build" / "dd" / "Build" / "Products").rglob("*.app"))
    if not apps:
        return {"ok": False, "step": "install", "error": ".app not found"}
    run(["xcrun", "simctl", "boot", udid], timeout=60)
    run(["xcrun", "simctl", "uninstall", udid, bundle_id], timeout=60)
    ins = run(["xcrun", "simctl", "install", udid, str(apps[0])], timeout=120)
    if not ins.get("ok"):
        return {"ok": False, "step": "install", "detail": ins}
    # 4) captions + 5) capture + 6) brand + 7) sync
    captions_from_catalog(app, locales)
    shots = json.loads((app / "design" / "project" / brand_layout.STORE_LAYOUT).read_text(encoding="utf-8")).get("shots")
    cap = capture_all(udid, md, bundle_id, locales, screens=screens_for(shots or []) or None)
    lay = brand_layout.apply_layout(app)
    if not lay.get("ok"):
        return {"ok": False, "step": "layout", "detail": lay}
    br = brand(md)
    if not br.get("ok"):
        return {"ok": False, "step": "brand", "detail": br}
    sy = sync(md, app / "fastlane" / "screenshots")
    return {"ok": sy.get("ok"), "sample": smp.get("ok"), "captured": cap.get("captured"),
            "synced_locales": sy.get("synced_locales"), "dest": sy.get("dest")}


# Default region per bare language, for AppleLocale (currency, number and date formats follow the
# region, digits follow the language: ar shows Arabic-Indic digits, like the app).
_DEFAULT_REGION = {
    "ar": "SA", "ca": "ES", "cs": "CZ", "da": "DK", "de": "DE", "el": "GR", "en": "US", "es": "ES", "fi": "FI",
    "fr": "FR", "he": "IL", "hi": "IN", "hr": "HR", "hu": "HU", "id": "ID", "it": "IT", "ja": "JP", "ko": "KR",
    "ms": "MY", "nb": "NO", "nl": "NL", "no": "NO", "pl": "PL", "pt": "BR", "ro": "RO", "ru": "RU", "sk": "SK",
    "sv": "SE", "th": "TH", "tr": "TR", "uk": "UA", "vi": "VN", "zh-Hans": "CN", "zh-Hant": "TW",
}


def region_locale(asc_locale: str) -> str:
    """ASC locale → AppleLocale identifier: de-DE → de_DE, tr → tr_TR, zh-Hant → zh-Hant_TW, no → nb_NO."""
    if asc_locale.startswith("zh-"):
        return f"{asc_locale}_{_DEFAULT_REGION.get(asc_locale, 'CN')}"
    lang, _, region = asc_locale.partition("-")
    lang = {"no": "nb"}.get(lang, lang)
    return f"{lang}_{region or _DEFAULT_REGION.get(lang, lang.upper())}"


def store_status_bar(udid: str, day: str = "2026-09-26") -> dict[str, Any]:
    """Apple's marketing status bar: 9:41 local on `day` (an ISO time also pins the Lock Screen date;
    simctl wants UTC with milliseconds), full bars, NOT charging at 100 % (App Review flagged the
    charging bolt as misleading), no carrier name."""
    import datetime as _dt
    local = _dt.datetime.fromisoformat(f"{day}T09:41:00").astimezone()
    t = local.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return run(["xcrun", "simctl", "status_bar", udid, "override", "--time", t, "--operatorName", " ",
                "--dataNetwork", "wifi", "--wifiMode", "active", "--wifiBars", "3",
                "--cellularMode", "active", "--cellularBars", "4",
                "--batteryState", "discharging", "--batteryLevel", "100"], timeout=30)


def capture_all(udid: str, marketing_dir: str | Path, bundle_id: str,
                locales: list[str] | None = None, settle: float = 4.0,
                screens: list[tuple[str, list[str]]] | None = None) -> dict[str, Any]:
    """For each locale × each screen: switch the app language AND region (launch args) and capture raw,
    under the store status bar. UI-TEST style; doesn't get stuck on PhotosPicker (fed via
    ScreenshotMode launch-args). Widgets, SpringBoard and the Watch ignore launch arguments: capture
    those after Scripts/sim_store_prep.sh switched the whole simulator's language."""
    locales = locales or DEFAULT_LOCALES
    screens = screens or DEFAULT_SCREENS
    store_status_bar(udid)
    raw_root = Path(marketing_dir).expanduser() / "raw"
    shutil.rmtree(raw_root, ignore_errors=True)
    shutil.rmtree(Path(marketing_dir).expanduser() / "branded", ignore_errors=True)
    total = 0
    for loc in locales:
        rdir = raw_root / loc
        rdir.mkdir(parents=True, exist_ok=True)
        bare = _ASC_TO_BARE.get(loc, loc)  # AppleLanguages wants the iOS bare code (ta, not ta-IN)
        for name, args in screens:
            run(["xcrun", "simctl", "terminate", udid, bundle_id], timeout=30)
            run(["xcrun", "simctl", "launch", udid, bundle_id, *args,
                 "-AppleLanguages", f"({bare})", "-AppleLocale", region_locale(loc)], timeout=60)
            time.sleep(settle)
            run(["xcrun", "simctl", "io", udid, "screenshot", str(rdir / f"{name}.png")], timeout=30)
            total += 1
    return {"ok": True, "locales": len(locales), "screens": len(screens), "captured": total}


def capture(udid: str, marketing_dir: str | Path, locale: str, name: str) -> dict[str, Any]:
    """Raw capture from a booted simulator → marketing/raw/<locale>/<name>.png."""
    raw = Path(marketing_dir).expanduser() / "raw" / locale
    raw.mkdir(parents=True, exist_ok=True)
    out = raw / (name if name.endswith(".png") else f"{name}.png")
    r = run(["xcrun", "simctl", "io", udid, "screenshot", str(out)], timeout=30)
    if r.get("ok"):
        r["path"] = str(out)
    return r


def brand(marketing_dir: str | Path) -> dict[str, Any]:
    """Produce branded screenshots via node build.mjs (npm install if needed)."""
    d = Path(marketing_dir).expanduser()
    if not (d / "build.mjs").exists():
        return {"ok": False, "error": f"build.mjs not found: {d}"}
    if not (d / "node_modules").exists():
        inst = run(["npm", "install"], cwd=str(d), timeout=300)
        if not inst.get("ok"):
            return {"ok": False, "step": "npm install", "detail": inst}
    return run(["node", "build.mjs"], cwd=str(d), timeout=300)


def sync(marketing_dir: str | Path, fastlane_screenshots_dir: str | Path) -> dict[str, Any]:
    """branded/<locale>/* → fastlane/screenshots/<locale>/."""
    branded = Path(marketing_dir).expanduser() / "branded"
    dest = Path(fastlane_screenshots_dir).expanduser()
    if not branded.exists():
        return {"ok": False, "error": f"branded not found: {branded} (run screenshot_brand first)"}
    synced = []
    for loc_dir in branded.iterdir():
        if not loc_dir.is_dir():
            continue
        out = dest / loc_dir.name
        out.mkdir(parents=True, exist_ok=True)
        for png in loc_dir.glob("*.png"):
            shutil.copy2(png, out / png.name)
        synced.append(loc_dir.name)
    return {"ok": True, "synced_locales": synced, "dest": str(dest)}
