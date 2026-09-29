"""firebase_* — Firebase Analytics setup per app (live event tracking).

Fully automatic, NO interactive login required: gcloud (user authed) + service account
key + firebase-tools. Flow:
  1. Create GCP project + enable firebase.googleapis.com
  2. Service account (owner) + JSON key → firebase-tools auth (GOOGLE_APPLICATION_CREDENTIALS)
  3. firebase projects:addfirebase → create iOS app
  4. addGoogleAnalytics → LINK the project to a GA4 account (GOTCHA: WITHOUT this the plist
     returns IS_ANALYTICS_ENABLED=false and the app sends NO events; the app won't appear in GA4)
  5. Download GoogleService-Info.plist → into Resources
The plist is written to the app's Resources/; App.swift calls FirebaseApp.configure() (if the plist exists).
Requires: gcloud authed + firebase-tools (npm i -g firebase-tools).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .proc import run

# GA4 account ID (the user's "Default Account for Firebase" account). addGoogleAnalytics
# automatically creates a GA4 property per app under this account.
GA_ACCOUNT_ID = "383697140"
_FB_API = "https://firebase.googleapis.com/v1beta1"


def _link_google_analytics(pid: str, env: dict) -> dict[str, Any]:
    """Link the project to a GA4 account (enables analytics collection). Firebase Management API
    with a gcloud user token + quota header. Waits until the operation completes."""
    tok = run(["gcloud", "auth", "print-access-token"], timeout=60).get("stdout", "").strip()
    if not tok:
        return {"ok": False, "error": "could not obtain gcloud access token"}
    hdr = ["-H", f"Authorization: Bearer {tok}", "-H", f"X-Goog-User-Project: {pid}",
           "-H", "Content-Type: application/json"]
    r = run(["curl", "-s", "-X", "POST", *hdr,
             "-d", json.dumps({"analyticsAccountId": GA_ACCOUNT_ID}),
             f"{_FB_API}/projects/{pid}:addGoogleAnalytics"], timeout=120)
    try:
        op = json.loads(r.get("stdout", "{}"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "could not parse addGoogleAnalytics response", "raw": r.get("stdout", "")[:300]}
    op_name = op.get("name")
    if not op_name:
        return {"ok": False, "error": op.get("error", "no operation")}
    # operation poll (GA property + data stream creation)
    for _ in range(20):
        pr = run(["curl", "-s", *hdr, f"{_FB_API}/{op_name}"], timeout=60)
        try:
            st = json.loads(pr.get("stdout", "{}"))
        except json.JSONDecodeError:
            st = {}
        if st.get("done"):
            prop = (st.get("response") or {}).get("analyticsProperty", {})
            return {"ok": True, "property_id": prop.get("id"), "account_id": prop.get("analyticsAccountId")}
        time.sleep(6)
    return {"ok": False, "error": "addGoogleAnalytics operation timeout"}


def setup(app_dir: str | Path, bundle_id: str, app_name: str) -> dict[str, Any]:
    """Firebase project + iOS app + GoogleService-Info.plist (into Resources). {ok, project_id, app_id}."""
    app = Path(app_dir).expanduser()
    slug = re.sub(r"[^a-z0-9]", "", app_name.lower())[:18] or "app"
    pid = f"{slug}-{str(int(time.time()))[-5:]}"
    steps: dict[str, Any] = {}

    steps["create"] = run(["gcloud", "projects", "create", pid, "--name", app_name], timeout=180)
    steps["enable"] = run(["gcloud", "services", "enable", "firebase.googleapis.com", "--project", pid], timeout=300)

    sa = f"fbadmin@{pid}.iam.gserviceaccount.com"
    run(["gcloud", "iam", "service-accounts", "create", "fbadmin", "--project", pid,
         "--display-name", "Firebase Admin"], timeout=120)
    run(["gcloud", "projects", "add-iam-policy-binding", pid,
         "--member", f"serviceAccount:{sa}", "--role", "roles/owner", "--condition", "None"], timeout=120)
    key = app / ".appfactory_fb_sa.json"
    kr = run(["gcloud", "iam", "service-accounts", "keys", "create", str(key), "--iam-account", sa], timeout=120)
    if not kr.get("ok"):
        return {"ok": False, "step": "sa_key", "detail": kr, "project_id": pid}

    env = os.environ.copy()
    env["GOOGLE_APPLICATION_CREDENTIALS"] = str(key)
    af = run(["firebase", "projects:addfirebase", pid], timeout=300, env=env)
    steps["addfirebase"] = {"ok": af.get("ok")}
    cr = run(["firebase", "apps:create", "IOS", app_name, "--bundle-id", bundle_id, "--project", pid],
             timeout=300, env=env)
    m = re.search(r"1:\d+:ios:[a-f0-9]+", (cr.get("stdout", "") + cr.get("stderr", "")))
    if not m:
        # if it already exists, take it from the list
        lst = run(["firebase", "apps:list", "IOS", "--project", pid], timeout=120, env=env)
        m = re.search(r"1:\d+:ios:[a-f0-9]+", lst.get("stdout", ""))
    if not m:
        return {"ok": False, "step": "ios_app", "detail": cr, "project_id": pid}
    app_id = m.group(0)

    # Link GA4 (enables analytics collection) — otherwise the plist stays IS_ANALYTICS_ENABLED=false.
    ga = _link_google_analytics(pid, env)
    steps["google_analytics"] = ga
    if ga.get("ok"):
        time.sleep(15)  # config propagation (IS_ANALYTICS_ENABLED=true propagating)

    cfg_out = run(["firebase", "apps:sdkconfig", "IOS", app_id, "--project", pid], timeout=120, env=env)
    plist_m = re.search(r"<\?xml.*?</plist>", cfg_out.get("stdout", ""), re.S)
    if not plist_m:
        return {"ok": False, "step": "sdkconfig", "detail": cfg_out, "project_id": pid, "app_id": app_id}
    (app / "Resources").mkdir(parents=True, exist_ok=True)
    (app / "Resources" / "GoogleService-Info.plist").write_text(plist_m.group(0), encoding="utf-8")
    key.unlink(missing_ok=True)  # do not leave the SA key in the repo

    return {"ok": True, "project_id": pid, "app_id": app_id,
            "google_analytics": steps.get("google_analytics"),
            "console": f"https://console.firebase.google.com/project/{pid}/overview",
            "plist": str(app / "Resources" / "GoogleService-Info.plist")}
