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

from sqlalchemy import text

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


class LegacyCoworkRoleItem(TypedDict):
    legacy_ref: str
    name: str
    description: str
    category: str


def list_published_cowork_roles() -> list[LegacyCoworkRoleItem]:
    """Every published/approved (org-wide) Cowork role -- read-only, never
    writes to the cowork_roles table.

    Deliberately does NOT call services/cowork_roles.py's own
    list_published_roles()/list_marketplace() -- found, while building this
    bridge, that both query `WHERE status = 'PUBLISHED'`, but nothing in
    that module ever writes that value: publish_role()/set_governance_status()
    (the ONLY real write paths) and CoworkRole.to_dict()'s own "published"
    key all consistently use status == 'APPROVED' (verified live: created +
    published a real role, then confirmed list_published_roles() returned an
    empty list for it while to_dict()['published'] was correctly True). This
    looks like a real, pre-existing bug in cowork_roles.py's own two read
    functions (the dataclass field's inline comment says "DRAFT" |
    "PUBLISHED" but every other real usage in the file says otherwise) --
    flagging it rather than fixing it (out of scope: "do not touch
    cowork_roles.py's own table/API" for this task) or silently working
    around it by querying 'PUBLISHED' anyway, which would make this bridge
    structurally unable to ever surface a real role. Instead: list_all_roles()
    (a real, correct, unfiltered listing) + the same status==APPROVED-and-
    visibility==public check to_dict() itself uses (there is no real
    is_published property, only that inline dict key).

    Returns [] (rather than raising) if services.cowork_roles can't be
    imported or its DB isn't reachable -- same "not configured is a valid
    state" convention as list_agentstudio_skills() above.
    """
    try:
        from services import cowork_roles
    except Exception:
        return []

    try:
        roles = cowork_roles.list_all_roles()
    except Exception:
        return []

    def _is_published(role) -> bool:
        # Same expression CoworkRole.to_dict() itself uses for its own
        # "published" key -- there is no real is_published property (only
        # a dict key computed inline), verified by reading to_dict() directly.
        return (role.status or "DRAFT") == "APPROVED" and (role.visibility or "") == "public"

    return [
        LegacyCoworkRoleItem(
            legacy_ref=role.id or role.name,
            name=role.name,
            description=role.description or "",
            # role.department is an org unit, not a taxonomy category (see
            # services/ecosystem/config_service.py's TAXONOMY_CATEGORIES) --
            # upsert_legacy_pointer_item() doesn't validate this field
            # (matching the pre-existing skills_pg/agentstudio backfills'
            # own unchecked "general" default), so an arbitrary department
            # string would silently land in a category no category filter
            # ever matches -- the exact "operations" bug class fixed
            # earlier this session for the crawler, avoided here by not
            # repeating it: always "general", never role.department.
            category="general",
        )
        for role in roles
        if role.id and _is_published(role)
    ]


class LegacyConnectorItem(TypedDict):
    legacy_ref: str
    name: str
    display_name: str
    category: str
    description: str
    icon_url: str | None
    is_builtin: bool


# connector_definitions.category values are a genuinely different,
# narrower vocabulary than TAXONOMY_CATEGORIES (confirmed live: real rows
# use "devtools"/"dpi", neither of which is a valid taxonomy category --
# "devtools" is close but not the real "dev-tools" spelling, and "dpi"
# (India's Account Aggregator / DigiLocker identity-and-finance rails)
# has no taxonomy equivalent at all). Passing either through unmapped
# would repeat the exact "operations" bug class fixed earlier this
# session for the crawler -- a category no category filter ever matches.
_CONNECTOR_CATEGORY_MAP = {
    "productivity": "productivity",
    "devtools": "dev-tools",
    "communication": "communication",
    "dpi": "general",
}


# Real duplicate found live (user report): "jira" (oauth2, 4 tools) and
# "jira_connector" (pat, 13 tools) are two genuinely separate NATIVE rows
# for the same real app -- not a native-vs-catalog duplicate (both already
# live in connector_definitions). Rather than a single hardcoded "jira"
# special-case (fragile -- the next duplicate pair would silently repeat
# this), dedupe generically by normalized display_name, keeping whichever
# row has MORE declared tools (treated as "more complete"/capable) --
# jira_connector (13 tools) wins over jira (4 tools) under this rule.
# Disclosed as a judgment call, not a definitive product decision: if the
# OAuth2-based "jira" row's simpler default is actually preferred, this
# rule picks the wrong one and needs a real preference field instead.
def _dedupe_by_display_name(rows: list[tuple]) -> list[tuple]:
    best: dict[str, tuple] = {}
    for row in rows:
        _name, display_name, _category, _description, _icon_url, _is_builtin, tool_count = row
        key = (display_name or _name).strip().lower()
        existing = best.get(key)
        if existing is None or tool_count > existing[6]:
            best[key] = row
    return sorted(best.values(), key=lambda r: r[0])


_DISPLAY_NAME_OVERRIDES = {
    # Reworded to lead with the real, recognizable brand name -- "DPI
    # Account Aggregator"/"DPI DigiLocker" -- per the user's own explicit
    # preferred wording. The underlying display_name column already held a
    # real name (not a raw id) either way, just in a different order.
    "Account Aggregator (DPI)": "DPI Account Aggregator",
    "DigiLocker (DPI)": "DPI DigiLocker",
}


def list_native_connector_definitions() -> list[LegacyConnectorItem]:
    """Every active row in connectors/registry.py's own backing table
    (ainxt.connector_definitions) -- read-only, never writes there, and
    never goes through ConnectorRegistry's own in-memory (private,
    unbootstrapped-at-import-time) _definitions list. Same real table
    connectors/registry.py._load_definitions() itself queries.
    Deduplicated by display_name -- see _dedupe_by_display_name().

    Real gap found and fixed (2026-09-30): this function originally threw
    away connector_definitions' own real `description`/`icon_url`/
    `is_builtin` columns in favor of a generic "Native <name> connector."
    template and no icon at all -- every real row already has a genuine,
    human-written description (e.g. "Connect to Slack — search messages,
    list channels, read conversations.") and a same-origin icon path
    (e.g. "/icons/slack.svg", already served by this app, never an
    external hotlink) that were simply never read."""
    db = SessionLocal()
    try:
        raw_rows = db.execute(
            text(
                "SELECT name, display_name, category, description, icon_url, is_builtin, "
                "jsonb_array_length(coalesce(tools, '[]'::jsonb)) "
                "FROM ainxt.connector_definitions WHERE is_active = TRUE ORDER BY name"
            )
        ).fetchall()
        rows = _dedupe_by_display_name([tuple(r) for r in raw_rows])
        return [
            LegacyConnectorItem(
                legacy_ref=row[0],
                name=row[0],
                display_name=_DISPLAY_NAME_OVERRIDES.get(row[1] or row[0], row[1] or row[0]),
                category=_CONNECTOR_CATEGORY_MAP.get(row[2] or "", "general"),
                description=row[3] or f"Connect to {row[1] or row[0]}.",
                icon_url=row[4],
                is_builtin=bool(row[5]),
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
