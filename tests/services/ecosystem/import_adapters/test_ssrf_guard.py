# SPDX-License-Identifier: MIT
# ============================================================
# SSRF guard tests. No live network -- socket.getaddrinfo is monkeypatched
# to return controlled fake addresses, never a real DNS lookup.
# ============================================================

from __future__ import annotations

import socket

import pytest

from services.ecosystem.errors import ImportFetchError
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url


def _fake_addrinfo(addresses: list[str]):
    def _getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addresses]
    return _getaddrinfo


def test_rejects_non_https_scheme():
    with pytest.raises(ImportFetchError, match="not https"):
        assert_safe_https_url("http://example.com/index.json")


def test_rejects_url_with_no_hostname():
    with pytest.raises(ImportFetchError, match="no hostname"):
        assert_safe_https_url("https:///path")


def test_allows_a_public_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["93.184.216.34"]))
    assert assert_safe_https_url("https://example.com/x") == "https://example.com/x"


def test_rejects_loopback_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["127.0.0.1"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://example.com/x")


def test_rejects_private_range_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["10.0.0.5"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://internal.example.com/x")


def test_rejects_link_local_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["169.254.169.254"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://metadata.example.com/x")


def test_rejects_if_any_resolved_address_is_private_even_with_a_public_one_too(monkeypatch):
    # DNS can return multiple A records -- one public, one not. All must be public.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["93.184.216.34", "10.0.0.5"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://example.com/x")


def test_rejects_unresolvable_hostname(monkeypatch):
    def _raise(*args, **kwargs):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(ImportFetchError, match="could not resolve"):
        assert_safe_https_url("https://does-not-exist.invalid/x")


def test_still_rejects_loopback_by_default_even_with_the_env_var_unset(monkeypatch):
    # The E2E escape hatch (ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS) must be a real
    # opt-in, not accidentally always-on -- explicitly ensures the var is
    # unset (rather than trusting the ambient test environment) before
    # asserting the normal, hardened behavior is unchanged.
    monkeypatch.delenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["127.0.0.1"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://localhost/x")


def test_e2e_env_var_allows_a_loopback_target_when_explicitly_set(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", "true")
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["127.0.0.1"]))
    assert assert_safe_https_url("https://localhost:8999/x") == "https://localhost:8999/x"


def test_e2e_env_var_also_allows_plain_http_to_a_local_host(monkeypatch):
    # The bypass covers BOTH checks this function makes (module docstring):
    # a local test-only OAuth provider (tests/e2e_fixtures/test_oauth_
    # provider.py) realistically can't serve real HTTPS with a trusted
    # cert in this environment either, so gating only the private-IP check
    # would still leave the plain-http case blocked.
    monkeypatch.setenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", "true")
    assert assert_safe_https_url("http://127.0.0.1:8099/authorize") == "http://127.0.0.1:8099/authorize"


def test_e2e_env_var_still_requires_a_real_hostname(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", "true")
    with pytest.raises(ImportFetchError, match="no hostname"):
        assert_safe_https_url("https:///path")


def test_still_rejects_non_https_by_default_even_with_the_env_var_unset(monkeypatch):
    monkeypatch.delenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", raising=False)
    with pytest.raises(ImportFetchError, match="not https"):
        assert_safe_https_url("http://127.0.0.1:8099/authorize")


def test_e2e_env_var_set_to_an_unrecognized_value_does_not_enable_the_bypass(monkeypatch):
    # Defense in depth: only the literal "1"/"true" (case-insensitive)
    # enable this -- a typo'd or unexpected value (e.g. accidentally
    # inheriting "false" from a shell default) must never silently bypass.
    monkeypatch.setenv("ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS", "false")
    monkeypatch.setattr(socket, "getaddrinfo", _fake_addrinfo(["127.0.0.1"]))
    with pytest.raises(ImportFetchError, match="non-public address"):
        assert_safe_https_url("https://localhost/x")
