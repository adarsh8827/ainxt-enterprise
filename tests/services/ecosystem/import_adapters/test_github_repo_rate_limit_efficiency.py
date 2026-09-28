# SPDX-License-Identifier: MIT
# ============================================================
# Rate-limit-efficiency review (2026-09-28): file content now comes from
# raw.githubusercontent.com (not subject to the REST API's rate limit at
# all), and every api.github.com metadata call is ETag-cached (a 304
# response does not count against the primary rate limit, per GitHub's
# own documented behavior). No live network.
# ============================================================

from __future__ import annotations

import json

import httpx
import pytest

from services.ecosystem.import_adapters import github_repo


def _json_response(status_code: int, payload, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, headers=headers or {},
        content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://api.github.com/fixture"),
    )


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(github_repo, "assert_safe_https_url", lambda url: url)


@pytest.fixture(autouse=True)
def _isolated_etag_cache(monkeypatch):
    # A real, per-test in-memory store instead of the module's real
    # Redis-backed fetch cache -- this file specifically tests the
    # caching BEHAVIOR (does a stored ETag actually get reused), so it
    # needs a store that starts empty every test, not real Redis state
    # left over from another test/run.
    store: dict[str, bytes] = {}
    monkeypatch.setattr(github_repo, "get_cached", lambda identity: store.get(identity))
    monkeypatch.setattr(github_repo, "put_cached", lambda identity, content: store.__setitem__(identity, content))


@pytest.fixture(autouse=True)
def _reset_stats():
    github_repo.reset_api_call_stats()
    yield
    github_repo.reset_api_call_stats()


def test_file_content_is_fetched_from_the_raw_host_never_the_contents_api(monkeypatch):
    calls = []

    def fake_relay(method, url, **kwargs):
        calls.append(url)
        assert "/contents/" not in url, f"content must not go through the Contents API, got {url!r}"
        return httpx.Response(200, content=b"file content", request=httpx.Request("GET", url))

    monkeypatch.setattr(github_repo, "relay_request", fake_relay)
    text = github_repo._fetch_text_file("acme", "repo", "a" * 40, "skills/one/SKILL.md")
    assert text == "file content"
    assert any("raw.githubusercontent.com" in u for u in calls)


def test_a_304_response_is_not_counted_as_rate_limit_consuming(monkeypatch):
    first_response = _json_response(200, {"default_branch": "main"}, headers={"ETag": '"abc123"'})
    responses = [first_response]

    def fake_relay(method, url, **kwargs):
        if responses:
            return responses.pop(0)
        # Second call: server says "unchanged" -- must have received the
        # ETag back as If-None-Match.
        assert kwargs.get("headers", {}).get("If-None-Match") == '"abc123"'
        return httpx.Response(304, request=httpx.Request("GET", url))

    monkeypatch.setattr(github_repo, "relay_request", fake_relay)

    github_repo._github_get("/repos/acme/repo")
    stats_after_first = github_repo.get_api_call_stats()
    assert stats_after_first["total_requests"] == 1
    assert stats_after_first["rate_limit_consuming_requests"] == 1

    result = github_repo._github_get("/repos/acme/repo")
    stats_after_second = github_repo.get_api_call_stats()
    assert result == {"default_branch": "main"}  # served from the cached body, not a fresh 200
    assert stats_after_second["total_requests"] == 2
    assert stats_after_second["rate_limit_consuming_requests"] == 1  # the 304 did NOT add to this


def test_get_resolved_head_sha_does_not_fetch_the_tree(monkeypatch):
    calls = []

    def fake_relay(method, url, **kwargs):
        calls.append(url)
        assert "/git/trees/" not in url, "get_resolved_head_sha must not fetch the tree"
        if "/commits/" in url:
            return _json_response(200, {"sha": "b" * 40})
        return _json_response(200, {"default_branch": "main"})

    monkeypatch.setattr(github_repo, "relay_request", fake_relay)
    sha = github_repo.get_resolved_head_sha("acme/repo")
    assert sha == "b" * 40
    assert len(calls) == 2  # repo meta + commit lookup only


def test_api_call_stats_reset_between_crawls():
    github_repo.reset_api_call_stats()
    assert github_repo.get_api_call_stats() == {"total_requests": 0, "rate_limit_consuming_requests": 0}
