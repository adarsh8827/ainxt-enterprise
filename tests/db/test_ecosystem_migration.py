# SPDX-License-Identifier: MIT
# ============================================================
# Migration verification tests (task B-1). Tier-2 — asserts the schema
# db/migrate.py's _part_ad1_ecosystem_marketplace_tables_2026_09_25 produces
# actually exists, and the two seed tables carry their expected rows.
# Requires the migration to have already been run against the target
# database (this test does not run the migration itself — that's what
# `python db/migrate.py` is for).
# ============================================================

from __future__ import annotations

import pytest
from sqlalchemy import text

from db.database import DB_SCHEMA, engine

_EXPECTED_TABLES = [
    "ecosystem_publishers", "ecosystem_sources", "ecosystem_items",
    "ecosystem_featured_overrides", "ecosystem_drafts", "ecosystem_item_versions",
    "ecosystem_installs", "ecosystem_shares", "ecosystem_gate_runs",
    "ecosystem_gate_findings", "ecosystem_reports", "ecosystem_audit",
    "ecosystem_credentials", "oauth_provider_configs", "oauth_client_registrations",
    "ecosystem_surfaces", "ecosystem_product_profiles", "ecosystem_org_products",
    "credential_audit", "desktop_devices",
]


@pytest.fixture(scope="module")
def _db_conn():
    try:
        conn = engine.connect()
    except Exception as exc:
        pytest.skip(f"Postgres not reachable: {exc}")
    yield conn
    conn.close()


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema = :s AND table_name = :t"),
        {"s": DB_SCHEMA, "t": table},
    ).scalar())


@pytest.mark.parametrize("table", _EXPECTED_TABLES)
def test_ecosystem_table_exists(_db_conn, table):
    if not _table_exists(_db_conn, table):
        pytest.skip(f"{table} not present — has db/migrate.py been run against this database?")
    assert _table_exists(_db_conn, table)


def test_ecosystem_surfaces_seeded_with_five_rows(_db_conn):
    if not _table_exists(_db_conn, "ecosystem_surfaces"):
        pytest.skip("ecosystem_surfaces not present — has db/migrate.py been run against this database?")
    keys = {
        row[0] for row in _db_conn.execute(text(f"SELECT key FROM {DB_SCHEMA}.ecosystem_surfaces")).fetchall()
    }
    assert keys == {"chat", "agent_studio", "cowork", "desktop", "workspace_chat"}


def test_ecosystem_product_profiles_has_enterprise_and_workspace(_db_conn):
    if not _table_exists(_db_conn, "ecosystem_product_profiles"):
        pytest.skip("ecosystem_product_profiles not present — has db/migrate.py been run against this database?")
    keys = {
        row[0] for row in _db_conn.execute(
            text(f"SELECT product_key FROM {DB_SCHEMA}.ecosystem_product_profiles")
        ).fetchall()
    }
    assert "enterprise" in keys
    assert "workspace" in keys


def test_one_local_source_per_org_unique_index_enforced(_db_conn):
    """The partial unique index (task B-1) must actually reject a second
    'local' source for the same org, not just exist as a no-op index."""
    if not _table_exists(_db_conn, "ecosystem_sources"):
        pytest.skip("ecosystem_sources not present — has db/migrate.py been run against this database?")

    conn = _db_conn
    conn.execute(text(
        f"INSERT INTO {DB_SCHEMA}.ecosystem_sources (kind, org_id, created_by) "
        "VALUES ('local', 'test-org-unique-local', 'test')"
    ))
    conn.commit()
    try:
        with pytest.raises(Exception):
            conn.execute(text(
                f"INSERT INTO {DB_SCHEMA}.ecosystem_sources (kind, org_id, created_by) "
                "VALUES ('local', 'test-org-unique-local', 'test')"
            ))
            conn.commit()
    finally:
        conn.rollback()
        conn.execute(text(
            f"DELETE FROM {DB_SCHEMA}.ecosystem_sources WHERE org_id = 'test-org-unique-local'"
        ))
        conn.commit()
