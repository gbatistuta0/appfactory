"""AppFactory config — load/write ~/.appfactory/config.toml.

Secrets (ASC .p8 path, Supabase token, AI keys) live here; never committed
to git. The file is written with 0600 permissions. AI keys go only to the
server-side (ai-proxy secrets); they are never injected into the app binary.
"""

from __future__ import annotations

import datetime as _dt
import os
import re as _re
import tomllib
from pathlib import Path
from typing import Any, Iterable

CONFIG_DIR = Path(os.path.expanduser("~/.appfactory"))
CONFIG_PATH = CONFIG_DIR / "config.toml"

# App Store Connect metadata locale codes (with Apple's CORRECT codes).
# Top-11 highest-value markets (was 48). GOTCHA: region-SUFFIXED codes where Apple requires them
# (es-ES, de-DE, fr-FR, pt-BR, zh-Hans); the iOS in-app String Catalog uses the BARE code → mapped via IN_APP_TO_ASC.
# To ship more languages, override `locales = [...]` in ~/.appfactory/config.toml (load_config applies it).
APP_STORE_LOCALES = [
    "en-US", "zh-Hans", "ja", "ko", "es-ES", "de-DE", "fr-FR", "pt-BR", "ru", "tr", "vi",
]

# iOS in-app (String Catalog) Apple-bare code → ASC App Store code mapping (only where they differ).
# The Apple in-app language wants the BARE code (de, fr, es, ar, nl, nb, en) — a region is used only
# when meaningful (zh-Hans/Hant, pt-BR/PT, es-MX, fr-CA, en-GB/AU/CA). de-DE/ar-SA → in-app MUST be de/ar,
# otherwise a device language of "de" falls back to English (and de-AT/de-CH users are not covered either).
IN_APP_TO_ASC = {"bn": "bn-BD", "gu": "gu-IN", "ml": "ml-IN", "mr": "mr-IN",
                 "or": "or-IN", "pa": "pa-IN", "sl": "sl-SI", "ta": "ta-IN", "te": "te-IN",
                 "de": "de-DE", "ar": "ar-SA", "es": "es-ES", "fr": "fr-FR", "nl": "nl-NL",
                 "nb": "no", "en": "en-US"}

# In-app (String Catalog) languages — BARE iOS codes (ta, bn, sl...) + fil.
# iOS uses bare codes; App Store/IAP are region-suffixed (mapped via IN_APP_TO_ASC).
_ASC_TO_IN_APP = {v: k for k, v in IN_APP_TO_ASC.items()}
IN_APP_LOCALES = [_ASC_TO_IN_APP.get(l, l) for l in APP_STORE_LOCALES] + ["fil"]

# IAP/subscription localization also supports ALL 48 languages with the CORRECT codes (it was a
# bare-code problem, not a platform limitation). IAP locale = App Store locale.
IAP_LOCALES = APP_STORE_LOCALES

DEFAULT_LOCALES = APP_STORE_LOCALES

# Known keys and their short descriptions (for config_doctor).
KNOWN_KEYS: dict[str, str] = {
    "asc_key_id": "App Store Connect API Key ID (from the .p8 file name)",
    "asc_issuer_id": "App Store Connect Issuer ID",
    "asc_key_filepath": "Full path to the AuthKey_*.p8 file",
    "team_id": "Apple Developer Team ID",
    "apple_id": "Apple ID email (ASC app creation via fastlane produce)",
    "apple_app_specific_password": "Apple app-specific password (fastlane produce fallback for app creation)",
    "apple_session": "fastlane spaceauth FASTLANE_SESSION (app creation, 2FA, ~30 days)",
    "supabase_access_token": "Supabase account access token",
    "fal_key": "fal.ai (Flux) API key — server-side (ai-proxy secret)",
    "replicate_token": "Replicate API token — server-side (ai-proxy secret)",
    "openai_api_key": "OpenAI API key (optional) — server-side",
    "anthropic_api_key": "Anthropic API key (optional) — server-side",
    "copyright": "ASC submission copyright text (e.g. '© 2026 Your Name')",
    "support_email": "Public support/contact email (legal pages, App Review contact, listing)",
    "legal_controller": "Legal name of the developer / data controller in the privacy policy and terms",
    "rc_secret_key": "RevenueCat v2 secret key (GLOBAL, all apps) — server-side only, never in an app",
    "review_contact_phone": "App Review contact phone (store_setup reads it; never logged or committed)",
    "asc_finance_key_id": "ASC API key id with Finance access (sales reports / SBP proof; issuer shared)",
    "asc_finance_key_filepath": "Full path to the Finance-capable AuthKey_*.p8 (e.g. ~/.appfactory/AuthKey_<id>.p8)",
    "asc_vendor_number": "App Store Connect vendor number (Payments and Financial Reports; sales reports)",
    "github_user": "GitHub account that owns app repos (optional; empty = the active `gh` account)",
    "signing_identity": "Name on the Apple Distribution certificate (optional; empty = auto-detect)",
}

