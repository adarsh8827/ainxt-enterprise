# SPDX-License-Identifier: MIT
# Real incident, 2026-09-29 (see services/ecosystem/service_health.py's own
# header comment): stale gateway/gate-worker/gate-sweeper containers serving
# old code produced real symptoms (a 27-hour-stale gate-worker never
# consuming the priority-lane queues; a mismatched file set mid-merge) with
# nothing anywhere reporting "you're running old code". These tests exercise
# the real Redis-backed self-report/read-back path end to end -- no mocking
# of core.kv, same convention as test_catalog_sync.py's own direct use of
# get_kv(RDB_CACHE, ...).
from __future__ import annotations

import json

import pytest

from core.config import RDB_CACHE
from core.job_queue import ECOSYSTEM_GATE_QUEUES_BY_PRIORITY
from core.kv import get_kv
from services.ecosystem import service_health


def _redis_reachable() -> bool:
    try:
        get_kv(RDB_CACHE, decode_responses=True).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_reachable(), reason="Redis not reachable on configured host/port")


@pytest.fixture(autouse=True)
def _clean_service_health_keys():
    kv = get_kv(RDB_CACHE, decode_responses=True)
    for name in service_health._KNOWN_SERVICES:
        kv.delete(f"{service_health._SERVICE_HEALTH_KV_PREFIX}{name}")
    yield
    for name in service_health._KNOWN_SERVICES:
        kv.delete(f"{service_health._SERVICE_HEALTH_KV_PREFIX}{name}")


def test_report_service_startup_writes_a_real_redis_row_read_back_by_get_all_service_health():
    service_health.report_service_startup("gateway")

    kv = get_kv(RDB_CACHE, decode_responses=True)
    raw = kv.get("ecosystem:service_health:gateway")
    assert raw is not None
    payload = json.loads(raw)
    assert payload["service"] == "gateway"
    assert payload["commit"]
    assert payload["started_at"]
    assert isinstance(payload["pid"], int)

    health = service_health.get_all_service_health()
    assert health["services"]["gateway"]["commit"] == payload["commit"]
    assert health["services"]["gate_worker"] is None
    assert health["services"]["gate_sweeper"] is None


def test_a_service_that_never_reported_produces_a_warning():
    service_health.report_service_startup("gateway")
    health = service_health.get_all_service_health()
    assert any("gate_worker" in w and "never reported" in w for w in health["warnings"])
    assert any("gate_sweeper" in w and "never reported" in w for w in health["warnings"])
    assert not any("gateway" in w and "never reported" in w for w in health["warnings"])


def test_a_commit_mismatch_against_the_gateway_produces_a_warning_and_is_flagged_on_that_service(monkeypatch):
    commits = iter(["commit-aaa", "commit-bbb"])
    monkeypatch.setattr(service_health, "_current_commit", lambda: next(commits))

    service_health.report_service_startup("gateway")  # reports commit-aaa
    service_health.report_service_startup("gate_worker")  # reports commit-bbb

    health = service_health.get_all_service_health()
    assert health["gateway_commit"] == "commit-aaa"
    assert health["services"]["gateway"]["commit_mismatch"] is False
    assert health["services"]["gate_worker"]["commit_mismatch"] is True
    assert any("gate_worker" in w and "does not match gateway's" in w for w in health["warnings"])


def test_report_gate_worker_startup_flags_missing_lanes_when_it_only_covers_the_legacy_queue():
    # The exact 2026-09-29 incident, reproduced directly: a stale worker
    # only knowing about the pre-priority-lane single queue.
    from core.job_queue import Q_ECOSYSTEM_GATE

    service_health.report_gate_worker_startup([Q_ECOSYSTEM_GATE])

    health = service_health.get_all_service_health()
    gate_worker = health["services"]["gate_worker"]
    assert set(gate_worker["missing_lanes"]) == set(ECOSYSTEM_GATE_QUEUES_BY_PRIORITY) - {Q_ECOSYSTEM_GATE}
    assert any("gate_worker" in w and "not consuming every configured priority lane" in w for w in health["warnings"])


def test_report_gate_worker_startup_has_no_missing_lanes_when_it_covers_every_priority_queue():
    service_health.report_gate_worker_startup(list(ECOSYSTEM_GATE_QUEUES_BY_PRIORITY))

    health = service_health.get_all_service_health()
    gate_worker = health["services"]["gate_worker"]
    assert gate_worker["missing_lanes"] == []
    assert not any("not consuming every configured priority lane" in w for w in health["warnings"])


def test_get_all_service_health_never_raises_when_redis_is_unreachable(monkeypatch):
    # service_health.py imports get_kv locally, at call time (`from core.kv
    # import get_kv` inside the function body) -- patching the core.kv
    # module's own attribute is what that fresh import actually resolves.
    import core.kv as core_kv

    def _boom(*args, **kwargs):
        raise ConnectionError("simulated redis outage")

    monkeypatch.setattr(core_kv, "get_kv", _boom)

    health = service_health.get_all_service_health()
    assert all(v is None for v in health["services"].values())
    assert health["gateway_commit"] is None
    assert len(health["warnings"]) == len(service_health._KNOWN_SERVICES)
