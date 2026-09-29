"""metadata_* — apple-metadata.md → fastlane/metadata/<locale>/*.txt.

Port of an earlier `export_fastlane_metadata.rb` script; generalized to the 32 ASC
languages (its xx-XX constraint removed). Validates character limits.

apple-metadata.md format (produced by the aso step):
    # <locale>            (e.g. en-US, tr, ja, zh-Hans)
    ## App Name — 24/30
    ```
    <content>
    ```
    ## Subtitle — ...
    ...
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from . import config as cfg

FIELD_FILES = {
    "App Name": "name.txt",
    "Subtitle": "subtitle.txt",
    "Promotional Text": "promotional_text.txt",
    "Keyword Field": "keywords.txt",
    "Description": "description.txt",
    "What's New": "release_notes.txt",
}

LIMITS = {
    "name.txt": 30,
    "subtitle.txt": 30,
    "promotional_text.txt": 170,
    "keywords.txt": 100,
    "description.txt": 4000,
    "release_notes.txt": 4000,
}

# Legacy compatibility: if tr-TR is written, fastlane expects "tr".
LOCALE_ALIASES = {"tr-TR": "tr"}


def _is_locale_heading(token: str) -> bool:
    if token in cfg.APP_STORE_LOCALES or token in LOCALE_ALIASES:
        return True
    return bool(re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", token))


def _fenced_block_after(lines: list[str], start: int) -> str | None:
    """Return the content of the ```...``` block after the start line."""
    opening = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "```":
            opening = i
            break
    if opening is None:
        return None
    for j in range(opening + 1, len(lines)):
        if lines[j].strip() == "```":
            return "\n".join(lines[opening + 1:j]).rstrip()
    return None


def parse(md_text: str) -> dict[str, dict[str, str]]:
    """apple-metadata.md → {locale: {filename: value}}."""
    lines = md_text.splitlines()
    locales: dict[str, dict[str, str]] = {}
    current: str | None = None
    for idx, line in enumerate(lines):
        m = re.match(r"^#\s+(\S+)\s*$", line)
        if m and _is_locale_heading(m.group(1)):
            current = m.group(1)
            locales.setdefault(current, {})
            continue
        if current is None:
            continue
        for heading, filename in FIELD_FILES.items():
            if line.startswith(f"## {heading}"):
                block = _fenced_block_after(lines, idx)
                if block is not None:
                    locales[current][filename] = block
    return locales


def validate(locale: str, filename: str, value: str) -> list[str]:
    errs = []
    limit = LIMITS.get(filename)
    if limit and len(value) > limit:
        errs.append(f"{locale}/{filename}: {len(value)}/{limit} (limit exceeded)")
    # Empty field = ASO hasn't filled it in yet (gate: metadata can't be produced without ASO).
    if not value.strip():
        errs.append(f"{locale}/{filename}: empty (ASO must fill it)")
    # Apple keyword field: a space after a comma wastes characters → reject it.
    # Intra-phrase spaces (e.g. Vietnamese "chân dung"; none in Chinese) are valid, allow them.
    if filename == "keywords.txt" and value.strip() and re.search(r",\s|\s,", value):
        errs.append(f"{locale}/{filename}: whitespace around a comma (comma-separate, no space after comma)")
    return errs


def check(source_md: str | Path) -> dict[str, Any]:
    """Validate only (no writing). Report over-limit/missing fields."""
    p = Path(source_md)
    if not p.exists():
        return {"ok": False, "error": f"apple-metadata.md not found: {p}"}
    locales = parse(p.read_text(encoding="utf-8"))
    if not locales:
        return {"ok": False, "error": "no locale could be parsed (format?)"}
    errors: list[str] = []
    for locale, files in locales.items():
        missing = set(FIELD_FILES.values()) - set(files.keys())
        if missing:
            errors.append(f"{locale}: missing field(s): {', '.join(sorted(missing))}")
        for filename, value in files.items():
            errors.extend(validate(locale, filename, value))
    return {"ok": not errors, "locales": sorted(locales.keys()), "errors": errors}


def export(
    source_md: str | Path,
    dest_dir: str | Path,
    support_url: str | None = None,
    privacy_url: str | None = None,
    primary_category: str | None = None,
    secondary_category: str | None = None,
) -> dict[str, Any]:
    """Write apple-metadata.md as fastlane/metadata/<locale>/*.txt (validated).
    Category (appInfo-level) is written to root primary_category.txt/secondary_category.txt;
    deliver_metadata pushes these to ASC. Value = appCategories id (e.g. PHOTO_AND_VIDEO)."""
    chk = check(source_md)
    if not chk["ok"]:
        return {"ok": False, "step": "check", "errors": chk.get("errors"), "error": chk.get("error")}
    locales = parse(Path(source_md).read_text(encoding="utf-8"))
    dest = Path(dest_dir)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    if primary_category:
        (dest / "primary_category.txt").write_text(primary_category.strip() + "\n", encoding="utf-8")
    if secondary_category:
        (dest / "secondary_category.txt").write_text(secondary_category.strip() + "\n", encoding="utf-8")
    written = []
    for locale, files in locales.items():
        out_locale = LOCALE_ALIASES.get(locale, locale)
        d = dest / out_locale
        d.mkdir(parents=True, exist_ok=True)
        for filename, value in files.items():
            (d / filename).write_text(value + "\n", encoding="utf-8")
        if support_url:
            (d / "support_url.txt").write_text(support_url + "\n", encoding="utf-8")
        if privacy_url:
            (d / "privacy_url.txt").write_text(privacy_url + "\n", encoding="utf-8")
        written.append(out_locale)
    return {"ok": True, "written_locales": written, "count": len(written), "dest": str(dest)}


# ---------------------------------------------------------------------------------------------
# store/metadata/listing.json — the per-app listing source
# ---------------------------------------------------------------------------------------------
import json as _json  # noqa: E402
import unicodedata as _ud  # noqa: E402

LISTING_REL = Path("store") / "metadata" / "listing.json"
LISTING_LIMITS = {"name": 30, "subtitle": 30, "keywords": 100, "promotional_text": 170, "description": 4000}
KEYWORD_MIN = 95
IAP_NAME_MAX, IAP_DESC_MAX = 30, 45
FILLER = {"app", "apps", "free", "best", "the"}
# Short function words may repeat across fields (Apple ignores them for matching).
STOPWORDS = {"&", "and", "y", "e", "et", "und", "ve", "de", "da", "do", "du", "la", "le", "el", "mit", "for",
             "of", "a", "o", "com", "con", "par", "pour", "per", "ile", "i"}
_UNLIMITED = re.compile(r"unlimited|ilimitad|illimit|unbegrenzt|sınırsız|sinirsiz|无限|無制限|무제한", re.I)
_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}")
DISCLOSURE_HEADING = re.compile(r"^-{3}\s*\S.*\S\s*-{3}$", re.M)


# A language's own name is filler in its keyword field: the storefront already serves that language
# (a 36-locale ASO audit: hi "hindi", tr "türkçe" dropped for real terms).
LANGUAGE_NAMES = {
    "english", "ingles", "spanish", "espanol", "portuguese", "portugues", "brasil", "german", "deutsch",
    "french", "francais", "turkish", "turkce", "italian", "italiano", "dutch", "nederlands", "russian",
    "русский", "ukrainian", "українська", "polish", "polski", "arabic", "عربي", "العربية", "hebrew", "עברית",
    "hindi", "हिंदी", "हिन्दी", "japanese", "日本語", "korean", "한국어", "chinese", "中文", "简体", "繁體", "繁体",
    "indonesian", "indonesia", "malay", "melayu", "thai", "ไทย", "vietnamese", "tiếng việt", "swedish", "svenska",
    "danish", "dansk", "norwegian", "norsk", "finnish", "suomi", "czech", "čeština", "cestina", "greek",
    "ελληνικά", "romanian", "română", "romana", "hungarian", "magyar",
}
# List marks that are NOT keyword separators for App Store Connect (it splits on the ASCII comma only).
_FOREIGN_COMMAS = "،、，﹐､"


def fold(text: str) -> str:
    """Lowercase and strip diacritics from LATIN letters so 'calorías' and 'calorias' compare equal.
    Other scripts keep their marks: й is not и (калорий ≠ калории), ї is not і, ガ is not カ."""
    out = []
    for ch in _ud.normalize("NFC", text.lower().replace("ı", "i")):
        parts = _ud.normalize("NFKD", ch)
        out.append("".join(c for c in parts if not _ud.combining(c)) if parts[0] < "\u0250" else ch)
    return "".join(out)


def words(text: str) -> list[str]:
    """Words of an indexed field; the Arabic comma and CJK list marks separate words too."""
    return [w for w in re.findall(r"[^\s,:&\-–—/،、，・·]+", fold(text)) if w not in STOPWORDS]


def singular(word: str) -> str:
    """Crude plural fold (Apple matches plurals itself): macros -> macro, calorias -> caloria."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def check_description_end(loc: str, desc: str, lang: str | None = None) -> list[str]:
    """The description must END with the subscription disclosure block: a `--- heading ---` line,
    the auto-renewal text (mentions the 24 hours), then the Terms and Privacy links (Apple 3.1.2;
    Terms link in the description is mandatory). Links must be the Supabase legal function (Terms
    may also be Apple's standard EULA) and carry ?lang=<locale language> when `lang` is given."""
    from . import legal as legal_mod
    errs: list[str] = []
    heads = list(DISCLOSURE_HEADING.finditer(desc))
    if not heads:
        return [f"{loc}: description must end with a '--- Subscription … ---' disclosure block"]
    tail = desc[heads[-1].end():]
    if "24" not in tail:
        errs.append(f"{loc}: disclosure must state the 24-hour auto-renewal rule")
    urls = re.findall(r"https?://\S+", tail)
    terms = [u for u in urls if legal_mod.is_legal_url(u, "terms") or "apple.com/legal/internet-services/itunes/dev/stdeula" in u]
    privacy = [u for u in urls if legal_mod.is_legal_url(u, "privacy")]
    if not terms:
        errs.append(f"{loc}: disclosure needs the Terms of Use link (legal function or Apple EULA)")
    if not privacy:
        errs.append(f"{loc}: disclosure needs the Privacy Policy link (the Supabase legal function)")
    lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
    if privacy and not any(privacy[0] in ln for ln in lines[-3:]):
        errs.append(f"{loc}: the description must end with the Terms/Privacy links (text found after them)")
    if lang:
        for u in terms + privacy:
            if "supabase.co" in u and not u.endswith(f"?lang={lang}"):
                errs.append(f"{loc}: {u} should use ?lang={lang}")
    return errs


def check_listing_locale(loc: str, entry: dict[str, Any], competitors: set[str] = frozenset(),
                         lang: str | None = None) -> list[str]:
    from . import legal as legal_mod
    errs = []
    for field, limit in LISTING_LIMITS.items():
        val = entry.get(field)
        if val is None:
            if field not in ("promotional_text",):
                errs.append(f"{loc}: missing {field}")
            continue
        if _PLACEHOLDER.search(val):
            errs.append(f"{loc}: {field} still has placeholders {_PLACEHOLDER.findall(val)[:3]}")
            continue
        if len(val) > limit:
            errs.append(f"{loc}: {field} is {len(val)} chars (limit {limit}): {val[:60]!r}")
    kw = entry.get("keywords", "") or ""
    if kw and not _PLACEHOLDER.search(kw):
        if len(kw) < KEYWORD_MIN:
            errs.append(f"{loc}: keywords use {len(kw)}/100 chars (target >= {KEYWORD_MIN})")
        if re.search(r"\s,|,\s", kw) or kw != kw.strip():
            errs.append(f"{loc}: keywords have spaces around commas")
        items = kw.split(",")
        if any(not i for i in items):
            errs.append(f"{loc}: keywords contain an empty entry")
        folded = [fold(i) for i in items]
        dup = {i for i in folded if folded.count(i) > 1}
        if dup:
            errs.append(f"{loc}: duplicate keywords {sorted(dup)}")
        foreign = sorted({ch for ch in kw if ch in _FOREIGN_COMMAS})
        if foreign:
            errs.append(f"{loc}: keywords use {foreign} as a separator — App Store Connect splits on the ASCII comma only")
        lang_names = sorted({i.strip() for i in folded if i.strip() in {fold(n) for n in LANGUAGE_NAMES}})
        if lang_names:
            errs.append(f"{loc}: language name(s) {lang_names} in keywords — filler, the storefront already serves that language")
    if not any(_PLACEHOLDER.search(entry.get(f, "") or "") for f in ("name", "subtitle", "keywords")):
        fields = {f: [singular(w) for w in words(entry.get(f, "") or "")] for f in ("name", "subtitle", "keywords")}
        seen: dict[str, str] = {}
        for f, ws in fields.items():
            for w in ws:
                if w in seen and seen[w] != f:
                    errs.append(f"{loc}: word {w!r} repeats in {seen[w]} and {f}")
                seen.setdefault(w, f)
            within = [w for w in ws if ws.count(w) > 1]
            if within and f != "name":
                errs.append(f"{loc}: word(s) {sorted(set(within))} repeat inside {f}")
        all_text = " ".join(fold(entry.get(f, "") or "") for f in ("name", "subtitle", "keywords"))
        for w in words(all_text):
            if w in FILLER:
                errs.append(f"{loc}: filler word {w!r} in an indexed field")
        for f in ("name", "subtitle", "keywords"):
            parts = fold(entry.get(f, "") or "").split(",") if f == "keywords" else [fold(entry.get(f, "") or "")]
            for part in parts:
                norm = " " + " ".join(re.findall(r"[a-z0-9.]+", part)) + " "
                for c in competitors:
                    if f" {fold(c)} " in norm:
                        errs.append(f"{loc}: competitor name {c!r} in {f} (Guideline 2.3.7)")
    desc = entry.get("description") or ""
    if desc and not _PLACEHOLDER.search(desc):
        errs += check_description_end(loc, desc, lang)
    for field, doc in (("privacy_url", "privacy"), ("support_url", None)):
        u = entry.get(field)
        if not u:
            errs.append(f"{loc}: missing {field}")
        elif _PLACEHOLDER.search(u):
            errs.append(f"{loc}: {field} still has placeholders")
        elif field == "privacy_url" and not legal_mod.is_legal_url(u, doc):
            errs.append(f"{loc}: privacy_url must be the Supabase legal function (…/functions/v1/legal/privacy)")
        elif field == "support_url" and not (legal_mod.is_legal_url(u) or u.startswith("https://")):
            errs.append(f"{loc}: support_url must be an https URL (legal/support recommended)")
    return errs


def check_listing(listing: dict[str, Any], spec: dict[str, Any] | None = None) -> list[str]:
    """All listing rules. With a spec: locales must equal spec.locales.store, the spec name counts as
    a brand word, IAP copy must cover every product × store locale, and URLs must carry the locale's
    app language."""
    from . import legal as legal_mod
    errs: list[str] = []
    locales = listing.get("locales") or {}
    app_locs = spec["locales"]["app"] if spec else None
    if spec:
        want = spec["locales"]["store"]
        missing = [loc for loc in want if loc not in locales]
        extra = [loc for loc in locales if loc not in want]
        if missing:
            errs.append(f"listing is missing store locales {missing}")
        if extra:
            errs.append(f"listing has locales not in spec.locales.store: {extra}")
    competitors = set(listing.get("competitors", []))
    for loc, entry in locales.items():
        errs += check_listing_locale(loc, entry, competitors, legal_mod.app_language(loc, app_locs) if app_locs else None)
    brand = {fold(b) for b in listing.get("brand_words", [])}
    if spec:
        brand |= {singular(w) for w in words(spec.get("display_name") or spec.get("name", ""))}
    allow = listing.get("cross_index_allow", {})
    for storefront, locs in (listing.get("cross_index") or {}).items():
        owner: dict[str, str] = {}
        for loc in locs:
            e = locales.get(loc)
            if not e or any(_PLACEHOLDER.search(e.get(f, "") or "") for f in ("name", "subtitle", "keywords")):
                continue
            for w in {singular(x) for f in ("name", "subtitle", "keywords") for x in words(e.get(f, "") or "")}:
                if w in brand or w in allow.get(storefront, []):
                    continue
                if w in owner:
                    errs.append(f"{storefront}: {w!r} is indexed twice ({owner[w]} and {loc})")
                else:
                    owner[w] = loc
    iap = listing.get("iap") or {}
    store_locs = spec["locales"]["store"] if spec else list(locales)
    for loc in store_locs:
        g = (iap.get("group_name") or {}).get(loc)
        if not g or _PLACEHOLDER.search(g):
            errs.append(f"iap: group name missing for {loc}")
        elif len(g) > IAP_NAME_MAX:
            errs.append(f"iap: group name {loc} is {len(g)} > {IAP_NAME_MAX}")
    keys = [p["key"] for p in spec["subscription"]["products"]] if spec else list((iap.get("products") or {}))
    for key in keys:
        per = (iap.get("products") or {}).get(key) or {}
        for loc in store_locs:
            v = per.get(loc)
            if not v or _PLACEHOLDER.search(v.get("name", "") + v.get("description", "")):
                errs.append(f"iap: {key} {loc} display name/description missing")
                continue
            if len(v["name"]) > IAP_NAME_MAX:
                errs.append(f"iap: {key} {loc} display name {len(v['name'])} > {IAP_NAME_MAX}")
            if len(v["description"]) > IAP_DESC_MAX:
                errs.append(f"iap: {key} {loc} description {len(v['description'])} > {IAP_DESC_MAX}")
            if _UNLIMITED.search(v["name"] + v["description"]):
                errs.append(f"iap: {key} {loc}: no 'unlimited' claims (usage is capped)")
    return errs


def load_listing(app_dir: str | Path) -> dict[str, Any]:
    return _json.loads((Path(app_dir).expanduser() / LISTING_REL).read_text(encoding="utf-8"))


def listing_check(app_dir: str | Path) -> dict[str, Any]:
    """Validate store/metadata/listing.json against the app's spec (no writes)."""
    from . import spec as spec_mod
    app = Path(app_dir).expanduser()
    p = app / LISTING_REL
    if not p.exists():
        return {"ok": False, "error": f"{LISTING_REL} not found"}
    try:
        listing = load_listing(app)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"listing.json unreadable: {e}"}
    sp = spec_mod.load(app) if spec_mod.path(app).exists() else None
    errs = check_listing(listing, sp)
    sizes = {loc: {"name": len(e.get("name", "")), "subtitle": len(e.get("subtitle", "")),
                   "keywords": len(e.get("keywords", "")), "promo": len(e.get("promotional_text", "") or "")}
             for loc, e in (listing.get("locales") or {}).items()}
    return {"ok": not errs, "errors": errs, "sizes": sizes}


def render_listing(app_dir: str | Path, spec: dict[str, Any], supabase_url: str | None = None) -> dict[str, Any]:
    """Make listing.json follow the spec: one entry per spec.locales.store (new ones copy the en-US
    skeleton), IAP copy slots for every product, and the legal URLs (privacy_url, support_url and the
    {{TERMS_URL}}/{{PRIVACY_URL}} in descriptions) pointing at the Supabase legal function with the
    locale's ?lang=. Never overwrites written copy."""
    from . import legal as legal_mod
    app = Path(app_dir).expanduser()
    p = app / LISTING_REL
    listing = load_listing(app)
    url_base = supabase_url or cfg.app_outputs(app).get("supabase_url")
    locales = listing.setdefault("locales", {})
    skeleton = locales.get("en-US") or next(iter(locales.values()), {})
    added = []
    for loc in spec["locales"]["store"]:
        if loc not in locales:
            locales[loc] = {k: v for k, v in skeleton.items()}
            added.append(loc)
        if url_base:
            lang = legal_mod.app_language(loc, spec["locales"]["app"])
            e = locales[loc]
            e["privacy_url"] = legal_mod.url(url_base, "privacy", lang)
            if not e.get("support_url") or _PLACEHOLDER.search(e["support_url"]) or legal_mod.is_legal_url(e["support_url"]):
                e["support_url"] = legal_mod.url(url_base, "support", lang)
            if e.get("description"):
                e["description"] = (e["description"]
                                    .replace("{{TERMS_URL}}", legal_mod.url(url_base, "terms", lang))
                                    .replace("{{PRIVACY_URL}}", legal_mod.url(url_base, "privacy", lang)))
    iap = listing.setdefault("iap", {})
    group = iap.setdefault("group_name", {})
    prods = iap.setdefault("products", {})
    for loc in spec["locales"]["store"]:
        group.setdefault(loc, "{{GROUP_NAME}}")
    for pr in spec["subscription"]["products"]:
        per = prods.setdefault(pr["key"], {})
        for loc in spec["locales"]["store"]:
            per.setdefault(loc, {"name": "{{PRODUCT_NAME_MAX_30}}", "description": "{{PRODUCT_DESCRIPTION_MAX_45}}"})
    listing.setdefault("app", {})["bundle_id"] = spec["bundle_id"]
    p.write_text(_json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "added_locales": added, "legal_urls": bool(url_base)}
