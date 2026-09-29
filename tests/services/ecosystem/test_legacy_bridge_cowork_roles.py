# SPDX-License-Identifier: MIT
# ============================================================
# Cowork-roles-as-plugins read-through bridge (Connectors+Plugins phase,
# PLUGINS_PHASE_PLAN.md item 3(a)). Same real-Postgres-tier convention as
# tests/services/ecosystem/test_legacy_bridge.py's skills_pg coverage.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from services import cowork_roles
from services.ecosystem.legacy_bridge import list_published_cowork_roles


def _make_role(name: str, *, publish: bool) -> str:
    role = cowork_roles.CoworkRole(
        name=name, system_prompt="be helpful", description=f"description for {name}", department="Sales",
    )
    created = cowork_roles.create_role(role)
    if publish:
        cowork_roles.publish_role(created.id, published_by="test-admin")
    return created.id


@pytest.fixture
def _cleanup_role_ids():
    ids: list[str] = []
    yield ids
    for role_id in ids:
        cowork_roles.delete_role(role_id)


def test_published_role_is_included(_cleanup_role_ids):
    name = f"test-bridge-published-{uuid.uuid4().hex[:8]}"
    role_id = _make_role(name, publish=True)
    _cleanup_role_ids.append(role_id)

    items = list_published_cowork_roles()
    match = next((i for i in items if i["legacy_ref"] == role_id), None)
    assert match is not None
    assert match["name"] == name
    assert match["category"] == "general"


def test_draft_role_is_excluded(_cleanup_role_ids):
    name = f"test-bridge-draft-{uuid.uuid4().hex[:8]}"
    role_id = _make_role(name, publish=False)
    _cleanup_role_ids.append(role_id)

    items = list_published_cowork_roles()
    assert all(i["legacy_ref"] != role_id for i in items)


def test_degrades_gracefully_when_list_all_roles_raises(monkeypatch):
    # Simulates the DB-unreachable case (mirrors
    # test_list_agentstudio_skills_degrades_gracefully_when_db_pool_unavailable's
    # style: patch the narrow function the bridge calls, not raw __import__).
    def _raise():
        raise RuntimeError("simulated: cowork_roles DB unreachable")

    monkeypatch.setattr(cowork_roles, "list_all_roles", _raise)
    result = list_published_cowork_roles()
    assert result == []
