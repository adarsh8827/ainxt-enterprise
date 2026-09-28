# SPDX-License-Identifier: MIT
# ============================================================
# Rate limiting + Idempotency-Key storage tests (task B-20).
#
# Backend-agnostic by design: check_rate_limit()/idempotency's
# get_cached_response()/store_response() behave the same whether backed by
# real Redis or the in-process fallback, so these tests pass either way —
# but they're most meaningful against real Redis (ECOSYSTEM_TEST_REDIS_HOST/
# PORT env vars), since only that path actually exercises the sliding-window
# sorted-set logic instead of the single-process dict fallback.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from services.ecosystem.idempotency_service import get_cached_response, store_response
from services.ecosystem.rate_limit_service import check_rate_limit


def test_unknown_action_class_raises():
    with pytest.raises(ValueError):
        check_rate_limit("user-1", "not_a_real_action_class")


def test_rate_limit_allows_within_limit():
    user_id = f"user-{uuid.uuid4()}"
    result = check_rate_limit(user_id, "report")
    assert result.allowed is True
    assert result.limit == 3


def test_rate_limit_blocks_after_limit_exceeded():
    user_id = f"user-{uuid.uuid4()}"
    results = [check_rate_limit(user_id, "report") for _ in range(5)]
    # Limit for 'report' is 3 per window (deliberately the tightest class).
    assert results[0].allowed is True
    assert results[1].allowed is True
    assert results[2].allowed is True
    assert results[3].allowed is False
    assert results[4].allowed is False
    assert results[3].retry_after > 0


def test_rate_limit_is_per_user():
    user_a = f"user-{uuid.uuid4()}"
    user_b = f"user-{uuid.uuid4()}"
    for _ in range(3):
        check_rate_limit(user_a, "report")
    # user_a is now at the limit; user_b's own counter is untouched.
    assert check_rate_limit(user_a, "report").allowed is False
    assert check_rate_limit(user_b, "report").allowed is True


def test_rate_limit_is_per_action_class():
    user_id = f"user-{uuid.uuid4()}"
    for _ in range(3):
        check_rate_limit(user_id, "report")
    assert check_rate_limit(user_id, "report").allowed is False
    # 'add' has its own counter — unaffected by 'report' being exhausted.
    assert check_rate_limit(user_id, "add").allowed is True


def test_idempotency_returns_none_when_nothing_cached():
    caller = f"caller-{uuid.uuid4()}"
    assert get_cached_response(caller, "some-key") is None


def test_idempotency_round_trips_cached_response():
    caller = f"caller-{uuid.uuid4()}"
    key = "idem-key-1"
    store_response(caller, key, {"job_id": "abc123", "status": "verifying"})
    cached = get_cached_response(caller, key)
    assert cached == {"job_id": "abc123", "status": "verifying"}


def test_idempotency_is_scoped_per_caller():
    key = "shared-key"
    store_response("caller-a", key, {"job_id": "for-a"})
    store_response("caller-b", key, {"job_id": "for-b"})
    assert get_cached_response("caller-a", key) == {"job_id": "for-a"}
    assert get_cached_response("caller-b", key) == {"job_id": "for-b"}


def test_idempotency_is_scoped_per_key():
    caller = f"caller-{uuid.uuid4()}"
    store_response(caller, "key-1", {"job_id": "one"})
    store_response(caller, "key-2", {"job_id": "two"})
    assert get_cached_response(caller, "key-1") == {"job_id": "one"}
    assert get_cached_response(caller, "key-2") == {"job_id": "two"}
