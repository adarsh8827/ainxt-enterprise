# SPDX-License-Identifier: MIT
# ============================================================
# mcp_registry adapter tests. No live network: connectors.net_relay.
# relay_request is monkeypatched to a URL-substring dispatch table
# (matching test_github_repo_discovery.py's own style). Registry/npm/
# PyPI response shapes below are constructed from the publicly documented
# MCP Registry API v0.1 and npm/PyPI JSON API fields this adapter reads
# (services/ecosystem/import_adapters/mcp_registry.py's own header
# discloses this is a first-pass interpretation of a still-evolving API).
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


def test_discover_mcp_servers_resolves_npm_license_and_includes_the_entry(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [{
                "name": "acme/local-server", "description": "A local MCP server.",
                "repository": {"url": "https://github.com/acme/local-server"},
                "packages": [{"registry_name": "npm", "name": "acme-local-server"}],
            }],
            "metadata": {"next_cursor": None},
        })),
        ("registry.npmjs.org/acme-local-server", _json_response(200, {"license": "MIT"})),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert len(candidates) == 1
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "MIT"
    assert candidates[0]["remote_only"] is False


def test_discover_mcp_servers_excludes_a_non_mit_apache_license(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [{
                "name": "acme/gpl-server", "description": "",
                "repository": {"url": "https://github.com/acme/gpl-server"},
                "packages": [{"registry_name": "npm", "name": "acme-gpl-server"}],
            }],
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
            "servers": [{"name": "acme/remote-only", "description": "", "packages": []}],
            "metadata": {},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["remote_only"] is True
    assert candidates[0]["allowed"] is False
    assert "ToS review" in candidates[0]["reason"]


def test_discover_mcp_servers_walks_pagination_via_next_cursor(monkeypatch):
    _install_relay(monkeypatch, [
        # More-specific cursor rule listed first so it wins for the second
        # call, even though the second call's URL also contains the bare
        # registry-host substring the first call's rule matches on.
        ("cursor=page2", _json_response(200, {
            "servers": [{"name": "a/two", "description": "", "packages": [{"registry_name": "npm", "name": "two"}]}],
            "metadata": {"next_cursor": None},
        })),
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [{"name": "a/one", "description": "", "packages": [{"registry_name": "npm", "name": "one"}]}],
            "metadata": {"next_cursor": "page2"},
        })),
        ("registry.npmjs.org/one", _json_response(200, {"license": "MIT"})),
        ("registry.npmjs.org/two", _json_response(200, {"license": "MIT"})),
    ])
    candidates = mcp_registry.discover_mcp_servers(max_pages=5)
    assert {c["name"] for c in candidates} == {"a/one", "a/two"}


def test_discover_mcp_servers_reads_oci_licenses_annotation(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [{
                "name": "acme/oci-server", "description": "",
                "packages": [{"registry_name": "oci", "name": "acme/oci-server", "annotations": {"licenses": "Apache-2.0"}}],
            }],
            "metadata": {},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "Apache-2.0"


def test_discover_mcp_servers_falls_back_to_pypi_license_classifier(monkeypatch):
    _install_relay(monkeypatch, [
        ("registry.modelcontextprotocol.io", _json_response(200, {
            "servers": [{
                "name": "acme/py-server", "description": "",
                "packages": [{"registry_name": "pypi", "name": "acme-py-server"}],
            }],
            "metadata": {},
        })),
        ("pypi.org/pypi/acme-py-server/json", _json_response(200, {
            "info": {"license": "UNKNOWN", "classifiers": ["License :: OSI Approved :: MIT License"]},
        })),
    ])
    candidates = mcp_registry.discover_mcp_servers()
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "MIT"
