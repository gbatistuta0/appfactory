"""Setup through the MCP tools + the local credentials page. Nothing touches the real home; no browser opens."""

from __future__ import annotations

import http.client
import json
import threading
import tomllib

import pytest

from appfactory import cli, server, setup_gui, setup_tools
from appfactory import config as cfg

REAL_REQUIRED = setup_tools.required  # conftest stubs setup_tools.required for other tests; these use the real one


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    monkeypatch.setattr(setup_gui.webbrowser, "open", lambda url: False)


def _serve(services, **kw):
    s = setup_gui.SetupServer(services, offline=True, **kw)
    t = threading.Thread(target=s.serve, daemon=True)
    t.start()
    return s, t


@pytest.fixture
def srv():
    cfg.save_config({"services": ["research", "apple", "supabase", "github"]})
    s, t = _serve(["apple", "supabase", "github"])
    yield s
    s.shutdown()
    t.join(5)


def call(s, method, path, body=None, token=True, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token:
        h["X-Setup-Token"] = s.token
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=5)
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, raw


# ---------------------------------------------------------------- the page
def test_binds_loopback_and_needs_token(srv):
    assert srv.server_address[0] == "127.0.0.1"
    assert call(srv, "GET", "/api/state", token=False)[0] == 401
    assert call(srv, "GET", "/", token=False)[0] == 401
    assert call(srv, "POST", "/api/save", {}, token=False)[0] == 401
    assert call(srv, "GET", "/api/state", headers={"X-Setup-Token": "wrong"}, token=False)[0] == 401
    assert call(srv, "GET", "/api/state")[0] == 200
    code, page = call(srv, "GET", f"/?t={srv.token}", token=False)
    assert code == 200 and b"AppFactory credentials" in page


def test_bad_host_and_origin_rejected(srv):
    assert call(srv, "GET", "/api/state", headers={"Origin": "http://evil.example"})[0] == 403
    assert call(srv, "POST", "/api/save", {}, headers={"Origin": "https://127.0.0.1"})[0] == 403
    assert call(srv, "GET", "/api/state", headers={"Host": "evil.example"})[0] == 403
    port = srv.server_address[1]
    assert call(srv, "GET", "/api/state", headers={"Origin": f"http://127.0.0.1:{port}"})[0] == 200


def test_secrets_never_returned(srv):
    cfg.save_config({"services": ["research", "supabase"], "supabase_access_token": "sbp_topsecret_123"})
    code, raw = call(srv, "GET", "/api/state")
    assert code == 200 and b"sbp_topsecret_123" not in raw
    sup = next(s for s in json.loads(raw)["services"] if s["name"] == "supabase")
    tok = next(f for f in sup["fields"] if f["key"] == "supabase_access_token")
    assert tok["set"] is True and "value" not in tok
    code, raw = call(srv, "POST", "/api/save", {"values": {"supabase_access_token": "sbp_new_456789"}})
    assert code == 200 and b"sbp_new_456789" not in raw
    assert b"sbp_new_456789" not in call(srv, "GET", "/api/state")[1]
    assert b"sbp_new_456789" not in call(srv, "GET", f"/?t={srv.token}", token=False)[1]
    assert cfg.load_config()["supabase_access_token"] == "sbp_new_456789"


def test_save_writes_config(srv, tmp_path):
    p8 = tmp_path / "AuthKey_ABC.p8"
    p8.write_text("k")
    body = {"values": {"asc_key_id": "ABC", "asc_issuer_id": "iss", "asc_key_filepath": str(p8),
                       "supabase_access_token": "sbp_abcdef"}, "approvals": True}
    assert call(srv, "POST", "/api/save", body)[0] == 200
    c = tomllib.loads(cfg.CONFIG_PATH.read_text())
    assert c["services"] == ["research", "apple", "supabase", "github"]  # untouched
    assert c["asc_key_id"] == "ABC" and c["supabase_access_token"] == "sbp_abcdef" and c["approvals"] == "required"
    assert (cfg.CONFIG_PATH.stat().st_mode & 0o777) == 0o600
    # empty secret keeps the saved value; empty plain field clears; approvals off is stored
    call(srv, "POST", "/api/save", {"values": {"supabase_access_token": "", "asc_key_id": ""}, "approvals": False})
    c = cfg.load_config()
    assert c["supabase_access_token"] == "sbp_abcdef" and "asc_key_id" not in c and c["approvals"] == "off"


