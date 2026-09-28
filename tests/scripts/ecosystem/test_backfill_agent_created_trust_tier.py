# SPDX-License-Identifier: MIT
# ============================================================
# Item 3 (M5 UI-polish round 2, 2026-09-28): backfill for a Create-with-AI
# item created BEFORE the same-day created_via_ai -> trust_tier='agent_created'
# fix, which only affects new submissions going forward. Tier-2 -- real
# Postgres, same construction pattern as test_config_service.py's
# _make_builtin_item().
# ============================================================

from __future__ import annotations

import uuid

import pytest

from db.database import SessionLocal
from db.models import EcosystemDraft, EcosystemItem, EcosystemPublisher, EcosystemSource
from scripts.ecosystem.backfill_agent_created_trust_tier import (
    backfill_agent_created_trust_tier,
    find_backfill_candidates,
)


def _make_item(namespace: str, trust_tier: str) -> str:
    db = SessionLocal()
    try:
        pub_slug = namespace.split("/")[0]
        if db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == pub_slug).first() is None:
            db.add(EcosystemPublisher(slug=pub_slug, owner_type="user", owner_ref="test-user"))
        source = EcosystemSource(kind="local", org_id="org-backfill-test", created_by="test-user")
        db.add(source)
        db.commit()
        db.refresh(source)

        item = EcosystemItem(
            namespace=namespace, item_type="skill", category="general",
            display_name="Backfill Test Item", description="d", source_id=source.id,
            scope="org_private", org_id="org-backfill-test", trust_tier=trust_tier, license="MIT",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def _make_submitted_draft(item_id: str) -> None:
    db = SessionLocal()
    try:
        db.add(EcosystemDraft(
            id=str(uuid.uuid4()), org_id="org-backfill-test", created_by="test-user",
            item_type="skill", status="submitted", submitted_item_id=item_id,
        ))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(EcosystemItem.id).filter(EcosystemItem.namespace.like("backfill-test/%")).all()]
        if ids:
            db.query(EcosystemDraft).filter(EcosystemDraft.submitted_item_id.in_(ids)).delete(synchronize_session=False)
            db.query(EcosystemItem).filter(EcosystemItem.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


def test_finds_and_fixes_a_community_item_with_a_matching_submitted_draft():
    item_id = _make_item(f"backfill-test/via-ai-{uuid.uuid4().hex[:8]}", trust_tier="community")
    _make_submitted_draft(item_id)

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert item_id in [c[0] for c in candidates]

        fixed = backfill_agent_created_trust_tier(db)
        db.commit()
        assert fixed >= 1

        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        assert item.trust_tier == "agent_created"
    finally:
        db.close()


def test_never_touches_a_community_item_with_no_submitted_draft():
    item_id = _make_item(f"backfill-test/plain-write-{uuid.uuid4().hex[:8]}", trust_tier="community")

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert item_id not in [c[0] for c in candidates]

        backfill_agent_created_trust_tier(db)
        db.commit()

        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        assert item.trust_tier == "community"  # untouched -- no reliable signal it was AI-created
    finally:
        db.close()


def test_never_overrides_a_non_community_tier_even_with_a_matching_draft():
    # A verified/org/builtin item with a matching draft is a real, if odd,
    # possibility (e.g. later manually re-verified) -- this backfill only
    # ever touches 'community', never overriding a deliberate later change.
    item_id = _make_item(f"backfill-test/later-verified-{uuid.uuid4().hex[:8]}", trust_tier="verified")
    _make_submitted_draft(item_id)

    db = SessionLocal()
    try:
        backfill_agent_created_trust_tier(db)
        db.commit()

        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        assert item.trust_tier == "verified"
    finally:
        db.close()


def test_idempotent_second_run_fixes_nothing_new():
    item_id = _make_item(f"backfill-test/idempotent-{uuid.uuid4().hex[:8]}", trust_tier="community")
    _make_submitted_draft(item_id)

    db = SessionLocal()
    try:
        first_run = backfill_agent_created_trust_tier(db)
        db.commit()
        assert first_run >= 1

        second_run = backfill_agent_created_trust_tier(db)
        db.commit()
        assert second_run == 0
    finally:
        db.close()
