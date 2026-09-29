"""deliver.py — display types, the read-only screenshot audit and subscription review screenshots
against a fake ASC client (no network)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from appfactory import deliver, spec


def _png(path: Path, w: int, h: int, seed: int = 0) -> Path:
    raw = b"".join(b"\x00" + bytes([seed % 256]) * (w * 3) for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


class FakeASC:
    """Routes GETs from a table; records writes."""

    def __init__(self, routes: dict[str, list | dict | None]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def request(self, method, path, params=None, json=None):
        self.calls.append((method, path))
        if method == "GET":
            data = self.routes.get(path)
            return {"ok": data is not None, "status": 200 if data is not None else 404, "data": {"data": data}}
        if method == "POST":
            return {"ok": True, "data": {"data": {"id": f"new{len(self.calls)}", "attributes": {"uploadOperations": []}}}}
        return {"ok": True, "data": {"data": {}}}

    # first-class asc commands (ASCClient methods)
    def upload_screenshot(self, localization_id, path, display_type):
        self.calls.append(("upload_screenshot", f"{localization_id}/{display_type}/{Path(path).name}"))
        return {"ok": True, "id": f"shot-{len(self.calls)}"}

    def delete_screenshot(self, sid):
        self.calls.append(("delete_screenshot", sid))
        return {"ok": True}

    def upload_subscription_review_screenshot(self, sub_id, path):
        self.calls.append(("upload_review_shot", sub_id))
        return {"ok": True, "id": f"rs-{len(self.calls)}"}

    def delete_subscription_review_screenshot(self, shot_id):
        self.calls.append(("delete_review_shot", shot_id))
        return {"ok": True}


def test_display_types_never_guess(tmp_path: Path):
    assert deliver._display_type(_png(tmp_path / "a.png", 1320, 2868)) == "APP_IPHONE_67"
    assert deliver._display_type(_png(tmp_path / "w.png", 422, 514)) == "APP_WATCH_ULTRA"
    assert deliver._display_type(_png(tmp_path / "x.png", 1000, 1000)) is None


def _app_with_shots(tmp_path: Path) -> tuple[Path, list[Path]]:
    app = tmp_path / "Hue"
    d = app / "fastlane" / "screenshots" / "en-US"
    files = [_png(d / "01_a.png", 1320, 2868, 1), _png(d / "02_b.png", 1320, 2868, 2), _png(d / "01_ring.png", 422, 514, 3)]
    return app, files


def _base_routes() -> dict:
    return {"/v1/apps": [{"id": "app-1"}],
            "/v1/apps/app-1/appStoreVersions": [{"id": "ver-1"}],
            "/v1/appStoreVersions/ver-1/appStoreVersionLocalizations": [{"id": "loc-en", "attributes": {"locale": "en-US"}}],
            "/v1/appStoreVersionLocalizations/loc-en/appPreviewSets": [{"id": "ps", "attributes": {"previewType": "IPHONE_67"}}]}


def test_audit_passes_only_on_exact_order_state_and_md5(tmp_path: Path):
    app, (a, b, ring) = _app_with_shots(tmp_path)
    shot = lambda f, state="COMPLETE", md5=None: {"attributes": {  # noqa: E731
        "fileName": f.name, "assetDeliveryState": {"state": state}, "sourceFileChecksum": md5 or deliver._md5(f)}}
    routes = {**_base_routes(),
              "/v1/appStoreVersionLocalizations/loc-en/appScreenshotSets": [
                  {"id": "set-ph", "attributes": {"screenshotDisplayType": "APP_IPHONE_67"}},
                  {"id": "set-w", "attributes": {"screenshotDisplayType": "APP_WATCH_ULTRA"}}],
              "/v1/appScreenshotSets/set-ph/appScreenshots": [shot(a), shot(b)],
              "/v1/appScreenshotSets/set-w/appScreenshots": [shot(ring)]}
    c = FakeASC(routes)
    ok = deliver.audit_screenshots(app, "com.x", client=c)
    assert ok["ok"] is True, ok["problems"]
    assert ok["locales"][0]["preview_sets"] == ["IPHONE_67"]
    assert all(m == "GET" for m, _ in c.calls)          # read-only

    routes["/v1/appScreenshotSets/set-ph/appScreenshots"] = [shot(b), shot(a, state="UPLOAD_COMPLETE", md5="0" * 32)]
    bad = deliver.audit_screenshots(app, "com.x", client=FakeASC(routes))
    text = " ".join(bad["problems"])
    assert bad["ok"] is False and "order/count" in text and "UPLOAD_COMPLETE" in text and "checksum" in text


def test_subscription_review_screenshots_are_idempotent(tmp_path: Path):
    app = tmp_path / "Hue"
    app.mkdir()
    sp = spec.build("Hue", "com.example.hue")
    spec.save(app, sp)
    shots = {p["key"]: _png(app / deliver.REVIEW_SHOTS_REL / f"{p['key']}.png", 1320, 2868, i)
             for i, p in enumerate(spec.products(sp))}
    subs = [{"id": f"sub-{p['key']}", "attributes": {"productId": p["id"]}} for p in spec.products(sp)]
    routes = {"/v1/apps": [{"id": "app-1"}], "/v1/apps/app-1/subscriptionGroups": [{"id": "g1"}],
              "/v1/subscriptionGroups/g1/subscriptions": subs,
              "/v1/subscriptions/sub-yearly/appStoreReviewScreenshot": {
                  "id": "rs-y", "attributes": {"sourceFileChecksum": deliver._md5(shots["yearly"]),
                                               "assetDeliveryState": {"state": "COMPLETE"}}},
              "/v1/subscriptions/sub-weekly/appStoreReviewScreenshot": {
                  "id": "rs-w", "attributes": {"sourceFileChecksum": "stale", "assetDeliveryState": {"state": "COMPLETE"}}}}
    c = FakeASC(routes)
    r = deliver.upload_subscription_review_screenshots(app, sp["bundle_id"], client=c)
    assert r["ok"] is True, r
    assert r["products"] == {"yearly": "unchanged", "weekly": "uploaded", "yearly_offer": "uploaded"}
    assert ("delete_review_shot", "rs-w") in c.calls
    assert sorted(p for m, p in c.calls if m == "upload_review_shot") == ["sub-weekly", "sub-yearly_offer"]

    shots["yearly_offer"].unlink()
    miss = deliver.upload_subscription_review_screenshots(app, sp["bundle_id"], client=FakeASC(routes))
    assert miss["ok"] is False and miss["missing"] == ["store/review-screenshots/yearly_offer.png"]


def test_screenshot_sync_uploads_only_changed_files_and_reorders(tmp_path: Path):
    app, (a, b, ring) = _app_with_shots(tmp_path)
    shot = lambda f, i, md5=None: {"id": i, "attributes": {  # noqa: E731
        "fileName": f.name, "assetDeliveryState": {"state": "COMPLETE"}, "sourceFileChecksum": md5 or deliver._md5(f)}}
    routes = {**_base_routes(),
              "/v1/appStoreVersionLocalizations/loc-en/appScreenshotSets": [
                  {"id": "set-ph", "attributes": {"screenshotDisplayType": "APP_IPHONE_67"}}],
              "/v1/appScreenshotSets/set-ph/appScreenshots": [shot(a, "old-a"), shot(b, "old-b", md5="stale")]}
    c = FakeASC(routes)
    r = deliver.sync_screenshots_api(app, "com.x", client=c)
    assert r["ok"] is True, r
    assert (r["uploaded"], r["skipped"], r["deleted"]) == (2, 1, 1)
    assert ("delete_screenshot", "old-b") in c.calls
    ups = [p for m, p in c.calls if m == "upload_screenshot"]
    assert ups == ["loc-en/APP_IPHONE_67/02_b.png", "loc-en/APP_WATCH_ULTRA/01_ring.png"]
    assert ("PATCH", "/v1/appScreenshotSets/set-ph/relationships/appScreenshots") in c.calls
    assert not any(m == "POST" for m, _ in c.calls)          # asc creates the missing Watch set itself
