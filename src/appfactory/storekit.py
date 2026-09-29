"""storekit_* — Configuration.storekit generated from app.spec.json, plus a parity check.

The StoreKit file is what the simulator sells and what the paywall's demo cards are checked
against, so it must equal the spec exactly (ASC == RevenueCat == Configuration.storekit, the
a hard-won lesson). `generate` writes it from the spec; `parity` reports every drift between a
StoreKit file on disk and the spec, so a hand edit can never silently diverge.

Layout (all from the spec): one subscription group, `level` = Apple's
groupNumber (1 = highest tier), free-trial intro offers on the products that declare one
(weekly + yearly by default), a trial-less `yearly.offer`, one `en_US` localization.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import spec as spec_mod

STOREKIT_REL = Path("Resources") / "Configuration.storekit"
GROUP_ID = "21000001"
LOCALE = "en_US"

# spec intro.type → StoreKit paymentMode
_PAYMENT_MODES = {"free": "free", "pay_as_you_go": "payAsYouGo", "pay_up_front": "payUpFront"}
_PERIOD_WORDS = {"D": "daily", "W": "weekly", "M": "monthly", "Y": "yearly"}

# Credits monetization only (legacy credits model): consumable top-up packs.
CREDIT_PACKS = [
    {"suffix": "credits.small", "usd": 4.99, "credits": 10, "name": "Credits Small"},
    {"suffix": "credits.medium", "usd": 9.99, "credits": 30, "name": "Credits Medium"},
    {"suffix": "credits.large", "usd": 17.99, "credits": 60, "name": "Credits Large"},
]


def _price(usd: float) -> str:
    return f"{Decimal(str(usd)):.2f}"


def _title(key: str) -> str:
    return key.replace("_", " ").title()


def generate(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the Configuration.storekit document for `spec`."""
    errs = spec_mod.validate(spec)
    if errs:
        raise ValueError("; ".join(errs))
    sub = spec["subscription"]
    display = spec.get("display_name") or spec["name"]
    subscriptions = []
    for i, p in enumerate(spec_mod.products(spec), start=1):
        unit = p["period"][-1]
        entry: dict[str, Any] = {
            "adHocOffers": [],
            "codeOffers": [],
            "displayPrice": _price(p["usd"]),
            "familyShareable": False,
            "groupNumber": int(p["level"]),
            "internalID": f"2110{i:04d}",
            "localizations": [{
                "description": f"{display} {sub['group']}, billed {_PERIOD_WORDS.get(unit, 'periodically')}"
                               + (" (one-time offer)" if p.get("offering") == "offer" else ""),
                "displayName": _title(p["key"]),
                "locale": LOCALE,
            }],
            "productID": p["id"],
            "promotionalOffers": [],
            "recurringSubscriptionPeriod": p["period"],
            "referenceName": _title(p["key"]),
            "subscriptionGroupID": GROUP_ID,
            "type": "RecurringSubscription",
        }
        intro = p.get("intro")
        if intro:
            entry["introductoryOffer"] = {
                "internalID": f"2110{i:04d}9",
                "numberOfPeriods": 1,
                "paymentMode": _PAYMENT_MODES.get(intro.get("type", "free"), "free"),
                "subscriptionPeriod": intro["duration"],
            }
        subscriptions.append(entry)

    consumables = []
    if spec.get("monetization") == "credits":
        for i, pack in enumerate(CREDIT_PACKS, start=1):
            consumables.append({
                "displayPrice": _price(pack["usd"]),
                "familyShareable": False,
                "internalID": f"2210{i:04d}",
                "localizations": [{"description": f"{pack['credits']} credits",
                                   "displayName": f"{pack['credits']} Credits", "locale": LOCALE}],
                "productID": f"{spec['bundle_id']}.{pack['suffix']}",
                "referenceName": pack["name"],
                "type": "Consumable",
            })

    return {
        "identifier": f"{spec_mod.slug(spec['name']).upper()}-STOREKIT",
        "nonRenewingSubscriptions": [],
        "products": consumables,
        "settings": {
            "_applicationInternalID": "0",
            "_developerTeamID": "",
            "_failTransactionsEnabled": False,
            "_lastSynchronizedDate": 0,
            "_locale": LOCALE,
            "_storefront": "USA",
            "_storeKitErrors": [],
        },
        "subscriptionGroups": [{
            "id": GROUP_ID,
            "localizations": [],
            "name": sub["group"],
            "subscriptions": subscriptions,
        }],
        "version": {"major": 4, "minor": 0},
    }


