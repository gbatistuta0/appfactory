"""signing_* — App Store distribution signing + TestFlight upload (fully automatic, headless).

fastlane match/sigh pattern, using the asc CLI + openssl + security:
  1. Distribution cert: openssl keypair+CSR → `asc certificates create` → legacy p12
     → import into a temporary keychain (+ Apple WWDR intermediate certs) → valid identity.
  2. App Store profile: `asc profiles create` (IOS_APP_STORE, bundleId + cert) → mobileprovision.
  3. Export: distribution IPA with manual signing (signingStyle manual).
  4. Upload: `asc builds upload --ipa` (replaces xcrun altool).

No system keychain password required (temporary keychain). OpenSSL 3 → -legacy + SHA1 PBE
(required for macOS Security MAC compatibility).
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from . import config as cfg
from .asc import ASCClient
from .proc import run

WWDR_URLS = [
    "https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer",
    "https://www.apple.com/certificateauthority/AppleWWDRCAG6.cer",
]
_KC_PASS_FILE = Path(os.path.expanduser("~/.appfactory/signing/keychain.pass"))


def _kc_pass() -> str:
    """Per-install random password of the build keychain (0600 file, created on first use)."""
    if _KC_PASS_FILE.exists():
        return _KC_PASS_FILE.read_text().strip()
    _KC_PASS_FILE.parent.mkdir(parents=True, exist_ok=True)
    pw = secrets.token_urlsafe(24)
    fd = os.open(_KC_PASS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(pw)
    return pw


def setup_distribution_signing(work_dir: str | None = None) -> dict[str, Any]:
    """Distribution cert + keychain. PERSISTENT + REUSABLE: the distribution cert is SINGLE
    for ALL apps (Apple returns 409 for a second one). Stored in a persistent keychain; reused
    if present (does not create a new cert). {ok, cert_id, identity, keychain}."""
    work = pathlib.Path(work_dir or os.path.expanduser("~/.appfactory/signing"))
    work.mkdir(parents=True, exist_ok=True)
    kc = str(work / "build.keychain")
    # If a valid Apple Distribution identity already exists, REUSE it (do not create a new cert)
    unlocked = run(["security", "unlock-keychain", "-p", _kc_pass(), kc])
    ids = run(["security", "find-identity", "-v", "-p", "codesigning", kc])
    # GOTCHA: if unlock fails (password mismatch) or no identity, do NOT reuse — set up fresh.
    # Otherwise codesign export fails with errSecInternalComponent (cannot access the key).
    if unlocked.get("ok") and "Apple Distribution" in ids.get("stdout", ""):
        cid = ""
        cid_file = work / "cert_id.txt"
        if cid_file.exists():
            cid = cid_file.read_text().strip()
        # CRITICAL: on reuse the partition list + long timeout are also REQUIRED (for codesign key access).
        run(["security", "set-keychain-settings", "-t", "36000", "-u", kc])
        run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
             "-s", "-k", _kc_pass(), kc])
        login_kc = run(["security", "login-keychain"]).get("stdout", "").strip().strip('"')
        run(["security", "list-keychains", "-d", "user", "-s", kc, login_kc])
        return {"ok": True, "cert_id": cid, "identity": "Apple Distribution", "keychain": kc, "reused": True}
    key, csr = work / "dist.key", work / "dist.csr"
    if not run(["openssl", "genrsa", "-out", str(key), "2048"]).get("ok"):
        return {"ok": False, "error": "openssl genrsa failed"}
    run(["openssl", "req", "-new", "-key", str(key), "-out", str(csr),
         "-subj", "/CN=AppFactory Distribution/O=Developer/C=US"])
    c = ASCClient()
    r = c.create_certificate(csr, "DISTRIBUTION")
    if not r.get("ok"):
        return {"ok": False, "step": "create_cert", "error": r.get("error")}
    cert = r["data"]["data"]
    cert_id = cert["id"]
    (work / "cert_id.txt").write_text(cert_id)  # the reuse branch reads from here (otherwise profile 409 with '' id)
    der = base64.b64decode(cert["attributes"]["certificateContent"])
    (work / "dist.cer").write_bytes(der)
    run(["openssl", "x509", "-inform", "DER", "-in", str(work / "dist.cer"), "-out", str(work / "dist.pem")])
    p12 = work / "dist.p12"
    mk = run(["openssl", "pkcs12", "-export", "-legacy", "-out", str(p12),
              "-inkey", str(key), "-in", str(work / "dist.pem"),
              "-keypbe", "PBE-SHA1-3DES", "-certpbe", "PBE-SHA1-3DES", "-macalg", "sha1",
              "-passout", f"pass:{_kc_pass()}"])
    if not p12.exists():
        return {"ok": False, "step": "p12", "detail": mk}
    # temporary keychain
    kc = str(work / "build.keychain")
    run(["security", "delete-keychain", kc])
    run(["security", "create-keychain", "-p", _kc_pass(), kc])
    run(["security", "unlock-keychain", "-p", _kc_pass(), kc])
    run(["security", "set-keychain-settings", "-t", "3600", "-u", kc])
    run(["security", "import", str(p12), "-k", kc, "-P", _kc_pass(),
         "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"])
    # WWDR intermediate certs (for chain validation)
    for url in WWDR_URLS:
        cer = work / pathlib.Path(url).name
        if run(["curl", "-fsSL", "-o", str(cer), url]).get("ok"):
            run(["security", "import", str(cer), "-k", kc, "-T", "/usr/bin/codesign"])
    run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", _kc_pass(), kc])
    ids = run(["security", "find-identity", "-v", "-p", "codesigning", kc])
    out = ids.get("stdout", "")
    if "Apple Distribution" not in out:
        return {"ok": False, "step": "keychain", "detail": out}
    # identity name
    identity = "Apple Distribution"
    return {"ok": True, "cert_id": cert_id, "identity": identity, "keychain": kc, "work_dir": str(work)}


def _write_profile(d: dict) -> dict[str, Any]:
    content = base64.b64decode(d["attributes"]["profileContent"])
    for p in ["~/Library/MobileDevice/Provisioning Profiles",
              "~/Library/Developer/Xcode/UserData/Provisioning Profiles"]:
        dpath = pathlib.Path(os.path.expanduser(p))
        dpath.mkdir(parents=True, exist_ok=True)
        (dpath / f"{d['attributes']['uuid']}.mobileprovision").write_bytes(content)
    return {"ok": True, "profile_name": d["attributes"]["name"], "uuid": d["attributes"]["uuid"]}


def exact_bundle_resource(c: Any, identifier: str) -> str | None:
    """ASC resource id of EXACTLY this bundle id. GET /v1/bundleIds?filter[identifier]=X matches
    substrings: "com.x.app" also returns "com.x.app.uitests.xctrunner" and "com.x.app.watchkitapp"
    also "…watchkitapp.complications" — the first hit is not necessarily ours."""
    found = c.bundle_ids(identifier)
    for b in found.get("data", {}).get("data", []):
        if (b.get("attributes") or {}).get("identifier") == identifier:
            return b["id"]
    return None


def embedded_bundle_ids(app_dir: str | Path, bundle_id: str) -> list[str]:
    """Bundle ids of the app extensions/companions in project.yml (widgets, Watch app, complications…):
    every PRODUCT_BUNDLE_IDENTIFIER under the app's own id except the test bundles. Each needs its own
    App Store profile in the manual-signing export."""
    pj = Path(app_dir).expanduser() / "project.yml"
    if not pj.exists():
        return []
    ids = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER:\s*\"?([A-Za-z0-9.\-_]+)\"?", pj.read_text(encoding="utf-8"))
    out = []
    for i in ids:
        if i.startswith(bundle_id + ".") and not re.search(r"\.(ui)?tests?$", i) and i not in out:
            out.append(i)
    return out


def create_appstore_profile(bundle_id: str, cert_id: str, name: str = "AppFactory AppStore",
                            client: Any = None) -> dict[str, Any]:
    """Create an IOS_APP_STORE provisioning profile + write it to standard locations. {ok, profile_name, uuid}.
    GOTCHA: if a profile with the same name EXISTS, Apple returns 409 'Multiple profiles' on POST → first
    delete existing ones, then create fresh with the cert (old profiles bind to an old/deleted cert, invalid).
    GOTCHA: the bundle id resource is matched EXACTLY (ASC's identifier filter is a substring match)."""
    c = client or ASCClient()
    bid = exact_bundle_resource(c, bundle_id)
    if not bid:
        return {"ok": False, "error": f"no exact bundleId resource: {bundle_id} (register it first)"}
    # clean up old profiles with the same name (avoid duplicate 409)
    for o in c.profiles_by_name(name):
        if (o.get("attributes") or {}).get("name") == name:  # the name filter may match loosely
            c.delete_profile(o["id"])
    r = c.create_profile(name, bid, cert_id, "IOS_APP_STORE")
    if not r.get("ok"):
        return {"ok": False, "step": "create_profile", "error": r.get("error")}
    d = r["data"]["data"]
    if (d.get("attributes") or {}).get("name") != name:
        return {"ok": False, "step": "create_profile", "error": f"ASC returned profile {d.get('attributes', {}).get('name')!r}"}
    return _write_profile(d)


def _api_auth_flags() -> list[str]:
    c = cfg.load_config()
    p8 = cfg.resolve_asc_key_filepath(c)
    return ["-authenticationKeyPath", str(p8),
            "-authenticationKeyID", c.get("asc_key_id"),
            "-authenticationKeyIssuerID", c.get("asc_issuer_id")]


def archive(project: str, scheme: str, archive_path: str, team_id: str) -> dict[str, Any]:
    """xcodebuild archive (automatic signing + profile update via ASC API key)."""
    return run([
        "xcodebuild", "-project", project, "-scheme", scheme, "-configuration", "Release",
        "-destination", "generic/platform=iOS", "-archivePath", archive_path, "archive",
        "-allowProvisioningUpdates", *_api_auth_flags(),
        f"DEVELOPMENT_TEAM={team_id}", "CODE_SIGN_STYLE=Automatic",
    ], timeout=1200)


def export_options_plist(team_id: str, profiles: dict[str, str]) -> str:
    """ExportOptions for a manual-signing App Store export: one profile per bundle id (app + every
    embedded extension), build numbers left as archived."""
    entries = "".join(f"<key>{b}</key><string>{n}</string>" for b, n in profiles.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>export</string>
  <key>teamID</key><string>{team_id}</string>
  <key>signingStyle</key><string>manual</string>
  <key>signingCertificate</key><string>Apple Distribution</string>
  <key>provisioningProfiles</key><dict>{entries}</dict>
  <key>uploadSymbols</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
"""


def export_appstore_ipa(archive_path: str, export_dir: str, bundle_id: str,
                        profile_name: str, team_id: str, keychain: str,
                        extra_profiles: dict[str, str] | None = None) -> dict[str, Any]:
    """Export an App Store IPA with manual signing (extra_profiles: extension bundle id → profile name)."""
    plist = pathlib.Path(export_dir).parent / "ExportOptions.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(export_options_plist(team_id, {bundle_id: profile_name, **(extra_profiles or {})}), encoding="utf-8")
    run(["security", "unlock-keychain", "-p", _kc_pass(), keychain])
    login_kc = run(["security", "login-keychain"]).get("stdout", "").strip().strip('"')
    run(["security", "list-keychains", "-d", "user", "-s", keychain, login_kc])
    return run(["xcodebuild", "-exportArchive", "-archivePath", archive_path,
                "-exportPath", export_dir, "-exportOptionsPlist", str(plist)], timeout=900)


def upload_testflight(ipa_path: str, app: str) -> dict[str, Any]:
    """Upload the IPA to App Store Connect / TestFlight with `asc builds upload` (app = app id or
    exact bundle id). {ok, stdout, [error]} — stdout is asc's JSON receipt."""
    r = ASCClient().upload_build(ipa_path, app)
    data = r.get("data")
    out = {"ok": bool(r.get("ok")), "stdout": data if isinstance(data, str) else json.dumps(data or {})}
    if not r.get("ok"):
        out["error"] = r.get("error")
    return out


def profile_name(scheme: str, app_bundle_id: str, bundle_id: str) -> str:
    """"<Scheme> AppStore" for the app, "<Scheme> <Suffix> AppStore" for an extension
    (com.x.app.watchkitapp.complications → "Hue Watchkitapp Complications AppStore")."""
    if bundle_id == app_bundle_id:
        return f"{scheme} AppStore"
    suffix = bundle_id[len(app_bundle_id) + 1:] if bundle_id.startswith(app_bundle_id + ".") else bundle_id
    return f"{scheme} {' '.join(w.capitalize() for w in re.split(r'[.\-_]', suffix) if w)} AppStore"


def ship_testflight(app_dir: str, project: str, scheme: str, bundle_id: str) -> dict[str, Any]:
    """End-to-end: set up signing → archive → profiles → export → TestFlight upload.

    Profiles are created AFTER the archive, immediately before -exportArchive:
    Xcode's background signing refresh sweeps ~/Library/MobileDevice/Provisioning Profiles of profiles it
    does not know while any xcodebuild runs, so profiles written before a minutes-long archive were
    gone by export time. Every embedded extension (widgets, Watch app, complications) gets its own
    profile, found in project.yml."""
    c = cfg.load_config()
    team = c.get("team_id")
    if not team:
        return {"ok": False, "error": "team_id not in config"}
    sign = setup_distribution_signing()
    if not sign.get("ok"):
        return {"ok": False, "step": "signing", "detail": sign}
    arch = f"{app_dir}/build/{scheme}.xcarchive"
    a = archive(project, scheme, arch, team)
    if not a.get("ok"):
        return {"ok": False, "step": "archive", "detail": a}
    profiles: dict[str, str] = {}
    for bid in [bundle_id, *embedded_bundle_ids(app_dir, bundle_id)]:
        prof = create_appstore_profile(bid, sign["cert_id"], name=profile_name(scheme, bundle_id, bid))
        if not prof.get("ok"):
            return {"ok": False, "step": "profile", "bundle_id": bid, "detail": prof}
        profiles[bid] = prof["profile_name"]
    expdir = f"{app_dir}/build/ipa"
    e = export_appstore_ipa(arch, expdir, bundle_id, profiles.pop(bundle_id), team, sign["keychain"],
                            extra_profiles=profiles)
    if not e.get("ok"):
        return {"ok": False, "step": "export", "detail": e}
    ipas = list(pathlib.Path(expdir).glob("*.ipa"))
    if not ipas:
        return {"ok": False, "step": "export", "error": "no ipa produced"}
    up = upload_testflight(str(ipas[0]), bundle_id)
    out = up.get("stdout", "") or ""
    res = {"ok": bool(up.get("ok")), "ipa": str(ipas[0]),
           "profiles": [profile_name(scheme, bundle_id, bundle_id), *profiles.values()], "upload": out[-300:]}
    if not up.get("ok"):
        res["error"] = up.get("error")
    return res
