# SPDX-License-Identifier: MIT
# ============================================================
# Gate orchestrator (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3 skeleton;
# stages land in B-8/B-9, M2).
#
# enqueue_gate_run() is real, not a stub — task B-4's backfill job (M1)
# needs to record that a gate run exists for each mirrored item, in report
# mode, even though no stage actually executes until B-8/B-9 land. Until
# then every enqueued run simply sits at verdict='pending' — which is
# exactly the correct, honest state for "not yet reviewed," never an
# implicit pass (see docs/ecosystem/design/LLD/gate.md, and the M0-review
# fix requiring reviewer-unavailable to also resolve to 'pending').
# ============================================================

from __future__ import annotations

from db.database import SessionLocal
from db.models import EcosystemGateRun

_SCANNER_VERSION = "0.0.0-unreleased"  # bumped when B-8/B-9's real stages ship


def enqueue_gate_run(version_id: str, trigger: str) -> str:
    """Create a gate_runs row for version_id and return its id.

    trigger must be one of ecosystem_gate_runs.trigger's CHECK values
    (docs/ecosystem/ECOSYSTEM_PLAN.md §4): 'ui_add' | 'chat_create' | 'cli'
    | 'index_ci' | 'admin_provision' | 'desktop' | 'new_version'.

    No stage runs yet (B-8/B-9 land in M2) — the row is created at
    verdict='pending' and stays there until a later milestone's gate
    orchestrator actually processes it.
    """
    db = SessionLocal()
    try:
        row = EcosystemGateRun(
            version_id=version_id,
            trigger=trigger,
            verdict="pending",
            scanner_version=_SCANNER_VERSION,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def run_gate(version_id: str) -> dict:
    """Stub — filled in by task B-8/B-9 (M2): actually executes the 7
    verification stages against version_id's content."""
    raise NotImplementedError("gate_service.run_gate lands in task B-8/B-9 (M2)")
