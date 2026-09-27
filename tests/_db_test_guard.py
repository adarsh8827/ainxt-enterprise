# SPDX-License-Identifier: MIT
# ============================================================
# Real incident (2026-09-27): tests/services/ecosystem/conftest.py's
# _clean_ecosystem_tables() autouse fixture TRUNCATEs the mutable
# ecosystem_* tables before every test in that package. Every pytest
# invocation this session set POSTGRES_HOST=localhost to reach the
# locally-exposed Postgres port, but never overrode POSTGRES_DB -- so it
# fell through to whatever db/database.py resolves that to (this
# deployment's own configured app database, ainxt_memory), the SAME
# database the developer's own running gateway/ai-ui dev servers were
# writing to. Every targeted pytest run this session truncated the
# developer's live Marketplace/chat data, repeatedly, all day.
#
# This module is the fix: a hard, loud guard that any destructive fixture
# must call BEFORE running a TRUNCATE/DELETE against `db.database.engine`.
# It queries the actual live connection (not just an env var, which could
# be stale or wrong) for current_database() and refuses to proceed unless
# that name is unambiguously a disposable test database.
# ============================================================

from __future__ import annotations

import pytest
from sqlalchemy import text as _text
from sqlalchemy.engine import Engine

# A test database name must end with this suffix -- e.g. "ainxt_test".
# Deliberately conservative: no allowlist of "known-safe" app DB names,
# since that list would just be one typo away from repeating this exact
# incident. Set up via: `CREATE DATABASE ainxt_test` on the same Postgres
# server, then `POSTGRES_DB=ainxt_test PGVECTOR_DB=ainxt_test` when
# running pytest -- see docs/ecosystem/TESTING_GUIDE.md's "Running tests
# without touching your dev data" section.
_REQUIRED_TEST_DB_SUFFIX = "_test"


def assert_safe_to_truncate(engine: Engine) -> None:
    """Raises (via pytest.fail — a hard failure, never a silent skip,
    since a skip here would hide exactly the danger this exists to
    surface) unless the engine's live connection is to a database whose
    real name (queried fresh, not read from an env var that could be
    stale) ends in `_test`.
    """
    with engine.connect() as conn:
        db_name = conn.execute(_text("SELECT current_database()")).scalar()

    if not db_name or not db_name.endswith(_REQUIRED_TEST_DB_SUFFIX):
        pytest.fail(
            f"REFUSING to run a destructive fixture against database {db_name!r} — "
            f"it does not end in {_REQUIRED_TEST_DB_SUFFIX!r}, so it is not "
            "confirmed to be a disposable test database. This almost certainly "
            "means POSTGRES_DB/PGVECTOR_DB was left pointing at a real "
            "deployment's own database. Set POSTGRES_DB=ainxt_test (create it "
            "once via `CREATE DATABASE ainxt_test` on the same Postgres server, "
            "then run db/migrate.py against it) before running this test suite. "
            "See docs/ecosystem/TESTING_GUIDE.md.",
            pytrace=False,
        )
