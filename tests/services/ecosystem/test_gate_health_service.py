# SPDX-License-Identifier: MIT
# ============================================================
# Gate-worker health signal tests (item 2's follow-up, pre-M3).
# Tier-2 — real Postgres + Redis.
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from services.ecosystem import gate_health_service
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _make_version(legacy_ref: str) -> str:
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type="skill", category="general",
        display_name="Health Test", description="d",
        org_id="org-health", legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    return version_id


@pytest.fixture(autouse=True)
def _require_redis():
    from core.config import RDB_CACHE
    from core.kv import get_kv

    try:
        get_kv(RDB_CACHE, decode_responses=True).ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")


def _mock_liveness(monkeypatch, *, healthy: bool, worker_count: int = 0):
    """Liveness (task, 2026-09-28 fork-lock fix) now reads RQ's own worker
    registry (core.job_queue.get_queue_worker_liveness) instead of a
    hand-rolled heartbeat key -- see that function's docstring for why the
    old key/thread was removed."""
    monkeypatch.setattr(
        "core.job_queue.get_queue_worker_liveness",
        lambda queue_name: {
            "healthy": healthy, "worker_count": worker_count,
            "workers": [{"name": f"w{i}", "state": "idle"} for i in range(worker_count)],
        },
    )


def test_get_health_reports_unhealthy_when_no_worker_registered(monkeypatch):
    _mock_liveness(monkeypatch, healthy=False)
    health = gate_health_service.get_health()
    assert health["gate_worker_healthy"] is False
    assert health["gate_worker_count"] == 0
    assert "No gate-worker" in health["message"]


def test_get_health_reports_healthy_when_an_rq_worker_is_registered(monkeypatch):
    _mock_liveness(monkeypatch, healthy=True, worker_count=1)
    health = gate_health_service.get_health()
    assert health["gate_worker_healthy"] is True
    assert health["gate_worker_count"] == 1
    assert health["stuck_verifying_count"] == 0
    assert health["message"] is None


def test_worker_liveness_reflects_a_real_rq_worker_registering_and_deregistering():
    """End-to-end against real RQ/Redis (task, 2026-09-28): register a real
    Worker's birth on the gate queue, confirm liveness flips healthy, then
    register its death and confirm it flips back -- proves get_health() is
    now reading RQ's own registry, not a signal our own code writes."""
    from core.job_queue import Q_ECOSYSTEM_GATE, get_queue_worker_liveness, _redis_conn

    if _redis_conn is None:
        pytest.skip("RQ/Redis backend unavailable")

    from rq import Queue, Worker

    queue = Queue(Q_ECOSYSTEM_GATE, connection=_redis_conn)
    worker = Worker([queue], connection=_redis_conn, name=f"test-liveness-{id(object())}")
    worker.register_birth()
    try:
        liveness = get_queue_worker_liveness(Q_ECOSYSTEM_GATE)
        assert liveness["healthy"] is True
        assert liveness["worker_count"] >= 1
        assert any(w["name"] == worker.name for w in liveness["workers"])
    finally:
        worker.register_death()

    liveness_after = get_queue_worker_liveness(Q_ECOSYSTEM_GATE)
    assert all(w["name"] != worker.name for w in liveness_after["workers"])


