# SPDX-License-Identifier: MIT
# ============================================================
# core/job_queue.py atomic depth check (Phase 4).
#
# Risk closed: _check_depth_atomic uses KVClient.register_script
# (EVALSHA on REDIS, per SPEC §6.7).
# If the script handle silently fails we must fall back to a plain
# LLEN — never a crash, never an unbounded enqueue.
#
# We do NOT test rq.Queue / rq.enqueue here — that's RQ's job. We
# surgically test the depth check against a fake "queue" with .name
# and .key.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from core import job_queue as _jq


class _FakeQueue:
    """Minimal duck-type matching what _check_depth_atomic reads."""
    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key

    def __len__(self):
        # Used by the LLEN fallback only — the test KV is the source of truth.
        return 0


@pytest.fixture(autouse=True)
def _reset_lua_cache():
    """Drop the cached script handle between tests so each case
    re-registers against its own fixture KV."""
    _jq._lua_check = None
    yield
    _jq._lua_check = None


@pytest.fixture
def patched_jq(monkeypatch, kv):
    """Force job_queue to look up its KV via the test fixture (DB9)."""
    monkeypatch.setattr(_jq, "get_kv", lambda *a, **k: kv)
    yield kv


def _fake_queue(key_prefix: str) -> _FakeQueue:
    qname = f"testq_{uuid.uuid4().hex[:6]}"
    return _FakeQueue(name=qname, key=key_prefix + qname)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_depth_atomic_returns_true_under_limit(patched_jq, key_prefix, monkeypatch):
    kv = patched_jq
    q = _fake_queue(key_prefix)
    # Use a custom limit so the test doesn't depend on _QUEUE_DEPTH_LIMITS.
    monkeypatch.setitem(_jq._QUEUE_DEPTH_LIMITS, q.name, 10)
    # Push 3 items via the KV directly (the Lua script reads LLEN).
    kv.rpush(q.key, "a", "b", "c")
    assert _jq._check_depth_atomic(q) is True


def test_depth_atomic_returns_false_at_limit(patched_jq, key_prefix, monkeypatch):
    kv = patched_jq
    q = _fake_queue(key_prefix)
    monkeypatch.setitem(_jq._QUEUE_DEPTH_LIMITS, q.name, 5)
    kv.rpush(q.key, *[f"item-{i}" for i in range(5)])
    assert _jq._check_depth_atomic(q) is False


# ---------------------------------------------------------------------------
# Script caching
# ---------------------------------------------------------------------------

def test_depth_atomic_reuses_script_handle(patched_jq, key_prefix, monkeypatch):
    """register_script should be called only once across two depth checks."""
    kv = patched_jq
    q = _fake_queue(key_prefix)
    monkeypatch.setitem(_jq._QUEUE_DEPTH_LIMITS, q.name, 100)

    call_count = {"register": 0}
    real_register = kv.register_script

    def _counting_register(src):
        call_count["register"] += 1
        return real_register(src)

    monkeypatch.setattr(kv, "register_script", _counting_register)
    _jq._check_depth_atomic(q)
    _jq._check_depth_atomic(q)
    assert call_count["register"] == 1


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------

def test_depth_atomic_falls_back_to_llen_on_script_error(monkeypatch):
    """If register_script raises, the function must fall back to len(queue)."""
    class _Q:
        name = "fallbackq"
        key = "kvtest:fallbackq"
        def __len__(self):
            return 3

    class _BadKV:
        def register_script(self, src):
            raise RuntimeError("script unavailable")

    monkeypatch.setitem(_jq._QUEUE_DEPTH_LIMITS, _Q.name, 5)
    monkeypatch.setattr(_jq, "get_kv", lambda *a, **k: _BadKV())
    _jq._lua_check = None
    # 3 < 5 → allowed.
    assert _jq._check_depth_atomic(_Q()) is True


# ---------------------------------------------------------------------------
# ecosystem_gate_job_id -- real bug found live (2026-09-27): the deterministic
# id used a colon separator, which RQ's own Job.create() rejects outright,
# so every single enqueue_ecosystem_gate_job() call failed silently (caught
# by gate_service's own enqueue-resilience try/except) and the B-6 sweeper
# built to recover exactly this kind of stuck row failed identically on
# every retry, since it computes the same id.
# ---------------------------------------------------------------------------

def test_ecosystem_gate_job_id_passes_rqs_own_validation():
    # rq==2.7.0 (pinned in requirements.txt) has no standalone
    # validate_job_id() function -- confirmed directly against the
    # installed package (a prior version of this test imported one that
    # never actually existed in this pinned version, so it always raised
    # ImportError rather than testing anything). RQ's real, current
    # validation lives in Job.id's own setter (rq/job.py), which raises
    # ValueError on a colon -- exercising that setter directly is "ask
    # RQ itself," matching this test's original intent.
    import redis
    from rq.job import Job

    job_id = _jq.ecosystem_gate_job_id("c9c121f0-532c-43b6-b2a7-3cdf97755006")
    # Job() requires a connection argument in this rq version but never
    # uses it for the .id setter below -- an unconnected client is
    # enough, no real Redis I/O happens in this test.
    job = Job(connection=redis.Redis())
    job.id = job_id  # raises ValueError if RQ itself would reject it


def test_ecosystem_gate_job_id_has_no_colon():
    assert ":" not in _jq.ecosystem_gate_job_id(str(uuid.uuid4()))