# Keys that used to be global but belong to ONE app. Per-app ids live in
# <app>/.appfactory/outputs.json (app_outputs); only rc_secret_key stays global.
DEPRECATED_GLOBAL_KEYS: dict[str, str] = {
    "rc_project_id": "per-app: .appfactory/outputs.json rc_project_id (store_setup writes it)",
    "rc_app_id": "per-app: .appfactory/outputs.json rc_app_id (store_setup writes it)",
    "rc_public_key": "per-app: .appfactory/outputs.json rc_public_key (goes to that app's AppConfig)",
}

SECRET_KEYS = {
    "apple_app_specific_password",
    "apple_session",
    "supabase_access_token",
    "fal_key",
    "replicate_token",
    "openai_api_key",
    "anthropic_api_key",
    "rc_secret_key",
    "review_contact_phone",
}

# "locales" is not in KNOWN_KEYS (it's a list, which doesn't fit config_doctor's
# str present/missing model) — but writing `locales = ["en-US", "fr-FR", ...]` to
# config.toml overrides DEFAULT_LOCALES (48 languages); load_config() already applies this.


def load_config() -> dict[str, Any]:
    """Load config; return empty if absent. Missing locales fall back to the default."""
    cfg: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    cfg.setdefault("locales", DEFAULT_LOCALES)
    return cfg


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        items = ", ".join(_toml_value(v) for v in value)
        return f"[{items}]"
    # string — escaped
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def save_config(cfg: dict[str, Any]) -> Path:
    """Write config with 0600 permissions. Flat TOML; values are str/bool/int/list[str]."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# AppFactory config — not committed to git, secrets live here (chmod 600)\n"]
    for key in sorted(cfg.keys()):
        lines.append(f"{key} = {_toml_value(cfg[key])}")
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(CONFIG_PATH, 0o600)
    return CONFIG_PATH


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Update the existing config with the given keys, save, and return the new state."""
    cfg = load_config()
    # skip empty/None values (to avoid accidentally clearing entries)
    for k, v in updates.items():
        if v is None or v == "":
            continue
        cfg[k] = v
    save_config(cfg)
    return cfg


def resolve_asc_key_filepath(cfg: dict[str, Any]) -> Path | None:
    """Resolve the ASC .p8 path: explicit path > derive from key_id > search on Desktop."""
    explicit = cfg.get("asc_key_filepath")
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.exists():
            return p
    key_id = cfg.get("asc_key_id")
    if key_id:
        for base in (CONFIG_DIR, Path(os.path.expanduser("~/Desktop"))):
            cand = base / f"AuthKey_{key_id}.p8"
            if cand.exists():
                return cand
    return None


def resolve_finance_key_filepath(cfg: dict[str, Any]) -> Path | None:
    """The Finance-capable ASC .p8 (sales reports): explicit path > AuthKey_<finance key id>.p8 in ~/.appfactory."""
    explicit = cfg.get("asc_finance_key_filepath")
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.exists():
            return p
    key_id = cfg.get("asc_finance_key_id")
    if key_id:
        cand = CONFIG_DIR / f"AuthKey_{key_id}.p8"
        if cand.exists():
            return cand
    return None


