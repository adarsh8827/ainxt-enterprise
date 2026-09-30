# SPDX-License-Identifier: MIT
# ============================================================
# Real, full connect -> disconnect OAuth E2E through the ACTUAL production
# HTTP endpoints (routers/connectors_router.py's oauth_start()/
# oauth_callback()/disconnect()), against the real local test-only OAuth
# provider (tests/e2e_fixtures/test_oauth_provider.py) -- not a mock, not
# a unit test of OAuth2Handler in isolation (that's already covered by
# test_oauth_provider_smoke.py). This is what "finish the local test-only
# OAuth provider for CI E2E" (2026-09-30) resolves to at the HTTP-router
# level: a real authorization-code + PKCE exchange, a real token stored
# encrypted in user_oauth_tokens, and a real, checkable server-side revoke
# on disconnect -- proven against the provider's own token store, not just
# a locally-cleared DB row.
#
# Deliberately NOT a Playwright browser test: the provider's own
# /authorize auto-consents (no real login UI to click through), so the
# "browser" step this test simulates via a plain httpx GET with
# follow_redirects=False is behaviorally identical to what a real browser
# does here -- land on /authorize, get redirected straight back with
# ?code=...&state=.... A real browser-level Playwright pass would add
# coverage of the SPA's own post-redirect landing/rendering, not of the
# OAuth mechanics themselves, which is what was actually missing and is
# what this file proves.
# ============================================================

from __future__ import annotations

import threading
import time
import uuid

import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from db.database import SessionLocal
from routers.connectors_router import router as connectors_router
from tests.e2e_fixtures.test_oauth_provider import TEST_CLIENT_ID, TEST_CLIENT_SECRET, app as provider_app, is_token_active

PORT = 8097
# A real UUID, matching a real logged-in user's JWT `sub` claim (users.id
# is a UUID column) -- oauth_callback() has no auth dependency override to
# short-circuit through (it's a plain GET redirect target the provider
# calls), so it genuinely resolves org_id from this value via the DB.
USER_ID = str(uuid.uuid4())
CONNECTOR_NAME = f"e2e_test_oauth_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def provider_server():
    config = uvicorn.Config(provider_app, host="127.0.0.1", port=PORT, log_level="warning")
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


