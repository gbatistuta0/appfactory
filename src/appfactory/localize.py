"""localize_* — in-app localization (SwiftUI String Catalog).

The in-app languages are exactly app.spec.json `locales.app` (default en, es, pt-BR, de, fr, tr);
apps without a spec fall back to config.IN_APP_LOCALES (legacy). Source language is English;
translations are provided as {key: {locale: value}} and written to Resources/Localizable.xcstrings.
App Store metadata localization is separate (aso_*/metadata_*, spec `locales.store`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config as cfg
from . import spec as spec_mod

# Generic translations embedded in the MCP (Continue, Settings, Restore... same for every app). Merged
# AUTOMATICALLY on every build_catalog call → only app-specific strings are translated per app.
_GENERIC_PATH = Path(__file__).parent / "data" / "generic_localizations.json"


def _load_generic() -> dict[str, dict[str, str]]:
    try:
        return json.loads(_GENERIC_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# The iOS String Catalog wants Apple-bare codes (de, ar, es, fr, nl, nb, en). Regional/ASC codes
# passed by mistake (de-DE, ar-SA, no, en-US) are CONVERTED to the bare in-app code — otherwise the
# device falls back to English when its language is "de". cfg._ASC_TO_IN_APP already maps de-DE→de, no→nb, en-US→en.
def _normalize_locales(per_locale: dict[str, str]) -> dict[str, str]:
    """Convert language codes to Apple in-app bare codes (de-DE→de, no→nb, en-US→en). Bare codes pass through."""
    out: dict[str, str] = {}
    for loc, val in per_locale.items():
        out[cfg._ASC_TO_IN_APP.get(loc, loc)] = val
    return out


def target_locales(app_dir: str | Path) -> list[str]:
    """In-app locales (bare Apple codes, source language excluded) for this app."""
    try:
        locs = spec_mod.load(app_dir)["locales"]["app"]
    except (OSError, ValueError, KeyError):
        locs = list(cfg.IN_APP_LOCALES)
    return [loc for loc in locs if loc != "en"]


def build_catalog(app_dir: str | Path, translations: dict[str, dict[str, str]], source_lang: str = "en") -> dict[str, Any]:
    """translations {english_key: {locale: value}} → Localizable.xcstrings.
    ADDITIVE: preserves existing translations + automatically merges the MCP's generic translations.
    Priority: generic (base) < existing Catalog < this call's translations."""
    app = Path(app_dir).expanduser()
    catalog_path = app / "Resources" / "Localizable.xcstrings"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    # Existing Catalog (additive — do not lose previous calls)
    strings: dict[str, Any] = {}
    if catalog_path.exists():
        try:
            strings = json.loads(catalog_path.read_text(encoding="utf-8")).get("strings", {})
        except Exception:  # noqa: BLE001
            strings = {}

    targets = set(target_locales(app))
    # Merge: generic base + this call's translations (call takes priority)
    combined: dict[str, dict[str, str]] = {k: dict(v) for k, v in _load_generic().items()}
    for key, per_locale in translations.items():
        combined.setdefault(key, {}).update(per_locale)

    locales_seen: set[str] = set()
    for key, per_locale in combined.items():
        locs: dict[str, Any] = strings.get(key, {}).get("localizations", {})
        # NORMALIZE language codes to IN_APP_LOCALES (bare 'de'/'ar' → 'de-DE'/'ar-SA'; 'en'→en-*).
        for locale, value in _normalize_locales(per_locale).items():
            if locale not in targets:
                continue  # only the app's own languages (spec locales.app)
            locs[locale] = {"stringUnit": {"state": "translated", "value": value}}
            locales_seen.add(locale)
        strings[key] = {**strings.get(key, {}), "extractionState": strings.get(key, {}).get("extractionState", "manual"),
                        "localizations": locs}

    catalog = {"sourceLanguage": source_lang, "strings": strings, "version": "1.0"}
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, separators=(",", " : "), sort_keys=True) + "\n",
                            encoding="utf-8")
    return {
        "ok": True,
        "catalog": str(catalog_path),
        "string_count": len(strings),
        "locale_count": len(locales_seen),
        "generic_merged": len(_load_generic()),
        "target_locales": sorted(targets),
    }


# ---------------------------------------------------------------------------------------------
# Plural coverage (e.g. a Russian "%lld days" needs one, few, many and other)
# ---------------------------------------------------------------------------------------------

# CLDR cardinal categories an app must provide per language for integer counts. "many" is left out
# where it only covers millions or fractions (es, fr, pt, it, ca), which "other" reads right with the
# digits the app prints.
PLURAL_CATEGORIES: dict[str, set[str]] = {
    **{lang: {"other"} for lang in ("ja", "ko", "zh-Hans", "zh-Hant", "th", "vi", "id", "ms", "my", "km", "lo")},
    **{lang: {"one", "other"} for lang in (
        "en", "de", "nl", "sv", "da", "nb", "no", "fi", "et", "el", "hu", "tr", "es", "it", "pt-BR", "pt-PT", "ca",
        "bg", "hi", "bn", "gu", "kn", "ml", "mr", "ta", "te", "ur", "fa", "af", "sq", "az", "kk", "uz", "fr")},
    **{lang: {"one", "few", "many", "other"} for lang in ("ru", "uk", "pl", "cs", "sk", "lt", "be")},
    "ro": {"one", "few", "other"}, "hr": {"one", "few", "other"}, "sr": {"one", "few", "other"},
    "sl": {"one", "two", "few", "other"}, "he": {"one", "two", "other"}, "lv": {"zero", "one", "other"},
    "ar": {"zero", "one", "two", "few", "many", "other"}, "ga": {"one", "two", "few", "many", "other"},
}


def _plural_keys(unit: dict[str, Any] | None) -> set[str] | None:
    plural = ((unit or {}).get("variations") or {}).get("plural")
    return set(plural) if isinstance(plural, dict) else None


def plural_problems(catalog: dict[str, Any], locales: list[str]) -> list[str]:
    """Every key whose English source varies by plural gives each app language all of its CLDR
    categories. A language whose rules are unknown here is skipped."""
    out = []
    for key, entry in (catalog.get("strings") or {}).items():
        locs = entry.get("localizations") or {}
        if _plural_keys(locs.get("en")) is None:
            continue
        for loc in locales:
            need = PLURAL_CATEGORIES.get(loc) or PLURAL_CATEGORIES.get(loc.split("-")[0])
            if not need or loc == "en":
                continue
            have = _plural_keys(locs.get(loc)) or set()
            if locs.get(loc) and _plural_keys(locs.get(loc)) is None and need == {"other"}:
                continue   # a single string is complete for a language with one category
            if not need <= have:
                out.append(f"{loc} {key!r}: missing plural {sorted(need - have)}")
    return out
