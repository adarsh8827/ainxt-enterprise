# SPDX-License-Identifier: MIT
# ============================================================
# Backfill job end-to-end tests (task B-4). Tier-2 — real Postgres.
# Covers the skills_pg half of the job; the AgentStudio half is exercised
# separately by test_legacy_bridge.py's graceful-degradation test, since
# AgentStudio's own DB isn't available in this milestone's test environment.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from db.database import SessionLocal
from db.models import EcosystemItem, SkillRecord


@pytest.fixture(autouse=True)
def _clean_skills_pg():
    db = SessionLocal()
    try:
        db.query(SkillRecord).filter(SkillRecord.name.like("test-backfill-%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _make_skill(name: str, org_id: str = "org-backfill") -> str:
    db = SessionLocal()
    try:
        row = SkillRecord(
            id=str(uuid.uuid4()), name=name, org_id=org_id,
            description=f"description for {name}", skill_type="behavioral",
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def test_backfill_skills_pg_mirrors_behavioral_skill(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG", "true")
    import importlib

    import core.config as config_module

    importlib.reload(config_module)

    from scripts.ecosystem.backfill_legacy_items import _backfill_skills_pg

    _make_skill("test-backfill-once")
    mirrored, created = _backfill_skills_pg()
    assert mirrored >= 1
    assert created >= 1

    db = SessionLocal()
    try:
        item = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.legacy_source == "skills_pg", EcosystemItem.display_name == "test-backfill-once")
            .one()
        )
    finally:
        db.close()
    assert item.status == "active"
    assert item.license == "MIT"
    assert item.org_id == "org-backfill"


def test_backfill_skills_pg_is_idempotent_across_runs(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG", "true")
    import importlib

    import core.config as config_module

    importlib.reload(config_module)

    from scripts.ecosystem.backfill_legacy_items import _backfill_skills_pg

    _make_skill("test-backfill-twice")
    _, created_run1 = _backfill_skills_pg()
    _, created_run2 = _backfill_skills_pg()

    assert created_run2 == 0  # nothing new the second time

    db = SessionLocal()
    try:
        count = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.legacy_source == "skills_pg", EcosystemItem.display_name == "test-backfill-twice")
            .count()
        )
    finally:
        db.close()
    assert count == 1  # no duplicate row


def test_backfill_never_writes_to_skills_pg():
    before = _make_skill("test-backfill-untouched")

    from scripts.ecosystem.backfill_legacy_items import _backfill_skills_pg

    _backfill_skills_pg()

    db = SessionLocal()
    try:
        row = db.query(SkillRecord).filter(SkillRecord.id == before).one()
    finally:
        db.close()
    # Original legacy row is completely unmodified by the backfill job.
    assert row.name == "test-backfill-untouched"
    assert row.skill_type == "behavioral"
