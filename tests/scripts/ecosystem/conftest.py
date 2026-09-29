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
def _compliance_engine_enabled_for_gate_tests(monkeypatch):
    """Same fixture as tests/services/ecosystem/conftest.py's own -- see
    its docstring. Duplicated for the same sibling-directory reason as
    _clean_ecosystem_tables below."""
    from agents.compliance_engine import compliance_engine

    monkeypatch.setattr(compliance_engine, "enabled", True)


@pytest.fixture(autouse=True)
def _run_ecosystem_gate_inline(monkeypatch):
    """Same fixture as tests/services/ecosystem/conftest.py's own -- see
    its docstring for the full rationale. Duplicated here for the same
    sibling-directory reason as _clean_ecosystem_tables below -- its
    absence here is the real root cause of
    test_seed_builtin_skills.py::test_seeded_skills_are_scope_builtin_and_pass_the_gate
    (2026-09-29 review round) staying stuck on verdict='pending' forever:
    seed_all() calls gate_service.enqueue_gate_run(), which only ever
    creates a pending row and enqueues a real RQ job for the real,
    standalone gate-worker container to pick up -- but that container is
    configured against the real ainxt_memory database, never the
    disposable ainxt_test database this test suite actually runs
    against, so it can never find the row it's asked to gate. Not a code
    regression -- confirmed directly against that worker's own logs --
    just this directory never having inherited the sibling fixture that
    every other Tier-2 ecosystem test relies on to get a resolved
    verdict without a real out-of-process worker at all."""
    import core.job_queue as _job_queue
    from workers.ecosystem_gate_worker import run_ecosystem_gate_job

    def _inline_enqueue(gate_run_id, **kwargs):
        run_ecosystem_gate_job({"gate_run_id": gate_run_id, **kwargs})
        return "inline-" + gate_run_id

    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", _inline_enqueue)


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
