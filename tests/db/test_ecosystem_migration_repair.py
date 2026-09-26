# SPDX-License-Identifier: MIT
# ============================================================
# Tests for db/migrate.py's _part_ad2_repair_ecosystem_constraints_2026_09_27.
#
# Real-world scenario: a database that ran db/migrate.py before the
# create_all() exclusion fix has ecosystem_* tables with no CHECK/UNIQUE
# constraints, even though _part_ad1_...'s own DDL text has always
# described them correctly (create_all() won the race and pre-created a
# bare table first, so _part_ad1's "CREATE TABLE IF NOT EXISTS" became a
# no-op that never added the constraints). This suite simulates that state
# directly (drop the constraint, then invoke the repair function) rather
# than standing up a second, separately-versioned migrate.py -- the repair
# function's own idempotent "does this exact constraint exist" check makes
# that equivalent to what a genuinely pre-fix database would trigger.
# ============================================================

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from db.database import DB_SCHEMA, engine
from db.migrate import (
    _part_ad2_repair_ecosystem_constraints_2026_09_27,
    _repair_constraint_exists,
)


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


def _require_ecosystem_tables(conn):
    if not _table_exists(conn, "ecosystem_item_versions") or not _table_exists(conn, "ecosystem_installs"):
        pytest.skip("ecosystem tables not present -- has db/migrate.py been run against this database?")


def test_repair_adds_check_constraint_dropped_to_simulate_a_pre_fix_database(_db_conn):
    """Drop a CHECK constraint the migration is supposed to have, confirm
    the repair notices it's missing and adds it back -- proving the repair
    actually detects and fixes the create_all() race, not just "runs"."""
    conn = _db_conn
    _require_ecosystem_tables(conn)

    name = "ecosystem_publishers_owner_type_check"
    conn.execute(text(f"ALTER TABLE {DB_SCHEMA}.ecosystem_publishers DROP CONSTRAINT IF EXISTS {name}"))
    conn.commit()
    assert not _repair_constraint_exists(conn, "ecosystem_publishers", name)

    _part_ad2_repair_ecosystem_constraints_2026_09_27()

    assert _repair_constraint_exists(conn, "ecosystem_publishers", name)


def test_repair_is_idempotent_when_constraint_already_present(_db_conn):
    """Running the repair twice must not error or duplicate the constraint --
    real deployments call db/migrate.py on every redeploy."""
    conn = _db_conn
    _require_ecosystem_tables(conn)

    _part_ad2_repair_ecosystem_constraints_2026_09_27()
    _part_ad2_repair_ecosystem_constraints_2026_09_27()

    assert _repair_constraint_exists(conn, "ecosystem_publishers", "ecosystem_publishers_owner_type_check")


def test_repair_skips_unique_constraint_and_reports_real_duplicates(_db_conn, capsys):
    """If the constraint was inert long enough for real duplicate rows to
    accumulate, adding it outright would either fail loudly or (worse)
    require deleting someone's data. The repair must instead report the
    duplicate and leave both the data and the missing constraint alone."""
    conn = _db_conn
    _require_ecosystem_tables(conn)

    name = "ecosystem_item_versions_item_id_version_key"
    conn.execute(text(f"ALTER TABLE {DB_SCHEMA}.ecosystem_item_versions DROP CONSTRAINT IF EXISTS {name}"))
    conn.commit()

    pub_slug = f"repair-test-{uuid.uuid4().hex[:8]}"
    source_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    try:
        conn.execute(text(
            f"INSERT INTO {DB_SCHEMA}.ecosystem_publishers (slug, owner_type, owner_ref) "
            "VALUES (:slug, 'org', 'test')"
        ), {"slug": pub_slug})
        conn.execute(text(
            f"INSERT INTO {DB_SCHEMA}.ecosystem_sources (id, kind, org_id, created_by) "
            "VALUES (:id, 'local', :org_id, 'test')"
        ), {"id": source_id, "org_id": pub_slug})
        conn.execute(text(
            f"INSERT INTO {DB_SCHEMA}.ecosystem_items "
            "(id, namespace, item_type, category, display_name, description, source_id, license) "
            "VALUES (:id, :ns, 'skill', 'general', 'Repair Test', 'repair test item', :source_id, 'MIT')"
        ), {"id": item_id, "ns": f"{pub_slug}/dup-item", "source_id": source_id})
        for content_hash in ("hash1", "hash2"):
            conn.execute(text(
                f"INSERT INTO {DB_SCHEMA}.ecosystem_item_versions "
                "(item_id, version, content_hash, object_key, license, attribution, manifest) "
                "VALUES (:item_id, '1.0.0', :hash, :hash, 'MIT', 'test', '{}')"
            ), {"item_id": item_id, "hash": content_hash})
        conn.commit()

        capsys.readouterr()
        _part_ad2_repair_ecosystem_constraints_2026_09_27()
        captured = capsys.readouterr()

        assert not _repair_constraint_exists(conn, "ecosystem_item_versions", name)
        assert "duplicate group" in captured.out
        assert item_id in captured.out or "ecosystem_item_versions" in captured.out
    finally:
        conn.execute(text(f"DELETE FROM {DB_SCHEMA}.ecosystem_item_versions WHERE item_id = :id"), {"id": item_id})
        conn.execute(text(f"DELETE FROM {DB_SCHEMA}.ecosystem_items WHERE id = :id"), {"id": item_id})
        conn.execute(text(f"DELETE FROM {DB_SCHEMA}.ecosystem_sources WHERE id = :id"), {"id": source_id})
        conn.execute(text(f"DELETE FROM {DB_SCHEMA}.ecosystem_publishers WHERE slug = :slug"), {"slug": pub_slug})
        conn.commit()

    # Now that the duplicate is gone, the repair must succeed on a later run --
    # confirms the earlier skip really was about the data, not the code path.
    _part_ad2_repair_ecosystem_constraints_2026_09_27()
    assert _repair_constraint_exists(conn, "ecosystem_item_versions", name)


def test_repair_leaves_non_ecosystem_tables_untouched(_db_conn):
    """The create_all() exclusion fix this repair complements only ever
    excludes ecosystem_*/oauth_*/credential_audit/desktop_devices tables --
    confirm a long-lived, unrelated table's constraint set is unaffected by
    running the repair (it has no entry in _REPAIR_CHECK_CONSTRAINTS /
    _REPAIR_UNIQUE_CONSTRAINTS, so this is really just a no-op sanity check)."""
    conn = _db_conn
    if not _table_exists(conn, "users"):
        pytest.skip("users table not present in this database")

    before = conn.execute(text(
        "SELECT conname FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid "
        "JOIN pg_namespace n ON t.relnamespace = n.oid "
        "WHERE n.nspname = :schema AND t.relname = 'users' ORDER BY conname"
    ), {"schema": DB_SCHEMA}).fetchall()

    _part_ad2_repair_ecosystem_constraints_2026_09_27()

    after = conn.execute(text(
        "SELECT conname FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid "
        "JOIN pg_namespace n ON t.relnamespace = n.oid "
        "WHERE n.nspname = :schema AND t.relname = 'users' ORDER BY conname"
    ), {"schema": DB_SCHEMA}).fetchall()

    assert before == after
