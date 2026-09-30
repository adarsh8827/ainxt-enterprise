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


def _insert_definition(name: str, display_name: str, category: str, *, active: bool = True) -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO ainxt.connector_definitions "
                "(name, display_name, category, auth_type, tools, is_active) "
                "VALUES (:name, :display_name, :category, 'oauth2', '[]'::jsonb, :active) "
                "ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, "
                "category = EXCLUDED.category, is_active = EXCLUDED.is_active"
            ),
            {"name": name, "display_name": display_name, "category": category, "active": active},
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