def test_save_validation(srv):
    assert call(srv, "POST", "/api/save", {"values": {"rc_secret_key": "x"}})[0] == 400  # service not shown
    assert call(srv, "POST", "/api/save", {"values": {"bogus": "x"}})[0] == 400
    assert call(srv, "POST", "/api/save", {"values": {"asc_key_id": 5}})[0] == 400
    assert "rc_secret_key" not in cfg.load_config()


def test_check_file_and_asc(srv, tmp_path):
    f = tmp_path / "k.p8"
    f.write_text("x")
    assert json.loads(call(srv, "POST", "/api/check-file", {"path": str(f)})[1]) == {"exists": True}
    assert json.loads(call(srv, "POST", "/api/check-file", {"path": str(f) + "x"})[1]) == {"exists": False}
    cfg.save_config({"services": ["research", "apple"], "asc_key_filepath": str(f) + "x"})
    r = json.loads(call(srv, "POST", "/api/test-asc", {})[1])
    assert r["ok"] is False and ".p8 not found" in r["messages"][0]
    assert call(srv, "POST", "/api/agents", {})[0] == 404  # no agent step: the user is already inside an agent


def test_finish_stops_server_and_idle_timeout():
    cfg.save_config({"services": ["research", "apple"]})
    s, t = _serve(["apple"])
    assert json.loads(call(s, "POST", "/api/finish", {})[1]) == {"ok": True}
    t.join(5)
    assert not t.is_alive() and s.finished
    s2, t2 = _serve(["apple"], idle_seconds=0.2)
    t2.join(5)
    assert not t2.is_alive()


# ---------------------------------------------------------------- setup_credentials tool
def test_setup_credentials_returns_url_and_serves():
    assert server.setup_credentials()["ok"] is False  # no services chosen yet
    setup_tools.set_services(["apple"], None)
    r = server.setup_credentials(["apple"])
    assert r["ok"] and r["url"].startswith("http://127.0.0.1:") and "?t=" in r["url"] and "setup_status" in r["message"]
    port, tok = r["url"].split(":")[2].split("/")[0], r["url"].split("?t=")[1]
    c = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
    c.request("GET", "/api/state", headers={"X-Setup-Token": tok})
    assert c.getresponse().status == 200
    c.close()
    setup_gui._active.shutdown()
    assert server.setup_credentials(["supabase"])["ok"] is False  # disabled service
    assert server.setup_credentials(["research"])["ok"] is False  # nothing to enter


# ---------------------------------------------------------------- chat-side tools
def test_setup_status_on_empty_config():
    st = server.setup_status()
    assert st["ok"] and not st["services_chosen"] and not st["config_exists"]
    assert any("setup_services" in n for n in st["next"])
    assert [s["name"] for s in st["services"] if s["enabled"]] == ["research"]


