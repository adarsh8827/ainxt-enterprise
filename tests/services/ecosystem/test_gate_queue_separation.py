# SPDX-License-Identifier: MIT
# ============================================================
# Item 2 (pre-M3): the ecosystem gate's Docker sandbox stage must run in a
# separate gate-worker process, never the gateway. Two independent
# guarantees, tested separately:
#
# 1. enqueue_gate_run() genuinely enqueues to ecosystem_gate_queue and does
#    NOT resolve a verdict in-process (this file's own tests explicitly
#    restore the real core.job_queue.enqueue_ecosystem_gate_job function,
#    undoing tests/services/ecosystem/conftest.py's inline-worker stub that
#    every other test in this package relies on).
# 2. sandbox/ecosystem_gate_executor.py refuses to touch Docker unless
#    ECOSYSTEM_GATE_SANDBOX_ALLOWED is set in its own process environment
#    — set only by docker-compose.yml's gate-worker service, never the
#    gateway. A refusal fails the item (a "block" finding), not the
#    calling process.
# ============================================================

from __future__ import annotations

import pytest

# Captured at collection time, before tests/services/ecosystem/conftest.py's
# autouse fixture ever runs and overwrites core.job_queue's module attribute
# with its inline-worker stub. Re-importing this name from inside a test
# body would just re-read whatever the fixture already patched it to (the
# stub) -- this module-level capture is the only way to get the genuine
# function back for test_enqueue_gate_run_does_not_resolve_a_verdict_in_process.
from core.job_queue import enqueue_ecosystem_gate_job as _REAL_ENQUEUE_ECOSYSTEM_GATE_JOB

from services.ecosystem.gate.types import Finding
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def test_worker_module_run_ecosystem_gate_job_calls_run_gate_with_payload(monkeypatch):
    """workers/ecosystem_gate_worker.py is the ONLY place run_gate() should
    be called from in production. Confirm it unpacks the payload correctly
    -- this is the function docker-compose.yml's gate-worker service
    actually runs, so a wiring mistake here is invisible to every other
    test in this package (they all call run_gate() directly via the inline
    stub, never through this module)."""
    import workers.ecosystem_gate_worker as _worker

    captured = {}

    def _fake_run_gate(gate_run_id, **kwargs):
        captured["gate_run_id"] = gate_run_id
        captured["kwargs"] = kwargs
        return {"gate_run_id": gate_run_id, "verdict": "pass", "stage_verdicts": {}}

    monkeypatch.setattr("services.ecosystem.gate_service.run_gate", _fake_run_gate)

    result = _worker.run_ecosystem_gate_job({
        "gate_run_id": "grun-123",
        "installed_by": "user-1",
        "installed_for": "user-1",
        "org_id": "org-a",
        "surfaces": ["chat"],
        "provision_scope": "private",
    })

    assert captured["gate_run_id"] == "grun-123"
    assert captured["kwargs"] == {
        "installed_by": "user-1", "installed_for": "user-1", "org_id": "org-a",
        "surfaces": ["chat"], "provision_scope": "private",
    }
    assert result["verdict"] == "pass"


def test_enqueue_gate_run_does_not_resolve_a_verdict_in_process(monkeypatch):
    """Undo this package's inline-worker conftest stub for just this test —
    with the REAL core.job_queue.enqueue_ecosystem_gate_job restored,
    enqueue_gate_run() must return immediately with the row still
    'pending', proving the sandbox/ethics/etc. stages never ran
    synchronously in this (gateway-equivalent) process."""
    import core.job_queue as _job_queue
    from db.database import SessionLocal
    from db.models import EcosystemGateRun
    from services.ecosystem.gate_service import enqueue_gate_run

    if not _job_queue._rq_available:
        pytest.skip("Redis/rq not reachable in this environment")

    # Restore the real function the conftest autouse fixture replaced.
    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", _REAL_ENQUEUE_ECOSYSTEM_GATE_JOB)

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/queue-sep", item_type="skill", category="general",
        display_name="Queue Sep", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="queue-sep-1",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})

    gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()

    # No worker consumed the queue in this test process, so the row must
    # still be exactly where enqueue_gate_run() left it: pending.
    assert run.verdict == "pending"

    from core.job_queue import Q_ECOSYSTEM_GATE
    assert _job_queue.get_queue(Q_ECOSYSTEM_GATE) is not None


def test_sandbox_executor_refuses_without_allow_flag(monkeypatch):
    monkeypatch.delenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", raising=False)
    from sandbox.ecosystem_gate_executor import EcosystemGateProcessNotAllowedError, _assert_gate_worker_process

    with pytest.raises(EcosystemGateProcessNotAllowedError):
        _assert_gate_worker_process()


def test_sandbox_executor_allows_when_flag_set(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", "true")
    from sandbox.ecosystem_gate_executor import _assert_gate_worker_process

    _assert_gate_worker_process()  # must not raise


def test_sandbox_stage_reports_block_finding_when_not_allowed_rather_than_crashing(monkeypatch):
    """A misconfigured deployment (this stage invoked outside the
    gate-worker) must fail the item, not crash the calling process."""
    monkeypatch.delenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", raising=False)
    from services.ecosystem.gate.sandbox_stage import run

    files = {"scripts/verify.py": "print('ok')"}
    manifest = {"test": "scripts/verify.py"}
    result = run(files, manifest)

    assert result.verdict == "fail"
    assert any(f.code == "SANDBOX_NOT_ALLOWED_HERE" for f in result.findings)


def test_gate_service_module_never_imports_docker_at_module_level():
    """The gateway process imports services.ecosystem.gate_service (e.g.
    transitively, via create_service.py) without ever needing Docker —
    confirms the sandbox executor import stays lazy/local (inside
    sandbox_stage.run(), not a module-level import anywhere on the
    gate_service -> ... -> sandbox_stage chain)."""
    import ast
    import inspect

    import services.ecosystem.gate.sandbox_stage as sandbox_stage

    tree = ast.parse(inspect.getsource(sandbox_stage))
    module_level_imports = [
        n for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    for node in module_level_imports:
        names = [alias.name for alias in node.names]
        assert not any("docker" in n.lower() or "ecosystem_gate_executor" in n.lower() for n in names), (
            f"sandbox_stage.py imports {names} at module level -- Docker-touching code "
            "must only be imported lazily inside run(), so importing this module (which "
            "gate_service.py does at ITS module level) never requires Docker to be present."
        )
