# SPDX-License-Identifier: MIT
# ============================================================
# Drafts service (task B-14, M5) -- backed by the existing AgentStudio
# Skill Factory pipeline via services/ecosystem/skill_factory_adapter.py.
# Never imports anything under AgentStudio/ directly -- only the adapter.
# See docs/ecosystem/design/LLD/create-with-ai.md.
#
# A draft is never itself browsable/installable -- it only becomes a real
# catalog entry on submit() (CONTRACTS.md §10).
# ============================================================

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from db.database import SessionLocal
from db.models import EcosystemDraft
from services.ecosystem import create_service
from services.ecosystem.errors import EcosystemError, NotFoundError
from services.ecosystem.skill_factory_adapter import DraftTurn, SkillFactoryAdapter

_ABANDONED_TTL_DAYS = 30
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-") or "draft"


def create_draft(*, org_id: str, created_by: str, item_type: str = "skill") -> dict[str, Any]:
    """A bare row, `status='drafting'`, `draft_content={}` -- the router's
    SSE handler fills draft_content in as SkillFactoryAdapter's turns
    arrive (see stream_draft_generation())."""
    db = SessionLocal()
    try:
        row = EcosystemDraft(org_id=org_id, created_by=created_by, item_type=item_type)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


async def stream_draft_generation(draft_id: str, intent: str, *, org_id: str) -> AsyncIterator[DraftTurn]:
    """Drives SkillFactoryAdapter.generate(intent), persisting the final
    assembled result onto the draft row as it arrives, yielding every turn
    for the router's own SSE relay. Raises NotFoundError if draft_id
    doesn't belong to this org.
    """
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id, EcosystemDraft.org_id == org_id).first()
        if row is None:
            raise NotFoundError(f"no draft {draft_id!r}")
    finally:
        db.close()

    adapter = SkillFactoryAdapter()
    async for turn in adapter.generate(intent):
        yield turn
        if turn.stage == "assembled" and turn.data:
            assembled = turn.data["assembled"]
            namespace = f"{_slugify(org_id)}/{_slugify(assembled.get('name', 'draft'))}"
            _merge_draft_content(draft_id, {
                "namespace": namespace,
                "display_name": assembled.get("display_name", ""),
                "description": assembled.get("description", ""),
                "category": assembled.get("category", "general"),
                "tags": assembled.get("tags", []),
                "license": "MIT",
                "instructions": assembled.get("content", ""),
                "files": [
                    {"name": f["rel_path"], "content": f.get("content", "")}
                    for f in assembled.get("bundle_files", []) if f.get("content")
                ],
                "quality": assembled.get("quality", {}),
            })
            _set_status(draft_id, "ready")


def _merge_draft_content(draft_id: str, patch: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id).first()
        if row is None:
            return
        row.draft_content = {**(row.draft_content or {}), **patch}
        db.commit()
    finally:
        db.close()


def _set_status(draft_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id).first()
        if row is None:
            return
        row.status = status
        db.commit()
    finally:
        db.close()


def get_draft(draft_id: str, *, org_id: str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id, EcosystemDraft.org_id == org_id).first()
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def patch_draft(draft_id: str, *, org_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """The "preview/edit card": the user edits draft_content directly
    (namespace, display_name, description, category, tags, license,
    instructions, files) -- never a chat reply, matching CONTRACTS.md
    §10's actual endpoint set (no "reply to a clarifying question" route
    exists at all)."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id, EcosystemDraft.org_id == org_id).first()
        if row is None:
            raise NotFoundError(f"no draft {draft_id!r}")
        if row.status in ("submitted", "abandoned"):
            raise EcosystemError(f"draft {draft_id!r} is {row.status} and can no longer be edited")
        row.draft_content = {**(row.draft_content or {}), **patch}
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def submit_draft(draft_id: str, *, org_id: str, created_by: str, caller_permissions: set[str] | None = None) -> dict[str, Any]:
    """Finalize: requires draft_content.license (MIT default); creates the
    real ecosystem_items/ecosystem_item_versions row via create_service
    (the exact same creation path and gate every other creation method
    goes through -- no fast path for a draft), enqueues a gate job, stamps
    ecosystem_drafts.submitted_item_id, sets status='submitted'.
    """
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id, EcosystemDraft.org_id == org_id).first()
        if row is None:
            raise NotFoundError(f"no draft {draft_id!r}")
        if row.status == "submitted":
            raise EcosystemError(f"draft {draft_id!r} was already submitted (item {row.submitted_item_id!r})")
        if row.status == "abandoned":
            raise EcosystemError(f"draft {draft_id!r} is abandoned and can no longer be submitted")
        content = dict(row.draft_content or {})
        item_type = row.item_type
    finally:
        db.close()

    namespace = content.get("namespace")
    if not namespace:
        raise EcosystemError(f"draft {draft_id!r} has no namespace set -- PATCH one before submitting")

    result = create_service.create_via_write(
        org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
        display_name=content.get("display_name", ""), description=content.get("description", ""),
        category=content.get("category", "general"), tags=content.get("tags", []),
        license=content.get("license", "MIT"),
        content={"instructions": content.get("instructions", ""), "files": content.get("files", [])},
        surfaces=content.get("surfaces", ["chat"]),
        caller_permissions=caller_permissions,
    )

    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id).first()
        if row is not None:
            row.status = "submitted"
            row.submitted_item_id = result["item_id"]
            db.commit()
    finally:
        db.close()

    return result


def purge_abandoned_drafts(*, older_than_days: int = _ABANDONED_TTL_DAYS, dry_run: bool = True) -> dict[str, int]:
    """Housekeeping job (CONTRACTS.md §10): purges `abandoned` drafts older
    than the TTL. Not wired into any scheduler in this pass -- a
    maintenance utility for now, matching this codebase's own existing
    precedent (installs_service.cleanup_installs_for_inactive_users()'s
    identical dry-run-by-default convention)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    db = SessionLocal()
    try:
        query = db.query(EcosystemDraft).filter(
            EcosystemDraft.status == "abandoned", EcosystemDraft.updated_at < cutoff,
        )
        rows = query.all()
        candidates = len(rows)
        deleted = 0
        if not dry_run:
            for row in rows:
                db.delete(row)
            db.commit()
            deleted = candidates
        return {"candidates": candidates, "deleted": deleted}
    finally:
        db.close()


def _row_to_dict(row: EcosystemDraft) -> dict[str, Any]:
    return {
        "id": row.id, "org_id": row.org_id, "created_by": row.created_by, "item_type": row.item_type,
        "status": row.status, "draft_content": row.draft_content or {}, "source_engine": row.source_engine,
        "submitted_item_id": row.submitted_item_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
