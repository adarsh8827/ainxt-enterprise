# SPDX-License-Identifier: MIT
# ============================================================
# Audit writes (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-20).
#
# Shared infrastructure only — this module provides write_audit_event();
# each mutating endpoint task (B-6 through B-19, M2) is responsible for
# actually calling it from its own code path. A test that walks every
# mutating endpoint and asserts an audit row exists can only be written
# once those endpoints exist (M2) — tests/services/ecosystem/
# test_audit_service.py in this milestone verifies write_audit_event()
# itself, not endpoint coverage.
# ============================================================

from __future__ import annotations

from typing import Any

from db.database import SessionLocal
from db.models import EcosystemAudit

# Matches ecosystem_audit.action's documented value set (ECOSYSTEM_PLAN.md §4)
_KNOWN_ACTIONS = (
    "install", "uninstall", "enable", "disable", "update", "rollback",
    "deprecate", "delete_draft", "block", "share", "policy_change",
)


def write_audit_event(
    *,
    org_id: str,
    actor: str,
    action: str,
    item_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Insert one ecosystem_audit row. Returns the new row's id.

    Raises ValueError for an action outside the documented set — a
    programmer error at the call site, not a runtime condition.
    """
    if action not in _KNOWN_ACTIONS:
        raise ValueError(f"unknown ecosystem audit action {action!r}, expected one of {_KNOWN_ACTIONS}")

    db = SessionLocal()
    try:
        row = EcosystemAudit(
            org_id=org_id,
            actor=actor,
            action=action,
            item_id=item_id,
            details=details or {},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()
