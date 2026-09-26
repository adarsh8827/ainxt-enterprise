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