def dumps(doc: dict[str, Any]) -> str:
    # Xcode's own format: 2-space indent, " : " separators.
    return json.dumps(doc, indent=2, separators=(",", " : "), ensure_ascii=False) + "\n"


def write(spec: dict[str, Any], app_dir: str | Path) -> Path:
    path = Path(app_dir).expanduser() / STOREKIT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(generate(spec)), encoding="utf-8")
    return path


def _intro_tuple(intro: dict[str, Any] | None) -> tuple[str, str] | None:
    if not intro:
        return None
    mode = intro.get("paymentMode") or _PAYMENT_MODES.get(intro.get("type", ""), intro.get("type"))
    return (str(mode), str(intro.get("subscriptionPeriod") or intro.get("duration")))


def parity(spec: dict[str, Any], storekit_path: str | Path) -> list[str]:
    """Every mismatch between a Configuration.storekit on disk and the spec (empty = in parity)."""
    path = Path(storekit_path).expanduser()
    if not path.exists():
        return [f"storekit file not found: {path}"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"storekit file is not valid JSON: {e}"]

    out: list[str] = []
    groups = doc.get("subscriptionGroups") or []
    if len(groups) != 1:
        out.append(f"expected exactly 1 subscription group, found {len(groups)}")
    if groups and groups[0].get("name") != spec["subscription"]["group"]:
        out.append(f"group name {groups[0].get('name')!r} != spec {spec['subscription']['group']!r}")
    locale = (doc.get("settings") or {}).get("_locale")
    if locale != LOCALE:
        out.append(f"storekit locale {locale!r} != {LOCALE!r}")

    on_disk = {s.get("productID"): s for g in groups for s in g.get("subscriptions", [])}
    wanted = {p["id"]: p for p in spec_mod.products(spec)}
    for pid in sorted(set(on_disk) - set(wanted)):
        out.append(f"{pid}: in storekit but not in spec")
    for pid, p in wanted.items():
        s = on_disk.get(pid)
        if s is None:
            out.append(f"{pid}: missing from storekit")
            continue
        if Decimal(str(s.get("displayPrice", "0"))) != Decimal(str(p["usd"])):
            out.append(f"{pid}: price {s.get('displayPrice')} != spec {_price(p['usd'])}")
        if s.get("recurringSubscriptionPeriod") != p["period"]:
            out.append(f"{pid}: period {s.get('recurringSubscriptionPeriod')} != spec {p['period']}")
        if s.get("groupNumber") != p["level"]:
            out.append(f"{pid}: level {s.get('groupNumber')} != spec {p['level']}")
        have = _intro_tuple(s.get("introductoryOffer"))
        want = _intro_tuple(p.get("intro"))
        if have != want:
            out.append(f"{pid}: intro offer {have} != spec {want}")
        locs = [loc.get("locale") for loc in s.get("localizations", [])]
        if LOCALE not in locs:
            out.append(f"{pid}: no {LOCALE} localization")

    consumables = {c.get("productID") for c in doc.get("products", []) if c.get("type") == "Consumable"}
    if spec.get("monetization") == "credits":
        need = {f"{spec['bundle_id']}.{pack['suffix']}" for pack in CREDIT_PACKS}
        for pid in sorted(need - consumables):
            out.append(f"{pid}: credit pack missing from storekit")
    elif consumables:
        out.append(f"subscription-only app sells consumables: {sorted(consumables)}")
    return out


def generate_for_app(app_dir: str | Path) -> dict[str, Any]:
    """MCP entry: read <app_dir>/app.spec.json, write Resources/Configuration.storekit."""
    try:
        s = spec_mod.load(app_dir)
        path = write(s, app_dir)
    except (OSError, ValueError, KeyError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "storekit": str(path), "products": [p["id"] for p in spec_mod.products(s)]}


def parity_for_app(app_dir: str | Path, storekit_path: str | None = None) -> dict[str, Any]:
    """MCP entry: compare the app's StoreKit file with its spec."""
    try:
        s = spec_mod.load(app_dir)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"cannot read spec: {e}"}
    path = Path(storekit_path).expanduser() if storekit_path else Path(app_dir).expanduser() / STOREKIT_REL
    mismatches = parity(s, path)
    return {"ok": not mismatches, "storekit": str(path), "mismatches": mismatches}
