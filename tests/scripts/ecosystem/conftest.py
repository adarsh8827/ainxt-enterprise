# SPDX-License-Identifier: MIT
# ============================================================
# Same fixture as tests/services/ecosystem/conftest.py — duplicated rather
# than shared, since tests/scripts/ecosystem/ is a sibling directory, not a
# subdirectory, so pytest's autouse-fixture directory scoping doesn't reach
# across from one to the other. (Discovered the hard way: without this
# file, tests/scripts/ecosystem/test_seed_builtin_skills.py's tests shared
# un-truncated state across test functions, since the sibling conftest's
# autouse fixture silently never applied to this directory at all.)
# ============================================================

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_ecosystem_tables():
    # See tests/services/ecosystem/conftest.py's own comment on the real
    # 2026-09-27 incident this guard exists to prevent a repeat of.
    try:
        from sqlalchemy import text as _text

        from db.database import engine
        from tests._db_test_guard import assert_safe_to_truncate
    except Exception as exc:
        pytest.skip(f"db module unavailable: {exc}")

    assert_safe_to_truncate(engine)

    try:
        with engine.connect() as conn:
            conn.execute(_text(
                "TRUNCATE ainxt.ecosystem_gate_findings, ainxt.ecosystem_gate_runs, "
                "ainxt.ecosystem_item_versions, ainxt.ecosystem_shares, ainxt.ecosystem_installs, "
                "ainxt.ecosystem_reports, ainxt.ecosystem_featured_overrides, "
                "ainxt.ecosystem_items, ainxt.ecosystem_sources, ainxt.ecosystem_publishers, "
                "ainxt.ecosystem_audit CASCADE"
            ))
            conn.commit()
    except Exception as exc:
        pytest.skip(f"ecosystem tables not reachable/migrated: {exc}")

    yield