def doctor_notes(cfg: dict[str, Any]) -> list[str]:
    """Advice for config_doctor: deprecated global keys (values never echoed)."""
    notes = []
    for key, where in DEPRECATED_GLOBAL_KEYS.items():
        if cfg.get(key):
            notes.append(f"{key} is set globally but belongs to one app → {where}; "
                         "tools ignore it for other apps")
    if cfg.get("asc_finance_key_id") and not resolve_finance_key_filepath(cfg):
        notes.append("asc_finance_key_id is set but its .p8 was not found (set asc_finance_key_filepath)")
    return notes


# ---- per-app outputs (live ids the tools create; the desired state stays in app.spec.json) ----
OUTPUTS_REL = ".appfactory/outputs.json"


def app_outputs(app_dir: str | Path) -> dict[str, Any]:
    """<app>/.appfactory/outputs.json: supabase_ref/url, asc_app_id, rc_project_id, rc_app_id,
    rc_public_key, rc_apple_notification_url, legal_base, applied_migrations… (no secrets)."""
    import json
    p = Path(app_dir).expanduser() / OUTPUTS_REL
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def update_app_outputs(app_dir: str | Path, **values: Any) -> dict[str, Any]:
    """Merge values (None skipped) into outputs.json and return the new state."""
    import json
    p = Path(app_dir).expanduser() / OUTPUTS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = app_outputs(app_dir)
    cur.update({k: v for k, v in values.items() if v is not None})
    p.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cur


_SESSION_FILE = CONFIG_DIR / "fastlane_session.yml"
_CREATED_RE = _re.compile(
    r'created_at:\s*(?:&\d+\s*)?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')
_MAXAGE_RE = _re.compile(r'max_age:\s*(\d+)')


