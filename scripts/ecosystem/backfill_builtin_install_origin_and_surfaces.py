#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-off backfill for two real bugs found live (2026-09-27):

1. A handful of builtin-skill installs were created (by early manual
   testing, before ensure_provisioned() was wired up correctly) with
   origin='added' instead of 'provisioned' -- Yours.tsx's own grouping
   is keyed on Install.origin, so these showed up under "Added from
   Discover" instead of "Org provisioned". ensure_provisioned() itself
   is correct and has been setting new rows to 'provisioned' all along;
   this fixes only the stale rows it never got a chance to correct
   (its own ConflictError-on-existing-row path silently skips a row that
   already exists, by design -- it's an idempotent *installer*, not a
   repair tool).
2. The one-click Add / Create-with-AI fast path defaulted surfaces to
   ["chat"] regardless of what other surfaces the caller's product
   profile actually allows -- fixed at the source in
   packages/ecosystem-ui (Card.tsx/Detail.tsx/CreateForm.tsx) separately;
   this backfills installs that were already created under the old,
   narrower default.

Scoped deliberately narrow: only touches installs whose ITEM is
scope='builtin', and only when the current value is still the old
default (origin='added', or surfaces exactly ['chat']) -- never a normal
user's own deliberate scope/surface choice on a non-builtin item.
Idempotent: re-running finds nothing left to fix the second time.

Usage:
    python -m scripts.ecosystem.backfill_builtin_install_origin_and_surfaces
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

from db.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        origin_fixed = db.execute(text("""
            UPDATE ainxt.ecosystem_installs i
            SET origin = 'provisioned'
            FROM ainxt.ecosystem_items e
            WHERE e.id = i.item_id AND e.scope = 'builtin' AND i.origin = 'added'
        """)).rowcount

        # Per-org: expand ['chat']-only builtin installs to every surface
        # that install's own org's product profile allows -- not a
        # blanket surfaces value, since enterprise/workspace profiles
        # allow different surface sets.
        rows = db.execute(text("""
            SELECT i.id, i.org_id
            FROM ainxt.ecosystem_installs i
            JOIN ainxt.ecosystem_items e ON e.id = i.item_id
            WHERE e.scope = 'builtin' AND i.surfaces = '["chat"]'::jsonb
        """)).fetchall()

        surfaces_fixed = 0
        for install_id, org_id in rows:
            from services.ecosystem.config_service import _resolve_product

            product_key = _resolve_product(org_id, None)
            profile_surfaces = db.execute(text("""
                SELECT enabled_surfaces FROM ainxt.ecosystem_product_profiles WHERE product_key = :pk
            """), {"pk": product_key}).scalar()
            if not profile_surfaces:
                continue
            db.execute(text("UPDATE ainxt.ecosystem_installs SET surfaces = :s WHERE id = :iid"), {
                "s": __import__("json").dumps(list(profile_surfaces)), "iid": install_id,
            })
            surfaces_fixed += 1

        db.commit()
        print(f"origin fixed: {origin_fixed} row(s); surfaces fixed: {surfaces_fixed} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
