# SPDX-License-Identifier: MIT
# ============================================================
# Gate orchestrator integration tests (tasks B-8/B-9). Tier-2 — real
# Postgres. The ethics stage's model call is mocked for determinism (a real
# LLM call isn't available/deterministic in this test environment) — every
# OTHER stage runs for real against real content.
#
# enqueue_gate_run() now genuinely enqueues to ecosystem_gate_queue (item
# 2, pre-M3) rather than running the stages in-process. What's being
# tested here is the orchestrator's stage sequencing/aggregation/caching
# logic (run_gate()); tests/services/ecosystem/conftest.py's
# `_run_ecosystem_gate_inline` autouse fixture stands in for the real
# ecosystem-gate-queue consumer (workers/ecosystem_gate_worker.py) so
# every enqueue_gate_run() call below resolves synchronously, in this test
# process, exactly as that worker would. The queue transport itself has
# its own dedicated test in test_gate_queue_separation.py.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemGateFinding, EcosystemGateRun, EcosystemItemVersion
from services.ecosystem.gate_service import enqueue_gate_run
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_item_and_version(name="Clean Skill", content_text="Say hello politely.", legacy_ref="gate-1"):
    # Namespace derived from legacy_ref, not a shared constant -- the
    # namespace-uniqueness partial index (task B-1) is genuinely enforced
    # (a bug fixed during this milestone made it inert before now), so two
    # calls in the same test with the same namespace+org_id would collide.
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type="skill", category="general",
        display_name=name, description="a clean test skill",
        org_id="org-a", legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    version_id, _ = create_or_refresh_legacy_version(
        item_id=item_id, content_text=content_text,
        manifest={"name": name, "description": "a clean test skill"},
    )
    return item_id, version_id


def test_clean_item_resolves_to_pass():
    _, version_id = _make_item_and_version(legacy_ref="gate-pass")
    with _mock_ethics_pass():
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()
    assert run.verdict == "pass"
    assert version.gate_verdict == "pass"


def test_secret_containing_item_resolves_to_warn_or_fail():
    _, version_id = _make_item_and_version(
        content_text='access_key = "AKIAIOSFODNN7EXAMPLE"',
        legacy_ref="gate-secret",
    )
    with _mock_ethics_pass():
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()
    assert run.verdict in ("warn", "fail")


def test_ethics_reviewer_unavailable_resolves_to_pending_never_pass():
    _, version_id = _make_item_and_version(legacy_ref="gate-ethics-down")
    with patch("models.model_router.model_router.generate", return_value="Error: no gateway available"):
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()
    assert run.verdict == "pending"
    assert version.gate_verdict == "pending"


def test_findings_are_recorded_in_gate_findings_table():
    _, version_id = _make_item_and_version(
        content_text='access_key = "AKIAIOSFODNN7EXAMPLE"',
        legacy_ref="gate-findings",
    )
    with _mock_ethics_pass():
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        findings = db.query(EcosystemGateFinding).filter(EcosystemGateFinding.gate_run_id == gate_run_id).all()
    finally:
        db.close()
    assert len(findings) > 0
    assert any(f.stage == "static_safety" for f in findings)


def test_disallowed_license_short_circuits_to_fail_without_invoking_ethics():
    # license_stage alone should be enough to fail the run -- and per the
    # cache/short-circuit logic, stages 5-7 (including the ethics call)
    # should never even be invoked once stages 1-4 already produced a fail.
    from db.database import SessionLocal as _SL
    from db.models import EcosystemItem

    _, version_id = _make_item_and_version(legacy_ref="gate-badlicense")
    db = _SL()
    try:
        item = db.query(EcosystemItem).join(
            EcosystemItemVersion, EcosystemItemVersion.item_id == EcosystemItem.id
        ).filter(EcosystemItemVersion.id == version_id).one()
        item.license = "GPL-3.0-only"
        db.commit()
    finally:
        db.close()

    with patch("models.model_router.model_router.generate") as mock_generate:
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")
        mock_generate.assert_not_called()

    db = _SL()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()
    assert run.verdict == "fail"


def test_content_hash_cache_hit_skips_sandbox_reinvocation():
    # Two DIFFERENT items sharing identical content (same content_hash) --
    # the second gate run should reuse the first's cached stages-5-7
    # verdict rather than re-invoking the (mocked) ethics call.
    _, version_id_1 = _make_item_and_version(content_text="identical shared content", legacy_ref="gate-cache-1")
    with _mock_ethics_pass() as mocked:
        enqueue_gate_run(version_id_1, trigger="admin_provision")
        first_call_count = mocked.call_count

    _, version_id_2 = _make_item_and_version(content_text="identical shared content", legacy_ref="gate-cache-2")
    with _mock_ethics_pass() as mocked2:
        gate_run_id_2 = enqueue_gate_run(version_id_2, trigger="admin_provision")
        assert mocked2.call_count == 0, "ethics stage was re-invoked despite an identical-content-hash cache hit"

    db = SessionLocal()
    try:
        run2 = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id_2).one()
        findings2 = db.query(EcosystemGateFinding).filter(EcosystemGateFinding.gate_run_id == gate_run_id_2).all()
    finally:
        db.close()
    assert run2.verdict == "pass"
    assert any(f.code == "CACHE_HIT" for f in findings2)
