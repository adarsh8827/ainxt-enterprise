# SPDX-License-Identifier: MIT
# ============================================================
# Items service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3 skeleton).
#
# get_or_create_local_source() and upsert_legacy_pointer_item() are real,
# not stubs — task B-4's backfill job (M1) needs them now, ahead of the
# create/list/get lifecycle (task B-6/B-10, M2) that fills in the rest of
# this file. See docs/ecosystem/design/LLD/data-model.md.
# ============================================================

from __future__ import annotations

from typing import Any

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemSource


def get_or_create_local_source(org_id: str, created_by: str = "system") -> str:
    """Return the id of org_id's 'local' ecosystem_sources row, creating it
    if this is the org's first user/agent-created (or backfilled) item.

    Exactly one 'local' source per org (db/migrate.py's
    ux_ecosystem_sources_one_local_per_org partial unique index, task B-1) —
    every item an org creates directly, or that gets backfilled from a
    legacy table on that org's behalf, points at this one row rather than a
    shared platform-wide row (M0-review fix, see CHANGELOG.md).
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.org_id == org_id, EcosystemSource.kind == "local")
            .first()
        )
        if existing is not None:
            return existing.id

        row = EcosystemSource(
            kind="local",
            org_id=org_id,
            created_by=created_by,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def upsert_legacy_pointer_item(
    *,
    namespace: str,
    item_type: str,
    category: str,
    display_name: str,
    description: str,
    org_id: str,
    legacy_source: str,
    legacy_ref: str,
    license: str = "MIT",
    trust_tier: str = "org",
) -> tuple[str, bool]:
    """Upsert a pointer-only ecosystem_items row for a legacy-bridged item
    (task B-4's backfill job). Matched by (legacy_source, legacy_ref) —
    re-running the backfill job is a no-op for an already-mirrored row
    (its metadata is refreshed in place, no duplicate is created).

    Returns (item_id, created) — created=True only the first time this
    (legacy_source, legacy_ref) pair is seen.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.legacy_source == legacy_source, EcosystemItem.legacy_ref == legacy_ref)
            .first()
        )
        source_id = get_or_create_local_source(org_id)

        if existing is not None:
            existing.display_name = display_name
            existing.description = description
            existing.category = category
            existing.source_id = source_id
            db.commit()
            return existing.id, False

        row = EcosystemItem(
            namespace=namespace,
            item_type=item_type,
            category=category,
            display_name=display_name,
            description=description,
            source_id=source_id,
            scope="org_private",
            org_id=org_id,
            trust_tier=trust_tier,
            license=license,
            legacy_source=legacy_source,
            legacy_ref=legacy_ref,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, True
    finally:
        db.close()


def get_item(item_id: str) -> dict[str, Any] | None:
    """Stub — filled in by task B-6/B-10 (M2)."""
    raise NotImplementedError("items_service.get_item lands in task B-6/B-10 (M2)")


def list_items(**filters: Any) -> list[dict[str, Any]]:
    """Stub — filled in by task B-6/B-11 (M2/M3)."""
    raise NotImplementedError("items_service.list_items lands in task B-6/B-11 (M2/M3)")


def create_item(**payload: Any) -> dict[str, Any]:
    """Stub — filled in by task B-6 (M2)."""
    raise NotImplementedError("items_service.create_item lands in task B-6 (M2)")
