"""Every test runs against a throwaway ~/.appfactory, never the real one."""

from __future__ import annotations

import os
import tempfile

# Point HOME at a throwaway dir before appfactory is imported, so module-level paths and
# module-scoped fixtures never read the developer's real ~/.appfactory.
os.environ["HOME"] = tempfile.mkdtemp(prefix="appfactory-test-home-")

import pytest

from appfactory import config


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("appfactory_home") / ".appfactory"
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_PATH", d / "config.toml")


@pytest.fixture(autouse=True)
def _setup_not_required(monkeypatch):
    """Run tools refuse with setup_required on a fresh config; most tests are about something else."""
    from appfactory import setup_tools
    monkeypatch.setattr(setup_tools, "required", lambda: None)


def approve_next(result: dict) -> str:
    """Test helper: approve the pending approval a tool just requested (what `appfactory approve` does)."""
    from appfactory import approvals
    aid = result["approval_required"]
    assert approvals.approve(aid)["ok"]
    return aid
