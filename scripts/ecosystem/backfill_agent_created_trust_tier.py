#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-off backfill for a real bug found live (2026-09-28): a Create-with-AI
skill's trust badge showed "Community" (now relabeled "Created with AI" for
the `agent_created` tier -- packages/ecosystem-ui/src/components/Badges.tsx)
instead of the correct tier, for any item CREATED BEFORE the earlier same-day
fix (`created_via_ai` -> `trust_tier='agent_created'`, create_service.py's
`_create_item_and_version()`). That fix only changes what happens for a NEW
submission going forward; it does nothing for a row already sitting in the
DB with `trust_tier='community'` that was, historically, actually created
via the AI drafting flow.

Reliable signal, found by tracing the actual code (not guessed): there is no
persisted "created_via_ai" column on ecosystem_items itself (it was always
just an in-memory bool at creation time) -- but `ecosystem_drafts.
submitted_item_id` (schema present since M1, task B-14's own docstring) is
stamped by `drafts_service.submit_draft()` at the exact moment a draft's
content becomes a real item (`row.submitted_item_id = result["item_id"]`),
predating today's trust_tier fix by weeks. submit_draft() is the ONLY
consumer of that column and the ONLY code path that ever sets it -- a plain
Write/Upload/Import never touches `ecosystem_drafts` at all. So: any
ecosystem_items row whose id appears as some ecosystem_drafts row's
submitted_item_id was, unambiguously, created via Create-with-AI, regardless
of what its trust_tier says today. This backfill sets trust_tier='agent_created'
for exactly those rows, and ONLY where trust_tier is still 'community' (never
touches a row some other process already changed to org/verified/builtin,
which would be a deliberate admin/verification action this script has no
business overriding).

Idempotent: re-running finds nothing left to fix the second time (the WHERE
trust_tier='community' guard is gone once a row is fixed).

Usage:
    python -m scripts.ecosystem.backfill_agent_created_trust_tier [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocal


def find_backfill_candidates(db: Session) -> list[tuple[str, str]]:
    """Returns [(item_id, namespace), ...] for every community-tier item
    that has at least one ecosystem_drafts row naming it as
    submitted_item_id -- the reliable, persisted signal this backfill
    relies on (see module docstring). Exposed separately from
    backfill_agent_created_trust_tier() so a caller (this module's own
    `main()`, or a test) can inspect exactly what would be touched
    without committing anything."""
    rows = db.execute(text("""
        SELECT DISTINCT e.id, e.namespace
        FROM ainxt.ecosystem_items e
        JOIN ainxt.ecosystem_drafts d ON d.submitted_item_id = e.id
        WHERE e.trust_tier = 'community'
    """)).fetchall()
    return [(str(item_id), namespace) for item_id, namespace in rows]


def backfill_agent_created_trust_tier(db: Session) -> int:
    """Sets trust_tier='agent_created' on every item find_backfill_candidates()
    would return, in one statement (re-checks the same condition rather than
    trusting a possibly-stale candidate list). Returns the number of rows
    updated. Does NOT commit -- the caller (main() below, or a test) owns
    the transaction boundary."""
    return db.execute(text("""
        UPDATE ainxt.ecosystem_items e
        SET trust_tier = 'agent_created'
        WHERE e.trust_tier = 'community'
          AND EXISTS (
            SELECT 1 FROM ainxt.ecosystem_drafts d WHERE d.submitted_item_id = e.id
          )
    """)).rowcount


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        if not candidates:
            print("nothing to backfill: no community-tier item has a matching ecosystem_drafts.submitted_item_id row")
            return

        for item_id, namespace in candidates:
            print(f"{'[dry-run] would fix' if dry_run else 'fixing'}: {namespace} ({item_id})")

        if dry_run:
            print(f"[dry-run] {len(candidates)} row(s) would be updated to trust_tier='agent_created' -- no changes made")
            return

        fixed = backfill_agent_created_trust_tier(db)
        db.commit()
        print(f"trust_tier fixed: {fixed} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
