# SPDX-License-Identifier: MIT
# ============================================================
# TOOL-CALL APPROVAL SERVICE
# docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 3 / standing rule
# "server-side enforcement" -- a read tool never needs a client-side
# gate to be safe; write/destructive tools are enforced HERE, not by
# whatever chat UI happens to render an approval card. A client that
# skips the card and calls the tool anyway still hits this same check.
#
# Every outcome (read passthrough, auto-approved, approved, denied) gets
# a real audit_service.write_audit_event() row -- never optional, per
# the same standing rule. Only a hash of params is ever audited, never
# the raw values (which may carry connector-call arguments a caller
# doesn't want in a durable audit log verbatim).
# ============================================================

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from mcp.tool_annotations import classify_tool
from services.ecosystem import audit_service


class ToolApprovalError(Exception):
    """Real failure (not found / wrong state) -- never used for a plain
    'this tool requires approval' outcome, which is a normal return value."""


def _params_hash(params: dict[str, Any]) -> str:
    encoded = json.dumps(params or {}, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_auto_approved(org_id: str, tool_name: str) -> bool:
    from db.database import SessionLocal
    from db.models import EcosystemToolAutoApprovePolicy

    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemToolAutoApprovePolicy)
            .filter(
                EcosystemToolAutoApprovePolicy.org_id == org_id,
                EcosystemToolAutoApprovePolicy.tool_name == tool_name,
            )
            .first()
        )
        return row is not None
    finally:
        db.close()


def request_tool_call(
    *,
    org_id: str,
    user_id: str,
    tool_name: str,
    tool_def: dict[str, Any],
    params: Optional[dict[str, Any]] = None,
    target: Optional[str] = None,
) -> dict[str, Any]:
    """Classify *tool_name* and either allow it immediately or create a
    pending approval row. Always audits.

    Returns one of:
      {"requires_approval": False, "status": "read_allowed"}
      {"requires_approval": False, "status": "auto_approved"}
      {"requires_approval": True,  "status": "pending", "approval_id": str}
    """
    annotation = classify_tool(tool_def)
    params_hash = _params_hash(params or {})

    if annotation.classification == "read":
        audit_service.write_audit_event(
            org_id=org_id, actor=user_id, action="tool_call_readonly",
            details={"tool_name": tool_name, "classification": "read", "params_hash": params_hash, "target": target},
        )
        return {"requires_approval": False, "status": "read_allowed"}

    if _is_auto_approved(org_id, tool_name):
        audit_service.write_audit_event(
            org_id=org_id, actor=user_id, action="tool_call_auto_approved",
            details={"tool_name": tool_name, "classification": annotation.classification, "params_hash": params_hash, "target": target},
        )
        return {"requires_approval": False, "status": "auto_approved"}

    from db.database import SessionLocal
    from db.models import EcosystemToolApproval

    db = SessionLocal()
    try:
        row = EcosystemToolApproval(
            id=str(uuid.uuid4()), org_id=org_id, user_id=user_id, tool_name=tool_name,
            classification=annotation.classification, params_json=params or {}, target=target,
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        approval_id = str(row.id)
    finally:
        db.close()

    audit_service.write_audit_event(
        org_id=org_id, actor=user_id, action="tool_call_pending",
        details={"tool_name": tool_name, "classification": annotation.classification, "params_hash": params_hash, "target": target, "approval_id": approval_id},
    )
    return {"requires_approval": True, "status": "pending", "approval_id": approval_id}


def list_pending(org_id: str, user_id: str) -> list[dict[str, Any]]:
    from db.database import SessionLocal
    from db.models import EcosystemToolApproval

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemToolApproval)
            .filter(
                EcosystemToolApproval.org_id == org_id,
                EcosystemToolApproval.user_id == user_id,
                EcosystemToolApproval.status == "pending",
            )
            .order_by(EcosystemToolApproval.created_at.desc())
            .all()
        )
        return [
            {
                "id": str(r.id), "tool_name": r.tool_name, "classification": r.classification,
                "params": r.params_json, "target": r.target,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def _resolve(org_id: str, user_id: str, approval_id: str, new_status: str, action: str) -> dict[str, Any]:
    from db.database import SessionLocal
    from db.models import EcosystemToolApproval

    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemToolApproval)
            .filter(
                EcosystemToolApproval.id == approval_id,
                EcosystemToolApproval.org_id == org_id,
                EcosystemToolApproval.user_id == user_id,
            )
            .first()
        )
        if not row:
            raise ToolApprovalError(f"approval {approval_id!r} not found for this caller")
        if row.status != "pending":
            raise ToolApprovalError(f"approval {approval_id!r} is already {row.status!r}")
        row.status = new_status
        row.resolved_at = datetime.utcnow()
        db.commit()
        tool_name, classification, params_hash = row.tool_name, row.classification, _params_hash(row.params_json)
    finally:
        db.close()

    audit_service.write_audit_event(
        org_id=org_id, actor=user_id, action=action,
        details={"tool_name": tool_name, "classification": classification, "params_hash": params_hash, "approval_id": approval_id},
    )
    return {"status": new_status}


def approve(org_id: str, user_id: str, approval_id: str) -> dict[str, Any]:
    return _resolve(org_id, user_id, approval_id, "approved", "tool_call_approved")


def deny(org_id: str, user_id: str, approval_id: str) -> dict[str, Any]:
    return _resolve(org_id, user_id, approval_id, "denied", "tool_call_denied")
