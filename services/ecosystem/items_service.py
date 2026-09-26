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
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion, EcosystemSource
from services.ecosystem.errors import NotFoundError

# CONTRACTS.md §6's full allowed_actions value set.
_ALL_ACTIONS = (
    "install", "uninstall", "enable", "disable", "update", "rollback",
    "share", "unshare", "report", "deprecate", "delete_draft",
    "force_disable", "unyank", "edit_policy",
)


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


def get_or_create_import_source(kind: str, url: str, created_by: str, tos_notes: str) -> str:
    """Return the id of the ecosystem_sources row for this exact external
    location, creating it on first import (task I, pre-M3).

    Instance-level, not per-org (org_id=None) -- github_repo/well_known
    content is the same external repo/domain regardless of which org
    imports it, unlike get_or_create_local_source()'s deliberately
    per-org 'local' row. One row per distinct (kind, url) records ToS
    acknowledgement (tos_checked_at/tos_notes) the first time that exact
    location is imported from; a later import of the same location reuses
    it and does not re-stamp tos_checked_at.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.kind == kind, EcosystemSource.url == url)
            .first()
        )
        if existing is not None:
            return existing.id

        from datetime import datetime, timezone

        row = EcosystemSource(
            kind=kind,
            url=url,
            org_id=None,
            created_by=created_by,
            tos_checked_at=datetime.now(timezone.utc),
            tos_notes=tos_notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def get_or_create_builtin_source(created_by: str = "system") -> str:
    """The one platform-level (org_id=NULL) 'local' source row every
    scope='builtin' item (task B-22) points at. Distinct from the per-org
    'local' sources get_or_create_local_source() manages — builtin items
    are org-independent, so they can't use an org-scoped source (and the
    DB's ux_ecosystem_sources_one_local_per_org partial index doesn't
    reliably dedupe NULL org_id rows on its own, since a plain UNIQUE index
    allows multiple NULLs — this function's own existing-row check is what
    actually keeps it to exactly one)."""
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.org_id.is_(None), EcosystemSource.kind == "local")
            .first()
        )
        if existing is not None:
            return existing.id
        row = EcosystemSource(kind="local", org_id=None, created_by=created_by)
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


def upsert_builtin_item(
    *,
    namespace: str,
    item_type: str,
    category: str,
    display_name: str,
    description: str,
    license: str = "MIT",
) -> tuple[str, bool]:
    """Upsert a scope='builtin' item (task B-22's seeding). Matched by
    namespace+item_type — re-running the seed step twice updates metadata
    in place rather than creating a duplicate row (the global namespace
    partial unique index from task B-1 would reject a literal duplicate
    anyway; this makes the upsert explicit rather than relying on catching
    that constraint violation).

    Returns (item_id, created).
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.namespace == namespace, EcosystemItem.item_type == item_type)
            .first()
        )
        source_id = get_or_create_builtin_source()

        if existing is not None:
            existing.display_name = display_name
            existing.description = description
            existing.category = category
            existing.source_id = source_id
            db.commit()
            return existing.id, False

        row = EcosystemItem(
            namespace=namespace, item_type=item_type, category=category,
            display_name=display_name, description=description, source_id=source_id,
            scope="builtin", org_id=None, trust_tier="builtin", license=license,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, True
    finally:
        db.close()


def get_item_row(item_id: str) -> EcosystemItem:
    """Raise NotFoundError if item_id doesn't exist — the ORM-row form used
    internally by other services (compute_allowed_actions, create_service,
    installs_service). get_item() below is the public, dict-shaped read."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if row is None:
            raise NotFoundError(f"no ecosystem item {item_id!r}")
        db.expunge(row)
        return row
    finally:
        db.close()


def get_item(item_id: str) -> dict[str, Any] | None:
    """Public read — filled in fully by task B-11 (M3), which adds
    resolver-driven visibility filtering. This is a minimal, direct lookup
    sufficient for B-6/B-10's own needs (e.g. confirming an item exists
    before acting on it) — not the final GET /ecosystem/items/{id} shape."""
    try:
        row = get_item_row(item_id)
    except NotFoundError:
        return None
    return {
        "id": row.id, "namespace": row.namespace, "item_type": row.item_type,
        "display_name": row.display_name, "description": row.description,
        "category": row.category, "scope": row.scope, "org_id": row.org_id,
        "trust_tier": row.trust_tier, "license": row.license, "status": row.status,
        "legacy_source": row.legacy_source,
    }


def list_items(**filters: Any) -> list[dict[str, Any]]:
    """Stub — filled in by task B-11 (M3), which needs the resolver's
    visibility rules (surface/enabled_item_types filtering) to do this
    correctly. Not needed by any M2 task."""
    raise NotImplementedError("items_service.list_items lands in task B-11 (M3)")


def get_latest_version(item_id: str) -> EcosystemItemVersion | None:
    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id)
            .order_by(EcosystemItemVersion.created_at.desc())
            .first()
        )
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def compute_allowed_actions(
    *,
    item: EcosystemItem,
    caller_user_id: str,
    caller_org_id: str,
    caller_permissions: set[str],
    install: EcosystemInstall | None = None,
    is_owner: bool = False,
    has_other_installs: bool = False,
    has_multiple_versions: bool = False,
    newer_version_available: bool = False,
) -> list[str]:
    """The single source of truth for CONTRACTS.md §6's allowed_actions —
    every router endpoint that mutates an item/install re-derives this
    itself server-side rather than trusting whatever the client last saw,
    per the standing "allowed_actions enforced server-side" rule.

    Pure function, no DB access — callers gather the boolean context
    (there's an install? multiple versions? etc.) so this stays trivially
    unit-testable without a database.
    """
    actions: set[str] = set()

    item_retired = item.status in ("deprecated", "yanked", "source_unavailable")

    if install is None:
        if not item_retired:
            actions.add("install")
    else:
        actions.add("uninstall")
        if install.scope != "required":
            actions.add("enable" if not install.enabled else "disable")
        if newer_version_available and not item_retired:
            actions.add("update")
        if has_multiple_versions:
            actions.add("rollback")
        if "marketplace:share" in caller_permissions:
            actions.add("share")
        if install.scope == "shared":
            actions.add("unshare")

    # Reporting a suspect item is deliberately never permission-gated —
    # restricting who can flag a problem works against the gate's own
    # safety goals (task B-19).
    actions.add("report")

    if item.status == "active" and (is_owner or "marketplace:admin_sources" in caller_permissions):
        actions.add("deprecate")

    # delete_draft: owner-only, item still private, and no OTHER install
    # exists besides the owner's own (CONTRACTS.md §6, Review fix 6).
    if is_owner and item.scope == "org_private" and item.org_id == caller_org_id and not has_other_installs:
        actions.add("delete_draft")

    if "marketplace:admin_sources" in caller_permissions:
        if item.status != "yanked":
            actions.add("force_disable")
        else:
            actions.add("unyank")

    if "marketplace:admin_policy" in caller_permissions:
        actions.add("edit_policy")

    # Stable, documented order — never set iteration order, which is
    # insertion-order-dependent and not something a client should rely on
    # but shouldn't be gratuitously random between calls either.
    return [a for a in _ALL_ACTIONS if a in actions]


def create_item(**payload: Any) -> dict[str, Any]:
    """Stub — filled in by task B-6 (M2), see services/ecosystem/create_service.py."""
    raise NotImplementedError("items_service.create_item lands in task B-6 (M2) — see create_service.py")
