# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from services.ecosystem.import_adapters import fetch_cache


@pytest.fixture(autouse=True)
def _require_redis():
    from core.config import RDB_CACHE
    from core.kv import get_kv

    try:
        get_kv(RDB_CACHE, decode_responses=True).get("probe")
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")


def test_cache_miss_returns_none():
    assert fetch_cache.get_cached("no-such-identity-ever") is None


def test_put_then_get_round_trips():
    identity = "github_repo:acme/example:deadbeef"
    fetch_cache.put_cached(identity, b"hello world")
    assert fetch_cache.get_cached(identity) == b"hello world"


def test_different_identities_are_isolated():
    fetch_cache.put_cached("identity-a", b"content a")
    fetch_cache.put_cached("identity-b", b"content b")
    assert fetch_cache.get_cached("identity-a") == b"content a"
    assert fetch_cache.get_cached("identity-b") == b"content b"
