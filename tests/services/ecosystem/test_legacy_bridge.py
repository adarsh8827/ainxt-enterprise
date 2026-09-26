# SPDX-License-Identifier: MIT
# ============================================================
# Legacy bridge tests (task B-4). Tier-2 for the skills_pg read path (real
# Postgres); the AgentStudio path is tested for its graceful-degradation
# behavior only, since AgentStudio's own DB isn't available in this
# milestone's test environment.
# ============================================================

from __future__ import annotations

import asyncio
import uuid

import pytest

from db.database import SessionLocal
from db.models import SkillRecord
from services.ecosystem.legacy_bridge import list_agentstudio_skills, list_behavioral_skills_pg_items, slugify


@pytest.fixture(autouse=True)
def _clean_skills_pg():
    db = SessionLocal()
    try:
        db.query(SkillRecord).filter(SkillRecord.name.like("test-bridge-%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _make_skill(name: str, skill_type: str, org_id: str = "org-a") -> str:
    db = SessionLocal()
    try:
        row = SkillRecord(
            id=str(uuid.uuid4()),
            name=name,
            org_id=org_id,
            description=f"description for {name}",
            skill_type=skill_type,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def test_slugify_lowercases_and_collapses_invalid_chars():
    assert slugify("My Skill Name!") == "my-skill-name"


def test_slugify_pads_short_results():
    assert len(slugify("a")) >= 2


def test_slugify_empty_string_falls_back_to_item():
    assert slugify("") == "item"


def test_list_behavioral_skills_pg_items_includes_behavioral_only():
    _make_skill("test-bridge-behavioral", "behavioral")
    _make_skill("test-bridge-execution", "execution")

    items = list_behavioral_skills_pg_items()
    names = {i["name"] for i in items}
    assert "test-bridge-behavioral" in names
    assert "test-bridge-execution" not in names


def test_list_behavioral_skills_pg_items_carries_org_id():
    _make_skill("test-bridge-org-carry", "behavioral", org_id="org-carry")
    items = list_behavioral_skills_pg_items()
    match = next(i for i in items if i["name"] == "test-bridge-org-carry")
    assert match["org_id"] == "org-carry"


def test_list_agentstudio_skills_degrades_gracefully_when_unavailable(monkeypatch):
    # Force the import to fail, simulating a deployment without AgentStudio
    # configured -- must return [], never raise.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("AgentStudio"):
            raise ImportError("simulated: AgentStudio not available in this deployment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    result = asyncio.run(list_agentstudio_skills())
    assert result == []
