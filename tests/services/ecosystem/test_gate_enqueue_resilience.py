# SPDX-License-Identifier: MIT
# ============================================================
# Task B-6: "gate jobs occasionally never picked up".
#
# Root cause: services/ecosystem/gate_service.py's enqueue_gate_run()
# commits its ecosystem_gate_runs row (verdict='pending') BEFORE calling
# core.job_queue.enqueue_ecosystem_gate_job() -- correct, since it means an
# RQ job is never enqueued without a backing row -- but a transient failure
# in that enqueue call (queue at capacity, a Redis blip) used to propagate
# straight out of enqueue_gate_run() as an exception. The DB row was already
# committed by then: the caller (e.g. create_via_write()) would see its
# otherwise-successful item creation raise an error, AND the row was left
# 'pending' forever with no RQ job ever created for it and no way to
# reconstruct one (the auto-install/bump context only ever lived in the now
# never-created job's payload).
#
# This file reproduces that exact race directly (no real Redis/RQ needed --
# the failure is forced at the enqueue call itself) and proves both halves
# of the fix: (1) the caller no longer sees an exception, and (2) the row
# persists enough context on its own columns for a later sweep to recover it
# without the original caller's arguments.
# ============================================================

from __future__ import annotations

import pytest

from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _make_version(legacy_ref: str, org_id: str = "org-a") -> str:
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type="skill", category="general",
        display_name="Enqueue Resilience Test", description="d",
        org_id=org_id, legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    return version_id


def test_enqueue_gate_run_survives_a_failed_rq_enqueue(monkeypatch):
    """The race: the DB commit in enqueue_gate_run() succeeds, then the RQ
    enqueue call raises (simulating queue-at-capacity or a Redis blip).
    Before the fix, this exception propagated out of enqueue_gate_run() --
    the caller would see a failure for an item that, in fact, was created.
    After the fix, enqueue_gate_run() must swallow it and still return the
    gate_run_id, with the row left 'pending' for the sweeper to recover."""
    import core.job_queue as _job_queue
    from db.database import SessionLocal
    from db.models import EcosystemGateRun
    from services.ecosystem.gate_service import enqueue_gate_run

    def _boom(*args, **kwargs):
        raise RuntimeError("job_queue: queue 'ecosystem_gate_queue' at capacity (limit=200)")

    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", _boom)

    version_id = _make_version("enqueue-race-1")

    # Must not raise -- this is the whole fix.
    gate_run_id = enqueue_gate_run(
        version_id, trigger="chat_create",
        installed_by="user-1", installed_for="user-1", org_id="org-a",
        surfaces=["chat"], provision_scope="private",
    )
    assert gate_run_id is not None

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()

    # The row exists and is exactly where a genuinely-enqueued run would be
    # right after enqueue_gate_run() returns -- 'pending', not finished.
    assert run.verdict == "pending"
    assert run.finished_at is None


def test_enqueue_gate_run_persists_recovery_context_for_a_lost_job(monkeypatch):
    """Even when the RQ enqueue fails, the row must carry enough of its own
    context (db/migrate.py's Part AD5 columns) that a later sweep can
    reconstruct the exact same enqueue call -- the whole point of
    persisting this on the row instead of only ever having it live inside
    the (in this test, never-created) RQ job payload."""
    import core.job_queue as _job_queue
    from db.database import SessionLocal
    from db.models import EcosystemGateRun
    from services.ecosystem.gate_service import enqueue_gate_run

    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    version_id = _make_version("enqueue-race-2", org_id="org-b")

    gate_run_id = enqueue_gate_run(
        version_id, trigger="chat_create",
        installed_by="user-42", installed_for="user-42", org_id="org-b",
        surfaces=["chat", "agent_studio"], provision_scope="org_default_on",
    )

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()

    assert run.installed_by == "user-42"
    assert run.installed_for == "user-42"
    assert run.org_id == "org-b"
    assert run.surfaces == ["chat", "agent_studio"]
    assert run.provision_scope == "org_default_on"
    assert run.swept_at is None


def test_enqueue_gate_run_still_raises_from_the_db_commit_itself(monkeypatch):
    """The fix only swallows a failure in the RQ enqueue step -- a failure
    committing the row in the first place (a real DB outage, for example)
    must still surface as an error, since no row -- and therefore nothing
    for the sweeper to ever find -- was created at all."""
    from db import database as _database
    from services.ecosystem.gate_service import enqueue_gate_run

    class _ExplodingSession:
        def add(self, *a, **k):
            pass

        def commit(self):
            raise RuntimeError("db unavailable")

        def close(self):
            pass

    monkeypatch.setattr(_database, "SessionLocal", lambda: _ExplodingSession())
    # gate_service imported SessionLocal by name at module load time --
    # patch it there too so this test doesn't depend on import order.
    import services.ecosystem.gate_service as _gate_service
    monkeypatch.setattr(_gate_service, "SessionLocal", lambda: _ExplodingSession())

    with pytest.raises(RuntimeError):
        enqueue_gate_run("does-not-matter", trigger="chat_create")
