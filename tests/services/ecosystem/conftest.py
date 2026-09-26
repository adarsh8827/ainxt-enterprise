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
def _compliance_engine_enabled_for_gate_tests(monkeypatch):
    """static_safety_stage now resolves to 'pending' (never 'pass') when
    agents/compliance_engine.py's singleton is disabled (fail-closed fix,
    follow-up to item 3) -- COMPLIANCE_SERVICE_ENABLED defaults to false
    and CI never sets it, so every test in this package that expects a
    resolved pass/warn/fail verdict needs the singleton forced on,
    independent of that unrelated flag's ambient configuration.
    tests/services/ecosystem/gate/test_static_safety_stage.py's own
    scanner-disabled test explicitly overrides this back to False for
    itself.
    """
    from agents.compliance_engine import compliance_engine

    monkeypatch.setattr(compliance_engine, "enabled", True)


@pytest.fixture(autouse=True)
def _run_ecosystem_gate_inline(monkeypatch):
    """gate_service.enqueue_gate_run() genuinely enqueues to
    ecosystem_gate_queue (item 2, pre-M3) rather than running the gate's
    stages in-process — no rq worker runs during pytest, and most tests
    in this package need to assert on a *resolved* verdict right after
    calling enqueue_gate_run(), not "still pending because nothing
    consumed the queue." This stands in for workers/ecosystem_gate_worker.py,
    invoking the exact same job function synchronously, in this test
    process, the moment it would otherwise have been enqueued.

    tests/services/ecosystem/test_gate_queue_separation.py explicitly
    undoes this (via monkeypatch.undo() / its own patch) to test the real
    enqueue path against a real Redis/rq instance.
    """
    import core.job_queue as _job_queue
    from workers.ecosystem_gate_worker import run_ecosystem_gate_job

    def _inline_enqueue(gate_run_id, **kwargs):
        run_ecosystem_gate_job({"gate_run_id": gate_run_id, **kwargs})
        return "inline-" + gate_run_id

    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", _inline_enqueue)


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
                "ainxt.ecosystem_item_versions, ainxt.ecosystem_shares, ainxt.ecosystem_installs, "
                "ainxt.ecosystem_reports, ainxt.ecosystem_featured_overrides, "
                "ainxt.ecosystem_items, ainxt.ecosystem_sources, ainxt.ecosystem_publishers, "
                "ainxt.ecosystem_audit, ainxt.ecosystem_org_excluded_defaults CASCADE"
            ))
            conn.commit()
    except Exception as exc:
        pytest.skip(f"ecosystem tables not reachable/migrated: {exc}")

    yield
