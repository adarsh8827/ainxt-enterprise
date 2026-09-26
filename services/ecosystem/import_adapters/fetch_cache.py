# SPDX-License-Identifier: MIT
# ============================================================
# Content-by-hash fetch cache for external import adapters (task I,
# pre-M3) — "repeat imports don't refetch." Distinct from
# ecosystem_item_versions.content_hash's own idempotency (which dedupes
# the resulting VERSION row, after decoding into a manifest/files
# envelope) -- this cache short-circuits the network fetch itself, keyed
# by the *identity being fetched* (e.g. "github_repo:owner/repo:<sha>"),
# not the eventual content.
#
# Redis-backed (RDB_CACHE), 24h TTL -- matches services/ecosystem/
# idempotency_service.py's own TTL convention for the same reason (long
# enough that a user re-running an import minutes/hours later gets the
# fast path, short enough that a source's content isn't pinned forever).
# The cached value is the ecosystem_object_storage object_key (a sha256
# digest) pointing at the already-stored raw bytes, not the bytes
# themselves -- Redis stays small regardless of fetched payload size.
# ============================================================

from __future__ import annotations

import hashlib

from core.config import RDB_CACHE
from core.kv import get_kv
from store.ecosystem_object_storage import get_ecosystem_object_storage

_TTL_SECONDS = 24 * 60 * 60


def _cache_key(fetch_identity: str) -> str:
    digest = hashlib.sha256(fetch_identity.encode("utf-8")).hexdigest()
    return f"ecosystem:import_fetch_cache:{digest}"


def get_cached(fetch_identity: str) -> bytes | None:
    """Returns the previously-fetched raw bytes for this exact identity,
    or None on a cache miss (including any Redis/storage hiccup -- a
    cache-layer failure must never block an import, only make it a
    fraction slower by re-fetching)."""
    try:
        kv = get_kv(RDB_CACHE, decode_responses=True)
        object_key = kv.get(_cache_key(fetch_identity))
        if not object_key:
            return None
        return get_ecosystem_object_storage().get(object_key)
    except Exception:
        return None


def put_cached(fetch_identity: str, content: bytes) -> None:
    """Stores content (content-hash-addressed) and records the identity ->
    object_key mapping. Best-effort -- a failure here must not fail the
    import that just successfully fetched the content."""
    try:
        object_key = get_ecosystem_object_storage().put(content)
        kv = get_kv(RDB_CACHE, decode_responses=True)
        kv.setex(_cache_key(fetch_identity), _TTL_SECONDS, object_key)
    except Exception:
        pass
