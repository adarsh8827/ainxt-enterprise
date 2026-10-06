# SPDX-License-Identifier: MIT
# ============================================================
# Resolver service (task B-11, M3): get_effective_capabilities().
#
# "Merges task B-4's legacy bridge with native ecosystem_installs rows" —
# in practice this needs no separate legacy_bridge.py query at all:
# scripts/ecosystem/backfill_legacy_items.py (B-4) upserts a real
# ecosystem_items row per legacy skill and enqueues a gate run, but never
# calls installs_service.install() for it (its trigger is
# "admin_provision", not one of gate_service.py's own _AUTO_INSTALL_TRIGGERS
# = ("ui_add", "chat_create")) -- a backfilled item only becomes an
# effective capability once something actually installs it, exactly like
# any other item. So this resolver is a single, uniform query over
# ecosystem_installs join ecosystem_items -- no special-casing for
# legacy-sourced rows, and no separate merge step. This matches the task's
# own definition of done precisely: "installed+enabled+surface-matching+
# available-type skills for that caller, and nothing else."
# ============================================================

from __future__ import annotations

import hashlib
import json
from typing import Any

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion

_CACHE_TTL_SECONDS = 60
_ITEM_TYPE_FLAGS = {
    "skill": "ECOSYSTEM_TYPE_SKILL",
    "plugin": "ECOSYSTEM_TYPE_PLUGIN",
    "mcp_server": "ECOSYSTEM_TYPE_MCP",
    "connector": "ECOSYSTEM_TYPE_CONNECTOR",
}


def _available_item_types() -> frozenset[str]:
    import core.config as _cfg

    return frozenset(
        item_type for item_type, flag_name in _ITEM_TYPE_FLAGS.items()
        if getattr(_cfg, flag_name, False)
    )


def _cache_key(org_id: str, user_id: str, surface: str) -> str:
    digest = hashlib.sha256(f"{org_id}:{user_id}:{surface}".encode("utf-8")).hexdigest()
    return f"ecosystem:capabilities:{digest}"


def _get_cache():
    """Best-effort Redis cache -- returns None on any failure so a cache
    outage degrades to "always resolve fresh," never a hard error."""
    try:
        from core.config import RDB_CACHE
        from core.kv import get_kv

        return get_kv(RDB_CACHE, decode_responses=True)
    except Exception:
        return None


def invalidate_capabilities_cache(org_id: str, user_id: str | None = None) -> None:
    """Called directly by every mutating install-lifecycle action
    (installs_service.py's _publish_change(), alongside the
    ecosystem.changed publish) rather than relying on a separate
    subscriber process to react to that event asynchronously -- this
    guarantees "no stale-cache window beyond the explicit invalidation"
    even if nothing is currently listening on the pub/sub channel.
    user_id=None invalidates every surface for every user in the org that
    happens to be cached is not attempted (no reverse index exists, and
    isn't needed: org-wide provisioning actions are rare enough that a
    60s TTL naturally bounds the staleness window for those).
    """
    if user_id is None:
        return
    cache = _get_cache()
    if cache is None:
        return
    try:
        for surface in ("chat", "agent_studio", "cowork", "desktop", "workspace_chat"):
            cache.delete(_cache_key(org_id, user_id, surface))
    except Exception:
        pass


def _source_label(item: EcosystemItem) -> str:
    """Info-popover fix (2026-09-29): a human-readable "where did this
    come from" string, derived entirely from columns already on the same
    `EcosystemItem` row this query already selects -- no extra join/fetch.
    `catalog_pointer` is only ever set for items synced in from an external
    source (services/ecosystem/catalog_sync.py); everything else (Write/
    Upload/Import/Create-with-AI) was authored directly in this workspace.
    """
    pointer = item.catalog_pointer if isinstance(item.catalog_pointer, dict) else None
    if pointer:
        return pointer.get("source_url") or pointer.get("source_kind") or "External source"
    return "Created in this workspace"


