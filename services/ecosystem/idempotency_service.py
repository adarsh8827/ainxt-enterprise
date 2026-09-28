# SPDX-License-Identifier: MIT
# ============================================================
# Idempotency-Key storage (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-20).
#
# Redis-backed (caller, Idempotency-Key) -> response cache, 24h TTL, per
# docs/ecosystem/CONTRACTS.md §4. A retried POST with the same key returns
# the original response (e.g. the original job_id) rather than starting a
# second job. Same dedicated Redis DB as rate_limit_service.py (10) — a
# distinct key prefix keeps the two namespaces from colliding within it.
# ============================================================

from __future__ import annotations

import json

from core.logger import logger

_ECOSYSTEM_REDIS_DB = 10
_DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _get_redis():
    try:
        from core.config import redis_client

        rc = redis_client(db=_ECOSYSTEM_REDIS_DB, decode_responses=True)
        rc.ping()
        return rc
    except Exception:
        logger.warning("ecosystem_idempotency: Redis unavailable — idempotency cache disabled this request")
        return None


def _key(caller: str, idempotency_key: str) -> str:
    return f"ecosystem_idem:{caller}:{idempotency_key}"


def get_cached_response(caller: str, idempotency_key: str) -> dict | None:
    """Return the previously-cached response for (caller, idempotency_key),
    or None if there isn't one (first attempt, or the cache expired)."""
    rc = _get_redis()
    if rc is None:
        return None
    raw = rc.get(_key(caller, idempotency_key))
    return json.loads(raw) if raw else None


def store_response(caller: str, idempotency_key: str, response: dict, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
    """Cache response under (caller, idempotency_key) for ttl_seconds."""
    rc = _get_redis()
    if rc is None:
        return
    rc.set(_key(caller, idempotency_key), json.dumps(response), ex=ttl_seconds)
