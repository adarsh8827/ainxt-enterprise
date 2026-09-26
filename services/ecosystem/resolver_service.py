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
from db.models import EcosystemInstall, EcosystemItem

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


def get_effective_capabilities(org_id: str, user_id: str, surface: str) -> list[dict[str, Any]]:
    """Returns exactly the installed+enabled+surface-matching+available-type
    skills for this caller -- CONTRACTS.md §9's Capabilities.skills shape
    (namespace/display_name/description/slash_command), nothing else.
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
            )
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
        })

    if cache is not None:
        try:
            cache.setex(key, _CACHE_TTL_SECONDS, json.dumps(result))
        except Exception:
            pass

    return result
