"""cpp_* — App Store Connect Custom Product Pages (one per Search Ads theme).

For each theme: CPP create → version → localization. Returns deep-link URLs (Ad Ops synergy:
campaign/ad-group → CPP → keyword ROAS). Runs through the asc CLI (`asc product-pages custom-pages …`).
"""
from __future__ import annotations

from typing import Any


def cpp_url(app_apple_id: str, cpp_id: str) -> str:
    """CPP deep-link (Search Ads / sharing): apps.apple.com/app/idXXXX?ppid=<cpp-uuid>."""
    return f"https://apps.apple.com/app/id{app_apple_id}?ppid={cpp_id}"


def _id(r: dict[str, Any]) -> dict[str, Any]:
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    d = (r.get("data") or {}).get("data") or {}
    return {"ok": True, "id": d.get("id") if isinstance(d, dict) else None}


def create_cpp(c, app_id: str, name: str, visible: bool = True) -> dict[str, Any]:
    return _id(c.create_custom_product_page(app_id, name, visible))


def create_version(c, cpp_id: str) -> dict[str, Any]:
    return _id(c.create_custom_product_page_version(cpp_id))


def create_localization(c, version_id: str, locale: str) -> dict[str, Any]:
    return _id(c.create_custom_product_page_localization(version_id, locale))


def build_cpps(c, app_id: str, app_apple_id: str, themes: list[dict]) -> dict[str, Any]:
    """themes = [{name, locale?}]. A CPP+version+localization chain per theme.
    Returns: {ok, pages:[{theme, ok, id?, version_id?, localization_id?, url?, error?}]}."""
    pages: list[dict[str, Any]] = []
    for t in themes:
        name = t["name"]
        locale = t.get("locale", "en-US")
        cp = create_cpp(c, app_id, name)
        if not cp["ok"]:
            pages.append({"theme": name, "ok": False, "step": "create", "error": cp["error"]})
            continue
        v = create_version(c, cp["id"])
        if not v["ok"]:
            pages.append({"theme": name, "ok": False, "step": "version", "error": v["error"], "id": cp["id"]})
            continue
        loc = create_localization(c, v["id"], locale)
        if not loc["ok"]:
            pages.append({"theme": name, "ok": False, "step": "localization", "error": loc["error"], "id": cp["id"]})
            continue
        pages.append({"theme": name, "ok": True, "id": cp["id"], "version_id": v["id"],
                      "localization_id": loc["id"], "url": cpp_url(app_apple_id, cp["id"])})
    return {"ok": bool(pages) and all(p["ok"] for p in pages), "pages": pages}
