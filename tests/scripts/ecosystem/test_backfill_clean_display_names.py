# SPDX-License-Identifier: MIT
# ============================================================
# Real bug found live (2026-09-29): a catalog item's display_name showed
# the source repo's own internal namespacing convention verbatim (e.g.
# "stitch::react-native"). Fixed at the source going forward in
# github_repo.py/well_known.py's _clean_display_name() -- this backfill
# covers rows already in the DB from before that fix. Tier-2 -- real
# Postgres, same construction pattern as test_config_service.py's
# _make_builtin_item().
# ============================================================

from __future__ import annotations

import uuid

import pytest

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemPublisher, EcosystemSource
from scripts.ecosystem.backfill_clean_display_names import (
    backfill_clean_display_names,
    find_backfill_candidates,
)


def _make_item(namespace: str, display_name: str) -> str:
    db = SessionLocal()
    try:
        pub_slug = namespace.split("/")[0]
        if db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == pub_slug).first() is None:
            db.add(EcosystemPublisher(slug=pub_slug, owner_type="org", owner_ref="platform"))
        source = EcosystemSource(kind="github_repo", org_id=None, created_by="system")
        db.add(source)
        db.commit()
        db.refresh(source)

        item = EcosystemItem(
            namespace=namespace, item_type="skill", category="general",
            display_name=display_name, description="d", source_id=source.id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(EcosystemItem.id).filter(EcosystemItem.namespace.like("clean-name-test/%")).all()]
        if ids:
            db.query(EcosystemItem).filter(EcosystemItem.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


def test_finds_and_fixes_a_namespaced_display_name():
    namespace = f"clean-name-test/react-native-{uuid.uuid4().hex[:8]}"
    item_id = _make_item(namespace, "stitch::react-native")

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert item_id in [c[0] for c in candidates]

        fixed = backfill_clean_display_names(db)
        db.commit()
        assert fixed >= 1

        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        assert item.display_name == namespace.rsplit("/", 1)[-1]
        assert "::" not in item.display_name
    finally:
        db.close()


def test_never_touches_a_normal_display_name():
    namespace = f"clean-name-test/normal-{uuid.uuid4().hex[:8]}"
    item_id = _make_item(namespace, "Meeting Notes Summarizer")

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert item_id not in [c[0] for c in candidates]

        backfill_clean_display_names(db)
        db.commit()

        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        assert item.display_name == "Meeting Notes Summarizer"
    finally:
        db.close()


def test_idempotent_second_run_fixes_nothing_new():
    namespace = f"clean-name-test/idempotent-{uuid.uuid4().hex[:8]}"
    _make_item(namespace, "stitch::idempotent-check")

    db = SessionLocal()
    try:
        first_run = backfill_clean_display_names(db)
        db.commit()
        assert first_run >= 1

        second_run = backfill_clean_display_names(db)
        db.commit()
        assert second_run == 0
    finally:
        db.close()
