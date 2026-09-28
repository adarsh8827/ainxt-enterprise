# SPDX-License-Identifier: MIT
# ============================================================
# mcp_registry import adapter (External sources phase) -- discovery-only
# client for the official MCP Registry (https://registry.modelcontextprotocol.io,
# API v0.1). Crawler-side use only: builds catalog pointer entries for
# item_type="mcp_server", hidden in the UI until the MCP item type itself
# ships (ECOSYSTEM_TYPE_MCP is "coming_soon" -- see
# docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §3). Nothing here installs or
# runs an MCP server; it only records pointer metadata.
#
# License source (per the plan's §4 "Licensing" -- MCP entries have no
# SKILL.md/repo-LICENSE chain to inherit from): the registry entry's own
# `packages[]` list names an npm or PyPI package; that package's OWN
# registry metadata (registry.npmjs.org's `license` field / PyPI's JSON
# API `info.license` + `info.classifiers`) is the license signal, fetched
# fresh, never trusted from the MCP registry entry's own free-text fields.
# An OCI-packaged server is only included when it carries an explicit
# MIT/Apache "licenses" OCI annotation; a server with no installable
# package at all (remote-only) is never auto-included -- it's returned
# with allowed=False so a human reviews it and, if approved, marks it
# "remote service" with a recorded ToS note by hand (§4).
#
# This is a first-pass interpretation of a real but still-evolving public
# API, disclosed as such -- not a guarantee the registry's response shape
# never changes. Parsing is defensive throughout: an unrecognized field
# shape excludes that one entry (with a reason) rather than raising.
# ============================================================

from __future__ import annotations

from typing import Any

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_REGISTRY_BASE = "https://registry.modelcontextprotocol.io"
_SERVERS_PATH = "/v0/servers"
_NPM_REGISTRY_BASE = "https://registry.npmjs.org"
_PYPI_BASE = "https://pypi.org/pypi"
_MAX_PAGE_SIZE = 100


