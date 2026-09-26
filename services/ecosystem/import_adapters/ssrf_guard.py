# SPDX-License-Identifier: MIT
# ============================================================
# SSRF guard for the external-import adapters (task I, pre-M3).
#
# No existing SSRF (private-IP-blocking) validator exists elsewhere in this
# codebase — searched core/, connectors/, agents/ for one before writing
# this. connectors/net_relay.py's relay_request() is a real, existing
# "outbound guard" pattern, but it's an egress-topology relay (routes
# through LLM_PROXY_URL when the host has no direct internet access), not
# an SSRF validator — it never checks whether the destination is a
# private/loopback address. Both adapters reuse relay_request() for the
# actual HTTP transport (so imports respect the same proxy configuration
# as every other outbound connector call) and this module for the new
# validation relay_request itself doesn't do.
# ============================================================

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from services.ecosystem.errors import ImportFetchError

# A caller-supplied URL (a GitHub path, a well-known domain) always
# resolves to a fresh DNS lookup here rather than trusting a cached/
# previously-validated result — protects against DNS-rebinding (the
# hostname resolving to a public IP at check time and a private one at
# fetch time). Both adapters call assert_safe_https_url() immediately
# before every actual request, not just once per import.


def assert_safe_https_url(url: str) -> str:
    """Raises ImportFetchError unless url is a well-formed https:// URL
    whose hostname resolves to at least one address, and ALL resolved
    addresses are public (no private/loopback/link-local/multicast/
    reserved ranges). Returns the url unchanged on success, for chaining.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ImportFetchError(f"import fetch refused: {url!r} is not https://")
    hostname = parsed.hostname
    if not hostname:
        raise ImportFetchError(f"import fetch refused: {url!r} has no hostname")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ImportFetchError(f"import fetch refused: could not resolve {hostname!r}: {exc}") from exc

    if not addr_infos:
        raise ImportFetchError(f"import fetch refused: {hostname!r} resolved to no addresses")

    for family, _, _, _, sockaddr in addr_infos:
        raw_ip = sockaddr[0]
        ip = ipaddress.ip_address(raw_ip)
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            raise ImportFetchError(
                f"import fetch refused: {hostname!r} resolves to a non-public address ({raw_ip}) — "
                "refusing to fetch a private/loopback/link-local/reserved destination"
            )

    return url
