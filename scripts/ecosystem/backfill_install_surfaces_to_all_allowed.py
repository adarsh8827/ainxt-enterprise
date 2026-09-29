#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-off backfill for the per-surface toggles round (2026-09-29): the
Chat/Agent Studio/Desktop per-surface toggle UI is gone for normal users
(packages/ecosystem-ui's Yours.tsx/SurfaceToggles.tsx/AddDialog.tsx) --
a NEW install now defaults to every surface its org's product profile
allows (services/ecosystem/config_service.get_org_enabled_surfaces()),
subject to the file/terminal-tools compatibility exception
(services/ecosystem/compatibility.enforce_compatibility_on_surfaces()).
That default only ever applies going forward (routers/ecosystem_router.py's
install_item()); it does nothing for an install row already sitting in the
DB with whatever narrower surfaces list a since-removed manual toggle (or
an old, narrower create-time default) left it with.

This backfill sets EVERY EcosystemInstall row's `surfaces` to the same
target its org/item combination would get from a fresh install today:
    enforce_compatibility_on_surfaces(compatibility, get_org_enabled_surfaces(org_id))
-- deliberately not "only touch rows that look untouched by an admin",
since normal users can no longer narrow this manually anyway (the one
remaining write path, set_install_surfaces, is admin-only per this same
round) -- there is no other legitimate reason left for an existing row to
sit at anything narrower than the full allowed set.

Reuses the exact same resolution functions the live install path calls
(config_service.get_org_enabled_surfaces, versions_service.get_manifest,
compatibility.enforce_compatibility_on_surfaces) rather than re-deriving
the rules in raw SQL, so this can never drift from what a fresh install
actually computes. Org/version lookups are cached per backfill run (a
given org_id/version_id is asked for repeatedly across many install rows)
to avoid re-querying the same product profile or manifest hundreds of
times.

Idempotent: re-running finds nothing left to fix the second time (every
row's `surfaces` already equals its own freshly-recomputed target).

Usage:
    python -m scripts.ecosystem.backfill_install_surfaces_to_all_allowed [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocal
from services.ecosystem.compatibility import CHAT, enforce_compatibility_on_surfaces
from services.ecosystem.config_service import get_org_enabled_surfaces
from services.ecosystem.versions_service import get_manifest

# Memoized within one script run only -- never persisted, never shared
# across invocations. Keeps a large installs table from re-resolving the
# same org's product profile (a real DB round trip) or the same item
# version's manifest once per install row.
_org_surfaces_cache: dict[str, list[str]] = {}
_version_compatibility_cache: dict[str, str] = {}


def _target_surfaces_for(org_id: str, version_id: str) -> list[str]:
    """The exact list a fresh install for this (org_id, version_id) would
    get today -- same two calls routers/ecosystem_router.py's install_item()
    itself makes, in the same order."""
    if org_id not in _org_surfaces_cache:
        _org_surfaces_cache[org_id] = get_org_enabled_surfaces(org_id)
    if version_id not in _version_compatibility_cache:
        _version_compatibility_cache[version_id] = get_manifest(version_id).get("compatibility", CHAT)
    return enforce_compatibility_on_surfaces(
        _version_compatibility_cache[version_id], _org_surfaces_cache[org_id]
    )


def find_backfill_candidates(db: Session) -> list[tuple[str, str, str, list[str], list[str]]]:
    """Returns [(install_id, org_id, version_id, old_surfaces, new_surfaces), ...]
    for every install whose current `surfaces` doesn't already match its
    own freshly-recomputed target. Exposed separately from
    backfill_install_surfaces_to_all_allowed() so a caller (this module's
    own `main()`, or a test) can inspect exactly what would be touched
    without committing anything."""
    rows = db.execute(text("""
        SELECT id, org_id, version_id, surfaces
        FROM ainxt.ecosystem_installs
    """)).fetchall()

    candidates: list[tuple[str, str, str, list[str], list[str]]] = []
    for install_id, org_id, version_id, surfaces in rows:
        old_surfaces = list(surfaces or [])
        new_surfaces = _target_surfaces_for(org_id, str(version_id))
        if sorted(old_surfaces) != sorted(new_surfaces):
            candidates.append((str(install_id), org_id, str(version_id), old_surfaces, new_surfaces))
    return candidates


def backfill_install_surfaces_to_all_allowed(db: Session) -> int:
    """Sets `surfaces` to the freshly-recomputed target for every install
    find_backfill_candidates() would return. Returns the number of rows
    updated. Does NOT commit -- the caller (main() below, or a test) owns
    the transaction boundary."""
    candidates = find_backfill_candidates(db)
    fixed = 0
    for install_id, _org_id, _version_id, _old_surfaces, new_surfaces in candidates:
        # No explicit ::JSONB cast on the bind param -- Postgres implicitly
        # casts a plain string into a jsonb column on assignment, and (real
        # gotcha found here) SQLAlchemy's text() bind-param parser doesn't
        # cleanly split ":name" from an immediately-following "::" cast
        # operator anyway. Same convention this round's own sibling script,
        # backfill_builtin_install_origin_and_surfaces.py, already uses for
        # exactly this column.
        db.execute(
            text("UPDATE ainxt.ecosystem_installs SET surfaces = :surfaces WHERE id = :id"),
            {"surfaces": json.dumps(new_surfaces), "id": install_id},
        )
        fixed += 1
    return fixed


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        if not candidates:
            print("nothing to backfill: every install's surfaces already match its own recomputed target")
            return

        for install_id, org_id, version_id, old_surfaces, new_surfaces in candidates:
            prefix = "[dry-run] would fix" if dry_run else "fixing"
            print(f"{prefix}: {install_id} (org={org_id}, version={version_id}) {old_surfaces!r} -> {new_surfaces!r}")

        if dry_run:
            print(f"[dry-run] {len(candidates)} row(s) would be updated -- no changes made")
            return

        fixed = backfill_install_surfaces_to_all_allowed(db)
        db.commit()
        print(f"install surfaces fixed: {fixed} row(s)")
    finally:
        db.close()

    # Audit writes (2026-09-29 convention, same as the trust-tier/display-
    # name backfills earlier this session): one row per install actually
    # changed, using item_id=None -- an EcosystemAudit row's `item_id` FK
    # points at ecosystem_items, and this backfill touches
    # ecosystem_installs rows, which don't share that id; the install_id/
    # org_id/before/after values all go in `details` instead, same
    # convention items_service.delete_draft() already uses for exactly
    # this "the natural id doesn't fit the audit row's own FK" situation.
    from services.ecosystem.audit_service import write_audit_event
    for install_id, org_id, version_id, old_surfaces, new_surfaces in candidates:
        try:
            write_audit_event(
                org_id=org_id, actor="system:backfill_install_surfaces_to_all_allowed", action="backfill",
                item_id=None,
                details={
                    "install_id": install_id, "version_id": version_id, "field": "surfaces",
                    "old_value": old_surfaces, "new_value": new_surfaces,
                },
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