def get_effective_capabilities(org_id: str, user_id: str, surface: str) -> list[dict[str, Any]]:
    """Returns the installed+enabled+surface-matching+available-type skills
    for this caller -- CONTRACTS.md §9's Capabilities.skills shape
    (namespace/display_name/description/slash_command), plus `license`/
    `source` (info-popover fix, 2026-09-29: both are plain columns already
    on the same `EcosystemItem` row this query selects, so the chat UI's
    "ⓘ" popover never needs a second fetch). render_skill_index() only ever
    reads display_name/slash_command/description from this shape, so the
    two added fields never reach the model prompt.
    """
    cache = _get_cache()
    key = _cache_key(org_id, user_id, surface)
    if cache is not None:
        try:
            cached = cache.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass

    available_types = _available_item_types()
    if "skill" not in available_types:
        return []

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemInstall, EcosystemItem)
            .join(EcosystemItem, EcosystemInstall.item_id == EcosystemItem.id)
            # Real bug found live (2026-10-06, user report: "I can use it in
            # chat via slash command, but it shows Blocked -- confusing"):
            # this query only ever checked install.enabled + item.status --
            # never whether the SPECIFIC version this install is actually
            # pinned to (install.version_id) passed its own gate. The
            # "Blocked" badge the UI shows is driven by a completely
            # different signal (item.latest_verdict, the NEWEST version's
            # own verdict -- see Yours.jsx) with zero connection to this
            # query, so a failed version could show "Blocked" in Yours
            # while still being fully usable in chat. Joining on the
            # install's own version and requiring its gate_verdict to be
            # pass/warn closes that gap: chat now reflects the real,
            # specific verdict of what's actually installed, not a
            # loosely-related item-level status flag.
            .join(EcosystemItemVersion, EcosystemInstall.version_id == EcosystemItemVersion.id)
            .filter(
                EcosystemInstall.org_id == org_id,
                EcosystemInstall.installed_for == user_id,
                EcosystemInstall.enabled.is_(True),
                EcosystemItem.status == "active",
                EcosystemItemVersion.gate_verdict.in_(("pass", "warn")),
                # Explicit type filter (2026-09-29, Connectors/Plugins phase):
                # this function's return shape (slash_command etc.) is
                # skill-specific -- connector/mcp_server/plugin capabilities
                # get their own dedicated functions below, each with their
                # own shape, rather than being silently mixed into this list
                # the moment ECOSYSTEM_TYPE_CONNECTOR/_MCP/_PLUGIN flip on.
                EcosystemItem.item_type == "skill",
            )
            # Chat-skills task, 2026-09-28: deterministic order, not
            # whatever physical/insertion order Postgres happens to
            # return -- mcp/ecosystem_skill_tools.py's render_skill_index()
            # renders this list verbatim into the chat prompt, so an
            # unstable order changes that text byte-for-byte between
            # requests even when the installed skill SET hasn't changed,
            # busting prompt-cache reuse on the prefix that contains it.
            .order_by(EcosystemItem.namespace)
            .all()
        )
    finally:
        db.close()

    result = []
    for install, item in rows:
        if item.item_type not in available_types:
            continue
        if surface not in (install.surfaces or []):
            continue
        publisher_slug, _, name_slug = item.namespace.partition("/")
        result.append({
            "namespace": item.namespace,
            "display_name": item.display_name,
            "description": item.description,
            "slash_command": f"/{name_slug or item.namespace}",
            "license": item.license,
            "source": _source_label(item),
        })

    if cache is not None:
        try:
            cache.setex(key, _CACHE_TTL_SECONDS, json.dumps(result))
        except Exception:
            pass

    return result


def _get_installed_items_by_type(org_id: str, user_id: str, surface: str, item_type: str) -> list[tuple]:
    """Shared query for connector/mcp_tool capabilities below -- same
    installed+enabled+surface-matching+active filter as
    get_effective_capabilities(), parameterised on item_type instead of
    hardcoding 'skill'. Returns (install, item, latest_version.manifest)
    tuples; manifest is {} when the item has no version row yet."""
    from db.models import EcosystemItemVersion

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemInstall, EcosystemItem)
            .join(EcosystemItem, EcosystemInstall.item_id == EcosystemItem.id)
            .filter(
                EcosystemInstall.org_id == org_id,
                EcosystemInstall.installed_for == user_id,
                EcosystemInstall.enabled.is_(True),
                EcosystemItem.status == "active",
                EcosystemItem.item_type == item_type,
            )
            .order_by(EcosystemItem.namespace)
            .all()
        )
        out = []
        for install, item in rows:
            if surface not in (install.surfaces or []):
                continue
            version = (
                db.query(EcosystemItemVersion)
                .filter(EcosystemItemVersion.id == install.version_id)
                .first()
            )
            # Same fix as get_effective_capabilities() above: a connector/
            # mcp_tool capability must also reflect its own installed
            # version's real gate verdict, not just the item's status.
            if version is None or version.gate_verdict not in ("pass", "warn"):
                continue
            out.append((install, item, (version.manifest if version else {}) or {}))
        return out
    finally:
        db.close()


def get_effective_connector_capabilities(org_id: str, user_id: str, surface: str) -> list[dict[str, Any]]:
    """CONTRACTS.md §9 Capabilities.connectors[] -- one entry per installed+
    enabled+surface-matching connector, each carrying its own tool list
    classified via mcp.tool_annotations.classify_tool() (manifest["tools"],
    the same shape gate stage 7 already validates). No caching yet (unlike
    skills above) -- connection_status is read-through/live by design
    (credential_broker_service.get_connection_status()), so a cached
    Capabilities entry could show a stale status; revisit once a real
    perf need shows up rather than pre-optimising this."""
    if "connector" not in _available_item_types():
        return []

    from mcp.tool_annotations import classify_tool
    from services.ecosystem.credential_broker_service import get_connection_status

    result = []
    for install, item, manifest in _get_installed_items_by_type(org_id, user_id, surface, "connector"):
        tools = manifest.get("tools") if isinstance(manifest.get("tools"), list) else []
        status = get_connection_status(org_id, user_id, item.namespace)
        result.append({
            "connector_ref": item.namespace,
            "display_name": item.display_name,
            "description": item.description,
            "connection_status": status.status,
            "tools": [
                {"name": (t.get("name") if isinstance(t, dict) else str(t)), "classification": classify_tool(t if isinstance(t, dict) else {}).classification}
                for t in tools
            ],
        })
    return result


def get_effective_mcp_tool_capabilities(org_id: str, user_id: str, surface: str) -> list[dict[str, Any]]:
    """CONTRACTS.md §9 Capabilities.mcp_tools[] -- flattened individual
    tools (not grouped by server) from every installed+enabled+surface-
    matching mcp_server item, each tagged with its own read/write/
    destructive classification."""
    if "mcp_server" not in _available_item_types():
        return []

    from mcp.tool_annotations import classify_tool

    result = []
    for install, item, manifest in _get_installed_items_by_type(org_id, user_id, surface, "mcp_server"):
        tools = manifest.get("tools") if isinstance(manifest.get("tools"), list) else []
        for tool_def in tools:
            tool_def = tool_def if isinstance(tool_def, dict) else {"name": str(tool_def)}
            annotation = classify_tool(tool_def)
            result.append({
                "server_ref": item.namespace,
                "name": annotation.tool_name,
                "classification": annotation.classification,
                "description": tool_def.get("description", ""),
            })
    return result
