"""signing.py — exact bundle id matching, extension profiles and the archive → profiles → export order
(release lessons, no network)."""

from __future__ import annotations

from pathlib import Path

from appfactory import config, signing


class FakeASC:
    """ASCClient's signing methods (first-class asc commands)."""

    def __init__(self, existing_profiles=()):
        self.created = []
        self.deleted = []
        self.existing = list(existing_profiles)

    def bundle_ids(self, identifier):
        # ASC's identifier filter is a SUBSTRING match: the xctrunner comes first
        ids = ["com.x.hue.uitests.xctrunner", "com.x.hue", "com.x.hue.widgets"]
        return {"ok": True, "data": {"data": [{"id": f"res-{i}", "attributes": {"identifier": i}}
                                              for i in ids if identifier in i]}}

    def profiles_by_name(self, name):
        return [p for p in self.existing if name in p["attributes"]["name"]]

    def delete_profile(self, pid):
        self.deleted.append(pid)
        return {"ok": True}

    def create_profile(self, name, bundle_resource_id, cert_id, profile_type="IOS_APP_STORE"):
        self.created.append((name, bundle_resource_id, cert_id, profile_type))
        return {"ok": True, "data": {"data": {"attributes": {"name": name, "uuid": "u-1", "profileContent": ""}}}}


def test_exact_bundle_resource_ignores_substring_hits():
    c = FakeASC()
    assert signing.exact_bundle_resource(c, "com.x.hue") == "res-com.x.hue"
    assert signing.exact_bundle_resource(c, "com.x.hu") is None


def test_profile_uses_the_exact_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(signing, "_write_profile", lambda d: {"ok": True, "profile_name": d["attributes"]["name"]})
    c = FakeASC(existing_profiles=[{"id": "old", "attributes": {"name": "Hue AppStore"}},
                                   {"id": "other", "attributes": {"name": "Hue AppStore Legacy"}}])
    r = signing.create_appstore_profile("com.x.hue", "CERT", name="Hue AppStore", client=c)
    assert r["ok"] and c.created == [("Hue AppStore", "res-com.x.hue", "CERT", "IOS_APP_STORE")]
    assert c.deleted == ["old"]              # only the exact name is replaced


def test_embedded_bundle_ids_and_profile_names(tmp_path: Path):
    (tmp_path / "project.yml").write_text(
        "targets:\n  Hue:\n    settings:\n      base:\n        PRODUCT_BUNDLE_IDENTIFIER: com.x.hue\n"
        "  HueWidgets:\n    settings:\n      base:\n        PRODUCT_BUNDLE_IDENTIFIER: com.x.hue.widgets\n"
        "  HueWatch:\n    settings:\n      base:\n        PRODUCT_BUNDLE_IDENTIFIER: \"com.x.hue.watchkitapp\"\n"
        "  HueTests:\n    settings:\n      base:\n        PRODUCT_BUNDLE_IDENTIFIER: com.x.hue.tests\n"
        "  HueUITests:\n    settings:\n      base:\n        PRODUCT_BUNDLE_IDENTIFIER: com.x.hue.uitests\n")
    assert signing.embedded_bundle_ids(tmp_path, "com.x.hue") == ["com.x.hue.widgets", "com.x.hue.watchkitapp"]
    assert signing.profile_name("Hue", "com.x.hue", "com.x.hue") == "Hue AppStore"
    assert signing.profile_name("Hue", "com.x.hue", "com.x.hue.widgets") == "Hue Widgets AppStore"
    plist = signing.export_options_plist("TEAM", {"com.x.hue": "Hue AppStore", "com.x.hue.widgets": "Hue Widgets AppStore"})
    assert "<key>com.x.hue.widgets</key><string>Hue Widgets AppStore</string>" in plist
    assert "<key>manageAppVersionAndBuildNumber</key><false/>" in plist


def test_profiles_are_made_after_the_archive_right_before_export(monkeypatch, tmp_path: Path):
    (tmp_path / "project.yml").write_text("PRODUCT_BUNDLE_IDENTIFIER: com.x.hue\nPRODUCT_BUNDLE_IDENTIFIER: com.x.hue.widgets\n")
    order: list[str] = []
    monkeypatch.setattr(config, "load_config", lambda: {"team_id": "TEAM"})
    monkeypatch.setattr(signing, "setup_distribution_signing", lambda: {"ok": True, "cert_id": "C", "keychain": "k"})
    monkeypatch.setattr(signing, "archive", lambda *a: order.append("archive") or {"ok": True})
    monkeypatch.setattr(signing, "create_appstore_profile",
                        lambda bid, cert, name: order.append(f"profile {bid}") or {"ok": True, "profile_name": name})

    def export(arch, expdir, bid, name, team, kc, extra_profiles=None):
        order.append(f"export {name} {sorted(extra_profiles.values())}")
        Path(expdir).mkdir(parents=True)
        (Path(expdir) / "Hue.ipa").write_text("")
        return {"ok": True}
    monkeypatch.setattr(signing, "export_appstore_ipa", export)
    monkeypatch.setattr(signing, "upload_testflight", lambda ipa, app: order.append(f"upload {app}") or
                        {"ok": True, "stdout": '{"buildId": "b1"}'})
    r = signing.ship_testflight(str(tmp_path), "Hue.xcodeproj", "Hue", "com.x.hue")
    assert r["ok"] is True
    assert order == ["archive", "profile com.x.hue", "profile com.x.hue.widgets",
                     "export Hue AppStore ['Hue Widgets AppStore']", "upload com.x.hue"]


def test_testflight_upload_goes_through_asc_builds_upload(monkeypatch, tmp_path: Path):
    from asc_fake import FakeAsc, err
    fake = FakeAsc(monkeypatch, {("builds", "upload"): {"buildId": "b-9", "uploaded": True}})
    r = signing.upload_testflight(str(tmp_path / "Hue.ipa"), "com.x.hue")
    assert r["ok"] is True and "b-9" in r["stdout"]
    assert fake.calls[-1] == ["builds", "upload", "--app=com.x.hue", f"--ipa={tmp_path / 'Hue.ipa'}"]
    FakeAsc(monkeypatch, {("builds", "upload"): err("upload failed: invalid binary", status=409)})
    bad = signing.upload_testflight(str(tmp_path / "Hue.ipa"), "com.x.hue")
    assert bad["ok"] is False and "invalid binary" in bad["error"]
