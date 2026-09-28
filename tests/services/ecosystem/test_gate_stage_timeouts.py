# SPDX-License-Identifier: MIT
# ============================================================
# Item 8: real incident, 2026-09-27 -- no gate stage had a timeout of its
# own; the ethics stage (an LLM call) or the sandbox stage (Docker image
# pull + container run) could hang the whole gate-worker job indefinitely,
# with only RQ's own blunt, job-level 300s default eventually killing it
# via a confusing traceback (a deferred SIGALRM landing wherever the
# interpreter happened to be, often deep in an unrelated import).
#
# gate_service._run_stage_with_timeout() wraps every stage call in a
# per-stage wall-clock timeout (services/ecosystem/gate_service.py's
# _STAGE_TIMEOUT_SECONDS). This file proves: a stage that exceeds its
# timeout resolves to 'pending' with a STAGE_TIMEOUT finding (never an
# unhandled exception), the run's finished_at is deliberately left unset
# so it isn't a resolved dead end, and gate_health_service.
# sweep_stuck_gate_runs()'s EXISTING recovery path (task B-6) picks it up
# and re-enqueues it without any new, second retry mechanism.
# ============================================================

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from db.database import SessionLocal
from db.models import EcosystemGateRun
from services.ecosystem import gate_service
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _make_version(legacy_ref: str, org_id: str = "org-timeout") -> tuple[str, str]:
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type="skill", category="general",
        display_name="Stage Timeout Test", description="d",
        org_id=org_id, legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    return item_id, version_id


def test_a_stage_that_exceeds_its_timeout_resolves_to_pending_with_a_finding_not_a_crash(monkeypatch):
    monkeypatch.setitem(gate_service._STAGE_TIMEOUT_SECONDS, "manifest", 0.05)
    slow = gate_service.manifest_stage.run
    monkeypatch.setattr(gate_service.manifest_stage, "run", lambda *a, **k: (time.sleep(0.3), slow(*a, **k))[1])

    _item_id, version_id = _make_version("timeout-manifest")
    gate_run_id = gate_service.enqueue_gate_run(version_id, trigger="ui_add")
    result = gate_service.run_gate(gate_run_id)

    assert result["verdict"] == "pending"
    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        assert run.verdict == "pending"
        assert run.finished_at is None  # deliberately left unset -- not a resolved dead end
        assert run.stage_timings["manifest"]["status"] == "pending"
    finally:
        db.close()

    db = SessionLocal()
    try:
        findings = [f for f in db.query(gate_service.EcosystemGateFinding).filter(
            gate_service.EcosystemGateFinding.gate_run_id == gate_run_id
        ).all()]
    finally:
        db.close()
    assert any(f.code == "STAGE_TIMEOUT" and f.stage == "manifest" for f in findings)


def test_a_timed_out_run_gets_picked_up_by_the_existing_sweeper_no_second_retry_system(monkeypatch):
    from services.ecosystem import gate_health_service

    monkeypatch.setitem(gate_service._STAGE_TIMEOUT_SECONDS, "manifest", 0.05)
    slow = gate_service.manifest_stage.run
    monkeypatch.setattr(gate_service.manifest_stage, "run", lambda *a, **k: (time.sleep(0.3), slow(*a, **k))[1])

    _item_id, version_id = _make_version("timeout-sweep")
    gate_run_id = gate_service.enqueue_gate_run(version_id, trigger="ui_add")
    gate_service.run_gate(gate_run_id)

    # Back-date started_at past the stuck threshold and force the RQ job
    # id to look not-in-flight (no real Redis/RQ needed -- get_job_status
    # is mocked, matching test_gate_health_service.py's own convention).
    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=gate_health_service.STUCK_VERIFYING_THRESHOLD_SECONDS + 5)
        db.commit()
    finally:
        db.close()

    import core.job_queue as job_queue
    monkeypatch.setattr(job_queue, "get_job_status", lambda job_id: {"status": "not_found"})
    reenqueued_ids = []
    monkeypatch.setattr(job_queue, "enqueue_ecosystem_gate_job", lambda gate_run_id, **kw: reenqueued_ids.append(gate_run_id))

    result = gate_health_service.sweep_stuck_gate_runs()

    assert gate_run_id in result["reenqueued_gate_run_ids"]
    assert gate_run_id in reenqueued_ids


def test_stage_timeout_never_produces_a_fail_verdict_a_timeout_is_not_evidence_of_bad_content(monkeypatch):
    monkeypatch.setitem(gate_service._STAGE_TIMEOUT_SECONDS, "supply_chain", 0.05)
    slow = gate_service.supply_chain_stage.run
    monkeypatch.setattr(gate_service.supply_chain_stage, "run", lambda *a, **k: (time.sleep(0.3), slow(*a, **k))[1])

    # Catalog-checking round (2026-09-28): supply_chain is now skipped
    # entirely (verdict='pass', never invoked) for an item with no
    # scripts/dependencies -- this test is specifically about the
    # TIMEOUT mechanism, so it needs supply_chain to actually run at
    # all, which now requires a declared dependency.
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/timeout-not-fail", item_type="skill", category="general",
        display_name="Stage Timeout Test", description="d",
        org_id="org-timeout", legacy_source="skills_pg", legacy_ref="timeout-not-fail",
    )
    version_id, _ = create_or_refresh_legacy_version(
        item_id=item_id, content_text="c", manifest={"dependencies": [{"name": "somepkg", "version": "1.0.0"}]},
    )
    gate_run_id = gate_service.enqueue_gate_run(version_id, trigger="ui_add")
    result = gate_service.run_gate(gate_run_id)

    assert result["stage_verdicts"]["supply_chain"] == "pending"
    assert result["verdict"] != "fail" or any(
        sv == "fail" for name, sv in result["stage_verdicts"].items() if name != "supply_chain"
    )
