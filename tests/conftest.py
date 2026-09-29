"""Every test runs against a throwaway ~/.appfactory, never the real one."""

from __future__ import annotations

import pytest

from appfactory import config


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("appfactory_home") / ".appfactory"
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_PATH", d / "config.toml")


def approve_next(result: dict) -> str:
    """Test helper: approve the pending approval a tool just requested (what `appfactory approve` does)."""
    from appfactory import approvals
    aid = result["approval_required"]
    assert approvals.approve(aid)["ok"]
    return aid
