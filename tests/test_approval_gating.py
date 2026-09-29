"""ASC / signing / firebase write tools are gated by out-of-band approval; internal dry_run defaults are safe."""

from __future__ import annotations

import inspect

import pytest

from appfactory import ai, approvals, github, server

from conftest import approve_next

GATED = {
    "asc_create_bundle_id": dict(identifier="com.x.app", name="X"),
    "asc_create_subscription_group": dict(app_id="1", reference_name="Premium"),
    "asc_create_subscription": dict(group_id="g", product_id="p", name="n"),
    "asc_ensure_subscription_prices": dict(bundle_id="com.x.app", default_usd="4.99"),
    "asc_localize_subscription": dict(sub_id="s", items={"en-US": {"name": "a", "description": "b"}}),
    "asc_localize_group": dict(group_id="g", name_by_locale={"en-US": "n"}),
    "asc_add_subscription_group_localization": dict(group_id="g", name="n"),
    "asc_finalize_subscription": dict(sub_id="s", name="n", description="d", usd_price="4.99"),
    "asc_append_subscription_disclosure": dict(bundle_id="com.x.app", privacy_url="https://x/p"),
    "asc_finalize_submission_requirements": dict(bundle_id="com.x.app", copyright="c"),
    "signing_setup_distribution": {},
    "signing_create_profile": dict(bundle_id="com.x.app", cert_id="c"),
    "firebase_setup": dict(app_dir="/tmp/nope", bundle_id="com.x.app", app_name="X"),
}


class Boom:
    """Any attribute access means a live client was reached."""

    def __getattr__(self, name):
        raise AssertionError(f"executed {name} without approval")


@pytest.fixture
def no_exec(monkeypatch):
    hits = []

    def _asc():
        hits.append("asc")
        return Boom(), None

    monkeypatch.setattr(server, "_asc", _asc)
    for mod, names in ((server.sign_mod, ("setup_distribution_signing", "create_appstore_profile")),
                       (server.fb_mod, ("setup",))):
        for n in names:
            monkeypatch.setattr(mod, n, lambda *a, _n=n, **k: hits.append(_n))
    return hits


@pytest.mark.parametrize("name", sorted(GATED))
def test_tool_without_approval_does_not_execute(name, no_exec):
    fn = getattr(server, name)
    assert "approval_id" in inspect.signature(fn).parameters
    r = fn(**GATED[name])
    assert r["ok"] is False and r["action"] == name and not no_exec
    assert (approvals.approvals_dir() / f"{r['approval_required']}.json").exists()


def test_approval_is_bound_to_arguments(no_exec):
    r = server.asc_create_subscription_group(app_id="1", reference_name="Premium")
    aid = approve_next(r)
    other = server.asc_create_subscription_group(app_id="2", reference_name="Premium", approval_id=aid)
    assert "does not match" in other["error"] and not no_exec


def test_approved_call_executes(monkeypatch):
    calls = []
    cl = type("C", (), {"create_subscription_group": lambda s, a, n: calls.append((a, n)) or {"ok": True}})()
    monkeypatch.setattr(server, "_asc", lambda: (cl, None))
    aid = approve_next(server.asc_create_subscription_group("1", "P"))
    assert server.asc_create_subscription_group("1", "P", approval_id=aid)["ok"] is True
    assert calls == [("1", "P")]


def test_approvals_off_runs_directly(monkeypatch):
    from appfactory import config
    config.save_config({"approvals": "off"})
    monkeypatch.setattr(server.sign_mod, "setup_distribution_signing", lambda: {"ok": True})
    assert server.signing_setup_distribution() == {"ok": True}


def test_internal_dry_run_defaults_are_true():
    assert inspect.signature(ai.deploy_backend).parameters["dry_run"].default is True
    assert inspect.signature(github.create_private_repo).parameters["dry_run"].default is True


def test_ai_deploy_proxy_passes_live_explicitly(tmp_path, monkeypatch):
    from appfactory import config, spec
    config.save_config({"approvals": "off"})
    seen = []
    monkeypatch.setattr(spec, "path", lambda p: tmp_path / "exists")
    (tmp_path / "exists").write_text("{}")
    monkeypatch.setattr(server.ai_mod, "deploy_backend", lambda *a, **k: seen.append(k) or {"ok": True})
    server.ai_deploy_proxy(str(tmp_path), "ref")
    assert seen == [{"dry_run": False}]