def _parse_dt(s: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(s.replace(" ", "T")).replace(tzinfo=_dt.timezone.utc)


def session_status(blob: str | None = None) -> dict[str, Any]:
    """fastlane FASTLANE_SESSION freshness. If no blob is given, read fastlane_session.yml
    (falling back to config apple_session). The EARLIEST expiry among long-lived
    (max_age>=86400) cookies is the basis; stale=True when <24 hours remain."""
    if blob is None:
        if _SESSION_FILE.exists():
            blob = _SESSION_FILE.read_text(encoding="utf-8")
        else:
            blob = str(load_config().get("apple_session", "") or "")
    if not blob.strip():
        return {"ok": True, "present": False, "stale": True, "hours_left": 0.0,
                "valid_until": None, "reason": "no fastlane session (fastlane spaceauth required)"}

    expiries: list[_dt.datetime] = []
    for block in blob.split("HTTP::Cookie"):
        ma = _MAXAGE_RE.search(block)
        ca = _CREATED_RE.search(block)
        if not ma or not ca:
            continue
        max_age = int(ma.group(1))
        if max_age < 86400:  # not a short-lived session cookie
            continue
        try:
            expiries.append(_parse_dt(ca.group(1)) + _dt.timedelta(seconds=max_age))
        except ValueError:
            continue
    if not expiries:
        return {"ok": True, "present": True, "stale": True, "hours_left": 0.0,
                "valid_until": None, "reason": "no long-lived auth cookie found"}

    valid_until = min(expiries)
    now = _dt.datetime.now(_dt.timezone.utc)
    hours_left = (valid_until - now).total_seconds() / 3600.0
    stale = hours_left < 24.0
    return {"ok": True, "present": True, "stale": stale, "hours_left": round(hours_left, 1),
            "valid_until": valid_until.isoformat(),
            "reason": "fresh" if not stale else "stale/≤24h — fastlane spaceauth -u <apple_id>"}


# ---- optional services (the setup CLI lets users choose; tools can gate on enabled_services) ----
# keys: config.toml keys the service needs (optional ones are listed in "optional_keys").
# binaries: local tools the service shells out to (name -> Homebrew install hint).
SERVICES: dict[str, dict[str, Any]] = {
    "research": {"description": "Idea harvesting + ASO research (App Store search, no account)",
                 "keys": [], "binaries": {}, "always_on": True},
    "apple": {"description": "App Store Connect: create apps, IAPs, metadata, TestFlight, submission",
              "keys": ["asc_key_id", "asc_issuer_id", "asc_key_filepath", "team_id"],
              "binaries": {"asc": "brew install asc"}},
    "xcode": {"description": "Local builds, simulator, archives",
              "keys": [], "binaries": {"xcodebuild": "install Xcode from the Mac App Store",
                                       "xcodegen": "brew install xcodegen"}},
    "supabase": {"description": "Supabase backend (database, edge functions, credits)",
                 "keys": ["supabase_access_token"],
                 "binaries": {"supabase": "brew install supabase/tap/supabase", "deno": "brew install deno"}},
    "revenuecat": {"description": "RevenueCat subscriptions and entitlements",
                   "keys": ["rc_secret_key"], "binaries": {}},
    "ai": {"description": "AI features via a server-side proxy (keys never ship in the app)",
           "keys": [], "optional_keys": ["fal_key", "openai_api_key", "anthropic_api_key"], "binaries": {}},
    "firebase": {"description": "Firebase Analytics setup",
                 "keys": [], "binaries": {"firebase": "brew install firebase-cli"}},
    "github": {"description": "GitHub repos and issues per app",
               "keys": [], "optional_keys": ["github_user"], "binaries": {"gh": "brew install gh"}},
    "design": {"description": "Screen design through the claude-design MCP",
               "keys": [], "binaries": {}},
    "maestro": {"description": "End-to-end UI tests on the simulator",
                "keys": [], "binaries": {"maestro": "brew install mobile-dev-inc/tap/maestro"}},
    "lottie": {"description": "Lottie animations (fetch + recolor)",
               "keys": [], "binaries": {"node": "brew install node"}},
}


def enabled_services(cfg: dict[str, Any] | None = None) -> set[str]:
    """Services the user turned on. No `services` key → all services (existing installs unaffected)."""
    if cfg is None:
        cfg = load_config()
    chosen = cfg.get("services")
    if chosen is None:
        return set(SERVICES)
    always = {n for n, s in SERVICES.items() if s.get("always_on")}
    return {s for s in chosen if s in SERVICES} | always


def first_disabled(needed: Iterable[str], cfg: dict[str, Any] | None = None) -> str | None:
    """The first service in `needed` the user turned off, or None when all of them are on."""
    needed = list(needed)
    if not needed:
        return None
    on = enabled_services(cfg)
    return next((s for s in needed if s not in on), None)


def disabled_message(service: str) -> str:
    return (f"the '{service}' service is disabled — enable it with `appfactory services enable {service}` "
            "or `appfactory setup`")


# ---- secret scrubbing (tool results never carry secret values) ----
def secret_values(cfg: dict[str, Any] | None = None) -> list[str]:
    """Known secret values: config SECRET_KEYS + saved Supabase service_role keys (longest first)."""
    import json
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    vals = {str(cfg[k]) for k in SECRET_KEYS if cfg.get(k)}
    sdir = CONFIG_DIR / "supabase"
    if sdir.is_dir():
        for f in sdir.glob("*.json"):
            try:
                v = json.loads(f.read_text(encoding="utf-8")).get("service_role_key")
            except Exception:  # noqa: BLE001
                continue
            if v:
                vals.add(str(v))
    return sorted((v for v in vals if len(v) >= 6), key=len, reverse=True)


def scrub(obj: Any, values: list[str] | None = None) -> Any:
    """Replace every known secret value inside strings of obj (dict/list/str, recursively) with ***."""
    if values is None:
        values = secret_values()
    if not values:
        return obj
    if isinstance(obj, str):
        for v in values:
            if v in obj:
                obj = obj.replace(v, "***")
        return obj
    if isinstance(obj, dict):
        new = {k: scrub(v, values) for k, v in obj.items()}
        return obj if all(new[k] is obj[k] for k in obj) else new
    if isinstance(obj, (list, tuple)):
        items = [scrub(v, values) for v in obj]
        return obj if all(a is b for a, b in zip(items, obj)) else type(obj)(items)
    return obj
