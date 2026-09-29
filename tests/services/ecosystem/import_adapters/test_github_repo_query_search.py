# SPDX-License-Identifier: MIT
# ============================================================
# search_repos_by_query() tests -- free-text GitHub repo search, the
# discovery primitive behind live_search_service.py's "From the web"
# feature (real gap found live, 2026-09-29). No live network.
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


def test_search_repos_by_query_returns_the_expected_fields(monkeypatch):
    def fake_relay(method, url, **kwargs):
        assert "search/repositories" in url
        assert "commit%20message%20writer" in url or "commit message writer" in url
        return _json_response(200, {"items": [{
            "full_name": "acme/commit-message-writer", "html_url": "https://github.com/acme/commit-message-writer",
            "description": "Writes commit messages.", "license": {"spdx_id": "MIT"},
            "pushed_at": "2026-09-01T00:00:00Z", "stargazers_count": 7,
        }]})
    monkeypatch.setattr(github_repo, "relay_request", fake_relay)

    results = github_repo.search_repos_by_query("commit message writer")
    assert len(results) == 1
    assert results[0]["full_name"] == "acme/commit-message-writer"
    assert results[0]["license_spdx"] == "MIT"


def test_search_repos_by_query_skips_items_with_no_full_name(monkeypatch):
    monkeypatch.setattr(github_repo, "relay_request", lambda *a, **k: _json_response(200, {"items": [{"full_name": ""}, {"description": "no name at all"}]}))
    assert github_repo.search_repos_by_query("anything") == []


def test_search_repos_by_query_propagates_rate_limiting(monkeypatch):
    def fake_relay(method, url, **kwargs):
        return httpx.Response(403, headers={"Retry-After": "30"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(github_repo, "relay_request", fake_relay)
    with pytest.raises(ImportRateLimitedError):
        github_repo.search_repos_by_query("anything")
