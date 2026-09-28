# SPDX-License-Identifier: MIT
# ============================================================
# search_repos_by_topic() tests -- GitHub topic search, discovery-only
# (§3 of docs/ecosystem/EXTERNAL_SOURCES_PLAN.md: results here are
# candidates for a human to add to sources.yaml via a reviewed PR, never
# something the crawler trusts automatically). No live network.
# ============================================================

from __future__ import annotations

import json

import httpx
import pytest

from services.ecosystem.errors import ImportRateLimitedError
from services.ecosystem.import_adapters import github_repo


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://api.github.com/fixture"),
    )


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(github_repo, "assert_safe_https_url", lambda url: url)


def test_search_repos_by_topic_returns_the_expected_fields(monkeypatch):
    def fake_relay(method, url, **kwargs):
        assert "search/repositories" in url
        assert "topic%3Aagent-skills" in url or "topic:agent-skills" in url
        return _json_response(200, {"items": [{
            "full_name": "addyosmani/agent-skills", "html_url": "https://github.com/addyosmani/agent-skills",
            "description": "A collection of skills.", "license": {"spdx_id": "MIT"},
            "pushed_at": "2026-09-01T00:00:00Z", "stargazers_count": 42,
        }]})
    monkeypatch.setattr(github_repo, "relay_request", fake_relay)

    results = github_repo.search_repos_by_topic("agent-skills")
    assert len(results) == 1
    assert results[0]["full_name"] == "addyosmani/agent-skills"
    assert results[0]["license_spdx"] == "MIT"


def test_search_repos_by_topic_skips_items_with_no_full_name(monkeypatch):
    monkeypatch.setattr(github_repo, "relay_request", lambda *a, **k: _json_response(200, {"items": [{"full_name": ""}, {"description": "no name at all"}]}))
    assert github_repo.search_repos_by_topic("agent-skills") == []


def test_search_repos_by_topic_propagates_rate_limiting(monkeypatch):
    def fake_relay(method, url, **kwargs):
        return httpx.Response(403, headers={"Retry-After": "30"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(github_repo, "relay_request", fake_relay)
    with pytest.raises(ImportRateLimitedError):
        github_repo.search_repos_by_topic("agent-skills")
