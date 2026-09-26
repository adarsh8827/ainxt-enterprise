# SPDX-License-Identifier: MIT
# ============================================================
# Policy service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-19):
# sharing, reporting, force-disable/unyank, featured overrides, and the
# require/unrequire actions from the Review round following M1 (item F).
#
# Org policy CRUD (who_can_add/allowed_sources/auto_update_default/shared-
# connector policy) is NOT implemented this pass — it needs a dedicated
# ecosystem_org_policy-shaped table this phase's migration (task B-1)
# didn't create (CONFIG_AND_PRODUCTS.md's policy_summary read shape was
# speced, but no write-side table was ever added to the DDL) — disclosed
# as a real gap for whichever task next needs GET/PUT /ecosystem/policy to
# actually persist anything, rather than silently faked here.
# ============================================================

from __future__ import annotations

from typing import Any

from db.database import SessionLocal
from db.models import EcosystemFeaturedOverride, EcosystemInstall, EcosystemItem, EcosystemReport, EcosystemShare
from services.ecosystem.errors import NotFoundError

# Task B-19's own test requirement names this exact scenario; a small,
# deliberately conservative threshold for a first-party marketplace where
# reporting is unrestricted (never permission-gated, so it must not be too
# easy to accidentally auto-hide something on a couple of spurious reports).
_AUTO_HIDE_REPORT_THRESHOLD = 3


def share(install_id: str, shared_with_type: str, shared_with_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        install = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if install is None:
            raise NotFoundError(f"no install {install_id!r}")
        row = EcosystemShare(install_id=install_id, shared_with_type=shared_with_type, shared_with_id=shared_with_id)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"share_id": row.id, "install_id": install_id, "shared_with_type": shared_with_type, "shared_with_id": shared_with_id}
    finally:
        db.close()


def unshare(share_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(EcosystemShare).filter(EcosystemShare.id == share_id).first()
        if row is None:
            raise NotFoundError(f"no share {share_id!r}")
        db.delete(row)
        db.commit()
    finally:
        db.close()


def report(item_id: str, reported_by: str, reason: str) -> dict[str, Any]:
    """Reporting a suspect item is deliberately never permission-gated
    (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-19) — restricting who can
    flag a problem works against the gate's own safety goals."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise NotFoundError(f"no item {item_id!r}")

        row = EcosystemReport(item_id=item_id, reported_by=reported_by, reason=reason)
        db.add(row)
        db.commit()
        db.refresh(row)

        open_count = (
            db.query(EcosystemReport)
            .filter(EcosystemReport.item_id == item_id, EcosystemReport.status == "open")
            .count()
        )
        if open_count >= _AUTO_HIDE_REPORT_THRESHOLD:
            db.query(EcosystemReport).filter(
                EcosystemReport.item_id == item_id, EcosystemReport.status == "open"
            ).update({"status": "auto_hidden"}, synchronize_session=False)
            db.commit()

        return {"report_id": row.id, "item_id": item_id, "status": row.status}
    finally:
        db.close()


def force_disable(item_id: str) -> None:
    """Admin-only (enforced by the router's require_permission dependency,
    not here — this function trusts its caller). Maps to ecosystem_items
    .status='yanked', the same status an upstream-source-initiated removal
    already uses — force_disable is the platform-initiated equivalent."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise NotFoundError(f"no item {item_id!r}")
        item.status = "yanked"
        db.commit()
    finally:
        db.close()


def unyank(item_id: str) -> None:
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise NotFoundError(f"no item {item_id!r}")
        item.status = "active"
        db.commit()
    finally:
        db.close()


def set_featured_override(org_id: str, item_id: str, featured: bool, set_by: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemFeaturedOverride)
            .filter(EcosystemFeaturedOverride.org_id == org_id, EcosystemFeaturedOverride.item_id == item_id)
            .first()
        )
        if existing is not None:
            existing.featured = featured
            existing.set_by = set_by
            db.commit()
            return {"org_id": org_id, "item_id": item_id, "featured": featured}
        row = EcosystemFeaturedOverride(org_id=org_id, item_id=item_id, featured=featured, set_by=set_by)
        db.add(row)
        db.commit()
        return {"org_id": org_id, "item_id": item_id, "featured": featured}
    finally:
        db.close()


def delete_featured_override(org_id: str, item_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(EcosystemFeaturedOverride).filter(
            EcosystemFeaturedOverride.org_id == org_id, EcosystemFeaturedOverride.item_id == item_id
        ).delete()
        db.commit()
    finally:
        db.close()


def require_item(item_id: str, org_id: str) -> int:
    """Promotes every existing 'provisioned' install of item_id in org_id to
    'required' (CONFIG_AND_PRODUCTS.md §12 point 3/Review round item F) —
    removing 'disable' from their allowed_actions. Future lazy-provisioning
    calls (task B-12) are expected to check for this via the same
    origin='required' rows this creates, so a not-yet-provisioned user gets
    'required' from their first call rather than 'provisioned'. Returns the
    number of rows promoted."""
    db = SessionLocal()
    try:
        count = (
            db.query(EcosystemInstall)
            .filter(
                EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id,
                EcosystemInstall.origin == "provisioned",
            )
            .update({"scope": "required", "origin": "required"}, synchronize_session=False)
        )
        db.commit()
        return count
    finally:
        db.close()


def unrequire_item(item_id: str, org_id: str) -> int:
    db = SessionLocal()
    try:
        count = (
            db.query(EcosystemInstall)
            .filter(
                EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id,
                EcosystemInstall.origin == "required",
            )
            .update({"scope": "provisioned", "origin": "provisioned"}, synchronize_session=False)
        )
        db.commit()
        return count
    finally:
        db.close()
