# SPDX-License-Identifier: MIT
# ============================================================
# Audit write tests (task B-20). Tier-2 — real Postgres.
#
# This covers write_audit_event() itself. The full "every mutating endpoint
# writes an audit row" coverage test described in
# docs/ecosystem/SKILLS_PHASE_PLAN.md task B-20 can only be written once
# those endpoints exist (task B-6 through B-19, milestone M2) — tracked
# there, not silently dropped here.
# ============================================================

from __future__ import annotations

import pytest

from db.database import SessionLocal
from db.models import EcosystemAudit
from services.ecosystem.audit_service import write_audit_event


def test_write_audit_event_inserts_a_row():
    audit_id = write_audit_event(org_id="org-a", actor="user-1", action="install", item_id=None, details={"k": "v"})
    db = SessionLocal()
    try:
        row = db.query(EcosystemAudit).filter(EcosystemAudit.id == audit_id).one()
    finally:
        db.close()
    assert row.org_id == "org-a"
    assert row.actor == "user-1"
    assert row.action == "install"
    assert row.details == {"k": "v"}


def test_write_audit_event_rejects_unknown_action():
    with pytest.raises(ValueError):
        write_audit_event(org_id="org-a", actor="user-1", action="not_a_real_action")


def test_write_audit_event_defaults_details_to_empty_dict():
    audit_id = write_audit_event(org_id="org-a", actor="user-1", action="uninstall")
    db = SessionLocal()
    try:
        row = db.query(EcosystemAudit).filter(EcosystemAudit.id == audit_id).one()
    finally:
        db.close()
    assert row.details == {}