def test_stuck_verifying_run_is_counted_and_messaged_even_when_healthy(monkeypatch):
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    _mock_liveness(monkeypatch, healthy=True, worker_count=1)

    version_id = _make_version("health-stuck")

    db = SessionLocal()
    try:
        stale_started_at = datetime.now(timezone.utc) - timedelta(
            seconds=gate_health_service.STUCK_VERIFYING_THRESHOLD_SECONDS + 60
        )
        row = EcosystemGateRun(
            version_id=version_id,
            trigger="admin_provision", verdict="pending", scanner_version="test",
            started_at=stale_started_at,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    health = gate_health_service.get_health()
    assert health["gate_worker_healthy"] is True
    assert health["stuck_verifying_count"] >= 1
    assert "verifying" in health["message"]


def test_recent_pending_run_is_not_counted_as_stuck(monkeypatch):
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    version_id = _make_version("health-recent")
    _mock_liveness(monkeypatch, healthy=True, worker_count=1)

    db = SessionLocal()
    try:
        row = EcosystemGateRun(
            version_id=version_id,
            trigger="admin_provision", verdict="pending", scanner_version="test",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    health = gate_health_service.get_health()
    assert health["stuck_verifying_count"] == 0
    assert health["message"] is None


# ── Stuck-run sweeper (task B-6) ────────────────────────────────────────────
#
# Reproduces the actual "occasionally never picked up" scenario: a gate_runs
# row stuck 'pending' well past the threshold, with no RQ job in flight for
# it -- exactly what's left behind when enqueue_gate_run()'s RQ enqueue call
# fails after its DB commit already succeeded (see
# tests/services/ecosystem/test_gate_enqueue_resilience.py for that half).


def _make_stuck_row(legacy_ref: str, **overrides):
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    version_id = _make_version(legacy_ref)
    stale_started_at = datetime.now(timezone.utc) - timedelta(
        seconds=gate_health_service.STUCK_VERIFYING_THRESHOLD_SECONDS + 60
    )
    db = SessionLocal()
    try:
        row = EcosystemGateRun(
            version_id=version_id,
            trigger="chat_create", verdict="pending", scanner_version="test",
            started_at=stale_started_at,
            installed_by=overrides.get("installed_by", "user-1"),
            installed_for=overrides.get("installed_for", "user-1"),
            org_id=overrides.get("org_id", "org-a"),
            surfaces=overrides.get("surfaces", ["chat"]),
            provision_scope=overrides.get("provision_scope", "private"),
            swept_at=overrides.get("swept_at"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_sweep_reenqueues_a_run_with_no_rq_job_in_flight(monkeypatch):
    """The exact recovery case: nothing in RQ for this gate_run_id (the
    original enqueue never landed) -- the sweeper must re-enqueue it using
    the row's own persisted context, not raise, not skip it."""
    import services.ecosystem.gate_health_service as _health

    gate_run_id = _make_stuck_row("sweep-lost")

    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "unknown"})
    captured = []
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: captured.append((gate_run_id, kwargs)),
    )

    result = _health.sweep_stuck_gate_runs()

    assert result["checked"] == 1
    assert result["reenqueued"] == 1
    assert result["still_in_flight"] == 0
    assert gate_run_id in result["reenqueued_gate_run_ids"]
    assert len(captured) == 1
    reenqueued_id, kwargs = captured[0]
    assert reenqueued_id == gate_run_id
    assert kwargs == {
        "installed_by": "user-1", "installed_for": "user-1", "org_id": "org-a",
        "surfaces": ["chat"], "provision_scope": "private",
    }

    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        assert run.swept_at is not None
    finally:
        db.close()


def test_sweep_never_touches_a_run_genuinely_in_flight(monkeypatch):
    """A row that LOOKS stuck by DB timestamp alone but whose RQ job is
    actually still queued/running must be left alone -- re-enqueueing it
    would double-process the same gate run."""
    import services.ecosystem.gate_health_service as _health

    gate_run_id = _make_stuck_row("sweep-in-flight")

    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "started"})
    calls = []
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: calls.append(gate_run_id),
    )

    result = _health.sweep_stuck_gate_runs()

    assert result["checked"] == 1
    assert result["reenqueued"] == 0
    assert result["still_in_flight"] == 1
    assert calls == []

    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        assert run.swept_at is None
    finally:
        db.close()


def test_sweep_skips_a_row_already_swept_within_the_cooldown(monkeypatch):
    """A row already re-enqueued recently must not be re-enqueued again on
    every sweep tick -- idempotency across repeated sweeper runs."""
    import services.ecosystem.gate_health_service as _health

    recent_sweep = datetime.now(timezone.utc) - timedelta(seconds=5)
    gate_run_id = _make_stuck_row("sweep-cooldown", swept_at=recent_sweep)

    calls = []
    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "unknown"})
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: calls.append(gate_run_id),
    )

    result = _health.sweep_stuck_gate_runs()

    assert result["checked"] == 0
    assert result["reenqueued"] == 0
    assert calls == []


# ── Retry/backoff + max-attempts (real incident, 2026-09-28) ────────────────
# A gate-worker's own RQ work-horse was killed out-of-band mid-job
# ("Work-horse terminated unexpectedly; waitpid returned None" -- RQ moves
# such a job to its FailedJobRegistry, i.e. get_job_status() reports
# "failed", never one of _IN_FLIGHT_STATUSES). These tests simulate exactly
# that RQ-visible state and prove the sweeper backs off between retries and
# eventually gives up with a clear, permanent failure instead of retrying
# a genuinely-broken row forever.

def test_sweep_reenqueues_a_run_whose_rq_job_was_marked_failed_by_a_killed_work_horse(monkeypatch):
    """The real incident's exact RQ-visible signature: status='failed' (not
    'unknown') -- must still be treated as "not in flight, safe to retry",
    same as the no-job-at-all case."""
    import services.ecosystem.gate_health_service as _health

    gate_run_id = _make_stuck_row("sweep-killed-horse")

    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "failed"})
    captured = []
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: captured.append(gate_run_id),
    )

    result = _health.sweep_stuck_gate_runs()

    assert result["reenqueued"] == 1
    assert result["still_in_flight"] == 0
    assert captured == [gate_run_id]

    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        assert run.sweep_attempts == 1
    finally:
        db.close()


