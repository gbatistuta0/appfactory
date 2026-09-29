"""Tests for the setup CLI — every path lives under tmp_path; the real home is never touched."""

from __future__ import annotations

import pytest

from src.appfactory import cli
from src.appfactory import config as cfg


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cfg, "CONFIG_DIR", home / ".appfactory")
    monkeypatch.setattr(cfg, "CONFIG_PATH", home / ".appfactory" / "config.toml")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no claude, no binaries
    return home


def _feed(monkeypatch, answers, secrets=()):
    it, sec = iter(answers), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(sec))


def test_enabled_services_default_is_all():
    assert cfg.enabled_services({}) == set(cfg.SERVICES)
    assert cfg.enabled_services({"services": ["supabase", "bogus"]}) == {"supabase", "research"}


def test_services_toggle_roundtrip(fake_home):
    assert cli.main(["services", "disable", "lottie"]) == 0
    assert "lottie" not in cfg.enabled_services()
    assert cli.main(["services", "enable", "lottie"]) == 0
    assert "lottie" in cfg.enabled_services()
    assert cli.main(["services", "disable", "research"]) == 2
    assert cli.main(["services", "enable", "nope"]) == 2


def test_setup_wizard_writes_config(fake_home, monkeypatch, capsys):
    p8 = fake_home / "AuthKey_ABC.p8"
    p8.write_text("key")
    # services in SERVICES order (research is automatic): apple y, xcode n, supabase y, rest n
    services = ["y", "n", "y", "n", "n", "n", "n", "n", "n", "n"]
    apple = ["ABC", "issuer-1", str(p8), "TEAM1"]
    _feed(monkeypatch, services + apple + ["y"], secrets=["sbp_secret"])
    assert cli.main(["setup", "--offline"]) == 0
    c = cfg.load_config()
    assert c["services"] == ["research", "apple", "supabase"]
    assert c["asc_key_id"] == "ABC" and c["supabase_access_token"] == "sbp_secret" and c["approvals"] == "required"
    out = capsys.readouterr().out
    assert "sbp_secret" not in out and cli.FIRST_PROMPT in out
    assert not (fake_home / ".gemini").exists() and "Connect agents" not in out  # no agent wiring any more


def test_setup_rerun_enter_keeps_values(fake_home, monkeypatch):
    cfg.save_config({"services": ["research", "revenuecat"], "rc_secret_key": "sk_old"})
    _feed(monkeypatch, [""] * 11, secrets=[""])
    assert cli.main(["setup", "--offline"]) == 0
    c = cfg.load_config()
    assert c["services"] == ["research", "revenuecat"] and c["rc_secret_key"] == "sk_old"


def test_doctor_never_prints_secrets(fake_home, capsys):
    cfg.save_config({"supabase_access_token": "sbp_topsecret"})
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "sbp_topsecret" not in out and "supabase_access_token=set" in out


def test_save_config_round_trips_multiline_and_quotes(tmp_path, monkeypatch):
    from appfactory import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config.toml")
    value = '---\n- cookie: "a\\b"\n\ttab'
    cfg.save_config({"apple_session": value, "services": ["research"]})
    assert cfg.load_config()["apple_session"] == value
