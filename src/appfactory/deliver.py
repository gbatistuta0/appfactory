"""deliver_* — upload metadata + screenshots to the ASC draft through the asc CLI.

Uploads use first-class asc commands (`asc screenshots upload`, `asc subscriptions review screenshots
create`, `asc localizations update|create`, `asc categories set`); reads and the few writes asc has
no command for go through `asc api` (ASCClient.request). The local layout stays
fastlane/metadata + fastlane/screenshots (a directory convention only; fastlane itself is not run).
Submit is NEVER done here (only asc_submit_for_review, human-approved).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import config as cfg

# PNG resolution → ASC screenshotDisplayType. Our output is 1320x2868 (iPhone 6.9"): ASC files the
# 6.9" size under APP_IPHONE_67 (checked against fastlane/spaceship device_types.rb; ASC has no GET-able
# enum). Apple Watch shots live in their own set on the same iPhone localization: 422x514 (Watch
# Ultra 3) and 410x502 are APP_WATCH_ULTRA.
_DISPLAY_BY_SIZE = {
    (1320, 2868): "APP_IPHONE_67", (1290, 2796): "APP_IPHONE_67",
    (1242, 2688): "APP_IPHONE_65", (1284, 2778): "APP_IPHONE_65",
    (1170, 2532): "APP_IPHONE_61", (1125, 2436): "APP_IPHONE_58",
    (2048, 2732): "APP_IPAD_PRO_3GEN_129", (2064, 2752): "APP_IPAD_PRO_129",
    (422, 514): "APP_WATCH_ULTRA", (410, 502): "APP_WATCH_ULTRA",
    (416, 496): "APP_WATCH_SERIES_10", (396, 484): "APP_WATCH_SERIES_7",
}


def _png_size(p: Path) -> tuple[int, int]:
    """(width, height) from the PNG IHDR — without PIL."""
    b = p.read_bytes()[16:24]
    return int.from_bytes(b[:4], "big"), int.from_bytes(b[4:8], "big")


def _display_type(p: Path) -> str | None:
    """None for a size ASC has no slot for: never guess (a wrong set is rejected or, worse, shown)."""
    w, h = _png_size(p)
    return _DISPLAY_BY_SIZE.get((w, h)) or _DISPLAY_BY_SIZE.get((h, w))


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _upload_one_screenshot(c, localization_id: str, display_type: str, p: Path) -> dict[str, Any]:
    """One screenshot through `asc screenshots upload` (reserve → upload → commit with MD5). No retry
    of its own: fastlane deliver's retry duplicated frames mid-upload (several locales had to be re-done by
    hand); a failed file is reported and the next sync uploads it again."""
    return c.upload_screenshot(localization_id, p, display_type)


def sync_screenshots_api(app_dir: str | Path, bundle_id: str, client: Any = None) -> dict[str, Any]:
    """Checksum-based INCREMENTAL screenshot sync (asc CLI).
    For each language × screen: if local MD5 == the sourceFileChecksum on ASC, SKIP; otherwise/if missing
    delete the old one + upload. At the end, reorders each set by file name. NO submit."""
    from .asc import ASCClient
    app = Path(app_dir).expanduser()
    shots = app / "fastlane" / "screenshots"
    if not shots.exists():
        return {"ok": False, "error": f"screenshots not found: {shots}"}
    c = client or ASCClient()
    # locale → localization id (ASC limit max=50; 200 → 400 → empty map → screenshot upload fails)
    loc_id, err = _localizations(c, bundle_id)
    if err:
        return err

    uploaded, skipped, deleted, errors = 0, 0, 0, []
    for d in sorted(shots.iterdir()):
        if not d.is_dir():
            continue
        loc = d.name
        lid = loc_id.get(loc)
        if not lid:
            errors.append({"locale": loc, "error": "no localization on ASC"})
            continue
        pngs = sorted(d.glob("*.png"))
        # display type → set; one set per (localization, display)
        by_dt: dict[str, list[Path]] = {}
        for p in pngs:
            dt = _display_type(p)
            if dt is None:
                errors.append({"locale": loc, "file": p.name, "error": "size %dx%d has no ASC display type" % _png_size(p)})
                continue
            by_dt.setdefault(dt, []).append(p)
        sets = c.request("GET", f"/v1/appStoreVersionLocalizations/{lid}/appScreenshotSets").get("data", {}).get("data", [])
        set_by_dt = {s["attributes"]["screenshotDisplayType"]: s["id"] for s in sets}
        for dt, files in by_dt.items():
            set_id = set_by_dt.get(dt)  # none yet → `asc screenshots upload` creates the set
            existing = c.request("GET", f"/v1/appScreenshotSets/{set_id}/appScreenshots",
                                 params={"limit": "30"}).get("data", {}).get("data", []) if set_id else []
            by_name = {e["attributes"]["fileName"]: e for e in existing}
            for p in files:
                ex = by_name.get(p.name)
                if ex and (ex["attributes"].get("sourceFileChecksum") == _md5(p)) and ex["attributes"].get("assetDeliveryState", {}).get("state") != "FAILED":
                    skipped += 1
                    continue
                if ex:  # different/corrupt → delete
                    c.delete_screenshot(ex["id"])
                    deleted += 1
                res = _upload_one_screenshot(c, lid, dt, p)
                if res.get("ok"):
                    uploaded += 1
                else:
                    errors.append({"locale": loc, "file": p.name, **res})
            if not set_id:
                sets = c.request("GET", f"/v1/appStoreVersionLocalizations/{lid}/appScreenshotSets").get("data", {}).get("data", [])
                set_id = next((s["id"] for s in sets if s["attributes"]["screenshotDisplayType"] == dt), None)
                if not set_id:
                    continue
            # ordering: reorder by file name (01_.. 06_..) — asc has no reorder command → `asc api` PATCH
            cur = c.request("GET", f"/v1/appScreenshotSets/{set_id}/appScreenshots",
                            params={"limit": "30"}).get("data", {}).get("data", [])
            order = sorted(cur, key=lambda e: e["attributes"]["fileName"])
            if order:
                c.request("PATCH", f"/v1/appScreenshotSets/{set_id}/relationships/appScreenshots",
                          json={"data": [{"type": "appScreenshots", "id": e["id"]} for e in order]})
    return {"ok": not errors, "uploaded": uploaded, "skipped": skipped,
            "deleted": deleted, "errors": errors}


def _localizations(c, bundle_id: str) -> tuple[dict[str, str] | None, dict | None]:
    """locale → appStoreVersionLocalization id of the newest version, or (None, error)."""
    apps = c.request("GET", "/v1/apps", params={"filter[bundleId]": bundle_id}).get("data", {}).get("data", [])
    if not apps:
        return None, {"ok": False, "error": f"app not found: {bundle_id}"}
    vers = c.request("GET", f"/v1/apps/{apps[0]['id']}/appStoreVersions", params={"limit": "1"}).get("data", {}).get("data", [])
    if not vers:
        return None, {"ok": False, "error": "appStoreVersion not found"}
    locs = c.request("GET", f"/v1/appStoreVersions/{vers[0]['id']}/appStoreVersionLocalizations",
                     params={"limit": "50"}).get("data", {}).get("data", [])
    return {l["attributes"]["locale"]: l["id"] for l in locs}, None


def audit_screenshots(app_dir: str | Path, bundle_id: str, client: Any = None) -> dict[str, Any]:
    """Read-only readiness audit of the uploaded screenshots:
    for every local fastlane/screenshots/<locale>, each ASC set must hold exactly the local files, in
    file-name order, every one COMPLETE and with the local file's MD5 as sourceFileChecksum (ASC
    stores MD5, not SHA-1). Also reports whether the localization has an app preview set. No writes."""
    from .asc import ASCClient
    app = Path(app_dir).expanduser()
    shots = app / "fastlane" / "screenshots"
    if not shots.exists():
        return {"ok": False, "error": f"screenshots not found: {shots}"}
    c = client or ASCClient()
    loc_id, err = _localizations(c, bundle_id)
    if err:
        return err
    rows, problems = [], []
    for d in sorted(x for x in shots.iterdir() if x.is_dir()):
        loc, lid = d.name, loc_id.get(d.name)
        if not lid:
            problems.append(f"{loc}: no localization on ASC")
            continue
        local: dict[str, list[Path]] = {}
        for f in sorted(d.glob("*.png")):
            local.setdefault(_display_type(f) or "UNKNOWN", []).append(f)
        sets = c.request("GET", f"/v1/appStoreVersionLocalizations/{lid}/appScreenshotSets").get("data", {}).get("data", [])
        set_by_dt = {x["attributes"]["screenshotDisplayType"]: x["id"] for x in sets}
        row: dict[str, Any] = {"locale": loc, "sets": {}}
        for dt, files in local.items():
            sid = set_by_dt.get(dt)
            have = c.request("GET", f"/v1/appScreenshotSets/{sid}/appScreenshots",
                             params={"limit": "30"}).get("data", {}).get("data", []) if sid else []
            names = [h["attributes"].get("fileName") for h in have]
            issues = []
            if names != [f.name for f in files]:
                issues.append(f"order/count {names} != {[f.name for f in files]}")
            by_name = {h["attributes"].get("fileName"): h["attributes"] for h in have}
            for f in files:
                a = by_name.get(f.name)
                if a is None:
                    continue
                if (a.get("assetDeliveryState") or {}).get("state") != "COMPLETE":
                    issues.append(f"{f.name} {(a.get('assetDeliveryState') or {}).get('state')}")
                if a.get("sourceFileChecksum") != _md5(f):
                    issues.append(f"{f.name} checksum differs from the local file")
            row["sets"][dt] = {"count": len(have), "ok": not issues, "issues": issues}
            problems += [f"{loc} {dt}: {i}" for i in issues]
        previews = c.request("GET", f"/v1/appStoreVersionLocalizations/{lid}/appPreviewSets").get("data", {}).get("data", [])
        row["preview_sets"] = [x["attributes"].get("previewType") for x in previews]
        rows.append(row)
    return {"ok": not problems, "locales": rows, "problems": problems}


REVIEW_SHOTS_REL = Path("store") / "review-screenshots"


def upload_subscription_review_screenshots(app_dir: str | Path, bundle_id: str, client: Any = None) -> dict[str, Any]:
    """App Review screenshot for every subscription (without it a subscription stays
    MISSING_METADATA). store/review-screenshots/<product key>.png, e.g. yearly.png / weekly.png showing
    the hard paywall with REAL sandbox prices and yearly_offer.png the offer paywall. Idempotent by MD5:
    a COMPLETE screenshot with the same checksum is kept, a different one is replaced."""
    from . import spec as spec_mod
    from .asc import ASCClient
    app = Path(app_dir).expanduser()
    sp = spec_mod.load(app)
    c = client or ASCClient()
    apps = c.request("GET", "/v1/apps", params={"filter[bundleId]": bundle_id}).get("data", {}).get("data", [])
    if not apps:
        return {"ok": False, "error": f"app not found: {bundle_id}"}
    states: dict[str, str] = {}
    by_pid: dict[str, str] = {}
    groups = c.request("GET", f"/v1/apps/{apps[0]['id']}/subscriptionGroups", params={"limit": "50"}).get("data", {}).get("data", [])
    for g in groups:
        for x in c.request("GET", f"/v1/subscriptionGroups/{g['id']}/subscriptions", params={"limit": "50"}).get("data", {}).get("data", []):
            by_pid[x["attributes"]["productId"]] = x["id"]
    missing, errors = [], []
    for prod in spec_mod.products(sp):
        f = app / REVIEW_SHOTS_REL / f"{prod['key']}.png"
        sid = by_pid.get(prod["id"])
        if not f.exists():
            missing.append(str(f.relative_to(app)))
            continue
        if not sid:
            errors.append({"product": prod["id"], "error": "subscription not in ASC (run store_setup apply)"})
            continue
        cur = (c.request("GET", f"/v1/subscriptions/{sid}/appStoreReviewScreenshot").get("data") or {}).get("data")
        if cur:
            a = cur.get("attributes") or {}
            if a.get("sourceFileChecksum") == _md5(f) and (a.get("assetDeliveryState") or {}).get("state") == "COMPLETE":
                states[prod["key"]] = "unchanged"
                continue
            c.delete_subscription_review_screenshot(cur["id"])
        res = c.upload_subscription_review_screenshot(sid, f)
        if res.get("ok"):
            states[prod["key"]] = "uploaded"
        else:
            errors.append({"product": prod["id"], **res})
    return {"ok": not missing and not errors, "products": states, "missing": missing, "errors": errors}


def upload_metadata_api(app_dir: str | Path, bundle_id: str, client: Any = None) -> dict[str, Any]:
    """Upload metadata through the asc CLI (fastlane deliver had a 'No data' bug).

    name/subtitle → appInfoLocalizations; description/keywords/promotionalText/supportUrl
    → appStoreVersionLocalizations (PREPARE_FOR_SUBMISSION). whatsNew is forbidden on the
    first version → skipped.
    """
    import re
    from .asc import ASCClient
    app_root = Path(app_dir).expanduser()
    meta = app_root / "fastlane" / "metadata"
    if not meta.exists():
        return {"ok": False, "error": f"metadata not found: {meta}"}
    # Privacy Policy URL is REQUIRED (in every appInfoLocalization). Source order: listing.json per
    # locale (the Supabase legal function with ?lang=), the app's legal base (outputs), AppConfig.swift.
    priv_url = None
    priv_by_locale: dict[str, str] = {}
    listing_p = app_root / "store" / "metadata" / "listing.json"
    if listing_p.exists():
        try:
            listing = json.loads(listing_p.read_text(encoding="utf-8"))
            priv_by_locale = {loc: e["privacy_url"] for loc, e in (listing.get("locales") or {}).items()
                              if e.get("privacy_url") and "{{" not in e["privacy_url"]}
        except Exception:  # noqa: BLE001
            priv_by_locale = {}
    legal_base = cfg.app_outputs(app_root).get("legal_base")
    if legal_base:
        priv_url = f"{legal_base}/privacy"
    cfg_swift = app_root / "Sources" / "AppConfig.swift"
    if not priv_url and cfg_swift.exists():
        m = re.search(r'privacyURL\s*=\s*"([^"]+)"', cfg_swift.read_text(encoding="utf-8"))
        if m:
            priv_url = m.group(1)
    # Category (appInfo-level): root *.txt in fastlane/metadata → appCategories id (e.g. PHOTO_AND_VIDEO).
    def _cat(fn: str) -> str | None:
        f = meta / fn
        return f.read_text(encoding="utf-8").strip() if f.exists() else None
    primary_cat, secondary_cat = _cat("primary_category.txt"), _cat("secondary_category.txt")
    c = client or ASCClient()
    apps = c.get_app_by_bundle(bundle_id).get("data", {}).get("data", [])
    if not apps:
        return {"ok": False, "error": f"app not found: {bundle_id}"}
    app_id = apps[0]["id"]
    ai = c.request("GET", f"/v1/apps/{app_id}/appInfos").get("data", {}).get("data", [])
    vs = c.request("GET", f"/v1/apps/{app_id}/appStoreVersions",
                   params={"filter[appStoreState]": "PREPARE_FOR_SUBMISSION"}).get("data", {}).get("data", [])
    if not ai or not vs:
        return {"ok": False, "error": "no appInfo/PREPARE_FOR_SUBMISSION version (run asc_create_app/version first)"}
    ai_id, vid = ai[0]["id"], vs[0]["id"]
    # GOTCHA: ASC limit max = 50 (200 → 400 PARAMETER_ERROR → empty map → POST per locale → 409 DUPLICATE).
    aimap = {l["attributes"]["locale"]: l["id"]
             for l in c.request("GET", f"/v1/appInfos/{ai_id}/appInfoLocalizations",
                                params={"limit": 50}).get("data", {}).get("data", [])}
    vmap = {l["attributes"]["locale"]: l["id"]
            for l in c.request("GET", f"/v1/appStoreVersions/{vid}/appStoreVersionLocalizations",
                               params={"limit": 50}).get("data", {}).get("data", [])}

    def rd(loc: str, fn: str) -> str | None:
        f = meta / loc / fn
        return f.read_text(encoding="utf-8").strip() if f.exists() else None

    ok_locs, errors = [], []
    for d in sorted(meta.iterdir()):
        if not d.is_dir():
            continue
        loc = d.name
        # appInfo: name + subtitle + privacyPolicyUrl (privacy REQUIRED, in every locale)
        ai_attrs = {k: rd(loc, fn) for k, fn in [("name", "name.txt"), ("subtitle", "subtitle.txt")] if rd(loc, fn)}
        loc_priv = priv_by_locale.get(loc) or rd(loc, "privacy_url.txt") or priv_url
        if loc_priv:
            ai_attrs["privacyPolicyUrl"] = loc_priv
        if ai_attrs:
            if loc in aimap:
                r = c.update_localization(aimap[loc], ai_attrs, app_info=True)
            else:  # asc has no app-info localization create command → `asc api` POST
                r = c.request("POST", "/v1/appInfoLocalizations", json={"data": {
                    "type": "appInfoLocalizations", "attributes": {"locale": loc, **ai_attrs},
                    "relationships": {"appInfo": {"data": {"type": "appInfos", "id": ai_id}}}}})
            if not r.get("ok"):
                errors.append({"locale": loc, "where": "appInfo", "error": r.get("error")})
        # version: description/keywords/promo/support (create if missing)
        v_attrs = {k: rd(loc, fn) for k, fn in [
            ("description", "description.txt"), ("keywords", "keywords.txt"),
            ("promotionalText", "promotional_text.txt"), ("supportUrl", "support_url.txt"),
            ("marketingUrl", "marketing_url.txt")] if rd(loc, fn)}
        if v_attrs:
            if loc in vmap:
                r = c.update_localization(vmap[loc], v_attrs)
            else:
                r = c.create_version_localization(vid, loc, v_attrs)
            if r.get("ok"):
                ok_locs.append(loc)
            else:
                errors.append({"locale": loc, "where": "version", "error": r.get("error")})
    # Category (appInfo-level, once): primary + secondary appCategories relationship.
    rc: dict[str, Any] = {"ok": True}
    if primary_cat:
        rc = c.set_categories(app_id, primary_cat, secondary_cat, app_info_id=ai_id)
    elif secondary_cat:  # `asc categories set` requires a primary → `asc api` PATCH
        rc = c.request("PATCH", f"/v1/appInfos/{ai_id}", json={"data": {"type": "appInfos", "id": ai_id, "relationships": {
            "secondaryCategory": {"data": {"type": "appCategories", "id": secondary_cat}}}}})
    if not rc.get("ok"):
        errors.append({"where": "category", "error": rc.get("error")})
    return {"ok": not errors, "uploaded_locales": ok_locs, "count": len(ok_locs),
            "privacy_url": priv_url, "categories": [primary_cat, secondary_cat], "errors": errors}