def _get_json(url: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
    safe_url = assert_safe_https_url(url)
    try:
        resp = relay_request("GET", safe_url, headers={"Accept": "application/json"}, timeout=timeout)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        parsed = resp.json()
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def list_servers(cursor: str | None = None) -> dict[str, Any]:
    """One page of `GET /v0/servers` (API v0.1). Returns
    {"servers": [...raw entries...], "next_cursor": str | None}. Raises
    ImportFetchError if the registry itself is unreachable or returns a
    non-2xx -- this is the "index the crawler walks," so an outage here
    should stop the crawl step for this source, not silently produce an
    empty page."""
    url = f"{_REGISTRY_BASE}{_SERVERS_PATH}?limit={_MAX_PAGE_SIZE}"
    if cursor:
        url = f"{url}&cursor={cursor}"
    data = _get_json(url)
    if data is None:
        raise ImportFetchError(f"MCP Registry ({url}) is unreachable or returned a non-2xx/non-JSON response")
    servers = data.get("servers")
    if not isinstance(servers, list):
        raise ImportFetchError("MCP Registry response has no 'servers' list")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {"servers": servers, "next_cursor": metadata.get("next_cursor")}


def _npm_license(package_name: str) -> str | None:
    fetch_identity = f"mcp_registry:npm_license:{package_name}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        return cached.decode("utf-8") or None
    data = _get_json(f"{_NPM_REGISTRY_BASE}/{package_name}")
    license_str = None
    if data:
        raw_license = data.get("license")
        if isinstance(raw_license, str):
            license_str = raw_license
        elif isinstance(raw_license, dict):
            license_str = raw_license.get("type")
    put_cached(fetch_identity, (license_str or "").encode("utf-8"))
    return license_str


def _pypi_license(package_name: str) -> str | None:
    fetch_identity = f"mcp_registry:pypi_license:{package_name}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        return cached.decode("utf-8") or None
    data = _get_json(f"{_PYPI_BASE}/{package_name}/json")
    license_str = None
    if data:
        info = data.get("info") or {}
        candidate = info.get("license")
        if isinstance(candidate, str) and candidate.strip() and candidate.strip().upper() != "UNKNOWN":
            license_str = candidate.strip()
        else:
            for classifier in info.get("classifiers") or []:
                if isinstance(classifier, str) and classifier.startswith("License :: OSI Approved :: MIT"):
                    license_str = "MIT"
                    break
                if isinstance(classifier, str) and classifier.startswith("License :: OSI Approved :: Apache Software License"):
                    license_str = "Apache-2.0"
                    break
    put_cached(fetch_identity, (license_str or "").encode("utf-8"))
    return license_str


def _resolve_license_for_entry(entry: dict[str, Any]) -> tuple[str | None, str]:
    """Returns (effective_license_or_None, evidence_string). Tries each
    declared package in order (npm, then pypi, then oci) -- first package
    that resolves to a real license wins; an OCI-only package needs an
    explicit MIT/Apache 'licenses' annotation (never inferred)."""
    packages = entry.get("packages")
    if not isinstance(packages, list):
        return None, "entry has no packages[] list to derive a license from"

    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        registry_name = (pkg.get("registry_name") or pkg.get("registryType") or "").lower()
        name = pkg.get("name") or pkg.get("identifier") or ""
        if not name:
            continue
        if registry_name == "npm":
            found = _npm_license(name)
            if found:
                return found, f"npm package {name!r}'s registry license field"
        elif registry_name in ("pypi", "pip"):
            found = _pypi_license(name)
            if found:
                return found, f"PyPI package {name!r}'s registry metadata"
        elif registry_name == "oci":
            annotations = pkg.get("annotations") if isinstance(pkg.get("annotations"), dict) else {}
            licenses_annotation = annotations.get("licenses") or annotations.get("org.opencontainers.image.licenses")
            if licenses_annotation:
                return str(licenses_annotation), f"OCI package {name!r}'s 'licenses' annotation"

    return None, "no npm/PyPI package with a discoverable license, and no MIT/Apache OCI 'licenses' annotation"


def discover_mcp_servers(max_pages: int = 20) -> list[dict[str, Any]]:
    """Walks the MCP Registry's server list end to end (bounded by
    `max_pages` -- a real cursor-paginated crawl, not a single page),
    returning one candidate dict per entry with a resolved license
    verdict, mirroring discover_skills_in_repo()'s shape. A server with
    no installable package at all (remote-only, no packages[] entries) is
    returned with allowed=False and remote_only=True -- catalog inclusion
    for those requires a human to review its ToS and mark it explicitly
    (§4 of the External sources plan), never automatic.
    """
    candidates: list[dict[str, Any]] = []
    cursor: str | None = None
    pages_walked = 0

    while pages_walked < max_pages:
        page = list_servers(cursor)
        pages_walked += 1
        for entry in page["servers"]:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("id") or ""
            if not name:
                continue
            packages = entry.get("packages") if isinstance(entry.get("packages"), list) else []
            remote_only = len(packages) == 0
            if remote_only:
                candidates.append({
                    "name": name,
                    "display_name": entry.get("name") or name,
                    "description": entry.get("description", ""),
                    "repository_url": (entry.get("repository") or {}).get("url") if isinstance(entry.get("repository"), dict) else None,
                    "license_evidence": {},
                    "remote_only": True,
                    "allowed": False,
                    "reason": "remote-only server (no installable package) -- requires a human ToS review before inclusion",
                })
                continue

            effective_license, evidence = _resolve_license_for_entry(entry)
            allowed = is_allowed_license(effective_license)
            candidates.append({
                "name": name,
                "display_name": entry.get("name") or name,
                "description": entry.get("description", ""),
                "repository_url": (entry.get("repository") or {}).get("url") if isinstance(entry.get("repository"), dict) else None,
                "license_evidence": {"effective_license": effective_license, "source": evidence},
                "remote_only": False,
                "allowed": allowed,
                "reason": "" if allowed else f"effective license ({effective_license!r}) is not MIT/Apache-2.0 ({evidence})",
            })

        cursor = page.get("next_cursor")
        if not cursor:
            break

    return candidates
