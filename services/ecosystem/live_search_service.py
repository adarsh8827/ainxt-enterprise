# SPDX-License-Identifier: MIT
# ============================================================
# Live search "From the web" (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §10;
# real gap found live, 2026-09-29: ECOSYSTEM_LIVE_SOURCES/
# live_sources_enabled existed as flags with nothing behind them).
#
# Deliberately NOT a second content-fetch/license/neutrality
# implementation -- this module only does discovery + a cheap, repo-level
# license pre-filter (the same MIT/Apache-2.0 check the crawler/import
# path already uses, is_allowed_license()). It returns pointer-shaped
# results, never full skill content. Installing a result reuses
# create_service.py's create_via_import(kind="github_repo", ...)
# directly -- the EXACT same path a manual "Import from URL" already
# takes, which (since this session's own earlier fix) already runs the
# real per-skill license check AND the neutrality scanner before
# anything is created. This module's own repo-level filter is a cheap
# search-result-quality signal, not a substitute for that real check.
#
# Cached + rate-limit-aware "for free": search_repos_by_query() calls the
# SAME _github_get() every other adapter call in this session's crawler/
# import path already uses -- ETag-cached (services/ecosystem/
# import_adapters/fetch_cache.py), credential-aware (github_credential.py),
# and raises the same typed ImportRateLimitedError/ImportFetchError on a
# real 403/429/failure, never silently swallowed.
# ============================================================

from __future__ import annotations

from typing import Any

from core.config import ECOSYSTEM_LIVE_SOURCES
from services.ecosystem.license_policy import is_allowed_license


def live_search_enabled(org_id: str) -> bool:
    """Both the instance-wide flag AND this org's own policy toggle must
    be true -- the org toggle can only ever narrow the instance flag,
    never widen it (same convention as every other per-org marketplace
    policy setting, see services/ecosystem/policy_service.py)."""
    if not ECOSYSTEM_LIVE_SOURCES:
        return False
    from services.ecosystem.policy_service import get_policy

    return bool(get_policy(org_id).get("live_sources_enabled", False))


def search_live(query: str, *, org_id: str) -> list[dict[str, Any]]:
    """Returns pointer-shaped results (namespace/display_name/description/
    license_spdx/source_kind/source_url/ref) for a live GitHub repo
    search, filtered to MIT/Apache-2.0-licensed repos only -- a cheap,
    repo-level pre-filter, not the real per-skill check (see module
    docstring). Returns [] (never raises) if either gate is off, or if
    query is blank -- a disabled/empty search is silence, not an error.
    """
    if not query or not query.strip():
        return []
    if not live_search_enabled(org_id):
        return []

    from services.ecosystem.import_adapters.github_repo import search_repos_by_query

    hits = search_repos_by_query(query.strip())
    results: list[dict[str, Any]] = []
    for hit in hits:
        license_spdx = hit.get("license_spdx")
        if not is_allowed_license(license_spdx):
            continue
        full_name = hit["full_name"]
        results.append({
            "namespace": full_name,
            "display_name": full_name.split("/", 1)[-1],
            "description": hit.get("description", ""),
            "license_spdx": license_spdx,
            "source_kind": "github_repo",
            "source_url": hit.get("html_url", f"https://github.com/{full_name}"),
            # The exact `ref` create_via_import(kind="github_repo", ref=...)
            # expects -- installing a live-search result is that same
            # call, made by the frontend, with this ref verbatim.
            "ref": full_name,
        })
    return results