def test_resweep_cooldown_grows_exponentially_with_attempt_count():
    from services.ecosystem.gate_health_service import _resweep_cooldown_for, _RESWEEP_COOLDOWN_SECONDS, _MAX_RESWEEP_COOLDOWN_SECONDS

    assert _resweep_cooldown_for(0) == _RESWEEP_COOLDOWN_SECONDS
    assert _resweep_cooldown_for(1) == _RESWEEP_COOLDOWN_SECONDS * 2
    assert _resweep_cooldown_for(2) == _RESWEEP_COOLDOWN_SECONDS * 4
    assert _resweep_cooldown_for(20) == _MAX_RESWEEP_COOLDOWN_SECONDS  # caps, never grows unbounded


def test_a_row_with_prior_attempts_is_not_reswept_before_its_own_backed_off_cooldown(monkeypatch):
    """attempt=1's real cooldown is 2x the base -- a row swept `base + 60`
    seconds ago (long enough for an attempt-0 row, per the widest-net SQL
    filter) must still be skipped in the per-row Python check, since its
    OWN backed-off cooldown hasn't elapsed yet."""
    import services.ecosystem.gate_health_service as _health

    swept_recently_for_this_attempt_count = datetime.now(timezone.utc) - timedelta(
        seconds=gate_health_service.STUCK_VERIFYING_THRESHOLD_SECONDS + 60
    )
    gate_run_id = _make_stuck_row("sweep-backoff-not-due", swept_at=swept_recently_for_this_attempt_count)

    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        run.sweep_attempts = 1
        db.commit()
    finally:
        db.close()

    calls = []
    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "failed"})
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: calls.append(gate_run_id),
    )

    result = _health.sweep_stuck_gate_runs()

    assert calls == []
    assert result["reenqueued"] == 0
    assert result["permanently_failed"] == 0


def test_exceeding_max_sweep_attempts_marks_the_run_permanently_failed(monkeypatch):
    """Past _MAX_SWEEP_ATTEMPTS, stop retrying and resolve to a real 'fail'
    verdict with a clear GATE_WORKER_INTERRUPTED finding -- never leave the
    item stuck in 'Verifying...' forever just because the worker keeps
    dying the same way."""
    import services.ecosystem.gate_health_service as _health

    long_ago = datetime.now(timezone.utc) - timedelta(hours=6)
    gate_run_id = _make_stuck_row("sweep-max-attempts", swept_at=long_ago)

    from db.database import SessionLocal
    from db.models import EcosystemGateRun, EcosystemGateFinding, EcosystemItemVersion

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        run.sweep_attempts = _health._MAX_SWEEP_ATTEMPTS
        db.commit()
    finally:
        db.close()

    calls = []
    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "failed"})
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: calls.append(gate_run_id),
    )

    result = _health.sweep_stuck_gate_runs()

    assert calls == []  # never re-enqueued once attempts are exhausted
    assert result["reenqueued"] == 0
    assert result["permanently_failed"] == 1
    assert gate_run_id in result["permanently_failed_gate_run_ids"]

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        assert run.verdict == "fail"
        assert run.finished_at is not None

        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == run.version_id).one()
        assert version.gate_verdict == "fail"

        finding = (
            db.query(EcosystemGateFinding)
            .filter(EcosystemGateFinding.gate_run_id == gate_run_id, EcosystemGateFinding.code == "GATE_WORKER_INTERRUPTED")
            .one()
        )
        assert finding.severity == "block"
        assert finding.stage == "sweep"
    finally:
        db.close()


def test_get_health_surfaces_the_last_sweep_summary(monkeypatch):
    import services.ecosystem.gate_health_service as _health

    _mock_liveness(monkeypatch, healthy=True, worker_count=1)
    _make_stuck_row("sweep-visible")

    _health.sweep_stuck_gate_runs()  # real RQ lookup/enqueue -- may no-op if Redis unreachable, that's fine

    health = gate_health_service.get_health()
    assert "last_sweep" in health
    assert health["last_sweep"] is not None
    assert "checked" in health["last_sweep"]


# ── Sweeper runs in its own process now (task, 2026-09-28 fork-lock fix) ────
# workers/start_workers.py's --gate-sweeper mode runs _run_gate_sweeper_loop()
# as the entire body of a dedicated process/compose service, never sharing a
# process with --gate (which forks RQ work-horses per job). This proves that
# loop function itself does the real work (re-enqueues an orphaned job) when
# ticked, independent of which process happens to call it.

