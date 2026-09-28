# SPDX-License-Identifier: MIT
# ============================================================
# mcp_registry adapter tests. No live network: connectors.net_relay.
# relay_request is monkeypatched to a URL-substring dispatch table
# (matching test_github_repo_discovery.py's own style).
#
# Fixture shapes below are the REAL, live MCP Registry API v0.1 response
# shape (verified 2026-09-28 against https://registry.modelcontextprotocol.io
# directly, during the first real crawl) -- an earlier version of this
# adapter/these tests assumed an unwrapped, snake_case shape that turned
# out not to match the real API at all (every server entry wraps the
# actual object under "server", the pagination cursor is
# metadata.nextCursor (camelCase), and the registry returns every
# published VERSION of a server as its own list entry, disambiguated by
# _meta.io.modelcontextprotocol.registry/official.isLatest).
# ============================================================

from __future__ import annotations

import json

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError
from services.ecosystem.import_adapters import mcp_registry


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://fixture.example/"),
    )


def _server_entry(server: dict, *, is_latest: bool = True) -> dict:
    return {
        "server": server,
        "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": is_latest}},
    }


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(mcp_registry, "assert_safe_https_url", lambda url: url)


@pytest.fixture(autouse=True)
def _bypass_fetch_cache(monkeypatch):
    monkeypatch.setattr(mcp_registry, "get_cached", lambda identity: None)
    monkeypatch.setattr(mcp_registry, "put_cached", lambda identity, content: None)


def _install_relay(monkeypatch, rules: list[tuple[str, httpx.Response]]):
    """First substring match wins, checked in the given order -- callers
    list more-specific rules (e.g. a particular cursor value) before
    more-general ones (e.g. the bare registry host) when a test needs to
    tell two calls to overlapping URLs apart."""
    def fake_relay_request(method, url, **kwargs):
        for substring, response in rules:
            if substring in url:
                return response
        raise AssertionError(f"no fixture registered for {url!r}")
    monkeypatch.setattr(mcp_registry, "relay_request", fake_relay_request)


def test_list_servers_raises_when_the_registry_is_unreachable(monkeypatch):
    _install_relay(monkeypatch, [("registry.modelcontextprotocol.io", httpx.Response(
        status_code=503, content=b"", request=httpx.Request("GET", "https://fixture.example/"),
    ))])
    with pytest.raises(ImportFetchError):
        mcp_registry.list_servers()


def test_list_servers_reads_the_camelcase_next_cursor(monkeypatch):
    _install_relay(monkeypatch, [("registry.modelcontextprotocol.io", _json_response(200, {
        "servers": [], "metadata": {"nextCursor": "abc123", "count": 0},
    }))])
    page = mcp_registry.list_servers()
    assert page["next_cursor"] == "abc123"


def test_discover_mcp_servers_unwraps_the_server_object(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({
                "name": "ai.acme/local-server", "description": "A local MCP server.",
                "repository": {"url": "https://github.com/acme/local-server"},
                "packages": [{"registryType": "npm", "identifier": "acme-local-server"}],
            })],
            "metadata": {},
        })),
        ("registry.npmjs.org/acme-local-server", _json_response(200, {"license": "MIT"})),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert len(candidates) == 1
    assert candidates[0]["name"] == "ai.acme/local-server"
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "MIT"
    assert candidates[0]["remote_only"] is False


def test_discover_mcp_servers_excludes_a_non_mit_apache_license(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({
                "name": "ai.acme/gpl-server", "description": "",
                "repository": {"url": "https://github.com/acme/gpl-server"},
                "packages": [{"registryType": "npm", "identifier": "acme-gpl-server"}],
            })],
            "metadata": {},
        })),
        ("registry.npmjs.org/acme-gpl-server", _json_response(200, {"license": "GPL-3.0"})),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["allowed"] is False
    assert "not MIT/Apache-2.0" in candidates[0]["reason"]


def test_discover_mcp_servers_marks_a_remote_only_server_excluded(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({"name": "ai.acme/remote-only", "description": "", "remotes": [{"type": "streamable-http", "url": "https://example.com"}]})],
            "metadata": {},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["remote_only"] is True
    assert candidates[0]["allowed"] is False
    assert "ToS review" in candidates[0]["reason"]


def test_discover_mcp_servers_skips_non_latest_versions_of_the_same_server(monkeypatch):
    # Real, live finding: the registry returns one list entry per
    # published version of a server -- without the isLatest filter, the
    # same namespace showed up twice in one real crawl.
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [
                _server_entry({"name": "ai.acme/versioned", "description": "", "version": "1.0.0",
                               "packages": [{"registryType": "npm", "identifier": "acme-versioned"}]}, is_latest=False),
                _server_entry({"name": "ai.acme/versioned", "description": "", "version": "1.0.1",
                               "packages": [{"registryType": "npm", "identifier": "acme-versioned"}]}, is_latest=True),
            ],
            "metadata": {},
        })),
        ("registry.npmjs.org/acme-versioned", _json_response(200, {"license": "MIT"})),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert len(candidates) == 1


def test_discover_mcp_servers_walks_pagination_via_next_cursor(monkeypatch):
    _install_relay(monkeypatch, [
        # More-specific cursor rule listed first so it wins for the second
        # call, even though the second call's URL also contains the bare
        # registry-host substring the first call's rule matches on.
        ("cursor=page2", _json_response(200, {
            "servers": [_server_entry({"name": "a/two", "description": "", "packages": [{"registryType": "npm", "identifier": "two"}]})],
            "metadata": {"nextCursor": None},
        })),
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({"name": "a/one", "description": "", "packages": [{"registryType": "npm", "identifier": "one"}]})],
            "metadata": {"nextCursor": "page2"},
        })),
        ("registry.npmjs.org/one", _json_response(200, {"license": "MIT"})),
        ("registry.npmjs.org/two", _json_response(200, {"license": "MIT"})),
    ])
    candidates = mcp_registry.discover_mcp_servers(max_pages=5)
    assert {c["name"] for c in candidates} == {"a/one", "a/two"}


def test_discover_mcp_servers_reads_oci_licenses_annotation(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({
                "name": "ai.acme/oci-server", "description": "",
                "packages": [{"registryType": "oci", "identifier": "acme/oci-server", "annotations": {"licenses": "Apache-2.0"}}],
            })],
            "metadata": {},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "Apache-2.0"


def test_discover_mcp_servers_falls_back_to_pypi_license_classifier(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [_server_entry({
                "name": "ai.acme/py-server", "description": "",
                "packages": [{"registryType": "pypi", "identifier": "acme-py-server"}],
            })],
            "metadata": {},
        })),
        ("pypi.org/pypi/acme-py-server/json", _json_response(200, {
            "info": {"license": "UNKNOWN", "classifiers": ["License :: OSI Approved :: MIT License"]},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "MIT"


def test_pypi_license_falls_back_to_classifier_when_the_license_field_is_full_text(monkeypatch):
    # Real, live finding: some PyPI packages put the ENTIRE license text
    # (not a short identifier) in info.license -- storing that verbatim
    # as an entry's "effective_license" would be wrong.
    monkeypatch.setattr(mcp_registry, "relay_request", lambda method, url, **kw: _json_response(200, {
        "info": {
            "license": "MIT License\n\nCopyright (c) 2026 Example\n\nPermission is hereby granted...",
            "classifiers": ["License :: OSI Approved :: MIT License"],
        },
    }))
    assert mcp_registry._pypi_license("acme-full-text-license") == "MIT"