def test_setup_services_and_missing_keys_flow():
    assert server.setup_services(enable=["apple", "supabase", "nope"])["ok"] is False
    st = server.setup_services(enable=["apple", "supabase"])
    assert st["services_chosen"] and st["approvals"] == "required"
    apple = next(s for s in st["services"] if s["name"] == "apple")
    assert {k["key"] for k in apple["keys"] if k["state"] == "missing"} == {"asc_key_id", "asc_issuer_id",
                                                                            "asc_key_filepath", "team_id"}
    assert any("setup_set" in n and "apple" in n for n in st["next"])
    assert any("setup_credentials" in n and "supabase_access_token" in n for n in st["next"])
    assert server.setup_services(disable=["research"])["ok"] is False
    for k, v in (("asc_key_id", "ABC"), ("asc_issuer_id", "iss"), ("team_id", "T1"),
                 ("asc_key_filepath", "~/AuthKey_ABC.p8")):
        assert server.setup_set(k, v)["ok"]
    c = cfg.load_config()
    assert c["asc_key_id"] == "ABC" and not c["asc_key_filepath"].startswith("~")
    assert server.setup_set("asc_key_id", "")["state"] == "missing"
    st = server.setup_services(disable=["supabase"])
    assert next(s for s in st["services"] if s["name"] == "supabase")["enabled"] is False
    assert "supabase" not in cfg.load_config()["services"]


def test_setup_set_refuses_secrets_and_unknown_keys():
    r = server.setup_set("supabase_access_token", "sbp_should_not_pass")
    assert r["ok"] is False and "setup_credentials" in r["error"]
    assert "supabase_access_token" not in cfg.load_config()
    assert server.setup_set("bogus", "x")["ok"] is False
    assert "sbp_should_not_pass" not in json.dumps(server.setup_status())


def test_setup_approvals_off_needs_the_human():
    assert server.setup_approvals("required")["ok"]
    r = server.setup_approvals("off")
    assert r["ok"] is False and "human" in r["error"] and cfg.load_config()["approvals"] == "required"
    assert server.setup_approvals("maybe")["ok"] is False


def test_setup_tools_are_not_service_gated():
    for t in ("setup_status", "setup_services", "setup_set", "setup_approvals", "setup_credentials"):
        assert t not in server.TOOL_SERVICES


def test_run_tools_return_setup_required_until_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_tools, "required", REAL_REQUIRED)
    for r in (server.orchestrator_preflight(), server.pipeline_next(str(tmp_path)),
              server.orchestrator_next_action(str(tmp_path))):
        assert r["ok"] is False and r["setup_required"] and "setup_services" in r["how"]
    server.setup_services(enable=["supabase"])
    r = server.orchestrator_preflight()
    assert r["setup_required"] and any("supabase_access_token" in n for n in r["next"])
    cfg.save_config({"services": ["research"], "approvals": "required"})
    assert REAL_REQUIRED() is None  # research-only needs nothing
    assert "setup_required" not in server.orchestrator_preflight()


def test_run_prompt_and_playbook_start_with_setup():
    assert "setup_status()" in server.playbook().split("## Before you start", 1)[1][:900]
    assert "setup_status()" in server.run_prompt()[:200]


def test_cli_has_no_agent_wiring_and_setup_flags(monkeypatch):
    assert not hasattr(cli, "install_agent") and not hasattr(cli, "mcp_command")
    called = {}
    monkeypatch.setattr(setup_gui, "run", lambda offline=False: called.setdefault("gui", True) and 0)
    monkeypatch.setattr(cli, "setup", lambda offline=False: called.setdefault("cli", True) and 0)
    cli.main(["setup", "--browser"])
    cli.main(["setup"])
    assert called == {"gui": True, "cli": True}


def test_run_prints_url_when_browser_unavailable(capsys, monkeypatch):
    cfg.save_config({"services": ["research", "apple"]})
    monkeypatch.setattr(setup_gui.SetupServer, "serve", lambda self: None)
    assert setup_gui.run() == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:" in out and "?t=" in out and "could not open a browser" in out


def test_services_are_asked_one_by_one_and_dependencies_follow():
    from appfactory import setup_tools
    st = setup_tools.status()
    assert "EACH service separately" in " ".join(st["next"])
    r = setup_tools.set_services(["ai", "maestro"], [])
    on = {s["name"] for s in r["services"] if s["enabled"]}
    assert {"ai", "supabase", "maestro", "xcode"} <= on and "lottie" not in on
    assert setup_tools.set_services([], ["supabase"])["ok"] is False