def test_gate_sweeper_loop_reenqueues_an_orphaned_job_then_stops_on_event(monkeypatch):
    import threading

    from workers.start_workers import _run_gate_sweeper_loop

    gate_run_id = _make_stuck_row("sweeper-loop-orphan")

    monkeypatch.setattr("core.job_queue.get_job_status", lambda job_id: {"status": "unknown"})
    captured = []
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda gate_run_id, **kwargs: captured.append(gate_run_id),
    )
    # Make the loop's own poll interval effectively instant so the test
    # doesn't wait a real 30s between the first tick and stop_event check.
    monkeypatch.setattr("services.ecosystem.gate_health_service.HEARTBEAT_INTERVAL_SECONDS", 0)

    stop_event = threading.Event()

    def _stop_after_first_tick():
        stop_event.wait(timeout=2)

    # Run the loop body in a thread (it blocks on stop_event.wait internally)
    # and stop it right after the first tick has had time to run.
    t = threading.Thread(target=_run_gate_sweeper_loop, args=(stop_event,), daemon=True)
    t.start()
    import time
    deadline = time.monotonic() + 5
    while gate_run_id not in captured and time.monotonic() < deadline:
        time.sleep(0.05)
    stop_event.set()
    t.join(timeout=5)

    assert gate_run_id in captured
    assert not t.is_alive()


# ── Fork-lock deadlock reproduction (real incident, 2026-09-28) ─────────────
# See db/database.py's and core/kv/queue.py's os.register_at_fork() hooks,
# and workers/start_workers.py's removal of the custom heartbeat/sweeper
# threads from the process that forks RQ work-horses. This test reproduces
# the actual hazard class directly: a connection checked out (held) in one
# thread of the parent at the moment of fork() used to be exactly the kind
# of state that could leave a forked child deadlocked on the pool's internal
# lock forever; dispose(close=False)/reset() in the child (registered via
# os.register_at_fork) must let the child get a fresh, working connection
# quickly regardless of what the parent was doing when it forked.

@pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork() is POSIX-only")
def test_child_process_can_use_the_db_after_fork_while_the_pools_own_lock_is_held():
    """Deterministic reproduction, not a timing-dependent race: holds the
    connection pool's OWN internal bookkeeping lock (SQLAlchemy's
    util.queue.Queue.mutex, the exact class of lock a checkout/checkin
    briefly takes) in a thread that never releases it, then forks. Without
    db/database.py's os.register_at_fork(after_in_child=dispose(close=False))
    hook, the forked child inherits that lock already acquired forever (its
    owning thread doesn't exist in the child) and any connect() attempt
    through the SAME pool object deadlocks -- this is exactly the
    2026-09-28 incident. With the hook, dispose() swaps in a brand-new pool
    object in the child, so the stuck old mutex is simply never touched.
    """
    import select
    import threading
    from sqlalchemy import text

    from db.database import engine

    mutex = engine.pool._pool.mutex
    held = threading.Event()

    def _hold_the_pool_mutex_forever():
        mutex.acquire()
        held.set()
        # Deliberately never released — this thread simply doesn't exist
        # anymore once we fork, exactly reproducing "lock held at fork time".

    holder = threading.Thread(target=_hold_the_pool_mutex_forever, daemon=True)
    holder.start()
    assert held.wait(timeout=5), "test setup failed to acquire the pool's own lock"

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        # ── child ──
        os.close(read_fd)
        try:
            conn = engine.connect()
            conn.execute(text("SELECT 1"))
            conn.close()
            os.write(write_fd, b"OK")
        except BaseException:
            os.write(write_fd, b"FAIL")
        finally:
            os.close(write_fd)
            os._exit(0)

    # ── parent ──
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 10)
        result = os.read(read_fd, 10) if ready else b"TIMEOUT"
    finally:
        os.close(read_fd)
        # A genuine regression means the child is blocked forever inside
        # engine.connect() and will never reach os._exit() on its own -- a
        # blocking os.waitpid(pid, 0) here would hang this test (and the
        # whole suite) right along with it. Poll non-blockingly instead,
        # and forcibly kill+reap the child if it hasn't exited on its own.
        import signal
        import time as _time

        deadline = _time.monotonic() + 2
        reaped_pid = 0
        while _time.monotonic() < deadline:
            reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
            if reaped_pid == pid:
                break
            _time.sleep(0.05)
        if reaped_pid != pid:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        # holder thread deliberately never joined — it holds the mutex forever
        # by design and this test process exits right after, taking it with it.

    assert result == b"OK", (
        f"child's DB connect() after fork did not complete cleanly ({result!r}) -- "
        "this is exactly the 2026-09-28 fork-lock hazard reappearing"
    )
