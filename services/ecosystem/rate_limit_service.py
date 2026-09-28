# SPDX-License-Identifier: MIT
# ============================================================
# Rate limiting (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-20).
#
# Per-(user_id, action_class) sliding-window counters, action_class in
# {add, install, connect, report}. Reuses the sliding-window-via-Redis-
# sorted-set technique already established in core/rate_limiter.py's
# _check_rate_limit_redis() — same algorithm, cited rather than duplicated
# blindly — but framework-agnostic (no FastAPI Request/HTTPException here,
# per task B-3's "services are framework-agnostic" rule; core/rate_limiter.py
# is itself FastAPI-coupled by design since every one of its call sites is a
# route handler, which none of this service's callers are). The router
# layer (once it exists, task B-6 onward) is responsible for turning a
# RateLimitResult(allowed=False, ...) into the actual 429 + headers.
#
# Uses a dedicated Redis DB (10) — DBs 0-9 are already allocated elsewhere
# in this codebase (see core/rate_limiter.py DB=7, auth/session_manager.py
# DB=7, auth/dependencies.py DB=8, and others), so this claims the next free
# slot rather than colliding.
# ============================================================

from __future__ import annotations

import time
from dataclasses import dataclass

from core.logger import logger

_ECOSYSTEM_REDIS_DB = 10

_ACTION_CLASSES = ("add", "install", "connect", "report")

# Per-action-class (limit, window_seconds). "report" is the tightest since
# an unthrottled report endpoint is itself an abuse vector against other
# users' items (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-20's own test
# calls out "the 4th report call within a window" as the example case).
_LIMITS: dict[str, tuple[int, int]] = {
    "add": (30, 300),
    "install": (60, 300),
    "connect": (20, 300),
    "report": (3, 300),
}

_fallback_counters: dict[str, tuple[int, float]] = {}


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    window_seconds: int
    retry_after: int


def _get_redis():
    try:
        from core.config import redis_client

        rc = redis_client(db=_ECOSYSTEM_REDIS_DB, decode_responses=True)
        rc.ping()
        return rc
    except Exception:
        logger.warning("ecosystem_rate_limit: Redis unavailable, falling back to in-process counter")
        return None


def _check_redis(rc, key: str, limit: int, window_seconds: int) -> int:
    now = time.time()
    pipe = rc.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window_seconds)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 1)
    results = pipe.execute()
    return results[2]


def _check_fallback(key: str, window_seconds: int) -> int:
    now = time.time()
    entry = _fallback_counters.get(key)
    if entry is None or (now - entry[1]) >= window_seconds:
        _fallback_counters[key] = (1, now)
        return 1
    count, start = entry
    count += 1
    _fallback_counters[key] = (count, start)
    return count


def check_rate_limit(user_id: str, action_class: str) -> RateLimitResult:
    """Check (and record) one attempt of action_class by user_id.

    Raises ValueError for an unrecognized action_class — this is a
    programmer error (a typo'd call site), not a runtime condition to
    handle gracefully.
    """
    if action_class not in _ACTION_CLASSES:
        raise ValueError(f"unknown ecosystem rate-limit action_class {action_class!r}")

    limit, window_seconds = _LIMITS[action_class]
    key = f"ecosystem_rl:{action_class}:{user_id}"

    rc = _get_redis()
    count = _check_redis(rc, key, limit, window_seconds) if rc is not None else _check_fallback(key, window_seconds)

    allowed = count <= limit
    remaining = max(limit - count, 0)
    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=remaining,
        window_seconds=window_seconds,
        retry_after=0 if allowed else window_seconds,
    )
