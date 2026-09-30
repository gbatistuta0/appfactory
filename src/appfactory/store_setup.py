"""store_setup — idempotent App Store Connect + RevenueCat setup from app.spec.json + listing.json.

Ported from a live-proven store setup script, made spec-driven:
products, periods, group levels, USD prices, intro offers, price overrides, grace period, locales and
placements come from app.spec.json; store copy (names, subtitles, keywords, descriptions, IAP display
copy) from store/metadata/listing.json; legal URLs from the app's Supabase `legal` function.

Modes (never submits anything for review):
  plan   offline: every operation against an empty in-memory store. No network, no credentials.
  check  live reads + simulated writes: exactly what apply would change (and CONFLICTs).
  apply  live writes; requires confirm == bundle id.

Every step reads first and writes only what is missing or different, so a second run is a no-op.
State that contradicts the spec (wrong period, an intro offer on an offer product, a package holding
another product, a different SKU) is a CONFLICT and never deleted/overwritten.

Gotchas baked in (store/CHECKLIST.md): availability before prices (else 409); equalization = one
POST per territory from the USA price point's equalizations; intro offers are per territory (no
territory → ENTITY_ERROR.RELATIONSHIP.REQUIRED) and exactly as the spec says (offer products: none);
product ids are never reusable; GETs are retried on 5xx, writes never retried in the same run; the
review phone comes only from config `review_contact_phone` and is never printed.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from . import config as cfg
from . import legal as legal_mod
from . import metadata as meta
from . import spec as spec_mod

EDITABLE_STATES = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED"}
# Generative-AI apps need a licence on the China storefront.
EXCLUDED_TERRITORIES = ["CHN"]
PERIODS = {"P1W": "ONE_WEEK", "P1M": "ONE_MONTH", "P2M": "TWO_MONTHS", "P3M": "THREE_MONTHS",
           "P6M": "SIX_MONTHS", "P1Y": "ONE_YEAR"}
INTRO_DURATIONS = {"P3D": "THREE_DAYS", "P1W": "ONE_WEEK", "P2W": "TWO_WEEKS", "P1M": "ONE_MONTH",
                   "P2M": "TWO_MONTHS", "P3M": "THREE_MONTHS", "P6M": "SIX_MONTHS", "P1Y": "ONE_YEAR"}
# Day-based spellings of the same lengths (spec_mod.INTRO_DURATION_ALIASES) are normalised first, so a
# spec written with P7D still plans as ONE_WEEK.
# Offline fallback for currency → ASC territories (live runs read each territory's currency).
CURRENCY_TERRITORIES = {
    "EUR": ["AUT", "BEL", "BGR", "BIH", "CYP", "DEU", "ESP", "EST", "FIN", "FRA", "GRC", "HRV", "IRL", "ITA",
            "LTU", "LUX", "LVA", "MLT", "MNE", "NLD", "PRT", "SRB", "SVK", "SVN", "XKS"],
    "BRL": ["BRA"], "TRY": ["TUR"], "GBP": ["GBR"], "MXN": ["MEX"], "JPY": ["JPN"], "USD": ["USA"],
}
AGE_NONE = ["alcoholTobaccoOrDrugUseOrReferences", "contests", "gamblingSimulated", "gunsOrOtherWeapons",
            "horrorOrFearThemes", "matureOrSuggestiveThemes", "medicalOrTreatmentInformation",
            "profanityOrCrudeHumor", "sexualContentGraphicAndNudity", "sexualContentOrNudity",
            "violenceCartoonOrFantasy", "violenceRealistic", "violenceRealisticProlongedGraphicOrSadistic"]
AGE_FALSE = ["advertising", "ageAssurance", "gambling", "lootBox", "messagingAndChat", "parentalControls",
             "unrestrictedWebAccess", "userGeneratedContent"]
RC_S2S_URL_RE = re.compile(
    r"^https://api\.revenuecat\.com/v1/incoming-webhooks/apple-server-to-server-notification/[A-Za-z0-9]{32}$")
RC_S2S_MANUAL = ("RevenueCat dashboard → app → Apple Server-to-Server notification URL → paste into store_setup "
                 "(rc_apple_notification_url=…)")
MARKER_REL = Path(".appfactory") / "verify" / "store_setup.json"


class ApiError(Exception):
    pass


class Report:
    """One line per decision; the counts decide ok. Kinds: OK CREATE UPDATE CONFLICT ERROR MANUAL."""

    def __init__(self, redact: tuple[str, ...] = ()):
        self.lines: list[tuple[str, str]] = []
        self.mcp: list[dict[str, Any]] = []
        self._redact = tuple(r for r in redact if r)

    def _clean(self, msg: str) -> str:
        for r in self._redact:
            msg = msg.replace(r, "<redacted>")
            digits = re.sub(r"\D", "", r)
            if len(digits) >= 6:
                msg = msg.replace(digits, "<redacted>")
        return msg

    def add(self, kind: str, msg: str) -> None:
        self.lines.append((kind, self._clean(msg)))

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.lines if k == kind)

    @property
    def writes(self) -> int:
        return self.count("CREATE") + self.count("UPDATE")

    def summary(self) -> dict[str, int]:
        return {"changes": self.writes, "ok": self.count("OK"), "manual": self.count("MANUAL"), "extra": self.count("EXTRA"),
                "conflict": self.count("CONFLICT"), "error": self.count("ERROR")}


# ---------------------------------------------------------------------------------------------
# Desired state (from the spec + listing)
# ---------------------------------------------------------------------------------------------

def _money(x: Any) -> str:
    return f"{Decimal(str(x)):.2f}"


def _same_price(a: Any, b: Any) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, TypeError):
        return False


def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    return (parts[0], " ".join(parts[1:]) or parts[0]) if parts else ("", "")


def desired_state(spec: dict[str, Any], listing: dict[str, Any], config: dict[str, Any] | None = None,
                  review_notes: str | None = None, today: _dt.date | None = None) -> dict[str, Any]:
    c = config if config is not None else {}
    name = spec.get("display_name") or spec["name"]
    store_locs = spec["locales"]["store"]
    iap = listing.get("iap") or {}
    sub = spec["subscription"]
    subs = []
    for p in spec_mod.products(spec):
        intro = p.get("intro")
        subs.append({
            "key": p["key"], "product_id": p["id"],
            "reference_name": f"{name} {p['key'].replace('_', ' ').title()}",
            "period": PERIODS.get(p["period"], p["period"]),
            "group_level": p["level"], "usd_price": _money(p["usd"]),
            "intro_offer": None if not intro else {
                "mode": "FREE_TRIAL" if intro.get("type") == "free" else str(intro.get("type")).upper(),
                "duration": INTRO_DURATIONS.get(spec_mod.intro_duration(intro["duration"]),
                                                intro["duration"]), "periods": 1},
            "offer_product": p.get("offering") == "offer",
            "localizations": {loc: ((iap.get("products") or {}).get(p["key"]) or {}).get(loc) for loc in store_locs},
            "overrides": {cur: _money(t[p["key"]]) for cur, t in (sub.get("price_overrides") or {}).items() if p["key"] in t},
        })
    gp = sub.get("grace_period") or {}
    first, last = split_name(c.get("legal_controller") or "")
    offerings: dict[str, dict[str, Any]] = {}
    for p in spec_mod.products(spec):
        o = offerings.setdefault(p["offering"], {
            "lookup_key": p["offering"],
            "display_name": "Hard paywall" if p["offering"] == "default" else f"{p['offering'].title()} paywall",
            "is_current": p["offering"] == "default", "packages": []})
        o["packages"].append({"lookup_key": p["package"], "display_name": p["key"].replace("_", " ").title(),
                              "position": len(o["packages"]) + 1, "product_id": p["id"]})
    offer_placements = set(spec.get("offer_placements") or [])
    st = spec_mod.store(spec)
    year = (today or _dt.date.today()).year
    return {
        "bundle_id": spec["bundle_id"], "sku": spec["sku"], "app_name": name,
        "excluded_territories": list(st["excluded_territories"]),
        "app_level": {
            "primary_category": st["primary_category"], "secondary_category": st["secondary_category"],
            "content_rights": st["content_rights"],
            "copyright": st["copyright"] or f"© {year} {name}",
            "free": True,
        },
        "review_notes": review_notes,
        "capabilities": capabilities(spec),
        "store_locales": store_locs,
        "group": {"reference_name": f"{name} {sub.get('group', 'Premium')}",
                  "localizations": {loc: {"name": (iap.get("group_name") or {}).get(loc)} for loc in store_locs}},
        "subscriptions": subs,
        "grace_period": None if not gp.get("enabled") else {
            "optIn": True, "sandboxOptIn": bool(gp.get("sandbox", True)),
            "renewalType": gp.get("renewals", "ALL_RENEWALS"), "duration": gp.get("duration", "SIXTEEN_DAYS")},
        "age_rating": {**{k: "NONE" for k in AGE_NONE}, **{k: False for k in AGE_FALSE},
                       "healthOrWellnessTopics": bool(spec.get("consent", {}).get("health"))},
        "review_contact": {**{k: v for k, v in (("contactFirstName", first), ("contactLastName", last),
                                                ("contactEmail", c.get("support_email"))) if v},
                           # No login in these apps (anonymous account): a demo-account flag left on
                           # blocks the submission.
                           **({"demoAccountRequired": False} if c.get("support_email") else {})},
        "listing": {loc: (listing.get("locales") or {}).get(loc) or {} for loc in store_locs},
        "revenuecat": {
            "project_name": name,
            "entitlement": {"lookup_key": sub.get("entitlement", "premium"), "display_name": f"{name} Premium"},
            "offerings": list(offerings.values()),
            "placements": {pl: ("offer" if pl in offer_placements else "default") for pl in spec.get("placements", [])},
        },
    }


_PH = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}")


def validate_desired(d: dict[str, Any]) -> list[str]:
    """Static checks before anything touches a live store (plan reports them, check/apply refuse)."""
    errs = []
    for s in d["subscriptions"]:
        pid = s["product_id"]
        if s["period"] not in PERIODS.values():
            errs.append(f"{pid}: unsupported period {s['period']}")
        io = s["intro_offer"]
        if s["offer_product"] and io:
            errs.append(f"{pid}: offer products never carry an intro offer")
        if io and (io["mode"] != "FREE_TRIAL" or io["duration"] not in INTRO_DURATIONS.values()):
            errs.append(f"{pid}: only free-trial intro offers are supported ({io['mode']} {io['duration']})")
        for loc, v in s["localizations"].items():
            if not v or _PH.search((v.get("name") or "") + (v.get("description") or "")):
                errs.append(f"{pid} {loc}: IAP display copy missing in listing.json iap.products")
            elif len(v["name"]) > 30 or len(v["description"]) > 45:
                errs.append(f"{pid} {loc}: IAP display name > 30 or description > 45")
    for loc, v in d["group"]["localizations"].items():
        if not v.get("name") or _PH.search(v["name"]):
            errs.append(f"group name {loc} missing in listing.json iap.group_name")
    for loc, e in d["listing"].items():
        for f in ("name", "subtitle", "keywords", "description", "privacy_url", "support_url"):
            if not e.get(f) or _PH.search(e.get(f) or ""):
                errs.append(f"listing {loc}: {f} missing or unfilled")
    return errs


# ---------------------------------------------------------------------------------------------
# App Store Connect
# ---------------------------------------------------------------------------------------------

def asc_all(api, path: str, params: dict | None = None) -> tuple[list, list]:
    items: list = []
    included: list = []
    page = api.get(path, params)
    while page:
        data = page.get("data")
        items += data if isinstance(data, list) else ([data] if data else [])
        included += page.get("included") or []
        nxt = (page.get("links") or {}).get("next")
        page = api.get(nxt) if nxt else None
    return items, included


def rel_id(item: dict, name: str) -> str | None:
    data = ((item.get("relationships") or {}).get(name) or {}).get("data")
    return data.get("id") if isinstance(data, dict) else None


def territory_of(item: dict) -> str | None:
    """Territory of a price/price point: the relationship, else decoded from the base64 JSON id."""
    tid = rel_id(item, "territory")
    if tid:
        return tid
    import base64
    raw = item.get("id", "")
    try:
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("t")
    except Exception:  # noqa: BLE001
        return None


def asc_body(kind: str, attributes: dict | None = None, relationships: dict | None = None,
             id_: str | None = None) -> dict:
    data: dict[str, Any] = {"type": kind}
    if id_:
        data["id"] = id_
    if attributes is not None:
        data["attributes"] = attributes
    if relationships:
        data["relationships"] = {k: {"data": v} for k, v in relationships.items()}
    return {"data": data}


def ref(kind: str, id_: str) -> dict:
    return {"type": kind, "id": id_}


def guarded(rep: Report, label: str, fn: Callable[[], Any]) -> bool:
    try:
        fn()
        return True
    except ApiError as e:
        rep.add("ERROR", f"{label}: {e}")
        return False


def sync_localizations(api, rep: Report, label: str, existing: list, desired: dict[str, dict],
                       kind: str, parent_rel: str, parent: dict) -> None:
    by_locale = {e["attributes"]["locale"]: e for e in existing}
    for loc, fields in desired.items():
        fields = {k: v for k, v in (fields or {}).items() if v}
        if not fields:
            continue
        cur = by_locale.get(loc)
        if cur is None:
            if guarded(rep, f"{label} {loc}", lambda: api.post(
                    f"/v1/{kind}", asc_body(kind, {"locale": loc, **fields}, {parent_rel: parent}))):
                rep.add("CREATE", f"{label} {loc}")
            continue
        diff = {k: v for k, v in fields.items() if (cur["attributes"].get(k) or "") != v}
        if diff:
            if guarded(rep, f"{label} {loc}", lambda: api.patch(
                    f"/v1/{kind}/{cur['id']}", asc_body(kind, diff, id_=cur["id"]))):
                rep.add("UPDATE", f"{label} {loc}: {', '.join(sorted(diff))}")
        else:
            rep.add("OK", f"{label} {loc}")


def sync_prices(api, rep: Report, sub: dict, sub_id: str, excluded: set[str]) -> None:
    """USA base price + Apple's equalized price in EVERY other territory, the excluded ones included.
    Availability keeps them unsold; but ASC refuses the first subscription submission with
    409 IAP_SUBMISSION_NOT_ALLOWED_MISSING_PRICING_DATA for any unpriced territory, even one the app is
    not available in (e.g. CHN)."""
    pid, usd = sub["product_id"], sub["usd_price"]
    prices, _ = asc_all(api, f"/v1/subscriptions/{sub_id}/prices", {"include": "territory", "limit": 200})
    priced = {territory_of(p) for p in prices} - {None}
    points, _ = asc_all(api, f"/v1/subscriptions/{sub_id}/pricePoints", {"filter[territory]": "USA", "limit": 200})
    base = next((p for p in points if _same_price(p["attributes"].get("customerPrice"), usd)), None)
    if base is None:
        if sub_id.startswith("dry-"):
            rep.add("CREATE", f"price {pid}: USD {usd} in USA + equalized territories (ids resolve at apply)")
            return
        rep.add("CONFLICT", f"price {pid}: no USA price point for {usd}")
        return
    equal, _ = asc_all(api, f"/v1/subscriptionPricePoints/{base['id']}/equalizations", {"include": "territory", "limit": 200})
    targets = [("USA", base["id"])] + [(territory_of(p), p["id"]) for p in equal]
    if any(t is None for t, _ in targets):
        rep.add("CONFLICT", f"price {pid}: could not resolve territories of equalized price points")
        return
    todo = [(t, pp) for t, pp in targets if t not in priced]
    failed = []
    for terr, pp in todo:
        try:
            api.post("/v1/subscriptionPrices", asc_body(
                "subscriptionPrices", {"preserveCurrentPrice": False},
                {"subscription": ref("subscriptions", sub_id), "subscriptionPricePoint": ref("subscriptionPricePoints", pp)}))
        except ApiError as e:
            failed.append(f"{terr}: {str(e)[-160:]}")
    if failed:
        rep.add("ERROR", f"price {pid}: {len(failed)} territories failed, first: {failed[0]}")
    note = f" (incl. unsold {sorted(excluded)})" if excluded else ""
    if len(todo) > len(failed):
        rep.add("CREATE", f"price {pid}: USD {usd} base, {len(todo) - len(failed)} territories{note}")
    elif not todo:
        rep.add("OK", f"price {pid}: {len(priced)} territories priced{note}")


def override_targets(sub: dict, currency_of: dict[str, str], sellable: list[str]) -> dict[str, str]:
    """spec.price_overrides {currency: price} → {territory: price} for sellable territories."""
    out: dict[str, str] = {}
    for cur, price in sub["overrides"].items():
        terrs = [t for t, c in currency_of.items() if c == cur] or CURRENCY_TERRITORIES.get(cur, [])
        for t in terrs:
            if t in sellable:
                out[t] = price
    return out


def sync_price_overrides(api, rep: Report, sub: dict, sub_id: str, overrides: dict[str, str]) -> None:
    """Local prices replacing the equalized price. The current price of a territory is its price
    record with the latest start date."""
    if not overrides:
        return
    if sub_id.startswith("dry-"):
        rep.add("CREATE", f"price override {sub['product_id']}: {len(overrides)} territories "
                          f"({', '.join(sorted(set(overrides.values())))})")
        return
    prices, included = asc_all(api, f"/v1/subscriptions/{sub_id}/prices",
                               {"include": "subscriptionPricePoint,territory", "limit": 200})
    customer = {i["id"]: (i.get("attributes") or {}).get("customerPrice") for i in included
                if i.get("type") == "subscriptionPricePoints"}
    current: dict[str | None, tuple[str | None, str | None]] = {}
    for p in sorted(prices, key=lambda x: (x.get("attributes") or {}).get("startDate") or ""):
        pp = rel_id(p, "subscriptionPricePoint")
        price = customer.get(pp) or (pp.split("|")[3] if pp and pp.count("|") == 3 else None)
        current[territory_of(p)] = (pp, price)
    todo = {t: p for t, p in overrides.items() if not _same_price(current.get(t, (None, None))[1], p)}
    ok_n = len(overrides) - len(todo)
    if ok_n:
        rep.add("OK", f"price override {sub['product_id']}: {ok_n} territories already at the local price")
    if not todo:
        return
    try:
        points, _ = asc_all(api, f"/v1/subscriptions/{sub_id}/pricePoints",
                            {"filter[territory]": ",".join(sorted(todo)), "include": "territory", "limit": 200})
    except ApiError as e:
        rep.add("ERROR", f"price override {sub['product_id']}: reading price points failed: {e}")
        return
    point_ids: dict[tuple[str | None, str], str] = {}
    for x in points:
        point_ids.setdefault((territory_of(x), _money(x["attributes"].get("customerPrice"))), x["id"])
    changed = 0
    for terr, target in sorted(todo.items()):
        pp_id = point_ids.get((terr, _money(target)))
        if pp_id is None:
            rep.add("CONFLICT", f"price override {sub['product_id']} {terr}: no price point {target}")
            continue
        if guarded(rep, f"price override {sub['product_id']} {terr}", lambda: api.post("/v1/subscriptionPrices", asc_body(
                "subscriptionPrices", {"preserveCurrentPrice": False},
                {"subscription": ref("subscriptions", sub_id), "subscriptionPricePoint": ref("subscriptionPricePoints", pp_id)}))):
            changed += 1
    if changed:
        rep.add("UPDATE", f"price override {sub['product_id']}: {changed} territories → local prices")


def sync_intro_offer(api, rep: Report, sub: dict, sub_id: str, sellable: list[str]) -> None:
    """Intro offers are per territory: a "global" 3-day trial is one offer per sold territory.
    Exactly as the spec says: trial products get it everywhere, offer products get NONE."""
    pid, want = sub["product_id"], sub["intro_offer"]
    offers, _ = asc_all(api, f"/v1/subscriptions/{sub_id}/introductoryOffers", {"include": "territory", "limit": 200})
    if not want:
        if offers:
            rep.add("CONFLICT", f"intro offer {pid}: {len(offers)} offer(s) exist but the spec says none; delete by hand")
        else:
            rep.add("OK", f"intro offer {pid}: none, as specified")
        return

    def matches(o: dict) -> bool:
        a = o.get("attributes") or {}
        return a.get("offerMode") == want["mode"] and a.get("duration") == want["duration"]
    others = [o for o in offers if not matches(o)]
    if others:
        a = others[0].get("attributes") or {}
        rep.add("CONFLICT", f"intro offer {pid}: {len(others)} unexpected offer(s), e.g. {a.get('offerMode')} {a.get('duration')}")
    covered = {territory_of(o) for o in offers}
    todo = [t for t in sellable if t not in covered]
    failed = []
    for terr in todo:
        try:
            api.post("/v1/subscriptionIntroductoryOffers", asc_body(
                "subscriptionIntroductoryOffers",
                {"offerMode": want["mode"], "duration": want["duration"], "numberOfPeriods": want["periods"]},
                {"subscription": ref("subscriptions", sub_id), "territory": ref("territories", terr)}))
        except ApiError as e:
            failed.append(f"{terr}: {str(e)[-200:]}")
    if failed:
        rep.add("ERROR", f"intro offer {pid}: {len(failed)} territories failed, first: {failed[0]}")
    if len(todo) > len(failed):
        rep.add("CREATE", f"intro offer {pid}: {want['mode']} {want['duration']} in {len(todo) - len(failed)} territories")
    elif not todo:
        rep.add("OK", f"intro offer {pid}: {want['mode']} {want['duration']} in {len(covered)} territories")


def sync_grace_period(api, rep: Report, want: dict, app_id: str) -> None:
    """Billing Grace Period: one app-level resource that always exists; PATCH only differing attributes."""
    cur = (api.get(f"/v1/apps/{app_id}/subscriptionGracePeriod") or {}).get("data")
    if not cur:
        rep.add("CONFLICT", "grace period: the app has no subscriptionGracePeriod resource")
        return
    diff = {k: v for k, v in want.items() if (cur.get("attributes") or {}).get(k) != v}
    label = ", ".join(f"{k}={v}" for k, v in want.items())
    if not diff:
        rep.add("OK", f"grace period {label}")
        return
    if guarded(rep, "grace period", lambda: api.patch(f"/v1/subscriptionGracePeriods/{cur['id']}",
                                                      asc_body("subscriptionGracePeriods", diff, id_=cur["id"]))):
        rep.add("UPDATE", f"grace period: {', '.join(f'{k}={v}' for k, v in diff.items())}")


def sync_age_rating(api, rep: Report, want: dict, info_id: str) -> None:
    decl = (api.get(f"/v1/appInfos/{info_id}/ageRatingDeclaration") or {}).get("data")
    if not decl:
        rep.add("CONFLICT", "age rating: no declaration on the editable appInfo")
        return
    diff = {k: v for k, v in want.items() if (decl.get("attributes") or {}).get(k) != v}
    if not diff:
        rep.add("OK", "age rating questionnaire")
        return
    if guarded(rep, "age rating", lambda: api.patch(f"/v1/ageRatingDeclarations/{decl['id']}",
                                                    asc_body("ageRatingDeclarations", diff, id_=decl["id"]))):
        rep.add("UPDATE", f"age rating: {len(diff)} answer(s), healthOrWellnessTopics={want.get('healthOrWellnessTopics')}")


def sync_review_contact(api, rep: Report, contact: dict, version_id: str) -> None:
    """App Review contact on the version. ASC refuses to create one without contactPhone, which comes
    only from config review_contact_phone; the phone is compared by digits and never printed."""
    phone = contact.get("contactPhone") or ""

    def same(k: str, have: Any, want: Any) -> bool:
        if k == "contactPhone":
            return re.sub(r"\D", "", have or "") == re.sub(r"\D", "", want or "")
        return have == want

    if not contact.get("contactEmail"):
        rep.add("MANUAL", "review contact: set support_email (and legal_controller) in ~/.appfactory/config.toml, then re-run")
        return
    cur = (api.get(f"/v1/appStoreVersions/{version_id}/appStoreReviewDetail") or {}).get("data")
    if not cur:
        if not phone:
            rep.add("MANUAL", f"review contact {contact.get('contactEmail')}: ASC needs contactPhone to create it; "
                              "set review_contact_phone in ~/.appfactory/config.toml, then re-run")
            return
        if guarded(rep, "review contact", lambda: api.post("/v1/appStoreReviewDetails", asc_body(
                "appStoreReviewDetails", {**contact, "demoAccountRequired": False},
                {"appStoreVersion": ref("appStoreVersions", version_id)}))):
            rep.add("CREATE", f"review contact {contact.get('contactEmail')} (phone from local config)")
        return
    diff = {k: v for k, v in contact.items() if not same(k, (cur.get("attributes") or {}).get(k), v)}
    if not diff:
        rep.add("OK", "review contact")
    elif guarded(rep, "review contact", lambda: api.patch(f"/v1/appStoreReviewDetails/{cur['id']}",
                                                          asc_body("appStoreReviewDetails", diff, id_=cur["id"]))):
        rep.add("UPDATE", f"review contact: {', '.join(sorted(diff))}")


def sync_app_availability(api, rep: Report, app_id: str, territories: list[str], excluded: set[str]) -> None:
    """App availability (v2): every territory but the excluded ones, new territories on. Created only
    when the app has none (a founder's own choice is never overwritten); an existing one that sells in
    an excluded territory is a CONFLICT. A first submission is blocked while it is unset."""
    cur = (api.get(f"/v1/apps/{app_id}/appAvailabilityV2") or {}).get("data")
    if cur:
        have, included = asc_all(api, f"/v2/appAvailabilities/{cur['id']}/territoryAvailabilities",
                                 {"include": "territory", "limit": 200})
        sold = {territory_of(t) for t in have if (t.get("attributes") or {}).get("available")}
        leaks = sorted(sold & excluded)
        if leaks:
            rep.add("CONFLICT", f"app availability: available in excluded {leaks} (fix by hand in ASC → Pricing and Availability)")
        else:
            rep.add("OK", f"app availability: {len(sold)} territories, excluded {sorted(excluded)}")
        return
    refs, included = [], []
    for t in territories:
        local = f"${{t-{t}}}"
        refs.append(ref("territoryAvailabilities", local))
        included.append({"type": "territoryAvailabilities", "id": local, "attributes": {"available": t not in excluded},
                         "relationships": {"territory": {"data": ref("territories", t)}}})
    body = {"data": {"type": "appAvailabilities", "attributes": {"availableInNewTerritories": True},
                     "relationships": {"app": {"data": ref("apps", app_id)},
                                       "territoryAvailabilities": {"data": refs}}},
            "included": included}
    if guarded(rep, "app availability", lambda: api.post("/v2/appAvailabilities", body)):
        rep.add("CREATE", f"app availability: {len(territories) - len(excluded & set(territories))} territories, "
                          f"excluded {sorted(excluded)}, new territories on")


def sync_categories(api, rep: Report, info_id: str, primary: str | None, secondary: str | None) -> None:
    """Primary/secondary App Store category on the editable appInfo. Not managed while the
    spec leaves them unset."""
    if not primary:
        rep.add("MANUAL", "category: set spec.store.primary_category (ASC category id), then re-run")
        return
    rel: dict[str, Any] = {}
    for key, want in (("primaryCategory", primary), ("secondaryCategory", secondary)):
        if want is None:
            continue
        have = (api.get(f"/v1/appInfos/{info_id}/{key}") or {}).get("data")
        if (have or {}).get("id") != want:
            rel[key] = {"data": ref("appCategories", want)}
    label = primary + (f" / {secondary}" if secondary else "")
    if not rel:
        rep.add("OK", f"category {label}")
        return
    if guarded(rep, "category", lambda: api.patch(f"/v1/appInfos/{info_id}", {
            "data": {"type": "appInfos", "id": info_id, "relationships": rel}})):
        rep.add("UPDATE", f"category {label}")


def sync_content_rights(api, rep: Report, app: dict, want: str) -> None:
    """Content rights declaration: third-party content, e.g. a product database, must say so."""
    if (app.get("attributes") or {}).get("contentRightsDeclaration") == want:
        rep.add("OK", f"content rights {want}")
    elif guarded(rep, "content rights", lambda: api.patch(f"/v1/apps/{app['id']}", asc_body(
            "apps", {"contentRightsDeclaration": want}, id_=app["id"]))):
        rep.add("UPDATE", f"content rights {want}")


def sync_app_price(api, rep: Report, app_id: str) -> None:
    """Free app: one manual price at the USA FREE price point. An app with no price schedule cannot be
    submitted. An existing schedule is never changed."""
    try:
        sched = (api.get(f"/v1/apps/{app_id}/appPriceSchedule") or {}).get("data")
        manual = asc_all(api, f"/v1/appPriceSchedules/{sched['id']}/manualPrices", {"limit": 50})[0] if sched else []
    except ApiError:
        sched, manual = None, []
    if manual:
        rep.add("OK", f"app price schedule ({len(manual)} manual price(s))")
        return
    points, _ = asc_all(api, f"/v1/apps/{app_id}/appPricePoints", {"filter[territory]": "USA", "limit": 200})
    free = next((p for p in points if _same_price((p.get("attributes") or {}).get("customerPrice"), 0)), None)
    if free is None:
        rep.add("CONFLICT", "app price: no USA FREE price point found")
        return
    body = {"data": {"type": "appPriceSchedules", "relationships": {
                "app": {"data": ref("apps", app_id)},
                "baseTerritory": {"data": ref("territories", "USA")},
                "manualPrices": {"data": [ref("appPrices", "${price-free}")]}}},
            "included": [{"type": "appPrices", "id": "${price-free}", "attributes": {"startDate": None},
                          "relationships": {"appPricePoint": {"data": ref("appPricePoints", free["id"])}}}]}
    if guarded(rep, "app price", lambda: api.post("/v1/appPriceSchedules", body)):
        rep.add("CREATE", "app price: FREE, base territory USA")


def sync_copyright(api, rep: Report, version: dict, want: str) -> None:
    """Version copyright: the brand ("© 2026 <Brand>"), never the developer's personal name."""
    if (version.get("attributes") or {}).get("copyright") == want:
        rep.add("OK", f"copyright {want}")
    elif guarded(rep, "copyright", lambda: api.patch(f"/v1/appStoreVersions/{version['id']}", asc_body(
            "appStoreVersions", {"copyright": want}, id_=version["id"]))):
        rep.add("UPDATE", f"copyright {want}")


# ---------------------------------------------------------------------------------------------
# App Review notes (store/review-notes.md)
# ---------------------------------------------------------------------------------------------

REVIEW_NOTES_REL = Path("store") / "review-notes.md"
REVIEW_NOTES_LIMIT = 4000
_PHONE = re.compile(r"\+?\d[\d ().-]{8,}\d")


def review_notes_text(doc: str) -> str:
    """The paste-ready notes: the block between the review-notes markers, `<!-- … -->` comments removed."""
    body = doc.split("<!-- review-notes:start -->")[-1].split("<!-- review-notes:end -->")[0]
    body = body.strip().removeprefix("```text").removesuffix("```").strip()
    return re.sub(r"[ \t]*<!--.*?-->", "", body, flags=re.S).strip()


def review_notes_problems(text: str) -> list[str]:
    errs = []
    if len(text) > REVIEW_NOTES_LIMIT:
        errs.append(f"{len(text)} characters, over the {REVIEW_NOTES_LIMIT} limit")
    if any(len(re.sub(r"\D", "", m.group())) >= 9 for m in _PHONE.finditer(text)):
        errs.append("holds something that looks like a phone number (the phone goes only in the contact field)")
    if _PH.search(text):
        errs.append(f"unfilled placeholders {_PH.findall(text)[:3]}")
    return errs


def load_review_notes(app_dir: str | Path) -> tuple[str | None, list[str]]:
    """(notes, problems) from store/review-notes.md; (None, [reason]) when it is missing."""
    p = Path(app_dir).expanduser() / REVIEW_NOTES_REL
    if not p.exists():
        return None, [f"{REVIEW_NOTES_REL} is missing"]
    text = review_notes_text(p.read_text(encoding="utf-8"))
    return text, review_notes_problems(text)


def sync_server_notifications(api, rep: Report, app: dict, url: str | None) -> None:
    """App Store Server Notifications V2 → RevenueCat (production and sandbox)."""
    if not url:
        rep.add("MANUAL", RC_S2S_MANUAL)
        return
    want = {"subscriptionStatusUrl": url, "subscriptionStatusUrlVersion": "V2",
            "subscriptionStatusUrlForSandbox": url, "subscriptionStatusUrlVersionForSandbox": "V2"}
    attrs = app.get("attributes") or {}
    diff = {k: v for k, v in want.items() if attrs.get(k) != v}
    if not diff:
        rep.add("OK", "App Store Server Notifications V2 → RevenueCat (production + sandbox)")
        return
    if guarded(rep, "server notifications", lambda: api.patch(f"/v1/apps/{app['id']}",
                                                              asc_body("apps", diff, id_=app["id"]))):
        rep.add("UPDATE", f"App Store Server Notifications: {', '.join(sorted(diff))}")



# ---------------------------------------------------------------------------------------------
# Bundle ID capabilities (runs FIRST: keys, profiles and signing depend on them)
# ---------------------------------------------------------------------------------------------

KNOWN_CAPABILITIES = {"IN_APP_PURCHASE", "APPLE_ID_AUTH", "HEALTHKIT", "PUSH_NOTIFICATIONS", "ASSOCIATED_DOMAINS",
                      "APP_GROUPS", "ICLOUD", "GAME_CENTER", "WALLET", "SIRIKIT", "PERSONAL_VPN", "MAPS",
                      "DATA_PROTECTION", "HOMEKIT", "WIDGET_KIT"}
_CAP_SETTINGS = {
    "APPLE_ID_AUTH": [{"key": "APPLE_ID_AUTH_APP_CONSENT", "options": [{"key": "PRIMARY_APP_CONSENT"}]}],
}


def capabilities(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Desired App ID capabilities, derived from the spec (an App ID with only IN_APP_PURCHASE
    so the Sign in with Apple key could not be created and HealthKit was missing).
    Always IN_APP_PURCHASE; APPLE_ID_AUTH (PRIMARY_APP_CONSENT) unless the sign_in_with_apple option is
    off; HEALTHKIT only when
    spec.health.enabled; PUSH_NOTIFICATIONS only when spec.push.enabled (default off: no-push gate);
    plus spec.capabilities (extra capability types)."""
    types = ["IN_APP_PURCHASE"] + (["APPLE_ID_AUTH"] if spec_mod.option(spec, "sign_in_with_apple") else [])
    if (spec.get("health") or {}).get("enabled"):
        types.append("HEALTHKIT")
    if (spec.get("push") or {}).get("enabled"):
        types.append("PUSH_NOTIFICATIONS")
    for extra in spec.get("capabilities") or []:
        if extra not in types:
            types.append(extra)
    return [{"capabilityType": t, **({"settings": _CAP_SETTINGS[t]} if t in _CAP_SETTINGS else {})} for t in types]


def _settings_key(settings: Any) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for st in settings or []:
        out.append((st.get("key"), tuple(sorted(o.get("key") for o in st.get("options") or []))))
    return sorted(out)


def sync_capabilities(api, rep: Report, bundle_id: str, want: list[dict[str, Any]]) -> dict[str, Any]:
    """Enable missing capabilities on the App ID (POST /v1/bundleIdCapabilities), fix settings that
    differ (PATCH), report capabilities the spec does not ask for (EXTRA; PUSH_NOTIFICATIONS is a
    CONFLICT because of the no-push rule). Never disables anything."""
    ids: dict[str, Any] = {}
    found, _ = asc_all(api, "/v1/bundleIds", {"filter[identifier]": bundle_id, "limit": 20})
    bid = next((b for b in found if (b.get("attributes") or {}).get("identifier") == bundle_id), None)
    if bid is None:
        rep.add("CONFLICT", f"capabilities: bundle id {bundle_id} is not registered (asc_create_bundle_id first)")
        return ids
    ids["asc_bundle_id_resource"] = bid["id"]
    # no `limit`: ASC answers 400 "The parameter 'limit' can not be used with this request" here
    have, _ = asc_all(api, f"/v1/bundleIds/{bid['id']}/bundleIdCapabilities")
    by_type = {(h.get("attributes") or {}).get("capabilityType"): h for h in have}
    enabled = []
    for cap in want:
        t = cap["capabilityType"]
        cur = by_type.get(t)
        if cur is None:
            attrs = {"capabilityType": t, **({"settings": cap["settings"]} if cap.get("settings") else {})}
            if guarded(rep, f"capability {t}", lambda: api.post("/v1/bundleIdCapabilities", asc_body(
                    "bundleIdCapabilities", attrs, {"bundleId": ref("bundleIds", bid["id"])}))):
                rep.add("CREATE", f"capability {t}" + (" (PRIMARY_APP_CONSENT)" if t == "APPLE_ID_AUTH" else ""))
                enabled.append(t)
            continue
        if cap.get("settings") and _settings_key((cur.get("attributes") or {}).get("settings")) != _settings_key(cap["settings"]):
            if guarded(rep, f"capability {t} settings", lambda: api.patch(f"/v1/bundleIdCapabilities/{cur['id']}", asc_body(
                    "bundleIdCapabilities", {"capabilityType": t, "settings": cap["settings"]}, id_=cur["id"]))):
                rep.add("UPDATE", f"capability {t}: settings")
                enabled.append(t)
            continue
        rep.add("OK", f"capability {t}")
        enabled.append(t)
    wanted = {c["capabilityType"] for c in want}
    for t in sorted(k for k in by_type if k and k not in wanted):
        if t == "PUSH_NOTIFICATIONS":
            rep.add("CONFLICT", "capability PUSH_NOTIFICATIONS is enabled but the spec does not ask for it (no-push rule)")
        else:
            rep.add("EXTRA", f"capability {t} is enabled but not in the spec (left as is)")
    ids["capabilities_applied"] = sorted(enabled)
    return ids


def capabilities_pending(app_dir: str | Path) -> list[str]:
    """Capabilities the spec needs that no store_setup run has confirmed yet (offline, from outputs).
    Signing/profile/key steps refuse to run while this is non-empty."""
    app = Path(app_dir).expanduser()
    if not spec_mod.path(app).exists():
        return []
    want = {c["capabilityType"] for c in capabilities(spec_mod.load(app))}
    have = set(cfg.app_outputs(app).get("capabilities_applied") or [])
    return sorted(want - have)


def sync_asc(api, d: dict[str, Any], rep: Report, s2s_url: str | None = None) -> dict[str, Any]:
    """Make ASC match the desired state. Returns ids for the app outputs."""
    ids: dict[str, Any] = {}
    excluded = set(d.get("excluded_territories", EXCLUDED_TERRITORIES))
    apps, _ = asc_all(api, "/v1/apps", {"filter[bundleId]": d["bundle_id"]})
    if not apps:
        rep.add("CONFLICT", f"no ASC app with bundle id {d['bundle_id']} (create it first: asc_create_app)")
        return ids
    app = apps[0]
    aid = app["id"]
    ids["asc_app_id"] = aid
    rep.add("OK", f"app {aid} {app['attributes'].get('name')}")
    sku = app["attributes"].get("sku")
    if sku and sku != d["sku"]:
        rep.add("CONFLICT", f"SKU {sku} != spec {d['sku']} (the SKU cannot change after creation)")
    elif sku:
        rep.add("OK", f"SKU {sku}")
    sync_server_notifications(api, rep, app, s2s_url)
    if d.get("grace_period"):
        sync_grace_period(api, rep, d["grace_period"], aid)
    lvl = d.get("app_level") or {}
    if lvl:
        sync_content_rights(api, rep, app, lvl["content_rights"])

    g = d["group"]
    groups, _ = asc_all(api, f"/v1/apps/{aid}/subscriptionGroups", {"limit": 50})
    group = next((x for x in groups if x["attributes"].get("referenceName") == g["reference_name"]), None)
    if group is None:
        if groups:
            rep.add("CONFLICT", f"app already has subscription group(s) {[x['attributes'].get('referenceName') for x in groups]}, "
                                f"none named {g['reference_name']!r}")
            return ids
        group = api.post("/v1/subscriptionGroups", asc_body(
            "subscriptionGroups", {"referenceName": g["reference_name"]}, {"app": ref("apps", aid)}))["data"]
        rep.add("CREATE", f"subscription group {g['reference_name']}")
    else:
        rep.add("OK", f"subscription group {g['reference_name']}")
    gid = group["id"]
    ids["asc_subscription_group_id"] = gid
    glocs, _ = asc_all(api, f"/v1/subscriptionGroups/{gid}/subscriptionGroupLocalizations", {"limit": 50})
    sync_localizations(api, rep, "group localization", glocs, g["localizations"],
                       "subscriptionGroupLocalizations", "subscriptionGroup", ref("subscriptionGroups", gid))

    territories, _ = asc_all(api, "/v1/territories", {"limit": 200})
    sellable = [t["id"] for t in territories if t["id"] not in excluded]
    if lvl:
        sync_app_availability(api, rep, aid, [t["id"] for t in territories], excluded)
        if lvl.get("free"):
            sync_app_price(api, rep, aid)
    currency_of = {t["id"]: (t.get("attributes") or {}).get("currency") for t in territories
                   if (t.get("attributes") or {}).get("currency")}

    subs, _ = asc_all(api, f"/v1/subscriptionGroups/{gid}/subscriptions", {"limit": 50})
    by_pid = {s["attributes"].get("productId"): s for s in subs}
    ids["asc_subscription_ids"] = {}
    for sub in d["subscriptions"]:
        pid = sub["product_id"]
        cur = by_pid.get(pid)
        if cur is None:
            cur = api.post("/v1/subscriptions", asc_body("subscriptions", {
                "name": sub["reference_name"], "productId": pid, "subscriptionPeriod": sub["period"],
                "familySharable": False, "groupLevel": sub["group_level"]},
                {"group": ref("subscriptionGroups", gid)}))["data"]
            rep.add("CREATE", f"subscription {pid} ({sub['period']}, level {sub['group_level']})")
        else:
            period = cur["attributes"].get("subscriptionPeriod")
            if period and period != sub["period"]:
                rep.add("CONFLICT", f"subscription {pid}: period {period} != {sub['period']} (product ids cannot be reused)")
                continue
            level = cur["attributes"].get("groupLevel")
            if level is not None and level != sub["group_level"]:
                if guarded(rep, f"group level {pid}", lambda: api.patch(f"/v1/subscriptions/{cur['id']}", asc_body(
                        "subscriptions", {"groupLevel": sub["group_level"]}, id_=cur["id"]))):
                    rep.add("UPDATE", f"subscription {pid}: group level {level} → {sub['group_level']}")
            else:
                rep.add("OK", f"subscription {pid}")
        sid = cur["id"]
        ids["asc_subscription_ids"][sub["key"]] = sid
        slocs, _ = asc_all(api, f"/v1/subscriptions/{sid}/subscriptionLocalizations", {"limit": 50})
        sync_localizations(api, rep, f"localization {pid}", slocs, {k: v for k, v in sub["localizations"].items() if v},
                           "subscriptionLocalizations", "subscription", ref("subscriptions", sid))
        # Availability BEFORE prices (ASC answers 409 otherwise).
        avail = api.get(f"/v1/subscriptions/{sid}/subscriptionAvailability")
        if not (avail or {}).get("data"):
            if not guarded(rep, f"availability {pid}", lambda: api.post("/v1/subscriptionAvailabilities", asc_body(
                    "subscriptionAvailabilities", {"availableInNewTerritories": True},
                    {"subscription": ref("subscriptions", sid),
                     "availableTerritories": [ref("territories", t) for t in sellable]}))):
                continue
            rep.add("CREATE", f"availability {pid}: {len(sellable)} territories (excluded {sorted(excluded)})")
        else:
            rep.add("OK", f"availability {pid}")
        sync_prices(api, rep, sub, sid, excluded)
        sync_price_overrides(api, rep, sub, sid, override_targets(sub, currency_of, sellable))
        sync_intro_offer(api, rep, sub, sid, sellable)

    infos, _ = asc_all(api, f"/v1/apps/{aid}/appInfos", {"limit": 10})
    info = next((i for i in infos if (i["attributes"].get("appStoreState") or i["attributes"].get("state")) in EDITABLE_STATES), None)
    if info is not None:
        sync_age_rating(api, rep, d["age_rating"], info["id"])
        if lvl:
            sync_categories(api, rep, info["id"], lvl["primary_category"], lvl["secondary_category"])
    versions, _ = asc_all(api, f"/v1/apps/{aid}/appStoreVersions", {"limit": 10})
    version = next((v for v in versions if v["attributes"].get("appStoreState") in EDITABLE_STATES), None)
    locs = d["listing"]
    if info is None:
        rep.add("CONFLICT", "no editable appInfo (name/subtitle are locked while a version is in review)")
    else:
        existing, _ = asc_all(api, f"/v1/appInfos/{info['id']}/appInfoLocalizations", {"limit": 50})
        sync_localizations(api, rep, "app info", existing,
                           {loc: {"name": e.get("name"), "subtitle": e.get("subtitle"),
                                  "privacyPolicyUrl": e.get("privacy_url")} for loc, e in locs.items()},
                           "appInfoLocalizations", "appInfo", ref("appInfos", info["id"]))
    if version is None:
        rep.add("CONFLICT", "no editable App Store version")
    else:
        existing, _ = asc_all(api, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations", {"limit": 50})
        sync_localizations(api, rep, f"version {version['attributes'].get('versionString')}", existing,
                           {loc: {"keywords": e.get("keywords"), "promotionalText": e.get("promotional_text"),
                                  "description": e.get("description"), "supportUrl": e.get("support_url")}
                            for loc, e in locs.items()},
                           "appStoreVersionLocalizations", "appStoreVersion", ref("appStoreVersions", version["id"]))
        if lvl:
            sync_copyright(api, rep, version, lvl["copyright"])
        contact = dict(d["review_contact"])
        if d.get("review_notes") and contact.get("contactEmail"):
            contact["notes"] = d["review_notes"]
        sync_review_contact(api, rep, contact, version["id"])
    return ids


class LiveAscApi:
    """Adapter over AppFactory's ASCClient.request, i.e. the `asc api` passthrough: this reconciler is
    generic JSON:API (path + body), so it keeps raw paths instead of first-class asc commands. GETs
    retried on 5xx; writes never retried in-run. ASC_READ_ONLY=1 makes asc refuse every write."""

    def __init__(self, client: Any = None, sleep: Callable[[float], None] = time.sleep):
        if client is None:
            from . import asc
            client = asc.ASCClient()
        self.client = client
        self._sleep = sleep

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        r = self.client.request(method, path, params=params, json=body)
        for wait in (2, 5, 10):
            if method != "GET" or r.get("ok") or (r.get("status") or 0) < 500:
                break
            self._sleep(wait)
            r = self.client.request(method, path, params=params, json=body)
        if r.get("ok"):
            return r.get("data") or {}
        if method == "GET" and r.get("status") == 404:
            return None
        raise ApiError(f"{method} {path} -> {r.get('status')}: {json.dumps(r.get('error'))[:600]}")

    def get(self, path, params=None):
        return self._call("GET", path, params)

    def post(self, path, body):
        return self._call("POST", path, body=body)

    def patch(self, path, body):
        return self._call("PATCH", path, body=body)


class DryRunApi:
    """Real reads, recorded writes. Ids of would-be-created objects start with 'dry-'."""

    def __init__(self, inner):
        self.inner = inner
        self.writes: list[tuple[str, str, dict]] = []

    def get(self, path, params=None):
        if "dry-" in (path or ""):
            return {"data": []} if not path.endswith(("Availability", "ReviewDetail")) else {"data": None}
        return self.inner.get(path, params)

    def post(self, path, body):
        self.writes.append(("POST", path, body))
        data = body.get("data") if isinstance(body, dict) else None
        new_id = f"dry-{len(self.writes)}"
        if isinstance(data, dict):
            return {"data": {**data, "id": new_id}, "id": new_id}
        return {**(body or {}), "id": new_id}

    def patch(self, path, body):
        self.writes.append(("PATCH", path, body))
        return body

    def delete(self, path):
        self.writes.append(("DELETE", path, {}))
        return {}


class MemoryAscApi:
    """In-memory App Store Connect for `plan` and tests. Models only the endpoints used above."""

    CHILDREN = {
        ("apps", "subscriptionGroups"): ("subscriptionGroups", "app"),
        ("bundleIds", "bundleIdCapabilities"): ("bundleIdCapabilities", "bundleId"),
        ("subscriptionGroups", "subscriptionGroupLocalizations"): ("subscriptionGroupLocalizations", "subscriptionGroup"),
        ("subscriptionGroups", "subscriptions"): ("subscriptions", "group"),
        ("subscriptions", "subscriptionLocalizations"): ("subscriptionLocalizations", "subscription"),
        ("subscriptions", "introductoryOffers"): ("subscriptionIntroductoryOffers", "subscription"),
        ("subscriptions", "prices"): ("subscriptionPrices", "subscription"),
        ("apps", "appInfos"): ("appInfos", "app"),
        ("appInfos", "appInfoLocalizations"): ("appInfoLocalizations", "appInfo"),
        ("apps", "appStoreVersions"): ("appStoreVersions", "app"),
        ("appStoreVersions", "appStoreVersionLocalizations"): ("appStoreVersionLocalizations", "appStoreVersion"),
    }
    TIERS = ["2.99", "7.99", "9.99", "29.99", "49.99", "34.9", "119.9", "199.9", "199.99", "749.99", "1249.99"]
    TERRITORIES = {"USA": "USD", "GBR": "GBP", "DEU": "EUR", "FRA": "EUR", "ESP": "EUR", "MEX": "MXN",
                   "BRA": "BRL", "TUR": "TRY", "CHN": "CNY", "JPN": "JPY"}

    def __init__(self, bundle_id: str, app_id: str = "app-1", sku: str | None = None,
                 territories: dict[str, str] | None = None, app_name: str = "App"):
        self.store: dict[str, dict[str, dict]] = {}
        self.writes: list[tuple[str, str]] = []
        self.territories = territories or dict(self.TERRITORIES)
        self._n = 0
        self._put({"type": "apps", "id": app_id, "attributes": {"bundleId": bundle_id, "name": app_name, "sku": sku}})
        # A legacy App ID: only IN_APP_PURCHASE.
        self._put({"type": "bundleIds", "id": "bid-1", "attributes": {"identifier": bundle_id, "platform": "IOS"}})
        self._put({"type": "bundleIdCapabilities", "id": "cap-iap", "attributes": {"capabilityType": "IN_APP_PURCHASE"},
                   "relationships": {"bundleId": {"data": ref("bundleIds", "bid-1")}}})
        self._put({"type": "appInfos", "id": "info-1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"},
                   "relationships": {"app": {"data": ref("apps", app_id)}}})
        self._put({"type": "appInfoLocalizations", "id": "info-loc-en", "attributes": {"locale": "en-US", "name": app_name},
                   "relationships": {"appInfo": {"data": ref("appInfos", "info-1")}}})
        self._put({"type": "appStoreVersions", "id": "ver-1", "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
                   "relationships": {"app": {"data": ref("apps", app_id)}}})
        self._put({"type": "appStoreVersionLocalizations", "id": "ver-loc-en", "attributes": {"locale": "en-US"},
                   "relationships": {"appStoreVersion": {"data": ref("appStoreVersions", "ver-1")}}})

    def _put(self, item: dict) -> dict:
        self.store.setdefault(item["type"], {})[item["id"]] = item
        return item

    def items(self, kind: str) -> list[dict]:
        return list(self.store.get(kind, {}).values())

    def get(self, path, params=None):
        params = params or {}
        path = path.split("?")[0]
        if path == "/v1/apps":
            want = params.get("filter[bundleId]")
            return {"data": [a for a in self.items("apps") if a["attributes"]["bundleId"] == want]}
        if path == "/v1/territories":
            return {"data": [{"type": "territories", "id": t, "attributes": {"currency": c}} for t, c in self.territories.items()]}
        if path == "/v1/bundleIds":
            want = params.get("filter[identifier]")
            return {"data": [b for b in self.items("bundleIds") if b["attributes"]["identifier"].startswith(want or "")]}
        parts = path.strip("/").split("/")[1:]
        if len(parts) == 3:
            parent_kind, parent_id, child = parts
            if (parent_kind, child) in self.CHILDREN:
                kind, rel = self.CHILDREN[(parent_kind, child)]
                return {"data": [i for i in self.items(kind) if rel_id(i, rel) == parent_id]}
            if child == "subscriptionGracePeriod":
                gp = self.store.setdefault("subscriptionGracePeriods", {}).setdefault(parent_id, {
                    "type": "subscriptionGracePeriods", "id": parent_id,
                    "attributes": {"optIn": False, "sandboxOptIn": False, "duration": None, "renewalType": None}})
                return {"data": gp}
            if child == "ageRatingDeclaration":
                decl = self.store.setdefault("ageRatingDeclarations", {}).setdefault(
                    parent_id, {"type": "ageRatingDeclarations", "id": parent_id, "attributes": {}})
                return {"data": decl}
            if child == "appStoreReviewDetail":
                hit = [i for i in self.items("appStoreReviewDetails") if rel_id(i, "appStoreVersion") == parent_id]
                return {"data": hit[0] if hit else None}
            if child == "subscriptionAvailability":
                hit = [i for i in self.items("subscriptionAvailabilities") if rel_id(i, "subscription") == parent_id]
                return {"data": hit[0] if hit else None}
            if child == "appAvailabilityV2":
                hit = [i for i in self.items("appAvailabilities") if rel_id(i, "app") == parent_id]
                return {"data": hit[0] if hit else None}
            if child == "territoryAvailabilities":
                return {"data": [i for i in self.items("territoryAvailabilities") if rel_id(i, "appAvailability") == parent_id]}
            if child in ("primaryCategory", "secondaryCategory"):
                return {"data": ((self.store["appInfos"][parent_id].get("relationships") or {}).get(child) or {}).get("data")}
            if child == "appPriceSchedule":
                hit = [i for i in self.items("appPriceSchedules") if rel_id(i, "app") == parent_id]
                return {"data": hit[0] if hit else None}
            if child == "manualPrices":
                return {"data": [i for i in self.items("appPrices") if rel_id(i, "appPriceSchedule") == parent_id]}
            if child == "appPricePoints":
                return {"data": [{"type": "appPricePoints", "id": f"app-pp|USA|{p}", "attributes": {"customerPrice": p}}
                                 for p in ("0.0", "0.99", "1.99")]}
            if child == "pricePoints":
                terrs = params.get("filter[territory]", "USA").split(",")
                return {"data": [{"type": "subscriptionPricePoints", "id": f"pp|{parent_id}|{terr}|{p}",
                                  "attributes": {"customerPrice": p},
                                  "relationships": {"territory": {"data": ref("territories", terr)}}}
                                 for terr in terrs for p in self.TIERS]}
            if child == "equalizations":
                _, sid, _, price = parent_id.split("|")
                return {"data": [{"type": "subscriptionPricePoints", "id": f"pp|{sid}|{t}|{price}",
                                  "relationships": {"territory": {"data": ref("territories", t)}}}
                                 for t in self.territories if t != "USA"]}
        raise ApiError(f"MemoryAscApi: unmodelled GET {path}")

    def post(self, path, body):
        data = body["data"]
        kind = path.strip("/").split("/")[1]
        self._n += 1
        item = {"type": kind, "id": f"{kind}-{self._n}", "attributes": dict(data.get("attributes") or {}),
                "relationships": dict(data.get("relationships") or {})}
        if kind == "subscriptionPrices":
            terr = rel_id(item, "subscriptionPricePoint").split("|")[2]
            item["relationships"]["territory"] = {"data": ref("territories", terr)}
            item["attributes"]["startDate"] = f"2026-09-24T00:00:{self._n:05d}"
        if kind == "subscriptionIntroductoryOffers" and not rel_id(item, "territory"):
            raise ApiError("POST subscriptionIntroductoryOffers -> 409: ENTITY_ERROR.RELATIONSHIP.REQUIRED territory")
        # Inline-created children (`included` with ${local} ids): territory availabilities, app prices.
        child_rel = {"appAvailabilities": "appAvailability", "appPriceSchedules": "appPriceSchedule"}.get(kind)
        for inc in body.get("included") or []:
            self._n += 1
            self._put({"type": inc["type"], "id": f"{inc['type']}-{self._n}",
                       "attributes": dict(inc.get("attributes") or {}),
                       "relationships": {**(inc.get("relationships") or {}), child_rel: {"data": ref(kind, item["id"])}}})
        self.writes.append(("POST", kind))
        return {"data": self._put(item)}

    def patch(self, path, body):
        kind, id_ = path.strip("/").split("/")[1:3]
        self.store[kind][id_]["attributes"].update(body["data"].get("attributes") or {})
        if body["data"].get("relationships"):
            self.store[kind][id_].setdefault("relationships", {}).update(body["data"]["relationships"])
        self.writes.append(("PATCH", kind))
        return {"data": self.store[kind][id_]}


# ---------------------------------------------------------------------------------------------
# RevenueCat (REST API v2, secret key)
# ---------------------------------------------------------------------------------------------

def rc_all(api, path: str, params: dict | None = None) -> list:
    items: list = []
    page = api.get(path, params)
    while page:
        items += page.get("items") or []
        nxt = page.get("next_page")
        page = api.get(nxt) if nxt else None
    return items


def _mcp(rep: Report, tool: str, args: dict[str, Any], why: str) -> None:
    rep.mcp.append({"tool": tool, "args": args, "why": why})
    rep.add("MANUAL", f"{why} → RevenueCat MCP `{tool}` (structured plan in mcp_plan)")


def sync_rc(api, d: dict[str, Any], rep: Report, known: dict[str, Any]) -> dict[str, Any]:
    """Project, app, products, entitlement, offerings/packages, targeting rule with placements."""
    rc = d["revenuecat"]
    ids: dict[str, Any] = {}
    projects = rc_all(api, "/projects")
    project = None
    if known.get("rc_project_id"):
        project = next((p for p in projects if p.get("id") == known["rc_project_id"]), None)
    if project is None:
        project = next((p for p in projects if p.get("name") == rc["project_name"]), None)
    if project is None:
        try:
            project = api.post("/projects", {"name": rc["project_name"]})
            rep.add("CREATE", f"RevenueCat project {rc['project_name']}")
        except ApiError as e:
            _mcp(rep, "create-project", {"body": {"name": rc["project_name"]}},
                 f"this RC key cannot create projects ({str(e)[:80]}); create project {rc['project_name']!r}, then re-run "
                 "with its id recorded (store_setup rc_project_id=…)")
            return ids
    else:
        rep.add("OK", f"RevenueCat project {project.get('name')} ({project.get('id')})")
    pid = project["id"]
    ids["rc_project_id"] = pid

    apps = rc_all(api, f"/projects/{pid}/apps")
    app = next((a for a in apps if a.get("type") == "app_store"
                and (a.get("app_store") or {}).get("bundle_id") == d["bundle_id"]), None)
    if app is None:
        body = {"name": f"{d['app_name']} (App Store)", "type": "app_store", "app_store": {"bundle_id": d["bundle_id"]}}
        app = api.post(f"/projects/{pid}/apps", body)
        rep.add("CREATE", f"RC app {body['name']} ({d['bundle_id']})")
        rep.add("MANUAL", "RevenueCat dashboard → app → upload the In-App Purchase key and the App Store Connect "
                          "API key (needed to validate purchases and import products)")
    else:
        rep.add("OK", f"RC app {app.get('name')} ({app.get('id')})")
    app_id = app["id"]
    ids["rc_app_id"] = app_id
    keys = rc_all(api, f"/projects/{pid}/apps/{app_id}/public_api_keys") if not str(app_id).startswith("dry-") else []
    if keys:
        ids["rc_public_key"] = keys[0].get("key")
        rep.add("OK", "public SDK key present (iOS AppConfig)")
    else:
        rep.add("MANUAL", "public SDK key not visible yet (RevenueCat creates it with the app; re-run to record it)")

    products = rc_all(api, f"/projects/{pid}/products", {"app_id": app_id, "limit": 100})
    by_store_id = {p.get("store_identifier"): p for p in products}
    rc_ids: dict[str, str] = {}
    for sub in d["subscriptions"]:
        sid = sub["product_id"]
        cur = by_store_id.get(sid)
        if cur is None:
            cur = api.post(f"/projects/{pid}/products", {"store_identifier": sid, "app_id": app_id,
                                                          "type": "subscription", "display_name": sub["reference_name"]})
            rep.add("CREATE", f"RC product {sid}")
        else:
            rep.add("OK", f"RC product {sid}")
        rc_ids[sid] = cur["id"]

    ent_cfg = rc["entitlement"]
    ents = rc_all(api, f"/projects/{pid}/entitlements", {"limit": 100})
    ent = next((e for e in ents if e.get("lookup_key") == ent_cfg["lookup_key"]), None)
    if ent is None:
        ent = api.post(f"/projects/{pid}/entitlements", {"lookup_key": ent_cfg["lookup_key"], "display_name": ent_cfg["display_name"]})
        rep.add("CREATE", f"RC entitlement {ent_cfg['lookup_key']}")
        attached: set[str] = set()
    else:
        rep.add("OK", f"RC entitlement {ent_cfg['lookup_key']}")
        attached = {p.get("id") for p in rc_all(api, f"/projects/{pid}/entitlements/{ent['id']}/products", {"limit": 100})}
    missing = [i for i in rc_ids.values() if i not in attached]
    if missing:
        api.post(f"/projects/{pid}/entitlements/{ent['id']}/actions/attach_products", {"product_ids": missing})
        rep.add("CREATE", f"RC entitlement {ent_cfg['lookup_key']}: attach {len(missing)} product(s)")
    else:
        rep.add("OK", f"RC entitlement {ent_cfg['lookup_key']}: all products attached")

    offerings = rc_all(api, f"/projects/{pid}/offerings", {"limit": 100})
    by_key = {o.get("lookup_key"): o for o in offerings}
    offering_ids: dict[str, str] = {}
    for o_cfg in rc["offerings"]:
        off = by_key.get(o_cfg["lookup_key"])
        if off is None:
            off = api.post(f"/projects/{pid}/offerings", {"lookup_key": o_cfg["lookup_key"], "display_name": o_cfg["display_name"]})
            rep.add("CREATE", f"RC offering {o_cfg['lookup_key']}")
        else:
            rep.add("OK", f"RC offering {o_cfg['lookup_key']}")
        offering_ids[o_cfg["lookup_key"]] = off["id"]
        if o_cfg.get("is_current") and not off.get("is_current"):
            api.post(f"/projects/{pid}/offerings/{off['id']}", {"is_current": True})
            rep.add("UPDATE", f"RC offering {o_cfg['lookup_key']}: is_current = true")
        packages = rc_all(api, f"/projects/{pid}/offerings/{off['id']}/packages", {"limit": 100})
        pk_by_key = {p.get("lookup_key"): p for p in packages}
        for p_cfg in o_cfg["packages"]:
            pk = pk_by_key.get(p_cfg["lookup_key"])
            if pk is None:
                pk = api.post(f"/projects/{pid}/offerings/{off['id']}/packages",
                              {"lookup_key": p_cfg["lookup_key"], "display_name": p_cfg["display_name"], "position": p_cfg["position"]})
                rep.add("CREATE", f"RC package {o_cfg['lookup_key']}/{p_cfg['lookup_key']}")
                current = []
            else:
                current = [x.get("product", x).get("id") for x in rc_all(api, f"/projects/{pid}/packages/{pk['id']}/products")]
            want = rc_ids[p_cfg["product_id"]]
            if want in current:
                rep.add("OK", f"RC package {o_cfg['lookup_key']}/{p_cfg['lookup_key']} -> {p_cfg['product_id']}")
            elif current:
                rep.add("CONFLICT", f"RC package {o_cfg['lookup_key']}/{p_cfg['lookup_key']} holds another product; fix by hand")
            else:
                api.post(f"/projects/{pid}/packages/{pk['id']}/actions/attach_products",
                         {"products": [{"product_id": want, "eligibility_criteria": "all"}]})
                rep.add("CREATE", f"RC package {o_cfg['lookup_key']}/{p_cfg['lookup_key']}: attach {p_cfg['product_id']}")
    sync_placements(api, rep, pid, rc, offering_ids, d["app_name"])
    return ids


def placements_body(rc: dict[str, Any], offering_ids: dict[str, str], app_name: str) -> dict[str, Any]:
    default_id = offering_ids.get("default")
    return {
        "display_name": f"{app_name} paywall placements",
        "offering_id": default_id,
        "state": "active",
        "placements": {
            "fallback_offering_id": default_id,
            "placement_offerings": [{"placement_identifier": pl, "offering_id": offering_ids.get(off)}
                                   for pl, off in rc["placements"].items()],
        },
    }


def sync_placements(api, rep: Report, pid: str, rc: dict[str, Any], offering_ids: dict[str, str], app_name: str) -> None:
    """Targeting rule "All users" with per-placement offerings. REST v2 `targeting_rules` (GET verified
    live 2026-09-24; the POST body mirrors the RevenueCat MCP `create-targeting-rule` schema). If the
    REST write is refused (404/405), a structured plan for the MCP tool is emitted instead."""
    body = placements_body(rc, offering_ids, app_name)
    want = {x["placement_identifier"]: x["offering_id"] for x in body["placements"]["placement_offerings"]}
    try:
        rules = rc_all(api, f"/projects/{pid}/targeting_rules", {"limit": 100})
    except ApiError as e:
        rules = None
        rep.add("ERROR", f"RC targeting rules read failed: {str(e)[:120]}")
    for r in rules or []:
        have = {x.get("placement_identifier"): x.get("offering_id")
                for x in ((r.get("placements") or {}).get("placement_offerings") or [])}
        if not have:
            continue
        if have == want and r.get("state", "active") == "active":
            rep.add("OK", f"RC placements ({len(want)}) in targeting rule {r.get('id')}")
            return
        if set(have) & set(want):
            differ = sorted(k for k in want if k in have and have[k] != want[k])
            if differ:
                rep.add("CONFLICT", f"RC targeting rule {r.get('id')} maps the placements differently "
                                    f"({differ}); fix with the MCP `update-targeting-rule`")
                return
            # Only placements are missing (e.g. a new `billing_issue`): additive update of the same
            # rule. RC v2 updates a rule by POSTing the FULL placements object to its id (used live
            #); placements the rule has beyond the spec are kept.
            missing = sorted(set(want) - set(have))
            merged = [{"placement_identifier": k, "offering_id": v} for k, v in {**have, **want}.items()]
            upd = {"placements": {**(r.get("placements") or {}), "placement_offerings": merged}}
            try:
                api.post(f"/projects/{pid}/targeting_rules/{r.get('id')}", upd)
                rep.add("UPDATE", f"RC targeting rule {r.get('id')}: add placements {missing}")
            except ApiError as e:
                if re.search(r"-> (404|405)", str(e)):
                    _mcp(rep, "update-targeting-rule",
                         {"project_id": pid, "targeting_rule_id": r.get("id"), "body": upd},
                         "RC REST v2 refused the targeting-rule update")
                else:
                    rep.add("ERROR", f"RC targeting rule update: {str(e)[:200]}")
            return
    if rules is None:
        return
    try:
        api.post(f"/projects/{pid}/targeting_rules", body)
        rep.add("CREATE", f"RC targeting rule with {len(want)} placements")
    except ApiError as e:
        if re.search(r"-> (404|405)", str(e)):
            _mcp(rep, "create-targeting-rule", {"project_id": pid, "body": body},
                 "RC REST v2 refused the targeting-rule write")
        else:
            rep.add("ERROR", f"RC targeting rule: {str(e)[:200]}")


class LiveRcApi:
    BASE = "https://api.revenuecat.com"

    def __init__(self, key: str, http: Any = None, sleep: Callable[[float], None] = time.sleep):
        import httpx
        self.http = http or httpx.Client(timeout=30, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        self._sleep = sleep

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = path if path.startswith("http") else self.BASE + (path if path.startswith("/v2/") else "/v2" + path)
        server_retries = 0
        for _ in range(6):
            r = self.http.request(method, url, params=params, json=body)
            if r.status_code == 429:  # Project Configuration domain: 60 requests per minute
                try:
                    wait = float(r.headers.get("Retry-After") or 0) or (r.json().get("backoff_ms", 2000) / 1000)
                except Exception:  # noqa: BLE001
                    wait = 2.0
                self._sleep(min(wait, 60))
                continue
            if method == "GET" and r.status_code >= 500 and server_retries < 3:
                server_retries += 1
                self._sleep(2 * server_retries)
                continue
            if 200 <= r.status_code < 300:
                return r.json() if r.content else {}
            if method == "GET" and r.status_code == 404:
                return None
            raise ApiError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        raise ApiError(f"{method} {path}: gave up after retries")

    def get(self, path, params=None):
        return self._call("GET", path, params)

    def post(self, path, body):
        return self._call("POST", path, body=body)


class MemoryRcApi:
    """In-memory RevenueCat v2 for plan and tests."""

    def __init__(self, projects: list[dict] | None = None, can_create_project: bool = True,
                 targeting_rest: bool = True):
        self.projects = projects if projects is not None else []
        self.apps: dict[str, list[dict]] = {}
        self.products: list[dict] = []
        self.entitlements: list[dict] = []
        self.offerings: list[dict] = []
        self.packages: list[dict] = []
        self.rules: list[dict] = []
        self.writes: list[str] = []
        self.can_create_project = can_create_project
        self.targeting_rest = targeting_rest
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def get(self, path, params=None):
        p = path.split("?")[0].strip("/").split("/")
        if p == ["projects"]:
            return {"items": self.projects}
        if len(p) == 3 and p[2] == "apps":
            return {"items": self.apps.get(p[1], [])}
        if len(p) == 5 and p[4] == "public_api_keys":
            return {"items": [{"id": "k1", "key": "appl_test"}]}
        if len(p) == 3 and p[2] == "products":
            return {"items": self.products}
        if len(p) == 3 and p[2] == "entitlements":
            return {"items": self.entitlements}
        if len(p) == 5 and p[2] == "entitlements" and p[4] == "products":
            ent = next(e for e in self.entitlements if e["id"] == p[3])
            return {"items": [x for x in self.products if x["id"] in ent["_attached"]]}
        if len(p) == 3 and p[2] == "offerings":
            return {"items": self.offerings}
        if len(p) == 5 and p[2] == "offerings" and p[4] == "packages":
            return {"items": [k for k in self.packages if k["_offering"] == p[3]]}
        if len(p) == 5 and p[2] == "packages" and p[4] == "products":
            pk = next(k for k in self.packages if k["id"] == p[3])
            return {"items": [{"product": {"id": i}, "eligibility_criteria": "all"} for i in pk["_products"]]}
        if len(p) == 3 and p[2] == "targeting_rules":
            return {"items": self.rules}
        raise ApiError(f"MemoryRcApi: unmodelled GET {path}")

    def post(self, path, body):
        p = path.strip("/").split("/")
        self.writes.append(path)
        if p == ["projects"]:
            if not self.can_create_project:
                raise ApiError("POST /projects -> 403: forbidden for a project-scoped key")
            item = {"id": self._id("proj"), **body}
            self.projects.append(item)
            return item
        if len(p) == 3 and p[2] == "apps":
            item = {"id": self._id("app"), **body}
            self.apps.setdefault(p[1], []).append(item)
            return item
        if len(p) == 3 and p[2] == "products":
            item = {"id": self._id("prod"), **body}
            self.products.append(item)
            return item
        if len(p) == 3 and p[2] == "entitlements":
            item = {"id": self._id("entl"), **body, "_attached": []}
            self.entitlements.append(item)
            return item
        if len(p) == 6 and p[2] == "entitlements" and p[5] == "attach_products":
            ent = next(e for e in self.entitlements if e["id"] == p[3])
            ent["_attached"] += [i for i in body["product_ids"] if i not in ent["_attached"]]
            return ent
        if len(p) == 3 and p[2] == "offerings":
            item = {"id": self._id("ofrng"), **body, "is_current": False}
            self.offerings.append(item)
            return item
        if len(p) == 4 and p[2] == "offerings":
            off = next(o for o in self.offerings if o["id"] == p[3])
            if body.get("is_current"):
                for o in self.offerings:
                    o["is_current"] = False
            off.update(body)
            return off
        if len(p) == 5 and p[2] == "offerings" and p[4] == "packages":
            item = {"id": self._id("pkge"), **body, "_offering": p[3], "_products": []}
            self.packages.append(item)
            return item
        if len(p) == 6 and p[2] == "packages" and p[5] == "attach_products":
            pk = next(k for k in self.packages if k["id"] == p[3])
            pk["_products"] += [x["product_id"] for x in body["products"]]
            return pk
        if len(p) == 3 and p[2] == "targeting_rules":
            if not self.targeting_rest:
                raise ApiError(f"POST {path} -> 404: resource_missing")
            item = {"id": self._id("rule"), **body}
            self.rules.append(item)
            return item
        if len(p) == 4 and p[2] == "targeting_rules":
            if not self.targeting_rest:
                raise ApiError(f"POST {path} -> 404: resource_missing")
            rule = next(x for x in self.rules if x["id"] == p[3])
            rule.update(body)
            return rule
        raise ApiError(f"MemoryRcApi: unmodelled POST {path}")


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------

def _load(app_dir: Path) -> tuple[dict, dict]:
    sp = spec_mod.load(app_dir)
    listing = meta.load_listing(app_dir) if (app_dir / meta.LISTING_REL).exists() else {"locales": {}}
    return sp, listing


def run(app_dir: str | Path, mode: str = "plan", target: str = "all", confirm: str = "",
        rc_apple_notification_url: str | None = None, rc_project_id: str | None = None,
        asc_api: Any = None, rc_api: Any = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """plan | check | apply for target asc | rc | all. Returns {ok, summary, lines, mcp_plan, …}."""
    app = Path(app_dir).expanduser()
    if mode not in ("plan", "check", "apply"):
        return {"ok": False, "error": "mode must be plan | check | apply"}
    if target not in ("asc", "rc", "all", "capabilities"):
        return {"ok": False, "error": "target must be capabilities | asc | rc | all"}
    if not spec_mod.path(app).exists():
        return {"ok": False, "error": f"{spec_mod.SPEC_FILE} not found in {app}"}
    sp, listing = _load(app)
    serr = spec_mod.validate(sp)
    if serr:
        return {"ok": False, "error": "invalid app.spec.json: " + "; ".join(serr)}
    if mode == "apply" and confirm != sp["bundle_id"]:
        return {"ok": False, "error": f"apply writes to the live stores: pass confirm={sp['bundle_id']!r}"}
    if rc_apple_notification_url and not RC_S2S_URL_RE.match(rc_apple_notification_url):
        return {"ok": False, "error": "rc_apple_notification_url must look like https://api.revenuecat.com/v1/"
                                      "incoming-webhooks/apple-server-to-server-notification/<32-char token>"}
    c = config if config is not None else cfg.load_config()
    outs = cfg.app_outputs(app)
    if mode != "plan":
        cfg.update_app_outputs(app, rc_apple_notification_url=rc_apple_notification_url, rc_project_id=rc_project_id)
        outs = cfg.app_outputs(app)
    s2s = rc_apple_notification_url or outs.get("rc_apple_notification_url")
    notes, note_problems = load_review_notes(app)
    d = desired_state(sp, listing, c, review_notes=None if note_problems else notes)
    errors = validate_desired(d)
    phone = c.get("review_contact_phone") if mode != "plan" else None
    if phone:
        d["review_contact"] = {**d["review_contact"], "contactPhone": phone}
    rep = Report(redact=(phone or "",))
    ids: dict[str, Any] = {}
    # Capabilities run FIRST (keys, provisioning profiles and signing depend on them), then ASC, then RC.
    targets = {"all": ["capabilities", "asc", "rc"], "asc": ["capabilities", "asc"]}.get(target, [target])
    if errors and mode != "plan" and targets != ["capabilities"]:
        return {"ok": False, "error": "desired state incomplete (fill listing.json / spec first)", "errors": errors}
    shared_asc = None
    for t in targets:
        try:
            if t in ("capabilities", "asc"):
                if shared_asc is None:
                    api = asc_api
                    if api is None:
                        api = MemoryAscApi(sp["bundle_id"], sku=sp["sku"], app_name=d["app_name"]) if mode == "plan" else LiveAscApi()
                    if mode == "check" and asc_api is None:
                        api = DryRunApi(api)
                    shared_asc = api
                if t == "capabilities":
                    ids.update(sync_capabilities(shared_asc, rep, sp["bundle_id"], d["capabilities"]))
                else:
                    ids.update(sync_asc(shared_asc, d, rep, s2s))
            else:
                api = rc_api
                if api is None:
                    if mode == "plan":
                        api = MemoryRcApi()
                    else:
                        key = c.get("rc_secret_key")
                        if not key:
                            rep.add("CONFLICT", "no rc_secret_key in ~/.appfactory/config.toml")
                            continue
                        api = LiveRcApi(key)
                if mode == "check" and rc_api is None:
                    api = DryRunApi(api)
                ids.update(sync_rc(api, d, rep, outs))
        except ApiError as e:
            rep.add("ERROR", f"{t}: {e}")
    if "asc" in targets:
        for problem in note_problems:
            rep.add("MANUAL", f"review notes not synced: {problem} ({REVIEW_NOTES_REL})")
    if mode != "plan":
        live_ids = {k: v for k, v in ids.items() if not str(v).startswith("dry-") and not isinstance(v, dict)}
        if mode == "check":
            live_ids.pop("capabilities_applied", None)   # simulated writes prove nothing
        cfg.update_app_outputs(app, **live_ids)
    if mode == "apply":
        mk = app / MARKER_REL
        mk.parent.mkdir(parents=True, exist_ok=True)
        mk.write_text(json.dumps({"ok": not (rep.count("ERROR") or rep.count("CONFLICT")), "at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"), "target": target, "summary": rep.summary(),
            "manual": [m for k, m in rep.lines if k == "MANUAL"]}, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": not (rep.count("ERROR") or rep.count("CONFLICT")),
        "mode": mode, "target": target, "summary": rep.summary(),
        "lines": [f"{k:8} {m}" for k, m in rep.lines],
        "manual": [m for k, m in rep.lines if k == "MANUAL"],
        "mcp_plan": rep.mcp,
        "validation_errors": errors,
        "ids": {k: v for k, v in ids.items() if k != "rc_public_key"} | ({"rc_public_key": ids["rc_public_key"]} if ids.get("rc_public_key") else {}),
    }


# ---------------------------------------------------------------------------------------------
# pricing.md: unit economics from the MEASURED cost per call + the spec-driven layout blocks
# ---------------------------------------------------------------------------------------------

PROFILES = [  # (label, photo/day, text/day, active days/year)
    ("Realistic: 3 photo + 1 text on 120 active days", 3, 1, 120),
    ("Typical, every day: 3 photo + 1 text", 3, 1, 365),
    ("Heavy, every day: 6 photo + 4 text", 6, 4, 365),
]
_PERIODS_PER_YEAR = {"P1W": 52, "P1M": 12, "P2M": 6, "P3M": 4, "P6M": 2, "P1Y": 1}


def measured_costs(app_dir: str | Path, model: str) -> dict[str, Any] | None:
    """Latest backend/eval/results/*.json score for `model`: cost per call by mode (fal usage.cost)."""
    res = Path(app_dir).expanduser() / "backend" / "eval" / "results"
    for f in sorted(res.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for s in data.get("scores") or []:
            if s.get("model") == model:
                by = s.get("cost_per_call_by_mode") or {}
                return {"photo": by.get("photo") or s.get("cost_per_call_usd"),
                        "text": by.get("text") or s.get("cost_per_call_usd"),
                        "source": f"backend/eval/results/{f.name}"}
    return None


def unit_economics(spec: dict[str, Any], cost_photo: float, cost_text: float, apple_cut: float = 0.15) -> dict[str, Any]:
    caps = spec["usage"]["daily_caps"]
    profiles = PROFILES + [(f"Both caps every day: {caps.get('photo', 0)} photo + {caps.get('text', 0)} text",
                            caps.get("photo", 0), caps.get("text", 0), 365)]
    rows = []
    for label, ph, tx, days in profiles:
        ai_year = (ph * cost_photo + tx * cost_text) * days
        plans = {}
        for p in spec_mod.products(spec):
            revenue = p["usd"] * _PERIODS_PER_YEAR.get(p["period"], 1)
            net = revenue * (1 - apple_cut)
            margin = net - ai_year
            plans[p["key"]] = {"net": round(net, 2), "margin": round(margin, 2),
                               "margin_pct": round(margin / net * 100, 1) if net else 0.0}
        rows.append({"profile": label, "ai_cost_year": round(ai_year, 2), "plans": plans})
    free_cost = spec["usage"].get("free_lifetime_scans", 0) * cost_photo
    warnings = [f"{r['profile']}: {k} loses money ({v['margin']})" for r in rows for k, v in r["plans"].items() if v["margin"] < 0]
    return {"ok": True, "cost_photo": cost_photo, "cost_text": cost_text, "apple_cut": apple_cut,
            "rows": rows, "free_user_cost": round(free_cost, 4), "warnings": warnings}


def _decisions_block(spec: dict[str, Any]) -> str:
    lines = ["| Item | Value |", "|---|---|"]
    for p in spec_mod.products(spec):
        intro = p.get("intro")
        trial = f"{intro['duration']} free trial" if intro else "no intro offer"
        lines.append(f"| `{p['id']}` | ${p['usd']:.2f} per {p['period']}, level {p['level']}, {trial}, "
                     f"offering `{p['offering']}` ({p['package']}) |")
    u = spec["usage"]
    gp = spec["subscription"].get("grace_period") or {}
    lines += [
        f"| Entitlement | RevenueCat `{spec['subscription']['entitlement']}`, granted by every product |",
        f"| Free usage | {u.get('free_lifetime_scans', 0)} lifetime analysis, counted server-side |",
        f"| Subscriber caps | {u['daily_caps'].get('photo', 0)} photo + {u['daily_caps'].get('text', 0)} text per local day |",
        f"| Billing grace period | {'on, ' + gp.get('duration', '') + ', ' + gp.get('renewals', '') + (', sandbox' if gp.get('sandbox') else '') if gp.get('enabled') else 'off'} |",
        f"| Territories | all except {', '.join(EXCLUDED_TERRITORIES)} (generative AI licence) |",
    ]
    return "\n".join(lines)


def _economics_block(econ: dict[str, Any], spec: dict[str, Any], source: str) -> str:
    keys = [p["key"] for p in spec_mod.products(spec)]
    lines = [f"Measured AI cost per call ({source}): photo ${econ['cost_photo']:.4f}, text ${econ['cost_text']:.4f}. "
             f"Apple's cut {int(econ['apple_cut'] * 100)}%. Free user: ≈ ${econ['free_user_cost']:.4f} once.", "",
             "| Usage profile | AI / year | " + " | ".join(f"{k} margin" for k in keys) + " |",
             "|---|---:|" + "---:|" * len(keys)]
    for r in econ["rows"]:
        cells = [f"${r['plans'][k]['margin']:.2f} ({r['plans'][k]['margin_pct']}%)" for k in keys]
        lines.append(f"| {r['profile']} | ${r['ai_cost_year']:.2f} | " + " | ".join(cells) + " |")
    if econ["warnings"]:
        lines += ["", "Loss cases: " + "; ".join(econ["warnings"])]
    return "\n".join(lines)


def _asc_block(spec: dict[str, Any]) -> str:
    lines = ["| Product id | Period | Group level | US price | Introductory offer |", "|---|---|---|---|---|"]
    for p in spec_mod.products(spec):
        intro = f"Free trial {p['intro']['duration']}, all territories" if p.get("intro") else "none"
        lines.append(f"| `{p['id']}` | {PERIODS.get(p['period'], p['period'])} | {p['level']} | ${p['usd']:.2f} | {intro} |")
    lines.append("")
    lines.append("Lower level number = higher tier: moving to it is an upgrade (immediate, prorated).")
    return "\n".join(lines)


def _rc_block(spec: dict[str, Any]) -> str:
    d = desired_state(spec, {"locales": {}})
    lines = ["| Offering | Packages |", "|---|---|"]
    for o in d["revenuecat"]["offerings"]:
        pk = ", ".join(f"`{p['lookup_key']}` → `{p['product_id']}`" for p in o["packages"])
        lines.append(f"| `{o['lookup_key']}`{' (current)' if o['is_current'] else ''} | {pk} |")
    lines += ["", "| Placement | Offering |", "|---|---|"]
    lines += [f"| `{pl}` | `{off}` |" for pl, off in d["revenuecat"]["placements"].items()]
    return "\n".join(lines)


def _local_prices_block(spec: dict[str, Any]) -> str:
    ov = spec["subscription"].get("price_overrides") or {}
    if not ov:
        return "Apple equalization from the US price everywhere; no local overrides."
    keys = [p["key"] for p in spec_mod.products(spec)]
    lines = ["| Currency | Territories | " + " | ".join(keys) + " |", "|---|---|" + "---|" * len(keys)]
    for cur, t in ov.items():
        terrs = CURRENCY_TERRITORIES.get(cur, [])
        lines.append(f"| {cur} | {len(terrs)} ({', '.join(terrs[:6])}{'…' if len(terrs) > 6 else ''}) | "
                     + " | ".join(str(t.get(k, "equalized")) for k in keys) + " |")
    lines.append("")
    lines.append("Applied by store_setup (live runs read each territory's currency from ASC).")
    return "\n".join(lines)


def _anchor_block(spec: dict[str, Any]) -> str:
    a = spec.get("offer_anchor") or {}
    offer = next((p for p in spec_mod.products(spec) if p.get("offering") == "offer"), None)
    if not offer:
        return "No offer product."
    per_month = offer["usd"] / (12 if offer["period"] == "P1Y" else 1)
    return (f"Anchor item: **{a.get('item', '?')}** (string key `{a.get('label_key', '')}`). "
            f"US offer per month: ${per_month:.2f}. Check every storefront's local offer price ÷ 12 "
            "against the anchor's local price before shipping the copy.")


def write_pricing(app_dir: str | Path, cost_photo: float | None = None, cost_text: float | None = None,
                  apple_cut: float = 0.15) -> dict[str, Any]:
    """pricing_unit_economics: measured cost (eval results, or explicit) → store/pricing.md blocks."""
    from . import supabase as supa
    app = Path(app_dir).expanduser()
    sp = spec_mod.load(app)
    source = "explicit"
    if cost_photo is None or cost_text is None:
        m = measured_costs(app, sp["ai"]["model"])
        if not m:
            return {"ok": False, "error": f"no measured cost for {sp['ai']['model']} in backend/eval/results "
                                          "(run the eval with the lead's go, or pass cost_photo/cost_text)"}
        cost_photo = cost_photo if cost_photo is not None else m["photo"]
        cost_text = cost_text if cost_text is not None else m["text"]
        source = m["source"]
    econ = unit_economics(sp, float(cost_photo), float(cost_text), apple_cut)
    p = app / "store" / "pricing.md"
    if not p.exists():
        return {"ok": False, "error": "store/pricing.md not found", "economics": econ}
    text = p.read_text(encoding="utf-8")
    for name, body in (("decisions", _decisions_block(sp)), ("unit-economics", _economics_block(econ, sp, source)),
                       ("asc-layout", _asc_block(sp)), ("rc-layout", _rc_block(sp)),
                       ("local-prices", _local_prices_block(sp)), ("offer-anchor", _anchor_block(sp))):
        text = supa._replace_block(text, name, body)
    p.write_text(text, encoding="utf-8")
    return {**econ, "source": source, "written": "store/pricing.md"}
