# SPDX-License-Identifier: MIT
# ============================================================
# Ecosystem marketplace feature-flag registration tests.
#
# Covers docs/ecosystem/SKILLS_PHASE_PLAN.md task B-0 — every flag this
# phase introduces must exist in core.config with its documented default,
# before any task that reads it is implemented.
# ============================================================

from __future__ import annotations

import importlib

import pytest


def _reload_config():
    import core.config as _cfg
    return importlib.reload(_cfg)


@pytest.fixture(autouse=True)
def _isolate_ecosystem_env(monkeypatch):
    """Strip every ECOSYSTEM_*/ENABLE_ECOSYSTEM_* env var and reload
    core.config before AND after every test so the suite is hermetic."""
    names = [
        "ENABLE_ECOSYSTEM_MARKETPLACE",
        "ECOSYSTEM_TYPE_SKILL",
        "ECOSYSTEM_TYPE_PLUGIN",
        "ECOSYSTEM_TYPE_MCP",
        "ECOSYSTEM_TYPE_CONNECTOR",
        "ECOSYSTEM_CHAT_SKILLS",
        "ECOSYSTEM_OBJECT_STORAGE_BACKEND",
        "ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG",
        "ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO",
        "ECOSYSTEM_AGENTSTUDIO_MISSING_DEP",
        "ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE",
    ]
    for n in names:
        monkeypatch.delenv(n, raising=False)
    cfg = _reload_config()
    yield cfg
    for n in names:
        monkeypatch.delenv(n, raising=False)
    _reload_config()


def test_default_off_flags_are_false(_isolate_ecosystem_env):
    cfg = _isolate_ecosystem_env
    assert cfg.ENABLE_ECOSYSTEM_MARKETPLACE is False
    assert cfg.ECOSYSTEM_TYPE_PLUGIN is False
    assert cfg.ECOSYSTEM_TYPE_MCP is False
    assert cfg.ECOSYSTEM_TYPE_CONNECTOR is False
    assert cfg.ECOSYSTEM_CHAT_SKILLS is False
    assert cfg.ECOSYSTEM_AGENTSTUDIO_MISSING_DEP is False
    assert cfg.ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE is False


def test_default_on_flags_are_true(_isolate_ecosystem_env):
    cfg = _isolate_ecosystem_env
    # ECOSYSTEM_TYPE_SKILL ships on this phase — every other type stays off.
    assert cfg.ECOSYSTEM_TYPE_SKILL is True
    assert cfg.ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG is True
    assert cfg.ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO is True


def test_object_storage_backend_default(_isolate_ecosystem_env):
    assert _isolate_ecosystem_env.ECOSYSTEM_OBJECT_STORAGE_BACKEND == "local"


def test_flags_are_overridable_via_env(monkeypatch):
    monkeypatch.setenv("ENABLE_ECOSYSTEM_MARKETPLACE", "true")
    monkeypatch.setenv("ECOSYSTEM_TYPE_SKILL", "false")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "s3")
    cfg = _reload_config()
    assert cfg.ENABLE_ECOSYSTEM_MARKETPLACE is True
    assert cfg.ECOSYSTEM_TYPE_SKILL is False
    assert cfg.ECOSYSTEM_OBJECT_STORAGE_BACKEND == "s3"
