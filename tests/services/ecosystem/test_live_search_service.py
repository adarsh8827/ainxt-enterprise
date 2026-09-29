# SPDX-License-Identifier: MIT
# ============================================================
# live_search_service.py tests (real gap found live, 2026-09-29:
# ECOSYSTEM_LIVE_SOURCES/live_sources_enabled existed as flags with
# nothing behind them). No live network -- github_repo.search_repos_by_query()
# is mocked directly; its own real-adapter behavior (caching, rate-limit
# propagation) is covered separately in
# tests/services/ecosystem/import_adapters/test_github_repo_query_search.py.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.ecosystem import live_search_service
from services.ecosystem.policy_service import set_policy

_FAKE_HITS = [
    {"full_name": "acme/mit-skill", "html_url": "https://github.com/acme/mit-skill",
     "description": "MIT licensed.", "license_spdx": "MIT", "pushed_at": "2026-09-01T00:00:00Z", "stargazers_count": 3},
    {"full_name": "acme/gpl-skill", "html_url": "https://github.com/acme/gpl-skill",
     "description": "GPL licensed.", "license_spdx": "GPL-3.0", "pushed_at": "2026-09-01T00:00:00Z", "stargazers_count": 1},
    {"full_name": "acme/no-license-skill", "html_url": "https://github.com/acme/no-license-skill",
     "description": "No license at all.", "license_spdx": None, "pushed_at": "2026-09-01T00:00:00Z", "stargazers_count": 0},
]


def _enable_live_search(org_id: str, monkeypatch):
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", True)
    set_policy(org_id, live_sources_enabled=True, updated_by="admin-live-search")


def test_search_live_filters_out_non_mit_apache_results(monkeypatch):
    _enable_live_search("org-live-a", monkeypatch)
    with patch(
        "services.ecosystem.import_adapters.github_repo.search_repos_by_query", return_value=_FAKE_HITS
    ):
        results = live_search_service.search_live("skill", org_id="org-live-a")
    namespaces = {r["namespace"] for r in results}
    assert namespaces == {"acme/mit-skill"}, (
        f"GPL and no-license results must never appear, got {namespaces!r}"
    )


def test_search_live_result_ref_is_the_exact_create_via_import_ref(monkeypatch):
    _enable_live_search("org-live-b", monkeypatch)
    with patch(
        "services.ecosystem.import_adapters.github_repo.search_repos_by_query", return_value=_FAKE_HITS[:1]
    ):
        results = live_search_service.search_live("skill", org_id="org-live-b")
    assert results[0]["ref"] == "acme/mit-skill"
    assert results[0]["source_kind"] == "github_repo"


def test_search_live_returns_empty_when_the_instance_flag_is_off(monkeypatch):
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", False)
    set_policy("org-live-c", live_sources_enabled=True, updated_by="admin-live-search")
    with patch(
        "services.ecosystem.import_adapters.github_repo.search_repos_by_query", return_value=_FAKE_HITS
    ) as mock_search:
        results = live_search_service.search_live("skill", org_id="org-live-c")
    assert results == []
    mock_search.assert_not_called()  # never even hits GitHub when disabled


def test_search_live_returns_empty_when_the_org_policy_is_off(monkeypatch):
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", True)
    set_policy("org-live-d", live_sources_enabled=False, updated_by="admin-live-search")
    with patch(
        "services.ecosystem.import_adapters.github_repo.search_repos_by_query", return_value=_FAKE_HITS
    ) as mock_search:
        results = live_search_service.search_live("skill", org_id="org-live-d")
    assert results == []
    mock_search.assert_not_called()


def test_search_live_returns_empty_for_a_blank_query_without_even_checking_flags(monkeypatch):
    # A blank query short-circuits before the flag check -- confirmed by
    # NOT enabling live search at all here; if this ever called through
    # to search anyway, the flag check would also return [] for a
    # different reason, masking a real "never search on empty input" bug.
    with patch(
        "services.ecosystem.import_adapters.github_repo.search_repos_by_query", return_value=_FAKE_HITS
    ) as mock_search:
        assert live_search_service.search_live("", org_id="org-live-e") == []
        assert live_search_service.search_live("   ", org_id="org-live-e") == []
    mock_search.assert_not_called()


def test_live_search_enabled_requires_both_the_instance_flag_and_the_org_policy(monkeypatch):
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", True)
    set_policy("org-live-f", live_sources_enabled=True, updated_by="admin-live-search")
    assert live_search_service.live_search_enabled("org-live-f") is True

    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", False)
    assert live_search_service.live_search_enabled("org-live-f") is False
