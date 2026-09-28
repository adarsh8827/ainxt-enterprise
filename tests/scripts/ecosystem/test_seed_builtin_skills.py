# SPDX-License-Identifier: MIT
# ============================================================
# Builtin-skill seeding tests (task B-22). Tier-2 — real Postgres.
# Ethics stage mocked pass (deterministic); one test specifically covers
# the ethics-reviewer-unavailable path, per the M0-review correction that
# applies identically to this seeding path.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemGateRun, EcosystemItem, EcosystemItemVersion
from scripts.ecosystem.seed_builtin_skills import seed_all


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def test_seed_all_finds_the_shipped_starter_skills():
    with _mock_ethics_pass():
        results = seed_all()
    namespaces = {r["namespace"] for r in results}
    assert "ainxt/meeting-notes-summarizer" in namespaces
    assert "ainxt/commit-message-writer" in namespaces
    assert "ainxt/weekly-status-report" in namespaces
    assert "ainxt/email-tone-polish" in namespaces
    assert len(results) >= 3  # task B-22 requires 3-5 starter skills


def test_seeded_skills_are_scope_builtin_and_pass_the_gate():
    with _mock_ethics_pass():
        results = seed_all()
    db = SessionLocal()
    try:
        for r in results:
            item = db.query(EcosystemItem).filter(EcosystemItem.id == r["item_id"]).one()
            run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == r["gate_run_id"]).one()
            assert item.scope == "builtin"
            assert item.trust_tier == "builtin"
            assert item.org_id is None
            assert item.license == "MIT"
            assert run.verdict == "pass", f"{r['namespace']} did not pass the gate: {run.verdict}"
    finally:
        db.close()


def test_seeding_twice_produces_no_duplicate_versions():
    with _mock_ethics_pass():
        seed_all()
        results_2 = seed_all()

    db = SessionLocal()
    try:
        for r in results_2:
            count = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == r["item_id"]).count()
            assert count == 1, f"{r['namespace']} has {count} versions after re-seeding, expected 1 (idempotent)"
    finally:
        db.close()


def test_seeding_reuses_the_same_item_row_across_runs():
    with _mock_ethics_pass():
        results_1 = seed_all()
        results_2 = seed_all()

    ids_1 = {r["namespace"]: r["item_id"] for r in results_1}
    ids_2 = {r["namespace"]: r["item_id"] for r in results_2}
    assert ids_1 == ids_2


def test_ethics_reviewer_unavailable_during_seeding_never_grants_pass():
    with patch("models.model_router.model_router.generate", return_value="Error: no gateway available"):
        results = seed_all()

    db = SessionLocal()
    try:
        for r in results:
            run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == r["gate_run_id"]).one()
            assert run.verdict == "pending", (
                f"{r['namespace']} was granted verdict={run.verdict!r} while the ethics reviewer "
                "was unavailable -- seeding must never bypass the pending-not-pass rule"
            )
    finally:
        db.close()
