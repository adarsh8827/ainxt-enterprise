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


def _set_item_icon_url(item_id: str, icon_url: str) -> None:
    """upsert_legacy_pointer_item() has no icon_url param -- a small,
    additive, idempotent direct write (safe: this is the new
    ecosystem_items row this backfill job itself just created/owns, not
    the legacy connector_definitions table)."""
    from db.database import SessionLocal
    from db.models import EcosystemItem

    db = SessionLocal()
    try:
        row = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if row is not None and row.icon_url != icon_url:
            row.icon_url = icon_url
            db.commit()
    finally:
        db.close()


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


def _backfill_cowork_roles() -> tuple[int, int]:
    """Mirrors every PUBLISHED Cowork role as a plugin-typed pointer item
    (Connectors+Plugins phase, PLUGINS_PHASE_PLAN.md §0/§1 item 3(a)) --
    read-through only, never writes to cowork_roles. org_id='default',
    same single-tenant sentinel as the AgentStudio backfill (Cowork roles
    have no org_id column either)."""
    from services.ecosystem import gate_service, items_service, legacy_bridge, publishers_service, versions_service

    mirrored, created = 0, 0
    for role in legacy_bridge.list_published_cowork_roles():
        org_id = "default"
        org_slug = legacy_bridge.slugify(org_id)
        name_slug = legacy_bridge.slugify(role["name"])
        namespace = f"{org_slug}/{name_slug}"

        publishers_service.resolve_publisher(namespace, owner_type="org", owner_ref=org_id)

        item_id, item_created = items_service.upsert_legacy_pointer_item(
            namespace=namespace,
            item_type="plugin",
            category=role["category"],
            display_name=role["name"],
            description=role["description"],
            org_id=org_id,
            legacy_source="cowork_roles",
            legacy_ref=role["legacy_ref"],
        )

        version_id, version_created = versions_service.create_or_refresh_legacy_version(
            item_id=item_id,
            content_text=role["description"],
            manifest={"name": role["name"], "description": role["description"], "legacy_source": "cowork_roles"},
        )
        if version_created:
            gate_service.enqueue_gate_run(version_id, trigger="admin_provision")

        mirrored += 1
        created += int(item_created)
    return mirrored, created


def _backfill_native_connectors() -> tuple[int, int]:
    """Mirrors every active row in connectors/registry.py's own
    connector_definitions table as a connector-typed pointer item, so
    Discover has real, browsable cards for GitHub/Slack/Jira/etc. even
    with no crawl ever run -- read-through only, never writes to
    connector_definitions. org_id='default', same single-tenant sentinel
    as the AgentStudio/Cowork backfills (connector_definitions has no
    org_id column either -- it's platform-wide, not per-org)."""
    from services.ecosystem import gate_service, items_service, legacy_bridge, publishers_service, versions_service

    mirrored, created = 0, 0
    for conn in legacy_bridge.list_native_connector_definitions():
        org_id = "default"
        org_slug = legacy_bridge.slugify(org_id)
        name_slug = legacy_bridge.slugify(conn["name"])
        namespace = f"{org_slug}/{name_slug}"

        publishers_service.resolve_publisher(namespace, owner_type="org", owner_ref=org_id)

        item_id, item_created = items_service.upsert_legacy_pointer_item(
            namespace=namespace,
            item_type="connector",
            category=conn["category"],
            display_name=conn["display_name"],
            description=conn["description"],
            org_id=org_id,
            legacy_source="connector_definitions",
            legacy_ref=conn["legacy_ref"],
            # Real gap fixed: connector_definitions' own is_active=TRUE
            # rows are all platform-shipped, built-in integrations
            # (confirmed live: every real row has is_builtin=True) --
            # upsert_legacy_pointer_item()'s own default ("org") would
            # have shown these with the wrong trust badge.
            trust_tier="builtin" if conn["is_builtin"] else "org",
        )
        if conn["icon_url"]:
            # upsert_legacy_pointer_item() has no icon_url param -- same-
            # origin path already served by this app (e.g. "/icons/slack.svg"),
            # never an external hotlink, matching the existing "publisher-
            # provided upload, else a monogram, no hotlinked logos" rule.
            _set_item_icon_url(item_id, conn["icon_url"])

        version_id, version_created = versions_service.create_or_refresh_legacy_version(
            item_id=item_id,
            content_text=conn["description"],
            manifest={"name": conn["display_name"], "description": conn["description"], "legacy_source": "connector_definitions"},
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
    parser.add_argument("--skip-cowork-roles", action="store_true")
    parser.add_argument("--skip-connectors", action="store_true")
    args = parser.parse_args()

    from core.config import (
        ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO,
        ECOSYSTEM_LEGACY_BRIDGE_CONNECTORS,
        ECOSYSTEM_LEGACY_BRIDGE_COWORK_ROLES,
        ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG,
    )

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

    if ECOSYSTEM_LEGACY_BRIDGE_COWORK_ROLES and not args.skip_cowork_roles:
        mirrored, created = _backfill_cowork_roles()
        total_mirrored += mirrored
        total_created += created
        print(f"cowork_roles: {mirrored} eligible item(s), {created} newly mirrored")
    else:
        print("cowork_roles: skipped (ECOSYSTEM_LEGACY_BRIDGE_COWORK_ROLES is off, or --skip-cowork-roles)")

    if ECOSYSTEM_LEGACY_BRIDGE_CONNECTORS and not args.skip_connectors:
        mirrored, created = _backfill_native_connectors()
        total_mirrored += mirrored
        total_created += created
        print(f"connector_definitions: {mirrored} eligible item(s), {created} newly mirrored")
    else:
        print("connector_definitions: skipped (ECOSYSTEM_LEGACY_BRIDGE_CONNECTORS is off, or --skip-connectors)")

    print(f"Total: {total_mirrored} eligible item(s) across all sources, {total_created} newly mirrored this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