@pytest.fixture
def synthetic_connector(provider_server, monkeypatch):
    """A real connector_definitions row, seeded only by this test, pointed
    at the local test provider -- deliberately never added to
    connectors/seed.py's real SEED_CONNECTORS list (that would ship a fake
    OAuth connector to real deployments)."""
    monkeypatch.setenv("E2E_TEST_OAUTH_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setenv("E2E_TEST_OAUTH_CLIENT_SECRET", TEST_CLIENT_SECRET)
    monkeypatch.setenv("CONNECTOR_OAUTH_REDIRECT_BASE", "http://127.0.0.1:9999")  # unused by this test's own callback call, real value doesn't matter here

    db = SessionLocal()
    try:
        db.execute(
            sa.text(
                "INSERT INTO ainxt.connector_definitions "
                "(name, display_name, description, category, auth_type, auth_config, tools, is_builtin, is_active) "
                "VALUES (:name, :name, 'e2e test connector', 'general', 'oauth2', CAST(:auth_config AS jsonb), '[]'::jsonb, TRUE, TRUE)"
            ),
            {
                "name": CONNECTOR_NAME,
                "auth_config": (
                    '{"authorize_url": "%s/authorize", "token_url": "%s/token", '
                    '"revoke_url": "%s/revoke", "client_id_env": "E2E_TEST_OAUTH_CLIENT_ID", '
                    '"client_secret_env": "E2E_TEST_OAUTH_CLIENT_SECRET", "scopes": ["test:read"], "pkce": true}'
                ) % (provider_server, provider_server, provider_server),
            },
        )
        db.commit()
    finally:
        db.close()

    # Real test-isolation gap found live: connector_registry is a
    # process-wide singleton that loads connector_definitions once and
    # caches it (connectors/registry.py's own "self-heal" comment
    # confirms this is deliberate for a long-running process, not a bug
    # to fix there) -- in a full pytest run, an earlier test in the same
    # process may have already bootstrapped it before this fixture's own
    # INSERT runs, so /connectors/status would never see this synthetic
    # row without forcing a reload. Never reproduced in isolation (this
    # file run alone bootstraps fresh), only in a full-suite batch run.
    from connectors.registry import connector_registry
    connector_registry._load_definitions()

    yield CONNECTOR_NAME

    db = SessionLocal()
    try:
        db.execute(sa.text("DELETE FROM ainxt.connector_definitions WHERE name = :name"), {"name": CONNECTOR_NAME})
        db.execute(sa.text("DELETE FROM ainxt.user_oauth_tokens WHERE connector_name = :name"), {"name": CONNECTOR_NAME})
        db.commit()
    finally:
        db.close()
    connector_registry._load_definitions()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": USER_ID, "user_id": USER_ID, "org_id": "default", "role": "user"}
    return TestClient(app)


def test_real_connect_use_disconnect_flow_against_the_local_test_provider(synthetic_connector):
    client = _client()

    # 1. Connect: the real oauth_start() endpoint returns a real authorize_url.
    start_resp = client.get(f"/connectors/oauth/start/{synthetic_connector}")
    assert start_resp.status_code == 200, start_resp.text
    authorize_url = start_resp.json()["authorize_url"]
    assert authorize_url.startswith(f"http://127.0.0.1:{PORT}/authorize")

    # 2. "Browser" follows it -- the test provider auto-consents (no real
    # login UI) and redirects straight back with ?code=...&state=....
    redirect_resp = httpx.get(authorize_url, follow_redirects=False)
    assert redirect_resp.status_code in (302, 307), redirect_resp.text
    callback_url = redirect_resp.headers["location"]
    assert "code=" in callback_url and "state=" in callback_url

    # 3. The browser lands on the real GET callback route -- oauth_callback()
    # exchanges the code for a real token via the provider's own /token
    # endpoint (real PKCE verification happens there).
    from urllib.parse import urlparse, parse_qs

    query = parse_qs(urlparse(callback_url).query)
    callback_resp = client.get(
        f"/connectors/oauth/callback/{synthetic_connector}",
        params={"code": query["code"][0], "state": query["state"][0]},
        follow_redirects=False,
    )
    assert callback_resp.status_code in (200, 302, 307), callback_resp.text

    # 4. Real proof of a real connection: a real row in user_oauth_tokens,
    # AND the token is genuinely still active at the provider (not just
    # "we wrote a row locally").
    db = SessionLocal()
    try:
        row = db.execute(
            sa.text(
                "SELECT access_token, is_active FROM ainxt.user_oauth_tokens "
                "WHERE user_id = :uid AND connector_name = :cn"
            ),
            {"uid": USER_ID, "cn": synthetic_connector},
        ).fetchone()
    finally:
        db.close()
    assert row is not None, "no user_oauth_tokens row was created by the real oauth_callback()"
    assert row[1] is True

    from store.credential_vault import decrypt_value

    access_token = decrypt_value(row[0])
    assert is_token_active(access_token), "the exchanged token isn't actually active at the provider"

    # 5. Real status endpoint reflects a real connection.
    status_resp = client.get("/connectors/status")
    assert status_resp.status_code == 200, status_resp.text
    entry = next(s for s in status_resp.json() if s["name"] == synthetic_connector)
    assert entry["connected"] is True

    # 6. Disconnect: the real gap fixed 2026-09-30 -- this used to only
    # flip the local is_active flag, leaving the token genuinely valid at
    # the provider. Real proof it's now actually revoked SERVER-SIDE, not
    # just locally: is_token_active() (the provider's OWN store, checked
    # independently of this app's DB) must be False afterward.
    disconnect_resp = client.request("DELETE", f"/connectors/{synthetic_connector}")
    assert disconnect_resp.status_code == 200, disconnect_resp.text
    assert not is_token_active(access_token), "disconnect() did not actually revoke the token at the provider"

    status_resp_after = client.get("/connectors/status")
    entry_after = next(s for s in status_resp_after.json() if s["name"] == synthetic_connector)
    assert entry_after["connected"] is False
