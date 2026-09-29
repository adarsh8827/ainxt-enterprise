#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-off removal for real neutrality violations found live (2026-09-29):
a full content scan (services/ecosystem/catalog_crawler/neutrality_check.py's
real scan_for_ai_vendor_names(), against real DB content, not a synthetic
sample) found the crawler-pipeline's own automated neutrality check
(crawl.py) never runs for items imported via
services/ecosystem/create_service.py's create_via_import() -- the manual/
admin path scripts/ecosystem/admin_import.py's starter batch uses. One real
item landed through exactly that gap:
`addyosmani/documentation-and-adrs` (skill), whose content includes
"CLAUDE.md / rules files" -- a specific AI assistant's own convention-file
naming, the same pattern already disclosed and accepted for
mattpocock/skills in docs/ecosystem/catalog/sources.yaml, but never
supposed to reach the actual catalog for a NEW import. Fixed at the source
going forward: create_service.py's create_via_import() now runs the same
scanner before creating an item (see _reject_if_names_an_ai_vendor()) --
this script only removes rows that already landed in the DB before that
fix existed.

Deliberately narrower in scope than a full "delete_draft()" (which is a
CALLER-scoped action with its own is_owner/has_other_installs checks) --
this is an admin/compliance hard-removal of an item found to violate a
platform-wide rule after the fact, regardless of who owns/installed it.
Removes the item + its versions + gate runs/findings + installs, same
underlying tables items_service.delete_draft() touches, but without that
function's caller-authorization gate (there is no "caller" here -- this is
a compliance action, not a user-initiated one).

Also SCANS every other real catalog item's actual content (not just
metadata) for the same violation and reports any additional hits, without
removing them automatically -- a second real hit requires a human decision
per item, this script only auto-acts on the one namespace explicitly
confirmed live, to avoid removing something on a coincidental substring
match without a person having actually looked at it.

Usage:
    python -m scripts.ecosystem.remove_neutrality_violations [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import EcosystemGateFinding, EcosystemGateRun, EcosystemInstall, EcosystemItem, EcosystemItemVersion

# The one namespace confirmed live, 2026-09-29, via a real content scan --
# see this module's own docstring. Not a pattern/glob; adding another
# namespace here is a deliberate, reviewed decision, never automatic.
_CONFIRMED_VIOLATIONS = ("addyosmani/documentation-and-adrs",)


def scan_all_catalog_items_for_vendor_names(db: Session) -> dict[str, list[str]]:
    """Returns {namespace: [vendor names found]} for every ecosystem_items
    row whose latest version's manifest instructions (or display_name/
    description) name a specific AI vendor/product, per the real scanner --
    a superset of _CONFIRMED_VIOLATIONS, for reporting only."""
    from services.ecosystem.catalog_crawler.neutrality_check import scan_for_ai_vendor_names

    hits: dict[str, list[str]] = {}
    for item in db.query(EcosystemItem).all():
        version = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item.id)
            .order_by(EcosystemItemVersion.created_at.desc())
            .first()
        )
        text_to_scan = f"{item.display_name} {item.description}"
        if version is not None and isinstance(version.manifest, dict):
            text_to_scan += " " + str(version.manifest.get("instructions", ""))
        found = scan_for_ai_vendor_names(text_to_scan)
        if found:
            hits[item.namespace] = found
    return hits


def remove_item_hard(db: Session, item_id: str) -> None:
    """Same table set items_service.delete_draft() removes (versions, gate
    runs/findings, installs, the item itself) -- no caller-authorization
    check, since this is a compliance action, not a user-initiated one."""
    version_ids = [
        v.id for v in db.query(EcosystemItemVersion.id).filter(EcosystemItemVersion.item_id == item_id).all()
    ]
    if version_ids:
        gate_run_ids = [
            g.id for g in db.query(EcosystemGateRun.id).filter(EcosystemGateRun.version_id.in_(version_ids)).all()
        ]
        if gate_run_ids:
            db.query(EcosystemGateFinding).filter(
                EcosystemGateFinding.gate_run_id.in_(gate_run_ids)
            ).delete(synchronize_session=False)
            db.query(EcosystemGateRun).filter(EcosystemGateRun.id.in_(gate_run_ids)).delete(synchronize_session=False)
    db.query(EcosystemInstall).filter(EcosystemInstall.item_id == item_id).delete(synchronize_session=False)
    db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).delete(synchronize_session=False)
    db.query(EcosystemItem).filter(EcosystemItem.id == item_id).delete(synchronize_session=False)


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    db = SessionLocal()
    try:
        print("=== full catalog scan for AI-vendor-naming (real content, not metadata guesses) ===")
        all_hits = scan_all_catalog_items_for_vendor_names(db)
        for namespace, names in sorted(all_hits.items()):
            flag = " <- REMOVING (confirmed)" if namespace in _CONFIRMED_VIOLATIONS else " <- found, not auto-removed, needs review"
            print(f"  {namespace}: {names}{flag}")
        if not all_hits:
            print("  (none found)")

        removable = [
            item for item in db.query(EcosystemItem).all()
            if item.namespace in _CONFIRMED_VIOLATIONS
        ]
        if not removable:
            print("nothing to remove: no confirmed-violation namespace exists in the DB")
            return

        for item in removable:
            print(f"{'[dry-run] would remove' if dry_run else 'removing'}: {item.namespace} ({item.id})")

        if dry_run:
            print(f"[dry-run] {len(removable)} item(s) would be removed -- no changes made")
            return

        removed = [(item.id, item.namespace) for item in removable]
        for item_id, _ in removed:
            remove_item_hard(db, item_id)
        db.commit()
        print(f"removed: {len(removed)} item(s)")
    finally:
        db.close()

    from services.ecosystem.audit_service import write_audit_event
    for item_id, namespace in removed:
        try:
            write_audit_event(
                org_id="default", actor="system:remove_neutrality_violations", action="compliance_removal",
                item_id=None,  # the item is already gone -- same rationale as delete_draft()'s own audit write
                details={"namespace": namespace, "reason": "names a specific AI vendor/product", "deleted_item_id": item_id},
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
