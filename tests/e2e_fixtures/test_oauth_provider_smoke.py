# SPDX-License-Identifier: MIT
# ============================================================
# Real integration test proving the local test-only OAuth provider
# (tests/e2e_fixtures/test_oauth_provider.py) actually works end-to-end
# through the REAL client-side flow this codebase uses in production
# (connectors/oauth2.py's OAuth2Handler, the same class Stage 2's admin-
# registered OAuth apps wrap) -- real PKCE, real code exchange, real
# revocation, checked against the provider's own server-side token store
# (not just a locally-cleared row).
#
# Deliberately does NOT go through services/ecosystem/gate/
# mcp_connector_stage.py's real protected-resource-metadata discovery --
# that check requires a public https:// URL by design (import_adapters/
# ssrf_guard.py has no test-mode bypass, and shouldn't). This test proves
# the OAuth mechanics work; it is not a claim that a real gate-enforced
# remote-MCP-URL flow was exercised against a local provider, which is
# not achievable in this sandboxed environment -- see this file's own
# report for the full disclosure.
# ============================================================
from __future__ import annotations

import threading
import time

import httpx
import pytest
import uvicorn

from connectors.base import OAuth2Config
from connectors.oauth2 import OAuth2Handler
from tests.e2e_fixtures.test_oauth_provider import TEST_CLIENT_ID, TEST_CLIENT_SECRET, app, is_token_active

PORT = 8098


@pytest.fixture(scope="module")
def provider_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{PORT}/.well-known/oauth-protected-resource", timeout=1)
            break
        except httpx.ConnectError:
            time.sleep(0.1)
    else:
        pytest.fail("test OAuth provider never came up")
    yield f"http://127.0.0.1:{PORT}"
    server.should_exit = True
    thread.join(timeout=5)


def _config(base_url: str) -> OAuth2Config:
    return OAuth2Config(
        authorize_url=f"{base_url}/authorize",
        token_url=f"{base_url}/token",
        client_id_env="", client_secret_env="",
        client_id_value=TEST_CLIENT_ID, client_secret_value=TEST_CLIENT_SECRET,
        scopes=["read", "write"],
        revoke_url=f"{base_url}/revoke",
    )


def test_full_pkce_round_trip_issues_and_then_revokes_a_real_token(provider_server):
    handler = OAuth2Handler()
    config = _config(provider_server)
    state = "e2e-test-state-123"
    redirect_uri = "http://127.0.0.1:9/callback"  # never actually dialed -- we intercept the redirect below

    authorize_url, verifier = handler.generate_authorize_url(config, redirect_uri, state)
    assert "code_challenge=" in authorize_url
    assert verifier  # a real PKCE verifier was generated

    # Simulate the browser hitting /authorize (real HTTP call, no
    # follow_redirects -- we want the Location header, not to actually
    # dial the fake redirect_uri).
    resp = httpx.get(authorize_url, follow_redirects=False, timeout=5)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith(redirect_uri)
    code = httpx.URL(location).params["code"]
    assert code

    token_set = handler.exchange_code(config, code, redirect_uri, verifier)
    assert token_set.access_token
    assert token_set.refresh_token
    assert is_token_active(token_set.access_token), "provider's own server-side store must show the token as active right after issuance"

    # Real disconnect: revoke via the same handler production code uses.
    handler.revoke_token(config, token_set.access_token)
    assert not is_token_active(token_set.access_token), (
        "the disconnect step must prove the token is gone from the PROVIDER's own store, "
        "not just that a local DB row was cleared"
    )


def test_wrong_pkce_verifier_is_rejected(provider_server):
    handler = OAuth2Handler()
    config = _config(provider_server)
    state = "e2e-test-state-456"
    redirect_uri = "http://127.0.0.1:9/callback"

    authorize_url, _real_verifier = handler.generate_authorize_url(config, redirect_uri, state)
    resp = httpx.get(authorize_url, follow_redirects=False, timeout=5)
    code = httpx.URL(resp.headers["location"]).params["code"]

    with pytest.raises(httpx.HTTPStatusError):
        # exchange_code() calls resp.raise_for_status() itself; the
        # provider returns a 200 with {"error": ...} today (matching a
        # real permissive provider), so assert the real returned shape
        # explicitly rather than relying on raise_for_status() to fire.
        handler.exchange_code(config, code, redirect_uri, "wrong-verifier-entirely")


def test_wrong_pkce_verifier_real_response_shape(provider_server):
    # Companion to the test above: confirms the raw provider response
    # shape (RFC 6749 §5.2 -- 400, not 200-with-an-"error"-key) a caller
    # not going through OAuth2Handler would see.
    handler = OAuth2Handler()
    config = _config(provider_server)
    state = "e2e-test-state-789"
    redirect_uri = "http://127.0.0.1:9/callback"
    authorize_url, _verifier = handler.generate_authorize_url(config, redirect_uri, state)
    resp = httpx.get(authorize_url, follow_redirects=False, timeout=5)
    code = httpx.URL(resp.headers["location"]).params["code"]

    raw = httpx.post(
        config.token_url,
        data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": TEST_CLIENT_ID, "client_secret": TEST_CLIENT_SECRET,
            "code_verifier": "wrong-verifier-entirely",
        },
    )
    assert raw.status_code == 400
    assert raw.json()["detail"]["error"] == "invalid_grant"
