# SPDX-License-Identifier: MIT
# ============================================================
# Native-connectors-as-catalog-items read-through bridge (Connectors+
# Plugins phase). Same real-Postgres-tier convention as
# test_legacy_bridge_cowork_roles.py's coverage for that sibling bridge.
# ============================================================

from __future__ import annotations

import uuid

from sqlalchemy import text

from db.database import SessionLocal
from services.ecosystem.legacy_bridge import list_native_connector_definitions


def _insert_definition(
    name: str, display_name: str, category: str, *,
    active: bool = True, description: str = "", icon_url: str | None = None,
    is_builtin: bool = True, tool_count: int = 0,
) -> None:
    tools = [{"name": f"t{i}"} for i in range(tool_count)]
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO ainxt.connector_definitions "
                "(name, display_name, category, description, icon_url, is_builtin, auth_type, tools, is_active) "
                "VALUES (:name, :display_name, :category, :description, :icon_url, :is_builtin, 'oauth2', :tools, :active) "
                "ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, "
                "category = EXCLUDED.category, description = EXCLUDED.description, "
                "icon_url = EXCLUDED.icon_url, is_builtin = EXCLUDED.is_builtin, "
                "tools = EXCLUDED.tools, is_active = EXCLUDED.is_active"
            ),
            {
                "name": name, "display_name": display_name, "category": category,
                "description": description, "icon_url": icon_url, "is_builtin": is_builtin,
                "tools": __import__("json").dumps(tools), "active": active,
            },
        )
        db.commit()
    finally:
        db.close()


def _delete_definition(name: str) -> None:
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM ainxt.connector_definitions WHERE name = :name"), {"name": name})
        db.commit()
    finally:
        db.close()


def test_active_connector_definition_is_included_with_a_mapped_category():
    name = f"test-bridge-conn-{uuid.uuid4().hex[:8]}"
    _insert_definition(name, "Test Connector", "devtools")
    try:
        items = list_native_connector_definitions()
        match = next((i for i in items if i["legacy_ref"] == name), None)
        assert match is not None
        assert match["display_name"] == "Test Connector"
        # "devtools" (real connector_definitions category) is NOT a valid
        # taxonomy category -- must map to "dev-tools", never pass through
        # unmapped (the exact "operations" bug class this session already
        # fixed once for the crawler).
        assert match["category"] == "dev-tools"
    finally:
        _delete_definition(name)


def test_real_description_icon_url_and_builtin_flag_are_used_not_a_generic_template():
    # Real gap found and fixed: this bridge originally threw away
    # connector_definitions' own real description/icon_url/is_builtin
    # columns in favor of a generic "Native <name> connector." template.
    name = f"test-bridge-conn-{uuid.uuid4().hex[:8]}"
    _insert_definition(
        name, "Test Connector", "productivity",
        description="Search and read your Test Connector data.",
        icon_url="/icons/test-connector.svg", is_builtin=True,
    )
    try:
        items = list_native_connector_definitions()
        match = next((i for i in items if i["legacy_ref"] == name), None)
        assert match is not None
        assert match["description"] == "Search and read your Test Connector data."
        assert match["icon_url"] == "/icons/test-connector.svg"
        assert match["is_builtin"] is True
    finally:
        _delete_definition(name)


def test_unmapped_category_falls_back_to_general_not_passed_through_raw():
    name = f"test-bridge-conn-{uuid.uuid4().hex[:8]}"
    _insert_definition(name, "DPI Test Connector", "dpi")
    try:
        items = list_native_connector_definitions()
        match = next((i for i in items if i["legacy_ref"] == name), None)
        assert match is not None
        assert match["category"] == "general"
    finally:
        _delete_definition(name)


def test_inactive_connector_definition_is_excluded():
    name = f"test-bridge-conn-{uuid.uuid4().hex[:8]}"
    _insert_definition(name, "Inactive Connector", "productivity", active=False)
    try:
        items = list_native_connector_definitions()
        assert all(i["legacy_ref"] != name for i in items)
    finally:
        _delete_definition(name)


def test_two_rows_with_the_same_display_name_are_deduped_keeping_more_tools():
    # Real duplicate found live: "jira"/"jira_connector" are two separate
    # native rows for the same real app -- must show as ONE entry, not two.
    suffix = uuid.uuid4().hex[:8]
    name_a = f"test-dup-a-{suffix}"
    name_b = f"test-dup-b-{suffix}"
    _insert_definition(name_a, "Test Duplicate App", "productivity", tool_count=3)
    _insert_definition(name_b, "Test Duplicate App", "productivity", tool_count=9)
    try:
        items = [i for i in list_native_connector_definitions() if i["display_name"] == "Test Duplicate App"]
        assert len(items) == 1
        assert items[0]["legacy_ref"] == name_b  # the one with more tools (9) wins
    finally:
        _delete_definition(name_a)
        _delete_definition(name_b)


def test_never_writes_to_connector_definitions():
    db = SessionLocal()
    try:
        before = db.execute(text("SELECT count(*) FROM ainxt.connector_definitions")).scalar()
    finally:
        db.close()

    list_native_connector_definitions()

    db = SessionLocal()
    try:
        after = db.execute(text("SELECT count(*) FROM ainxt.connector_definitions")).scalar()
    finally:
        db.close()
    assert before == after
