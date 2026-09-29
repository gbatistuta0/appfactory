"""App Store Connect client — every call goes through the `asc` CLI (asc_cli.py).

ASCClient's named methods run first-class asc commands; `ASCClient.request` is the `asc api` raw
passthrough for resources without one. Both return {ok, status, data|error} with Apple's JSON:API
envelope under `data`.

App creation is the one exception: Apple's public API cannot create an app record. asc can only do
it through an Apple web session (`asc web apps create`, interactive 2FA), the same constraint
fastlane produce has, so the existing produce path (FASTLANE_SESSION from `fastlane spaceauth`) is
kept for it.
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import asc_cli
from . import config as cfg


def _fastlane_runtime() -> tuple[str, dict[str, str]]:
    """Return the fastlane binary path plus an env whose PATH has a compatible Ruby.

    The system Ruby may be incompatible with fastlane (e.g. Ruby 4.x). If present,
    prefer fastlane installed under Homebrew ruby@3.3, and prepend that Ruby's bin
    to PATH so the shebang resolves the right interpreter.
    """
    env = os.environ.copy()
    candidates = [
        "/opt/homebrew/opt/ruby@3.3/bin",
        "/opt/homebrew/opt/ruby@3.2/bin",
        "/usr/local/opt/ruby@3.3/bin",
    ]
    gem_bins = [
        "/opt/homebrew/lib/ruby/gems/3.3.0/bin",
        "/opt/homebrew/lib/ruby/gems/3.2.0/bin",
        "/usr/local/lib/ruby/gems/3.3.0/bin",
    ]
    fastlane_bin = "fastlane"
    for rb, gb in zip(candidates, gem_bins):
        cand = os.path.join(gb, "fastlane")
        if os.path.exists(cand) and os.path.isdir(rb):
            env["PATH"] = f"{rb}:{gb}:" + env.get("PATH", "")
            fastlane_bin = cand
            break
    return fastlane_bin, env


def create_app_via_produce(bundle_id: str, app_name: str, sku: str | None = None, primary_language: str = "en-US") -> dict[str, Any]:
    """Create the app SHELL in App Store Connect (fastlane produce).

    Apple's ASC API does not support creating apps, so produce needs an Apple ID + an
    app-specific password. Fully automatic; the user does not add it by hand.
    """
    c = cfg.load_config()
    apple_id = c.get("apple_id")
    pw = c.get("apple_app_specific_password")
    team = c.get("team_id")
    # Session comes from the file first (multi-line YAML), otherwise from config.
    session_file = cfg.CONFIG_DIR / "fastlane_session.yml"
    session = session_file.read_text(encoding="utf-8") if session_file.exists() else c.get("apple_session")
    if not apple_id or not (session or pw):
        return {"ok": False, "error": "apple_id + apple_session (fastlane spaceauth) is required. Creating an app needs a 2FA web session; an app-specific password is not enough."}
    fastlane_bin, env = _fastlane_runtime()
    if session:
        env["FASTLANE_SESSION"] = session
    if pw:
        env["FASTLANE_PASSWORD"] = pw
    # Apple App ID names reject special characters (':' etc.), so strip them.
    clean_name = re.sub(r"[^A-Za-z0-9 ]", " ", app_name).strip()
    clean_name = re.sub(r"\s+", " ", clean_name)
    cmd = [fastlane_bin, "produce", "--username", apple_id, "--app_identifier", bundle_id,
           "--app_name", clean_name, "--language", primary_language,
           "--sku", sku or bundle_id.replace(".", "")]
    if team:
        cmd += ["--team_id", team]
    itc = c.get("itc_team_id")  # ASC team id (required on multi-team accounts)
    if itc:
        cmd += ["--itc_team_id", str(itc)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        full = p.stdout + p.stderr  # the marker is at the HEAD of stderr — scan it BEFORE truncating
        name_taken = any(m in full for m in _NAME_TAKEN_MARKERS)
        return {"ok": p.returncode == 0, "stdout": p.stdout.strip()[-1200:],
                "stderr": p.stderr.strip()[-1200:], "name_taken": name_taken}
    except FileNotFoundError:
        return {"ok": False, "error": "fastlane not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "produce timed out"}

_NAME_TAKEN_MARKERS = ("already being used", "already been used", "/included/1/name")


def create_app_auto(bundle_id: str, candidate_names: list[str], sku: str | None = None,
                    primary_language: str = "en-US") -> dict[str, Any]:
    """Create the app SHELL in App Store Connect, picking a UNIQUE name automatically.

    App Store app names are globally unique. Tries the candidate names in order and
    moves to the next one on a "name taken" error. On success it verifies via the API
    and returns {ok, app_id, name}. n8n-style: keeps going without stopping.
    """
    if not candidate_names:
        return {"ok": False, "error": "candidate_names is empty"}
    tried: list[str] = []
    for name in candidate_names:
        r = create_app_via_produce(bundle_id, name, sku=sku, primary_language=primary_language)
        blob = (r.get("stdout", "") + r.get("stderr", "") + str(r.get("error", ""))).lower()
        tried.append(name)
        if r.get("ok") or ("already exists" in blob and "app store connect" in blob):
            chosen = name
            break
        if r.get("name_taken") or any(m in blob for m in _NAME_TAKEN_MARKERS):
            continue  # name taken -> next candidate (marker is at the HEAD of stderr, so truncation does not hide it)
        # any other error: stop and report
        return {"ok": False, "error": r.get("stderr") or r.get("error"), "tried": tried}
    else:
        return {"ok": False, "error": "all candidate names are taken", "tried": tried}
    # Verify + app_id
    try:
        cl = ASCClient()
        data = asc_cli.items(cl.get_app_by_bundle(bundle_id))
        if data:
            return {"ok": True, "app_id": data[0]["id"], "name": data[0]["attributes"].get("name"),
                    "chosen_name": chosen, "tried": tried}
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "name": chosen, "tried": tried, "verify_error": str(e)}
    return {"ok": True, "name": chosen, "tried": tried}


# Intro offers are NOT embedded any more: they follow app.spec.json (products[].intro) and are
# created PER TERRITORY (ASC rejects an offer without a territory: ENTITY_ERROR.RELATIONSHIP.REQUIRED).
# The old embedded defaults ($37.49 pay-up-front on every yearly, a trial on every weekly) were wrong
# (trial on yearly, nothing on yearly.offer). store_setup is the spec-driven path; see store/CHECKLIST.md.
SPEC_INTRO_DURATIONS = {"P3D": "THREE_DAYS", "P1W": "ONE_WEEK", "P2W": "TWO_WEEKS", "P1M": "ONE_MONTH",
                        "P2M": "TWO_MONTHS", "P3M": "THREE_MONTHS", "P6M": "SIX_MONTHS", "P1Y": "ONE_YEAR"}


def intro_from_spec(intro: dict | None) -> dict | None:
    """spec product intro {"type": "free", "duration": "P3D"} → ASC {mode, duration}; None stays None."""
    if not intro:
        return None
    if intro.get("type") != "free":
        raise ValueError(f"unsupported intro type {intro.get('type')!r} (only free trials are spec-driven)")
    return {"mode": "FREE_TRIAL", "duration": SPEC_INTRO_DURATIONS[intro["duration"]]}


# App Review Notes (appStoreReviewDetails.notes ≤4000). 7-madde, app-jenerik + parametreli.
# Filled on every submit-prep to avoid an Apple 2.1 rejection (missing App Review notes/test steps).
REVIEW_NOTES_TEMPLATE = """\
1) App purpose: {app_name} is an AI-powered iPhone app. {app_purpose}

