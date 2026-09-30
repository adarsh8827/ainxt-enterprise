# SPDX-License-Identifier: MIT
# ============================================================
# Real gap found live (2026-09-30): a native connector's real OAuth
# flow (routers/connectors_router.py's oauth_start()/oauth_callback())
# only ever read client_id/client_secret from a hardcoded env var --
# connectors/base.py's OAuth2Config.client_id_value/client_secret_value
# already existed and already take precedence over the env var
# (connectors/oauth2.py's _resolve_client_credentials()), but nothing in
# the native-connector code path ever populated them from an admin-
# registered OAuth app (EcosystemOAuthApp / services.ecosystem.
# credential_broker_service.register_oauth_app()) the way the OTHER,
# non-native connector flow in ecosystem_connectors_router.py already did.
# This meant the new Admin -> OAuth Apps screen had no real effect on any
# native connector (github, slack, ...) at all. Tier 2 -- real Postgres.
# ============================================================

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from db.database import SessionLocal
from db.models import User
from routers.connectors_router import _admin_oauth_app_credentials, _org_id_for_user, router as connectors_router
from services.ecosystem.credential_broker_service import register_oauth_app


def _client(user_id: str = "u1", org_id: str = "org-a") -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": "admin"}
    return TestClient(app)


@pytest.fixture
def org_id():
    return f"oauth-app-test-org-{uuid.uuid4().hex[:8]}"


def test_admin_oauth_app_credentials_returns_none_when_nothing_registered(org_id):
    assert _admin_oauth_app_credentials(org_id, "some-provider-with-no-app") == (None, None)


def test_admin_oauth_app_credentials_returns_the_real_registered_client_id_and_decrypted_secret(org_id):
    register_oauth_app(org_id=org_id, provider="test-provider", client_id="cid-123", client_secret="csecret-456", created_by="admin-1")
    client_id, client_secret = _admin_oauth_app_credentials(org_id, "test-provider")
    assert client_id == "cid-123"
    assert client_secret == "csecret-456"


def test_org_id_for_user_resolves_from_the_real_users_table():
    user_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(User(id=user_id, email=f"{user_id}@test.local", name="Test User", org_id="resolved-org-x"))
        db.commit()
    finally:
        db.close()
    try:
        assert _org_id_for_user(user_id) == "resolved-org-x"
    finally:
        db2 = SessionLocal()
        try:
            db2.query(User).filter(User.id == user_id).delete()
            db2.commit()
        finally:
            db2.close()


def test_org_id_for_user_falls_back_to_default_for_an_unknown_user():
    assert _org_id_for_user(str(uuid.uuid4())) == "default"


def test_oauth_start_gives_a_clear_ask_your_admin_message_when_nothing_is_configured(org_id, monkeypatch):
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    resp = _client(org_id=org_id).get("/connectors/oauth/start/slack")
    assert resp.status_code == 400, resp.text
    body = resp.json()["detail"]
    assert body["code"] == "OAUTH_APP_NOT_CONFIGURED"
    assert "ask your admin" in body["message"].lower()
    assert body["details"]["admin_setup_path"] == "/marketplace/admin/oauth-apps"


def test_oauth_start_uses_the_admin_registered_app_over_an_unset_env_var(org_id, monkeypatch):
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    register_oauth_app(org_id=org_id, provider="slack", client_id="admin-configured-client-id", client_secret="admin-secret", created_by="admin-1")

    resp = _client(org_id=org_id).get("/connectors/oauth/start/slack")
    assert resp.status_code == 200, resp.text
    authorize_url = resp.json()["authorize_url"]
    assert "client_id=admin-configured-client-id" in authorize_url
