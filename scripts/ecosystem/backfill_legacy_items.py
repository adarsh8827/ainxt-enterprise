#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ecosystem marketplace — legacy bridge backfill job (task B-4).

Explicit, idempotent, re-runnable: mirrors every eligible behavioral
skills_pg row and every AgentStudio skills_catalog row into a pointer-only
ecosystem_items row (+ a version row, + a report-mode gate run), matched by
(legacy_source, legacy_ref) so re-running is a no-op for already-mirrored
items. Never writes to skills_pg or skills_catalog.

Usage:
    python scripts/ecosystem/backfill_legacy_items.py
    python scripts/ecosystem/backfill_legacy_items.py --skip-agentstudio
    python scripts/ecosystem/backfill_legacy_items.py --skip-skills-pg
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _backfill_skills_pg() -> tuple[int, int]:
    """Returns (mirrored_count, newly_created_count)."""
    from services.ecosystem import gate_service, items_service, legacy_bridge, publishers_service, versions_service

    mirrored, created = 0, 0
    for skill in legacy_bridge.list_behavioral_skills_pg_items():
        org_slug = legacy_bridge.slugify(skill["org_id"])
        name_slug = legacy_bridge.slugify(skill["name"])
        namespace = f"{org_slug}/{name_slug}"

        publishers_service.resolve_publisher(namespace, owner_type="org", owner_ref=skill["org_id"])

        item_id, item_created = items_service.upsert_legacy_pointer_item(
            namespace=namespace,
            item_type="skill",
            category="general",
            display_name=skill["name"],
            description=skill["description"],
            org_id=skill["org_id"],
            legacy_source="skills_pg",
            legacy_ref=skill["legacy_ref"],
        )

        version_id, version_created = versions_service.create_or_refresh_legacy_version(
            item_id=item_id,
            content_text=skill["description"],
            manifest={"name": skill["name"], "description": skill["description"], "legacy_source": "skills_pg"},
        )
        if version_created:
            gate_service.enqueue_gate_run(version_id, trigger="admin_provision")

        mirrored += 1
        created += int(item_created)
    return mirrored, created


def _backfill_agentstudio() -> tuple[int, int]:
    from services.ecosystem import gate_service, items_service, legacy_bridge, publishers_service, versions_service

    async def _run():
        return await legacy_bridge.list_agentstudio_skills()

    skills = asyncio.run(_run())

    mirrored, created = 0, 0
    for skill in skills:
        org_id = "default"
        org_slug = legacy_bridge.slugify(org_id)
        name_slug = legacy_bridge.slugify(skill["name"])
        namespace = f"{org_slug}/{name_slug}"

        publishers_service.resolve_publisher(namespace, owner_type="org", owner_ref=org_id)

        item_id, item_created = items_service.upsert_legacy_pointer_item(
            namespace=namespace,
            item_type="skill",
            category=skill.get("category") or "general",
            display_name=skill["name"],
            description=skill["description"],
            org_id=org_id,
            legacy_source="skills_catalog",
            legacy_ref=skill["legacy_ref"],
        )

        version_id, version_created = versions_service.create_or_refresh_legacy_version(
            item_id=item_id,
            content_text=skill["content"],
            manifest={"name": skill["name"], "description": skill["description"], "legacy_source": "skills_catalog"},
        )
        if version_created:
            gate_service.enqueue_gate_run(version_id, trigger="admin_provision")

        mirrored += 1
        created += int(item_created)
    return mirrored, created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-skills-pg", action="store_true")
    parser.add_argument("--skip-agentstudio", action="store_true")
    args = parser.parse_args()

    from core.config import ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO, ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG

    total_mirrored, total_created = 0, 0

    if ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG and not args.skip_skills_pg:
        mirrored, created = _backfill_skills_pg()
        total_mirrored += mirrored
        total_created += created
        print(f"skills_pg: {mirrored} eligible item(s), {created} newly mirrored")
    else:
        print("skills_pg: skipped (ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG is off, or --skip-skills-pg)")

    if ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO and not args.skip_agentstudio:
        mirrored, created = _backfill_agentstudio()
        total_mirrored += mirrored
        total_created += created
        print(f"skills_catalog (AgentStudio): {mirrored} eligible item(s), {created} newly mirrored")
    else:
        print("skills_catalog (AgentStudio): skipped (ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO is off, or --skip-agentstudio)")

    print(f"Total: {total_mirrored} eligible item(s) across both sources, {total_created} newly mirrored this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
