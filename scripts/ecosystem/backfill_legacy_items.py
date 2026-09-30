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
import re
import sys

_GATE_NAME_DISALLOWED = re.compile(r"[^A-Za-z0-9 _-]")


def _gate_safe_name(name: str) -> str:
    """The gate's manifest stage (services/ecosystem/gate/manifest_stage.py's
    _NAME_RE) only allows alnum/space/hyphen/underscore, 2-64 chars -- but a
    Cowork role's own `name` is free text a human typed (colons, parens,
    slashes, ampersands all legal there). Real gap found live (2026-09-30):
    a role name containing anything else fails gate stage 1 with
    INVALID_NAME, permanently blocking that role from ever appearing as a
    real (non-pending/non-failed) plugin -- discovered via this backfill's
    own first real end-to-end run against a real published role,  something
    nobody had exercised before (the source table was empty until now).
    Sanitize only this internal, gate-facing manifest field; display_name
    (what the UI actually shows) is never touched."""
    cleaned = _GATE_NAME_DISALLOWED.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"role {cleaned}".strip()
    return cleaned[:64] or "role"


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
    have no org_id column either).

    Real gap found live (2026-09-30): every role this function ever mirrors
    already passed legacy_bridge.list_published_cowork_roles()'s own
    status=="APPROVED" and visibility=="public" filter -- i.e. the Cowork
    author already published it to their org's own shared marketplace
    (services/cowork_roles.py's publish_role() docstring: "only published
    roles appear in the shared marketplace"). upsert_legacy_pointer_item()'s
    default scope, "org_private", means something different and narrower:
    "Yours-only, never browsable" (items_service.list_items()'s own 2026-
    09-28 fix deliberately excludes org_private from Discover for EVERY
    caller, including the item's own org). Left at that default, a
    published-to-marketplace role becomes invisible in Plugins Discover --
    confirmed live: zero results from a real, authenticated
    GET /ecosystem/items?item_type=plugin call for an org with a real
    APPROVED/public role already bridged. scope="optional" (defined in the
    schema, unused until now) is the correct fit: real org-owned content,
    not platform-shipped ("builtin") and not crawled ("central_index"),
    but deliberately catalog-browsable, matching what "published to the
    marketplace" already means for the source role."""
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
            scope="optional",
        )

        version_id, version_created = versions_service.create_or_refresh_legacy_version(
            item_id=item_id,
            content_text=role["description"],
            manifest={"name": _gate_safe_name(role["name"]), "description": role["description"], "legacy_source": "cowork_roles"},
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
            # Real gap found live (2026-09-30, via a real UI-reference-pack
            # screenshot capture pass): upsert_legacy_pointer_item()'s own
            # default scope ("org_private") is invisible to Discover/browse
            # for EVERY caller -- items_service.list_items()'s own filter
            # only shows scope IN ('builtin','optional','central_index').
            # All 13 real connectors had trust_tier="builtin" and a real
            # gate_verdict="pass" but were structurally unreachable in
            # Connectors Discover this whole time; a live
            # GET /ecosystem/items?item_type=connector call returned zero
            # items despite 13 real active rows in the DB. These are
            # platform-wide built-in integrations, not per-org content --
            # scope="builtin" (matching trust_tier) is the correct value,
            # not the org_private default every OTHER bridge source
            # (skills_pg/AgentStudio/Cowork roles) correctly keeps.
            scope="builtin" if conn["is_builtin"] else "org_private",
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
