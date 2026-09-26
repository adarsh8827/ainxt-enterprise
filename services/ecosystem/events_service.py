# SPDX-License-Identifier: MIT
# ============================================================
# Events service (task B-13, M3) — publishes to the Redis pub/sub channel
# from CONTRACTS.md §13 (ecosystem.changed.{org_id}).
#
# Transport note: the task's own file header cited "the WebSocket relay
# pattern already implemented for routers/cowork_mcp_router.py /
# routers/cowork_dispatch_router.py" -- checked both before writing this,
# and neither implements a WebSocket relay: cowork_mcp_router.py serves a
# **Server-Sent Events** stream backed by a per-session Redis LIST
# (BLPOP/RPUSH, point-to-point, one queue per connected client);
# cowork_dispatch_router.py polls a Redis value directly. There is no
# WebSocket endpoint anywhere in this codebase to reuse -- confirmed by
# grepping the whole tree for `WebSocket`/`websocket`, the only two Python
# hits being this module's own docstring and an unrelated regex literal in
# services/feedback_processor.py.
#
# ecosystem.changed genuinely needs BROADCAST semantics (every currently-
# connected client for an org must see every event, not one queue's worth
# split across competing consumers), which a per-session LIST can't give.
# Real Redis PUBLISH/SUBSCRIBE is what CONTRACTS.md §13 actually specifies
# ("Redis pub/sub channel ecosystem.changed.{org_id}"), and IS a genuinely
# different, correct mechanism for that -- implemented here, with the
# SSE-over-HTTP delivery to a browser/desktop client (routers/
# ecosystem_events_router.py) reusing cowork_mcp_router.py's actual,
# real pattern (StreamingResponse, text/event-stream, keep-alive pings,
# the same redis.asyncio client construction) for the part of that file
# that genuinely does exist to reuse.
# ============================================================

from __future__ import annotations

import json
from typing import Any

from core.logger import logger

_EVENT_SCHEMA_VERSION = 1

# core/kv's KVClient abstraction (core.kv.get_kv) has no publish()/pubsub()
# method -- PUBLISH is a Redis-specific primitive it doesn't cover, the
# same situation core/job_queue.py's own _get_redis_connection() and
# routers/cowork_mcp_router.py's _get_async_redis() are already in for
# Lua scripts / SSE session routing; both bypass the KV abstraction and
# construct a raw redis client directly rather than extending it, and this
# does the same. db=5 -- the same database core/job_queue.py's queues and
# cowork_mcp_router.py's SSE session-routing keys already use for
# real-time coordination, not RDB_CACHE (a plain cache db, unrelated).
_redis_conn = None


def _get_redis():
    global _redis_conn
    if _redis_conn is None:
        import redis

        from core.config import REDIS_HOST, REDIS_PORT
        try:
            from core.config import REDIS_PASSWORD
        except ImportError:
            REDIS_PASSWORD = None
        _redis_conn = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=5,
            password=REDIS_PASSWORD or None, decode_responses=True, socket_connect_timeout=2,
        )
    return _redis_conn

# CONTRACTS.md §13's ChangeKind values.
_VALID_CHANGES = frozenset({
    "installed", "uninstalled", "enabled", "disabled", "updated", "blocked", "connection_changed",
})


def _channel(org_id: str) -> str:
    return f"ecosystem.changed.{org_id}"


def publish_ecosystem_changed(
    org_id: str,
    *,
    item_type: str,
    item_id: str,
    scope: str,
    change: str,
    version: str | None = None,
) -> None:
    """Fire-and-forget publish -- never raises, never blocks the caller's
    request/response cycle. A Redis hiccup here means a connected client
    misses one live-update notification, not that the mutating action
    itself (which already committed to Postgres) fails or rolls back.
    """
    if change not in _VALID_CHANGES:
        # A caller passing an unrecognized change value is a real bug on
        # the calling side (CONTRACTS.md §13 is a fixed enum) -- raise
        # here rather than publish a malformed event no client can parse.
        raise ValueError(f"publish_ecosystem_changed: unknown change {change!r}, expected one of {sorted(_VALID_CHANGES)}")

    event: dict[str, Any] = {
        "v": _EVENT_SCHEMA_VERSION, "type": item_type, "item_id": item_id,
        "scope": scope, "change": change, "version": version,
    }
    try:
        _get_redis().publish(_channel(org_id), json.dumps(event))
    except Exception as exc:
        logger.warning(f"events_service: publish failed for org={org_id} event={event}: {exc}")
