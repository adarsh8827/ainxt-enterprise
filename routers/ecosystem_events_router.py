# SPDX-License-Identifier: MIT
# ============================================================
# ecosystem.changed SSE relay (task B-13, M3) — CONTRACTS.md §13's
# transport, "Redis pub/sub channel ecosystem.changed.{org_id} ->
# WebSocket relay". No WebSocket endpoint exists anywhere in this
# codebase to reuse (see services/ecosystem/events_service.py's own
# header for the full account) -- this reuses routers/cowork_mcp_router
# .py's real, existing SSE pattern instead (StreamingResponse,
# text/event-stream, keep-alive pings, the same redis.asyncio client
# construction), backed by genuine Redis PUBLISH/SUBSCRIBE (broadcast to
# every connected client for the org) rather than that file's own
# per-session LIST (point-to-point, one queue per client — the wrong
# primitive for a broadcast event).
#
# A separate, small router file (not folded into ecosystem_router.py) —
# same reasoning as mcp/ecosystem_skill_tools.py's own separation:
# independently reviewable/removable, and this one is the only ecosystem
# endpoint that's async/streaming rather than a plain request/response
# handler.
# ============================================================

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from auth.dependencies import get_current_user
from core.config import REDIS_HOST, REDIS_PORT
from core.logger import logger

try:
    from core.config import REDIS_PASSWORD as _REDIS_PASSWORD
except ImportError:
    _REDIS_PASSWORD = None

router = APIRouter(tags=["ecosystem"])

_async_redis = None
_redis_unavailable = False


def _get_async_redis():
    global _async_redis, _redis_unavailable
    if _async_redis is not None or _redis_unavailable:
        return _async_redis
    try:
        import redis.asyncio as aioredis
        _async_redis = aioredis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=5,
            password=_REDIS_PASSWORD or None,
            decode_responses=True, socket_connect_timeout=2,
            health_check_interval=30,
        )
    except Exception as exc:
        logger.warning(f"ecosystem_events: redis.asyncio unavailable ({exc}) — SSE relay disabled")
        _redis_unavailable = True
        _async_redis = None
    return _async_redis


@router.get("/ecosystem/events/stream")
async def ecosystem_events_stream(request: Request, current_user: dict = Depends(get_current_user)):
    """SSE stream of ecosystem.changed events for the caller's own org.
    No in-process fallback (unlike cowork_mcp_router.py's dev-mode
    single-worker queue) — without Redis, there is genuinely nothing to
    subscribe to, so the stream stays open emitting only keep-alives.
    """
    org_id = current_user.get("org_id") or "default"
    channel = f"ecosystem.changed.{org_id}"
    r = _get_async_redis()

    async def gen():
        pubsub = None
        try:
            if r is not None:
                pubsub = r.pubsub()
                await pubsub.subscribe(channel)
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                if pubsub is not None:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                    if message is not None:
                        yield f"data: {message['data']}\n\n"
                        continue
                else:
                    await asyncio.sleep(15)
                yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception:
                    pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
