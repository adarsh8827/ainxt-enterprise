# SPDX-License-Identifier: MIT
# ============================================================
# Shared fixtures for ecosystem service Tier-2 tests — these need a real
# Postgres with the ecosystem_* tables already migrated (db/migrate.py's
# _part_ad1_ecosystem_marketplace_tables_2026_09_25). Skipped automatically
# if that database isn't reachable, matching tests/conftest.py's existing
# skip-if-unreachable convention for Redis.
# ============================================================

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_ecosystem_tables():
    """Truncate the mutable ecosystem_* tables before each test, so tests
    don't see each other's rows. Leaves the seed tables (ecosystem_surfaces,
    ecosystem_product_profiles, ecosystem_org_products) untouched — nothing
    in this milestone's tests writes to those.

    Skips the whole test if Postgres isn't reachable or the ecosystem
    tables don't exist yet (this milestone's migration hasn't been applied
    in this environment).
    """
    try:
        from sqlalchemy import text as _text

        from db.database import engine
    except Exception as exc:
        pytest.skip(f"db module unavailable: {exc}")

    try:
        with engine.connect() as conn:
            conn.execute(_text(
                "TRUNCATE ainxt.ecosystem_gate_findings, ainxt.ecosystem_gate_runs, "
                "ainxt.ecosystem_item_versions, ainxt.ecosystem_installs, "
                "ainxt.ecosystem_items, ainxt.ecosystem_sources, ainxt.ecosystem_publishers, "
                "ainxt.ecosystem_audit CASCADE"
            ))
            conn.commit()
    except Exception as exc:
        pytest.skip(f"ecosystem tables not reachable/migrated: {exc}")

    yield