2) AI services: The app generates results via cloud AI ({ai_services}). All AI calls go through our backend proxy; no API keys are stored on-device.

3) No login required: The app is fully anonymous. There is no sign-up, no account, and no demo credentials are needed. Anonymous usage is enforced server-side.

4) In-App Purchases: First result is FREE (1 credit on first launch). Subscriptions: Weekly and Yearly auto-renewable subscriptions grant a recurring credit allowance that refreshes each subscription period (the Weekly and Yearly tiers differ in the number of credits granted per period). The Weekly subscription includes a 3-day free trial; it renews at the standard weekly price after the trial unless cancelled. If the user dismisses the first paywall, a one-time discounted offer subscription is shown. Subscriptions are managed via RevenueCat / Apple StoreKit.

5) Supported devices: iPhone only, portrait orientation. iOS 17.5+.

6) How to test: Launch the app → complete the short onboarding → use the 1 free credit to generate a result → dismiss the paywall to see the discounted offer paywall. No login or special setup required.

7) Contact: {contact_email}
"""


# Subscription disclosure in the description (Apple 3.1.2). The marker keeps it idempotent and prevents double insertion.
APPLE_STD_EULA = "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"
DISCLOSURE_MARKER = "--- Subscription & Legal ---"
DEFAULT_DISCLOSURE = (
    "Auto-renewable subscriptions. Payment is charged to your Apple ID account at "
    "purchase confirmation. The subscription renews automatically unless cancelled at "
    "least 24 hours before the end of the current period. Manage or cancel anytime in "
    "your App Store account settings."
)


FIRST_SUBSCRIPTION_STEPS = (
    "ASC web UI → the app → the iOS version page → 'In-App Purchases and Subscriptions' → select every "
    "subscription → Add for Review → Submit (the version and its subscriptions go into ONE review submission)")


def submission_blockers(states: dict[str, str]) -> list[str]:
    """Why an API submission of the version must not run:
    - MISSING_METADATA: usually a territory without a price (the excluded ones too: ASC answers
      IAP_SUBMISSION_NOT_ALLOWED_MISSING_PRICING_DATA) or a missing localization / review screenshot;
    - READY_TO_SUBMIT: a first subscription can only be submitted ON the version
      (FIRST_SUBSCRIPTION_MUST_BE_SUBMITTED_ON_VERSION); reviewSubmissionItems has no subscription
      relationship, so an API-submitted version would go to review without its products — a paywall
      with nothing to buy is a rejection."""
    out = []
    for pid, st in sorted(states.items()):
        if st == "MISSING_METADATA":
            out.append(f"{pid}: MISSING_METADATA — run store_setup check (prices in every territory incl. unsold "
                       "ones, localizations, review screenshot)")
        elif st == "READY_TO_SUBMIT":
            out.append(f"{pid}: READY_TO_SUBMIT — a first subscription is submitted with the version: "
                       + FIRST_SUBSCRIPTION_STEPS)
    return out


class ASCError(Exception):
    pass


def _f(name: str, value: Any) -> str:
    return asc_cli.flag(name, value)


def _first_id(r: dict[str, Any]) -> str | None:
    it = asc_cli.items(r)
    return it[0].get("id") if it else None


class ASCClient:
    """App Store Connect through the `asc` CLI (see asc_cli.py).

    `request` is the raw `asc api` passthrough and keeps the old httpx result shape
    ({ok, status, data|error}); it serves the generic JSON:API code (store_setup, gates, reads that
    have no first-class command). The named methods run first-class asc commands and return the
    same shape, with Apple's JSON:API envelope under `data`."""

    def __init__(self, timeout: float = asc_cli.DEFAULT_TIMEOUT):
        if not asc_cli.binary():
            raise ASCError(asc_cli.INSTALL_HINT)
        self._timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict[str, Any]:
        """Raw ASC API call through `asc api` ({ok, status, data|error})."""
        return asc_cli.api(method, path, params=params, body=json, timeout=self._timeout)

    def _cli(self, *args: str, timeout: float | None = None) -> dict[str, Any]:
        return asc_cli.cli(list(args), timeout=timeout or self._timeout)

    # ---- reads ----
    def list_apps(self, limit: int = 100) -> dict[str, Any]:
        return self._cli("apps", "list", _f("limit", limit))

    def get_app_by_bundle(self, bundle_id: str) -> dict[str, Any]:
        return self._cli("apps", "list", _f("bundle-id", bundle_id))

    def list_bundle_ids(self, limit: int = 200) -> dict[str, Any]:
        return self._cli("bundle-ids", "list", _f("limit", limit))

    def bundle_ids(self, identifier: str) -> dict[str, Any]:
        """Bundle id resources whose identifier CONTAINS `identifier` (ASC's filter is a substring
        match; signing.exact_bundle_resource picks the exact one)."""
        return self._cli("bundle-ids", "list", _f("identifier", identifier), _f("limit", 50))

    def versions(self, app_id: str, limit: int = 1, state: str | None = None,
                 platform: str | None = None) -> list[dict[str, Any]]:
        args = ["versions", "list", _f("app", app_id), _f("limit", limit)]
        if state:
            args.append(_f("state", state))
        if platform:
            args.append(_f("platform", platform))
        return asc_cli.items(self._cli(*args))

    def territories(self) -> list[str]:
        return [t["id"] for t in asc_cli.items(self._cli("pricing", "territories", "list", "--paginate", _f("limit", 200)))]

    # ---- creation (real side effects) ----
    def create_bundle_id(self, identifier: str, name: str) -> dict[str, Any]:
        return self._cli("bundle-ids", "create", _f("identifier", identifier), _f("name", name), _f("platform", "IOS"))

    def create_subscription_group(self, app_id: str, reference_name: str) -> dict[str, Any]:
        return self._cli("subscriptions", "groups", "create", _f("app", app_id), _f("reference-name", reference_name))

    def create_subscription(
        self, group_id: str, product_id: str, name: str, period: str, family_shareable: bool = False
    ) -> dict[str, Any]:
        """period: ONE_WEEK | ONE_MONTH | TWO_MONTHS | THREE_MONTHS | SIX_MONTHS | ONE_YEAR.
        Price is a separate step (set_subscription_price)."""
        args = ["subscriptions", "create", _f("group-id", group_id), _f("product-id", product_id),
                _f("reference-name", name), _f("subscription-period", period)]
        if family_shareable:
            args.append(_f("family-sharable", True))
        return self._cli(*args)

    # ---- subscription finalize (clears MISSING_METADATA) ----
    # Localizations use the legacy /v1/subscriptionLocalizations + /v1/subscriptionGroupLocalizations
    # resources through `asc api`: asc's first-class localization commands are version-scoped
    # (API 4.4.1 subscriptionVersions), a different model from the one the pipeline reads back.
    def add_subscription_localization(self, sub_id: str, name: str, description: str, locale: str = "en-US") -> dict[str, Any]:
        """Subscription display name + description (description <= ~45 characters)."""
        return self.request("POST", "/v1/subscriptionLocalizations", json={"data": {
            "type": "subscriptionLocalizations",
            "attributes": {"locale": locale, "name": name[:30], "description": description[:45]},
            "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub_id}}},
        }})

    def add_subscription_group_localization(self, group_id: str, name: str, locale: str = "en-US") -> dict[str, Any]:
        return self.request("POST", "/v1/subscriptionGroupLocalizations", json={"data": {
            "type": "subscriptionGroupLocalizations",
            "attributes": {"name": name[:30], "locale": locale},
            "relationships": {"subscriptionGroup": {"data": {"type": "subscriptionGroups", "id": group_id}}},
        }})

    def set_subscription_availability_all(self, sub_id: str, excluded: tuple[str, ...] = ("CHN",)) -> dict[str, Any]:
        """Sell the subscription in EVERY territory except `excluded` (must precede pricing, otherwise
        the price write answers 409)."""
        terrs = [t for t in self.territories() if t not in excluded]
        if not terrs:
            return {"ok": False, "error": "no territories returned by asc pricing territories list"}
        return self._cli("subscriptions", "pricing", "availability", "edit", _f("subscription-id", sub_id),
                         _f("territories", ",".join(terrs)), _f("available-in-new-territories", True))

    def _find_price_point(self, sub_id: str, usd_price: str, territory: str = "USA") -> str | None:
        r = self._cli("subscriptions", "pricing", "price-points", "list", _f("subscription-id", sub_id),
                      _f("territory", territory), _f("price", usd_price), "--paginate", _f("limit", 200))
        for p in asc_cli.items(r):
            if _same_price((p.get("attributes") or {}).get("customerPrice"), usd_price):
                return p["id"]
        return None

    def set_subscription_price(self, sub_id: str, usd_price: str) -> dict[str, Any]:
        """Price in EVERY territory ("Recalculate prices for all countries or regions"). A single
        price point sets only its own territory (tested 2026-06-25) and leaves the subscription
        MISSING_METADATA, so the USA point plus its ~174 equalizations are imported in one
        `asc subscriptions pricing prices import`. Unsold territories are priced too (ASC requires
        it). `asc subscriptions pricing equalize` is not used: it refuses while any equalized
        territory is outside the availability (CHN is, on purpose). Availability must be set first."""
        pp = self._find_price_point(sub_id, usd_price)
        if not pp:
            return {"ok": False, "error": f"{usd_price} USD price point not found"}
        eq = self._cli("subscriptions", "pricing", "price-points", "equalizations", _f("price-point-id", pp),
                       _f("include", "territory"), "--paginate", _f("limit", 200))
        if not eq.get("ok"):
            return {"ok": False, "error": eq.get("error"), "step": "equalizations"}
        rows = [("USA", usd_price, pp)]
        for x in asc_cli.items(eq):
            terr = (((x.get("relationships") or {}).get("territory") or {}).get("data") or {}).get("id")
            price = (x.get("attributes") or {}).get("customerPrice")
            if terr and price is not None:
                rows.append((terr, price, x["id"]))
        fd, path = tempfile.mkstemp(suffix=".csv", prefix="asc_prices_")
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["territory", "price", "price_point_id"])
                w.writerows(rows)
            r = asc_cli.run(["subscriptions", "pricing", "prices", "import", _f("subscription-id", sub_id),
                             _f("input", path), "--confirm"], timeout=1200)
        finally:
            os.unlink(path)
        data = r.get("data") if isinstance(r.get("data"), dict) else {}
        created, failed = int(data.get("created") or 0), int(data.get("failed") or 0)
        out: dict[str, Any] = {"ok": created > 0, "territories_set": created,
                               "skipped_or_failed": failed + max(0, len(rows) - created - failed)}
        if not r.get("ok") and not created:
            out["error"] = r.get("error")
        return out

    def create_introductory_offer(self, sub_id: str, usd_price: str | None, duration: str,
                                  mode: str = "PAY_AS_YOU_GO", territory: str = "USA") -> dict[str, Any]:
        """ONE intro offer in ONE territory (ASC requires the territory). duration:
        THREE_DAYS|ONE_WEEK|TWO_WEEKS|ONE_MONTH|TWO_MONTHS|THREE_MONTHS|SIX_MONTHS|ONE_YEAR.
        mode: FREE_TRIAL (no price point) | PAY_AS_YOU_GO | PAY_UP_FRONT (usd_price must be a valid tier)."""
        args = ["subscriptions", "offers", "introductory", "create", _f("subscription-id", sub_id),
                _f("territory", territory), _f("offer-mode", mode), _f("offer-duration", duration),
                _f("number-of-periods", 1)]
        if mode != "FREE_TRIAL":
            if not usd_price:
                return {"ok": False, "error": f"usd_price is required for {mode}"}
            pp = self._find_price_point(sub_id, usd_price, territory)
            if not pp:
                return {"ok": False, "error": f"{usd_price} price point not found in {territory}"}
            args.append(_f("price-point", pp))
        return self._cli(*args)

    def create_intro_offer_all_territories(self, sub_id: str, mode: str, duration: str,
                                           excluded: tuple[str, ...] = ("CHN",)) -> dict[str, Any]:
        """The same free-trial intro offer in every territory the subscription is available in
        (`--all-territories`; territories that already have one are skipped by asc). The availability
        already leaves out `excluded` (set_subscription_availability_all); the parameter is kept for
        callers."""
        r = asc_cli.run(["subscriptions", "offers", "introductory", "create", _f("subscription-id", sub_id),
                         "--all-territories", _f("offer-mode", mode), _f("offer-duration", duration),
                         _f("number-of-periods", 1), _f("continue-on-error", True)], timeout=1800)
        data = r.get("data") if isinstance(r.get("data"), dict) else {}
        fails = data.get("failures") or data.get("errors") or []
        failed = [x.get("territory") if isinstance(x, dict) else x for x in fails]
        n_failed = int(data.get("failed") or len(failed))
        out = {"ok": bool(r.get("ok")) and n_failed == 0, "created": int(data.get("created") or 0),
               "already": int(data.get("skipped") or 0), "failed": failed[:10]}
        if not r.get("ok"):
            out["error"] = r.get("error")
        return out

    def localize_subscription(self, sub_id: str, items: dict[str, dict[str, str]]) -> dict[str, Any]:
        """Localize the subscription into MANY languages. items={locale:{name,description}}. Languages
        ASC does not support for IAP fail (expected, skipped). Existing locales are skipped."""
        ex = {x["attributes"]["locale"] for x in self.request(
            "GET", f"/v1/subscriptions/{sub_id}/subscriptionLocalizations",
            params={"limit": 200}).get("data", {}).get("data", [])}
        ok, fail = 0, 0
        for loc, v in items.items():
            if loc in ex:
                continue
            r = self.request("POST", "/v1/subscriptionLocalizations", json={"data": {
                "type": "subscriptionLocalizations",
                "attributes": {"locale": loc, "name": v["name"][:30], "description": v["description"][:45]},
                "relationships": {"subscription": {"data": {"type": "subscriptions", "id": sub_id}}}}})
            ok += 1 if r.get("ok") else 0
            fail += 0 if r.get("ok") else 1
        return {"ok": ok > 0, "localized": ok, "unsupported": fail}

    def localize_group(self, group_id: str, name_by_locale: dict[str, str]) -> dict[str, Any]:
        """Localize the subscription group name into many languages (languages without IAP support are skipped)."""
        ex = {x["attributes"]["locale"] for x in self.request(
            "GET", f"/v1/subscriptionGroups/{group_id}/subscriptionGroupLocalizations",
            params={"limit": 200}).get("data", {}).get("data", [])}
        ok, fail = 0, 0
        for loc, name in name_by_locale.items():
            if loc in ex:
                continue
            r = self.request("POST", "/v1/subscriptionGroupLocalizations", json={"data": {
                "type": "subscriptionGroupLocalizations",
                "attributes": {"name": name[:30], "locale": loc},
                "relationships": {"subscriptionGroup": {"data": {"type": "subscriptionGroups", "id": group_id}}}}})
            ok += 1 if r.get("ok") else 0
            fail += 0 if r.get("ok") else 1
        return {"ok": ok > 0, "localized": ok, "unsupported": fail}

    def finalize_subscription(self, sub_id: str, name: str, description: str, usd_price: str,
                              period: str | None = None, intro: dict | None = None) -> dict[str, Any]:
        """Subscription setup (ORDER matters): localization → availability → price → intro offer.
        The intro offer follows the SPEC: pass `intro` as the spec product's intro
        ({"type": "free", "duration": "P3D"}) — it is created in every territory. No intro (offer
        products) → none is created. `period` is ignored (it used to attach embedded offers; that broke
        a real app). Prefer store_setup, which does all of this idempotently from app.spec.json."""
        steps = {}
        steps["localization"] = self.add_subscription_localization(sub_id, name, description)
        steps["availability"] = self.set_subscription_availability_all(sub_id)
        steps["price"] = self.set_subscription_price(sub_id, usd_price)
        want = intro_from_spec(intro)
        if want:
            steps["intro_offer"] = self.create_intro_offer_all_territories(sub_id, want["mode"], want["duration"])
        out = {"ok": all(s.get("ok") for s in steps.values()), "steps": steps}
        if period:
            out["note"] = "period is ignored: intro offers follow the spec (pass intro=…)"
        return out

    def create_review_submission(self, app_id: str, platform: str = "IOS") -> dict[str, Any]:
        return self._cli("review", "submissions-create", _f("app", app_id), _f("platform", platform))

    def subscription_states(self, app_id: str) -> dict[str, str]:
        """productId → ASC subscription state for every subscription of the app."""
        out: dict[str, str] = {}
        for s in asc_cli.items(self._cli("subscriptions", "list", _f("app", app_id), "--paginate", _f("limit", 200))):
            a = s.get("attributes") or {}
            out[a.get("productId") or s["id"]] = a.get("state") or "UNKNOWN"
        return out

    def submit_review(self, review_submission_id: str) -> dict[str, Any]:
        """Send the review submission (submitted=true). The single store release gate."""
        return self._cli("review", "submissions-submit", _f("id", review_submission_id), "--confirm")

    def finalize_submission_requirements(self, bundle_id: str, *, copyright: str,
                                         contact_first: str, contact_last: str,
                                         contact_phone: str, contact_email: str,
                                         free: bool = True, review_notes: str | None = None,
                                         app_name: str | None = None,
                                         ai_services: str | None = None) -> dict[str, Any]:
        """Fill the submit-blocking app-level fields in ONE pass: content rights + copyright +
        age rating (4+, no sensitive content) + free price + App Review contact + notes. App Privacy
        is EXCLUDED (not in Apple's API; do it in the ASC web UI, see the playbook). Photo/AI app defaults.
        review_notes verilirse aynen (≤4000); verilmezse REVIEW_NOTES_TEMPLATE app_name/ai_services
        (falls back to the ASC app name when app_name is missing, and a generic default when ai_services is missing)."""
        steps: dict[str, Any] = {}
        apps = asc_cli.items(self.get_app_by_bundle(bundle_id))
        if not apps:
            return {"ok": False, "error": f"app not found: {bundle_id}"}
        aid = apps[0]["id"]
        vs = self.versions(aid, limit=1)
        if not vs:
            return {"ok": False, "error": "appStoreVersion not found"}
        vid = vs[0]["id"]
        # 1) Content Rights
        steps["content_rights"] = self._cli("apps", "content-rights", "edit", _f("app", aid),
                                            _f("uses-third-party-content", False)).get("ok")
        # 2) Copyright
        steps["copyright"] = self._cli("versions", "update", _f("version-id", vid), _f("copyright", copyright)).get("ok")
        # 3) Age rating 4+: every content descriptor NONE, every boolean false (Apple's 2025
        #    questionnaire makes all of them required) — asc's --all-none sets exactly that.
        steps["age_rating"] = self._cli("age-rating", "edit", _f("app", aid), "--all-none").get("ok")
        # 4) Free price (USA base) only when the app has no price schedule yet
        if free and not self._cli("pricing", "schedule", "view", _f("app", aid)).get("ok"):
            steps["price"] = self._cli("pricing", "schedule", "create", _f("app", aid), "--free",
                                       _f("base-territory", "USA")).get("ok")
        # 5) App Review contact + notes (Apple 2.1: test steps + AI services)
        notes = review_notes[:4000] if review_notes else REVIEW_NOTES_TEMPLATE.format(
            app_name=app_name or (apps[0].get("attributes") or {}).get("name") or "This app",
            app_purpose="It turns a user request into an AI-generated result.",
            ai_services=ai_services or "OpenAI / image-generation models",
            contact_email=contact_email,
        )[:4000]
        contact = [_f(k, v) for k, v in (("contact-first-name", contact_first), ("contact-last-name", contact_last),
                                         ("contact-phone", contact_phone), ("contact-email", contact_email),
                                         ("notes", notes)) if v]
        contact.append(_f("demo-account-required", False))
        ex = _first_id(self._cli("review", "details-for-version", _f("version-id", vid)))
        if ex:
            steps["contact"] = self._cli("review", "details-update", _f("id", ex), *contact).get("ok")
        else:
            steps["contact"] = self._cli("review", "details-create", _f("version-id", vid), *contact).get("ok")
        return {"ok": all(v for v in steps.values()), "steps": steps,
                "note": "App Privacy (nutrition label) is NOT in Apple's API; it must be done in the ASC web UI."}

    def append_subscription_disclosure(self, bundle_id: str, *, privacy_url: str,
                                       terms_url: str | None = None,
                                       disclosure_by_locale: dict[str, str] | None = None) -> dict[str, Any]:
        """APPEND the subscription disclosure + Terms/EULA + Privacy to the description (every version-localization).
        Prevents an Apple 3.1.2 rejection (auto-renewable terms missing from the description). Idempotent:
        skipped when DISCLOSURE_MARKER is already present (no double insertion). Without terms_url, Apple's
        standard EULA is used. Truncated to <=4000. disclosure_by_locale is an optional per-locale block text;
        otherwise the English default."""
        apps = asc_cli.items(self.get_app_by_bundle(bundle_id))
        if not apps:
            return {"ok": False, "error": f"app not found: {bundle_id}"}
        vs = self.versions(apps[0]["id"], limit=1)
        if not vs:
            return {"ok": False, "error": "appStoreVersion not found"}
        vid = vs[0]["id"]
        terms = terms_url or APPLE_STD_EULA
        locs = asc_cli.items(self._cli("localizations", "list", _f("version", vid), "--paginate", _f("limit", 200)))
        patched, skipped_existing, skipped_missing = [], [], []
        for loc in locs:
            lid = loc["id"]
            locale = loc["attributes"].get("locale", "")
            desc = loc["attributes"].get("description") or ""
            if DISCLOSURE_MARKER in desc:
                skipped_existing.append(locale)
                continue
            body = (disclosure_by_locale or {}).get(locale) or DEFAULT_DISCLOSURE
            block = f"\n\n{DISCLOSURE_MARKER}\n{body}\nTerms of Use (EULA): {terms}\nPrivacy Policy: {privacy_url}"
            new_desc = (desc + block)[:4000]
            if DISCLOSURE_MARKER not in new_desc:
                # description too long -> the block does not fit; skip this locale (truncation-safe).
                skipped_missing.append(locale)
                continue
            r = self._cli("localizations", "update", _f("id", lid), _f("description", new_desc))
            if r.get("ok"):
                patched.append(locale)
            else:
                skipped_missing.append(locale)
        return {"ok": len(patched) > 0 or len(skipped_existing) > 0, "patched": patched,
                "skipped_existing": skipped_existing, "skipped_missing": skipped_missing}

    def ensure_subscription_prices(self, app_id: str, usd_price_by_product: dict[str, str] | None = None,
                                   default_usd: str | None = None) -> dict[str, Any]:
        """Walk ALL of the app's subscriptions and apply set_subscription_price to those WITHOUT a price.
        Clears MISSING_METADATA (missing price). Idempotent: priced ones are skipped. The price
        comes from usd_price_by_product[productId] or default_usd. Returns {ok, set, already, no_price}."""
        set_, already, no_price = [], [], []
        for s in asc_cli.items(self._cli("subscriptions", "list", _f("app", app_id), "--paginate", _f("limit", 200))):
            sid = s["id"]
            product_id = (s.get("attributes") or {}).get("productId", "")
            # RULE (2026-06-25): the price must exist in ALL countries ("Recalculate prices for all
            # countries or regions"). A single/few-country price (e.g. US only) leaves MISSING_METADATA.
            # So "has a price" is not enough; if the territory count is low, apply it AGAIN.
            cnt = len(asc_cli.items(self._cli("subscriptions", "pricing", "prices", "list", _f("subscription-id", sid),
                                              "--paginate", _f("limit", 200))))
            if cnt >= 100:  # all-country coverage (~175) -> done
                already.append(product_id or sid)
                continue
            price = (usd_price_by_product or {}).get(product_id) or default_usd
            if not price:
                no_price.append(product_id or sid)
                continue
            r = self.set_subscription_price(sid, price)
            if r.get("ok"):
                set_.append({"productId": product_id, "price": price})
            else:
                no_price.append(product_id or sid)
        return {"ok": len(no_price) == 0, "set": set_, "already": already, "no_price": no_price}

    # ---- media (screenshots, previews, review screenshots) ----
    def upload_screenshot(self, localization_id: str, path: str | Path, display_type: str) -> dict[str, Any]:
        """One screenshot into the localization's set for `display_type` (asc creates the set if
        needed, reserves, uploads and commits with the MD5 checksum). {ok, id}."""
        r = asc_cli.run(["screenshots", "upload", _f("version-localization", localization_id),
                         _f("path", str(path)), _f("device-type", display_type)], timeout=asc_cli.UPLOAD_TIMEOUT)
        return _upload_result(r)

    def delete_screenshot(self, screenshot_id: str) -> dict[str, Any]:
        return self._cli("screenshots", "delete", _f("id", screenshot_id), "--confirm")

    def upload_preview(self, localization_id: str, path: str | Path, preview_type: str) -> dict[str, Any]:
        r = asc_cli.run(["video-previews", "upload", _f("version-localization", localization_id),
                         _f("path", str(path)), _f("device-type", preview_type)], timeout=asc_cli.UPLOAD_TIMEOUT)
        return _upload_result(r)

    def set_preview_poster(self, preview_id: str, time_code: str) -> dict[str, Any]:
        return self._cli("video-previews", "set-poster-frame", _f("id", preview_id), _f("time-code", time_code))

    def delete_preview(self, preview_id: str) -> dict[str, Any]:
        return self._cli("video-previews", "delete", _f("id", preview_id), "--confirm")

    def upload_subscription_review_screenshot(self, sub_id: str, path: str | Path) -> dict[str, Any]:
        r = self._cli("subscriptions", "review", "screenshots", "create", _f("subscription-id", sub_id),
                      _f("file", str(path)), timeout=asc_cli.UPLOAD_TIMEOUT)
        if not r.get("ok"):
            return {"ok": False, "step": "upload", "error": r.get("error")}
        return {"ok": True, "id": _first_id(r)}

    def delete_subscription_review_screenshot(self, shot_id: str) -> dict[str, Any]:
        return self._cli("subscriptions", "review", "screenshots", "delete", _f("screenshot-id", shot_id), "--confirm")

    # ---- metadata ----
    def update_localization(self, localization_id: str, attrs: dict[str, str], app_info: bool = False) -> dict[str, Any]:
        """Patch an appStoreVersionLocalization (or, app_info=True, an appInfoLocalization) by id.
        attrs use the API attribute names (description, keywords, promotionalText, supportUrl,
        marketingUrl / name, subtitle, privacyPolicyUrl)."""
        args = ["localizations", "update", _f("id", localization_id)]
        if app_info:
            args.append(_f("type", "app-info"))
        args += [_f(_LOC_FLAGS[k], v) for k, v in attrs.items() if v]
        return self._cli(*args)

    def create_version_localization(self, version_id: str, locale: str, attrs: dict[str, str]) -> dict[str, Any]:
        return self._cli("localizations", "create", _f("version", version_id), _f("locale", locale),
                         *[_f(_LOC_FLAGS[k], v) for k, v in attrs.items() if v])

    def set_categories(self, app_id: str, primary: str, secondary: str | None = None,
                       app_info_id: str | None = None) -> dict[str, Any]:
        args = ["categories", "set", _f("app", app_id), _f("primary", primary)]
        if secondary:
            args.append(_f("secondary", secondary))
        if app_info_id:
            args.append(_f("app-info", app_info_id))
        return self._cli(*args)

    # ---- custom product pages ----
    def create_custom_product_page(self, app_id: str, name: str, visible: bool = True) -> dict[str, Any]:
        r = self._cli("product-pages", "custom-pages", "create", _f("app", app_id), _f("name", name))
        cid = _first_id(r) if r.get("ok") else None
        if cid and visible:
            v = self._cli("product-pages", "custom-pages", "update", _f("custom-page-id", cid), _f("visible", True))
            if not v.get("ok"):
                return {"ok": False, "error": v.get("error"), "id": cid}
        return r

    def create_custom_product_page_version(self, page_id: str) -> dict[str, Any]:
        return self._cli("product-pages", "custom-pages", "versions", "create", _f("custom-page-id", page_id))

    def create_custom_product_page_localization(self, version_id: str, locale: str) -> dict[str, Any]:
        return self._cli("product-pages", "custom-pages", "localizations", "create",
                         _f("custom-page-version-id", version_id), _f("locale", locale))

    # ---- signing + builds ----
    def create_certificate(self, csr_path: str | Path, certificate_type: str = "DISTRIBUTION") -> dict[str, Any]:
        return self._cli("certificates", "create", _f("certificate-type", certificate_type), _f("csr", str(csr_path)))

    def profiles_by_name(self, name: str) -> list[dict[str, Any]]:
        return asc_cli.items(self._cli("profiles", "list", _f("name", name), _f("limit", 20)))

    def delete_profile(self, profile_id: str) -> dict[str, Any]:
        return self._cli("profiles", "delete", _f("id", profile_id), "--confirm")

    def create_profile(self, name: str, bundle_resource_id: str, cert_id: str,
                       profile_type: str = "IOS_APP_STORE") -> dict[str, Any]:
        return self._cli("profiles", "create", _f("name", name), _f("profile-type", profile_type),
                         _f("bundle", bundle_resource_id), _f("certificate", cert_id))

    def upload_build(self, ipa_path: str | Path, app: str) -> dict[str, Any]:
        """IPA → App Store Connect/TestFlight (`asc builds upload`; `app` = app id or exact bundle id)."""
        return asc_cli.run(["builds", "upload", _f("app", app), _f("ipa", str(ipa_path))], timeout=asc_cli.UPLOAD_TIMEOUT)


_LOC_FLAGS = {"description": "description", "keywords": "keywords", "promotionalText": "promotional-text",
              "supportUrl": "support-url", "marketingUrl": "marketing-url", "whatsNew": "whats-new",
              "name": "name", "subtitle": "subtitle", "privacyPolicyUrl": "privacy-policy-url"}


def _same_price(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _upload_result(r: dict[str, Any]) -> dict[str, Any]:
    """asc screenshots/video-previews upload → {ok, id} (id = the new asset)."""
    if not r.get("ok"):
        return {"ok": False, "step": "upload", "error": r.get("error")}
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    results = data.get("results") or [x for loc in data.get("localizations") or [] for x in loc.get("results") or []]
    bad = [x for x in results if "fail" in str(x.get("state", "")).lower() or x.get("error")]
    if bad:
        return {"ok": False, "step": "upload", "error": bad[0].get("error") or bad[0].get("state"),
                "id": bad[0].get("assetId")}
    return {"ok": True, "id": next((x.get("assetId") for x in results if x.get("assetId")), None)}
