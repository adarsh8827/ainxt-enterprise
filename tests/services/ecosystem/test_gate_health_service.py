# SPDX-License-Identifier: MIT
# ============================================================
# Gate-worker health signal tests (item 2's follow-up, pre-M3).
# Tier-2 — real Postgres + Redis.
# ============================================================

from __future__ import annotations

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
        kv = get_kv(RDB_CACHE, decode_responses=True)
        kv.get("ecosystem:gate_worker:heartbeat")
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")


def _clear_heartbeat():
    from core.config import RDB_CACHE
    from core.kv import get_kv

    get_kv(RDB_CACHE, decode_responses=True).delete("ecosystem:gate_worker:heartbeat")


def test_get_health_reports_unhealthy_when_no_heartbeat_ever_recorded():
    _clear_heartbeat()
    health = gate_health_service.get_health()
    assert health["gate_worker_healthy"] is False
    assert health["last_heartbeat"] is None
    assert "No gate-worker" in health["message"]


def test_record_heartbeat_then_get_health_reports_healthy():
    gate_health_service.record_heartbeat()
    health = gate_health_service.get_health()
    assert health["gate_worker_healthy"] is True
    assert health["last_heartbeat"] is not None
    assert health["stuck_verifying_count"] == 0
    assert health["message"] is None


def test_stuck_verifying_run_is_counted_and_messaged_even_when_healthy():
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    gate_health_service.record_heartbeat()

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


def test_recent_pending_run_is_not_counted_as_stuck():
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    version_id = _make_version("health-recent")
    gate_health_service.record_heartbeat()

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


def test_get_health_surfaces_the_last_sweep_summary():
    import services.ecosystem.gate_health_service as _health

    gate_health_service.record_heartbeat()
    _make_stuck_row("sweep-visible")

    _health.sweep_stuck_gate_runs()  # real RQ lookup/enqueue -- may no-op if Redis unreachable, that's fine

    health = gate_health_service.get_health()
    assert "last_sweep" in health
    assert health["last_sweep"] is not None
    assert "checked" in health["last_sweep"]
