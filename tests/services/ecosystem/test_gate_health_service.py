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
