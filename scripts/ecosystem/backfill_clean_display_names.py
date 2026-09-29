#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-off backfill for a real bug found live (2026-09-29): a catalog item's
display_name showed the source repo's own internal namespacing convention
verbatim (e.g. "stitch::react-native" for google-labs-code/stitch-skills'
react-native skill, whose own SKILL.md frontmatter declares
`name: stitch::react-native`) instead of a clean, readable title. Fixed at
the source going forward in
services/ecosystem/import_adapters/{github_repo,well_known}.py's
`_clean_display_name()` -- this backfill only fixes rows already sitting in
the DB from before that fix, which a future crawl/re-import will otherwise
never touch again on its own (nothing re-derives an existing item's
display_name once it exists).

Reliable signal: a display_name containing "::" is unambiguous -- no
legitimate human-facing title uses that as a separator (ordinary titles are
things like "Meeting Notes Summarizer" or "Hello Skill": title case, spaces,
maybe a single colon for a subtitle, never a double colon). Re-derives a
clean name from the item's own `namespace` (always "publisher/name"-shaped,
built from the owner/repo-folder segments, never from frontmatter -- see
crawl.py's own namespace construction on feature/ecosystem-external-sources
-- so it's clean by construction regardless of what the source repo's own
frontmatter says).

Idempotent: re-running finds nothing left to fix the second time (the
"display_name LIKE '%::%'" guard is gone once a row is fixed).

Usage:
    python -m scripts.ecosystem.backfill_clean_display_names [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocal


def find_backfill_candidates(db: Session) -> list[tuple[str, str, str]]:
    """Returns [(item_id, namespace, display_name), ...] for every item
    whose display_name still carries a "::" namespace separator. Exposed
    separately from backfill_clean_display_names() so a caller (this
    module's own `main()`, or a test) can inspect exactly what would be
    touched without committing anything."""
    rows = db.execute(text("""
        SELECT id, namespace, display_name
        FROM ainxt.ecosystem_items
        WHERE display_name LIKE '%::%'
    """)).fetchall()
    return [(str(item_id), namespace, display_name) for item_id, namespace, display_name in rows]


def _clean_name_from_namespace(namespace: str) -> str:
    """Same fallback shape as the import adapters' own _clean_display_name()
    -- the namespace's own last path segment (already clean; namespace is
    built from owner/repo-folder segments, never from frontmatter)."""
    return namespace.rsplit("/", 1)[-1]


def backfill_clean_display_names(db: Session) -> int:
    """Sets display_name to a namespace-derived clean name for every row
    find_backfill_candidates() would return. Returns the number of rows
    updated. Does NOT commit -- the caller (main() below, or a test) owns
    the transaction boundary."""
    candidates = find_backfill_candidates(db)
    fixed = 0
    for item_id, namespace, _old_name in candidates:
        db.execute(
            text("UPDATE ainxt.ecosystem_items SET display_name = :name WHERE id = :id"),
            {"name": _clean_name_from_namespace(namespace), "id": item_id},
        )
        fixed += 1
    return fixed


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        if not candidates:
            print("nothing to backfill: no item's display_name contains '::'")
            return

        for item_id, namespace, old_name in candidates:
            new_name = _clean_name_from_namespace(namespace)
            print(f"{'[dry-run] would fix' if dry_run else 'fixing'}: {old_name!r} -> {new_name!r} ({namespace}, {item_id})")

        if dry_run:
            print(f"[dry-run] {len(candidates)} row(s) would be updated -- no changes made")
            return

        fixed = backfill_clean_display_names(db)
        db.commit()
        print(f"display_name fixed: {fixed} row(s)")
    finally:
        db.close()

    # Audit writes (2026-09-29): same rationale as
    # backfill_agent_created_trust_tier.py's own audit wiring -- a
    # backfill is a real mutating action, one durable row per item changed.
    from services.ecosystem.audit_service import write_audit_event
    for item_id, namespace, old_name in candidates:
        try:
            write_audit_event(
                org_id="default", actor="system:backfill_clean_display_names", action="backfill",
                item_id=item_id, details={"namespace": namespace, "field": "display_name",
                                           "old_value": old_name, "new_value": _clean_name_from_namespace(namespace)},
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
