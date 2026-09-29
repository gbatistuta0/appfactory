"""Shared fixtures for the backend/store tests: a Hue app dir with the template's backend + store
files, a spec, and a fully written listing.json. No network, no secrets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from appfactory import app as app_mod
from appfactory import spec

SUPA_URL = "https://abcdefghijklmnopqrst.supabase.co"
REF = "abcdefghijklmnopqrst"

NAMES = {
    "en-US": ("Hue: Color Analysis", "Find Your Signature Palette"),
    "en-GB": ("Hue: Colour Analysis", "Discover Flattering Shades"),
    "es-MX": ("Hue: Análisis de Tono", "Encuentra Tu Paleta Ideal"),
    "es-ES": ("Hue: Análisis Cromático", "Descubre Colores Favorecedores"),
    "pt-BR": ("Hue: Análise de Cores", "Descubra Sua Paleta"),
    "de-DE": ("Hue: Farbanalyse", "Finde Deine Farbpalette"),
    "fr-FR": ("Hue: Analyse Couleur", "Trouve Ta Palette Idéale"),
    "tr": ("Hue: Renk Analizi", "Sana Uyan Tonları Bul"),
}
LANG = {"en-US": "en", "en-GB": "en", "es-MX": "es", "es-ES": "es", "pt-BR": "pt-BR", "de-DE": "de",
        "fr-FR": "fr", "tr": "tr"}


def keywords(tag: str) -> str:
    """95–100 chars of unique tokens that never collide across locales."""
    toks, i = [], 0
    while len(",".join(toks)) < 95:
        toks.append(f"{tag}{i:02d}q")
        i += 1
    kw = ",".join(toks)
    return kw if len(kw) <= 100 else ",".join(toks[:-1]) + "," + f"{tag}z"[: 100 - len(",".join(toks[:-1])) - 1]


def description(loc: str) -> str:
    lang = LANG[loc]
    return ("Hue finds the colors that suit you.\n\n--- Subscription & Legal ---\n"
            "Payment is charged to your Apple Account at confirmation. Subscriptions renew automatically unless "
            "canceled at least 24 hours before the end of the period.\n"
            f"Terms of Use: {SUPA_URL}/functions/v1/legal/terms?lang={lang}\n"
            f"Privacy Policy: {SUPA_URL}/functions/v1/legal/privacy?lang={lang}")


def full_listing(sp: dict) -> dict:
    locs = {}
    for n, loc in enumerate(sp["locales"]["store"]):
        name, sub = NAMES[loc]
        locs[loc] = {"name": name, "subtitle": sub, "keywords": keywords(f"w{n}"),
                     "promotional_text": "New palettes every week.", "description": description(loc),
                     "privacy_url": f"{SUPA_URL}/functions/v1/legal/privacy?lang={LANG[loc]}",
                     "support_url": f"{SUPA_URL}/functions/v1/legal/support?lang={LANG[loc]}"}
    return {
        "brand_words": ["hue"],
        "cross_index": {"us": ["en-US", "es-MX"], "gb": ["en-GB"]},
        "cross_index_allow": {},
        "iap": {
            "group_name": {loc: "Hue Premium" for loc in sp["locales"]["store"]},
            "products": {p["key"]: {loc: {"name": f"Hue {p['key'].replace('_', ' ')}", "description": "Color analysis"}
                                    for loc in sp["locales"]["store"]} for p in sp["subscription"]["products"]},
        },
        "locales": locs,
    }


def make_app(tmp: Path, *, listing: bool = True, **spec_overrides) -> tuple[Path, dict]:
    app = tmp / "Hue"
    app.mkdir(parents=True, exist_ok=True)
    for d in ("supabase", "backend", "store"):
        shutil.copytree(app_mod.TEMPLATE_DIR / d, app / d, ignore=shutil.ignore_patterns("deno.lock", ".temp"))
    sp = spec.build("Hue", "com.example.hue", **spec_overrides)
    spec.save(app, sp)
    if listing:
        (app / "store" / "metadata" / "listing.json").write_text(json.dumps(full_listing(sp), indent=2), encoding="utf-8")
    return app, sp
