# SPDX-License-Identifier: MIT
# ============================================================
# Installs service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-10):
# install/uninstall/enable/disable/update/rollback. share/unshare/report/
# force_disable/unyank/deprecate/delete_draft/require/unrequire are task
# B-19's own additions in policy_service.py — this file owns the install
# row's own lifecycle only.
# ============================================================

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItemVersion
from services.ecosystem.errors import EcosystemError, NotFoundError


class ConflictError(EcosystemError):
    """A second install of the same item already exists for this
    (item_id, org_id, installed_for) — maps to CONTRACTS.md §3's CONFLICT."""


def install(
    *,
    item_id: str,
    version_id: str,
    org_id: str,
    installed_by: str,
    installed_for: str | None,
    surfaces: list[str],
    scope: str = "private",
    origin: str = "added",
    auto_update: bool = False,
) -> dict[str, Any]:
    """Create an install row. Raises ConflictError (not a silent duplicate)
    if one already exists for (item_id, org_id, installed_for) — the
    UNIQUE NULLS NOT DISTINCT constraint from task B-1 enforces this at the
    DB level; this function turns that constraint violation into a typed,
    catchable error rather than a raw IntegrityError leaking to the router.
    """
    db = SessionLocal()
    try:
        row = EcosystemInstall(
            item_id=item_id,
            version_id=version_id,
            org_id=org_id,
            installed_by=installed_by,
            installed_for=installed_for,
            scope=scope,
            origin=origin,
            surfaces=surfaces,
            auto_update=auto_update,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictError(
                f"an install already exists for item {item_id!r} in org {org_id!r}"
            ) from exc
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def get_install(install_id: str) -> EcosystemInstall:
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        db.expunge(row)
        return row
    finally:
        db.close()


def get_install_for_caller(item_id: str, org_id: str, installed_for: str | None) -> EcosystemInstall | None:
    """The (item_id, org_id, installed_for) triple is exactly the unique
    key from task B-1 — this is the canonical "does the caller already
    have this installed" lookup every allowed_actions computation needs."""
    db = SessionLocal()
    try:
        query = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id
        )
        query = query.filter(EcosystemInstall.installed_for.is_(None)) if installed_for is None else query.filter(
            EcosystemInstall.installed_for == installed_for
        )
        row = query.first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def uninstall(install_id: str) -> None:
    """Removes only the caller's own install row. Never touches
    ecosystem_items — uninstalling is never a way to affect the item
    itself (CONTRACTS.md §6's deprecate/uninstall distinction)."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        db.delete(row)
        db.commit()
    finally:
        db.close()


def set_enabled(install_id: str, enabled: bool) -> dict[str, Any]:
    """Toggle enable/disable. Refuses on scope='required' rows — those are
    only reachable via policy_service's unrequire (task B-19), never a
    plain disable, matching CONFIG_AND_PRODUCTS.md §12 point 3."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        if row.scope == "required" and not enabled:
            raise EcosystemError(f"install {install_id!r} is required and cannot be disabled")
        row.enabled = enabled
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def update_to_version(install_id: str, new_version_id: str) -> dict[str, Any]:
    """Point an install at a newer (already-gated) version. Never mutates
    ecosystem_item_versions — versions are immutable; this only moves which
    version_id the install row references."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == new_version_id).first()
        if version is None or version.item_id != row.item_id:
            raise NotFoundError(f"version {new_version_id!r} does not belong to this install's item")
        row.version_id = new_version_id
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def rollback(install_id: str, target_version_id: str) -> dict[str, Any]:
    """Same mechanism as update_to_version — rollback is just "update to an
    older, still-immutable version" rather than a distinct code path."""
    return update_to_version(install_id, target_version_id)


def list_installs(org_id: str, installed_for: str | None, item_type: str | None = None) -> tuple[list[dict[str, Any]], bool]:
    """Returns (installs, has_any) — has_any backs CONTRACTS.md §7's
    default-view rule (Review fix 8) and is computed from installs alone;
    the legacy_items half of has_any (Review round following M1, item C)
    is the router's job to OR in, since this service has no legacy-bridge
    awareness."""
    db = SessionLocal()
    try:
        query = db.query(EcosystemInstall).filter(EcosystemInstall.org_id == org_id)
        query = query.filter(EcosystemInstall.installed_for.is_(None)) if installed_for is None else query.filter(
            EcosystemInstall.installed_for == installed_for
        )
        rows = query.all()
        return [_row_to_dict(r) for r in rows], len(rows) > 0
    finally:
        db.close()


def _row_to_dict(row: EcosystemInstall) -> dict[str, Any]:
    return {
        "install_id": row.id, "item_id": row.item_id, "version_id": row.version_id,
        "org_id": row.org_id, "scope": row.scope, "origin": row.origin,
        "installed_by": row.installed_by, "installed_for": row.installed_for,
        "enabled": row.enabled, "surfaces": row.surfaces, "auto_update": row.auto_update,
        "installed_at": row.installed_at.isoformat() if row.installed_at else None,
    }
