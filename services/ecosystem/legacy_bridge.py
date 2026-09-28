# SPDX-License-Identifier: MIT
# ============================================================
# Legacy bridge — READ-ONLY (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-4).
#
# Reads only from skills_pg/SkillRecord (behavioral-type only, per
# docs/ecosystem/ECOSYSTEM_PLAN.md §15 decision 1 — execution-type rows are
# never surfaced) and AgentStudio's skills_catalog (via its own
# workflow_repo.list_skills(), never a direct query against its tables).
# Never writes to either legacy table. scripts/ecosystem/
# backfill_legacy_items.py is the only writer, and it writes exclusively to
# the new ecosystem_* tables.
# ============================================================

from __future__ import annotations

import re
from typing import Any, TypedDict

from db.database import SessionLocal
from db.models import SkillRecord

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(value: str) -> str:
    """Best-effort conversion of an arbitrary name/org_id into a segment
    that satisfies publishers_service._SLUG_RE. Collapses anything not
    alnum/hyphen/underscore to a single hyphen, lowercases, and pads short
    results (the slug regex requires at least 2 characters)."""
    s = _SLUG_INVALID_RE.sub("-", (value or "").strip().lower()).strip("-")
    if not s:
        s = "item"
    if len(s) < 2:
        s = f"{s}-x"
    return s[:64]


class LegacySkillPgItem(TypedDict):
    legacy_ref: str
    org_id: str
    name: str
    description: str


def list_behavioral_skills_pg_items() -> list[LegacySkillPgItem]:
    """Every skills_pg row eligible for the bridge: skill_type='behavioral'
    only (execution-type rows have no confirmed live execution path and are
    explicitly excluded, ECOSYSTEM_PLAN.md §15 decision 1)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(SkillRecord)
            .filter(SkillRecord.skill_type == "behavioral")
            .all()
        )
        return [
            LegacySkillPgItem(
                legacy_ref=row.id,
                org_id=row.org_id or "default",
                name=row.name,
                description=row.description or "",
            )
            for row in rows
        ]
    finally:
        db.close()


class LegacyAgentStudioItem(TypedDict):
    legacy_ref: str
    name: str
    description: str
    category: str
    content: str


async def list_agentstudio_skills() -> list[LegacyAgentStudioItem]:
    """Every AgentStudio skills_catalog row, via its own public API
    (workflow_repo.list_skills()) — never a direct query against
    AgentStudio's tables. AgentStudio's skills_catalog has no org_id column
    (it's a single shared catalog, not multi-tenant); every item from this
    source is attributed to org_id='default', the platform's existing
    single-org-deployment sentinel (ECOSYSTEM_PLAN.md §4), not a per-org
    value this source simply doesn't have.

    Returns [] (rather than raising) if AgentStudio's module can't be
    imported or its DB isn't reachable — a deployment without AgentStudio
    configured is a valid, expected state, not a backfill-job failure.

    Import note (found while testing task B-6/B-22's own AgentStudio
    interop): AgentStudio/backend's modules use bare top-level imports
    (workflow_repo.py itself does `from app.core.config import
    postgres_enabled`) that only resolve once AgentStudio/backend is on
    sys.path — the dotted path `AgentStudio.backend.app.core.workflow_repo`
    always raised ModuleNotFoundError on that internal import, in every
    environment, regardless of whether AgentStudio was genuinely configured
    or not, silently masking real availability behind the same "not
    available" fallback below. Fixed by reusing the same sys.path helper
    task B-6/B-22 needed for the same underlying reason
    (services/ecosystem/_agentstudio_interop.py), then importing via the
    resolvable `app.core.workflow_repo` route — the same one gateway.py's
    own AgentStudio mount uses (`gateway.py:1284-1291`).
    """
    try:
        from services.ecosystem._agentstudio_interop import ensure_agentstudio_backend_on_path

        ensure_agentstudio_backend_on_path()
        from app.core import workflow_repo
    except Exception:
        return []

    try:
        skills = await workflow_repo.list_skills()
    except Exception:
        return []

    return [
        LegacyAgentStudioItem(
            legacy_ref=skill["name"],
            name=skill["name"],
            description=skill.get("description", ""),
            category=skill.get("category", "general"),
            content=skill.get("content", ""),
        )
        for skill in skills
    ]
