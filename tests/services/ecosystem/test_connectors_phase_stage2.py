# SPDX-License-Identifier: MIT
# ============================================================
# Stage 2 (Connectors) backend tests -- docs/ecosystem/CONNECTORS_PHASE_PLAN.md.
# Covers: gate stage 7 SSRF rejection, tool-approval classification/audit/
# auto-approve, cross-org 404 on the new router endpoints, OAuth callback
# tampered-state rejection + happy path.
# ============================================================

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from core.ckms.key_service import KeyService
from db.database import SessionLocal
from db.models import EcosystemAudit, EcosystemItem, EcosystemItemVersion, EcosystemOAuthApp
from routers.ecosystem_connectors_router import router as connectors_router
from services.ecosystem import tool_approval_service
from services.ecosystem.gate import mcp_connector_stage

ORG_A, ORG_B = "conn-test-org-a", "conn-test-org-b"


@pytest.fixture(autouse=True)
def _install_test_dek():
    """Same convention as tests/store/test_ecosystem_secret_store.py -- a
    throwaway 32-byte DEK for KEY_CREDS so the OAuth-app secret path
    (store/ecosystem_secret_store.py) can encrypt/decrypt in-process."""
    KeyService.reset_for_tests()
    KeyService.instance().install(cache={"KEY_CREDS": b"\x22" * 32}, mapping={})
    yield
    KeyService.reset_for_tests()


# ── Gate stage 7: SSRF / HTTPS-only ──────────────────────────────────────

def test_skill_item_type_stays_a_no_op():
    result = mcp_connector_stage.run("skill", {"connector_url": "http://169.254.169.254/"})
    assert result.verdict == "pass"
    assert result.findings == []


def test_connector_rejects_a_private_address_url():
    result = mcp_connector_stage.run("connector", {"connector_url": "https://169.254.169.254/"})
    assert result.verdict == "fail"
    assert any(f.code == "UNSAFE_CONNECTOR_URL" for f in result.findings)


def test_connector_rejects_a_plain_http_url():
    result = mcp_connector_stage.run("connector", {"connector_url": "http://example.com/"})
    assert result.verdict == "fail"
    assert any(f.code == "UNSAFE_CONNECTOR_URL" for f in result.findings)


def test_connector_with_no_urls_and_no_tools_passes():
    result = mcp_connector_stage.run("connector", {})
    assert result.verdict == "pass"


def test_mcp_server_flags_an_unclassifiable_tool_as_info_not_block():
    result = mcp_connector_stage.run("mcp_server", {"tools": [{"name": "mystery_tool"}]})
    assert result.verdict == "pass"
    assert any(f.code == "TOOL_CLASSIFICATION_DEFAULTED" and f.severity == "info" for f in result.findings)


# ── Tool approval service ────────────────────────────────────────────────

def _audit_count(org_id: str, action: str) -> int:
    db = SessionLocal()
    try:
        return db.query(EcosystemAudit).filter(EcosystemAudit.org_id == org_id, EcosystemAudit.action == action).count()
    finally:
        db.close()


def test_read_tool_is_never_gated_and_is_audited():
    org_id = f"approval-test-{uuid.uuid4().hex[:8]}"
    before = _audit_count(org_id, "tool_call_readonly")
    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="u1", tool_name="search_files",
        tool_def={"name": "search_files", "annotations": {"readOnlyHint": True}},
    )
    assert result == {"requires_approval": False, "status": "read_allowed"}
    assert _audit_count(org_id, "tool_call_readonly") == before + 1


def test_write_tool_creates_a_pending_approval_and_is_audited():
    org_id = f"approval-test-{uuid.uuid4().hex[:8]}"
    before = _audit_count(org_id, "tool_call_pending")
    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="u1", tool_name="send_email",
        tool_def={"name": "send_email", "annotations": {"destructiveHint": False, "readOnlyHint": False}},
        params={"to": "a@b.com"},
    )
    assert result["requires_approval"] is True
    assert result["status"] == "pending"
    assert _audit_count(org_id, "tool_call_pending") == before + 1

    pending = tool_approval_service.list_pending(org_id, "u1")
    assert any(p["id"] == result["approval_id"] for p in pending)

    approved = tool_approval_service.approve(org_id, "u1", result["approval_id"])
    assert approved == {"status": "approved"}
    assert _audit_count(org_id, "tool_call_approved") == 1
    # Resolving twice is a real failure, not a silent no-op.
    with pytest.raises(tool_approval_service.ToolApprovalError):
        tool_approval_service.approve(org_id, "u1", result["approval_id"])


def test_destructive_tool_can_be_denied():
    org_id = f"approval-test-{uuid.uuid4().hex[:8]}"
    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="u1", tool_name="delete_repo",
        tool_def={"name": "delete_repo", "annotations": {"destructiveHint": True}},
    )
    denied = tool_approval_service.deny(org_id, "u1", result["approval_id"])
    assert denied == {"status": "denied"}
    assert _audit_count(org_id, "tool_call_denied") == 1


def test_auto_approve_policy_bypasses_the_pending_row():
    org_id = f"approval-test-{uuid.uuid4().hex[:8]}"
    from db.models import EcosystemToolAutoApprovePolicy

    db = SessionLocal()
    try:
        db.add(EcosystemToolAutoApprovePolicy(id=str(uuid.uuid4()), org_id=org_id, tool_name="safe_write_tool", enabled_by="admin1"))
        db.commit()
    finally:
        db.close()

    before = _audit_count(org_id, "tool_call_auto_approved")
    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="u1", tool_name="safe_write_tool",
        tool_def={"name": "safe_write_tool", "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    )
    assert result == {"requires_approval": False, "status": "auto_approved"}
    assert _audit_count(org_id, "tool_call_auto_approved") == before + 1
    assert tool_approval_service.list_pending(org_id, "u1") == []


# ── Router: cross-org isolation ──────────────────────────────────────────

def _client(org_id: str, user_id: str = "u1", role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": role}
    return TestClient(app)


def test_oauth_apps_are_isolated_per_org():
    provider = f"test-provider-{uuid.uuid4().hex[:8]}"
    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        client_a = _client(ORG_A)
        created = client_a.post(
            "/ainxt/v1/api/ecosystem/admin/oauth-apps",
            json={"provider": provider, "client_id": "cid-a", "client_secret": "secret-a", "scopes": []},
        )
        assert created.status_code == 201, created.text
        assert "client_secret" not in created.json()
        app_id = created.json()["id"]

        # Org A sees it.
        listing_a = client_a.get("/ainxt/v1/api/ecosystem/admin/oauth-apps")
        assert any(a["id"] == app_id for a in listing_a.json()["apps"])

        # Org B does not.
        client_b = _client(ORG_B)
        listing_b = client_b.get("/ainxt/v1/api/ecosystem/admin/oauth-apps")
        assert all(a["id"] != app_id for a in listing_b.json()["apps"])

        # Org B cannot delete Org A's app.
        delete_cross_org = client_b.delete(f"/ainxt/v1/api/ecosystem/admin/oauth-apps/{app_id}")
        assert delete_cross_org.status_code == 404


def test_admin_oauth_apps_requires_admin_permission():
    client = _client(ORG_A, role="developer")
    resp = client.post(
        "/ainxt/v1/api/ecosystem/admin/oauth-apps",
        json={"provider": "test-provider-2", "client_id": "x", "client_secret": "y", "scopes": []},
    )
    assert resp.status_code == 403


def test_connections_list_is_scoped_to_the_caller_only():
    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        client_a = _client(ORG_A, user_id="user-a")
        client_b = _client(ORG_B, user_id="user-b")

        from services.ecosystem.credential_broker_service import _upsert_connection_cache

        _upsert_connection_cache(ORG_A, "user-a", "some-remote-mcp", "connected")

        resp_a = client_a.get("/ainxt/v1/api/ecosystem/connections")
        assert any(c["connector_ref"] == "some-remote-mcp" for c in resp_a.json()["connections"])

        resp_b = client_b.get("/ainxt/v1/api/ecosystem/connections")
        assert all(c["connector_ref"] != "some-remote-mcp" for c in resp_b.json()["connections"])


def test_connect_native_connector_with_truly_empty_request_body():
    # Regression: packages/ecosystem-ui's RealEcosystemClient.connect() posts
    # with NO body at all (fetch(url, {method: "POST"}) never sets one) --
    # not even "{}". A bare `body: ConnectRequest` param (no default on the
    # parameter itself) makes FastAPI require *some* body and 422 on a truly
    # empty POST even though every field of ConnectRequest is optional. Both
    # /connect and /reconnect need `= ConnectRequest()` as their own default.
    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]), \
         patch(
             "routers.ecosystem_connectors_router._is_native_connector",
             return_value=True,
         ), patch(
             "routers.ecosystem_connectors_router._connect_native_async",
             return_value={"status": "connecting", "authorize_url": "https://example.com/authorize"},
         ):
        client = _client(ORG_A, user_id="user-a")
        resp = client.post("/ainxt/v1/api/ecosystem/connections/some-native-connector/connect")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "connecting"

        resp2 = client.post("/ainxt/v1/api/ecosystem/connections/some-native-connector/reconnect")
        assert resp2.status_code == 200, resp2.text


# ── OAuth callback: tampered state + happy path ──────────────────────────

def test_oauth_callback_rejects_an_unknown_state():
    client = _client(ORG_A, user_id="user-a")
    resp = client.post(
        "/ainxt/v1/api/ecosystem/connections/some-connector/oauth-callback",
        json={"code": "irrelevant", "state": "this-state-was-never-issued"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert resp.json()["code"] == "INVALID_STATE"


def _create_connector_item(namespace: str, manifest: dict) -> None:
    db = SessionLocal()
    try:
        from db.models import EcosystemSource

        source = db.query(EcosystemSource).filter(EcosystemSource.kind == "local").first()
        if not source:
            source = EcosystemSource(id=str(uuid.uuid4()), kind="local", org_id=None, created_by="test-fixture")
            db.add(source)
            db.commit()

        item = EcosystemItem(
            id=str(uuid.uuid4()), namespace=namespace, item_type="connector", category="productivity",
            display_name="Test Connector", description="d", source_id=source.id, org_id=ORG_A,
            license="MIT", status="active",
        )
        db.add(item)
        db.flush()
        version = EcosystemItemVersion(
            id=str(uuid.uuid4()), item_id=item.id, version="1.0.0", content_hash="deadbeef",
            object_key="test/key", license="MIT", attribution="MIT", manifest=manifest, gate_verdict="pass",
        )
        db.add(version)
        db.commit()
    finally:
        db.close()


def test_oauth_callback_happy_path_stores_tokens_and_marks_connected():
    connector_ref = f"conn-test/oauth-{uuid.uuid4().hex[:8]}"
    provider = f"happy-provider-{uuid.uuid4().hex[:8]}"
    _create_connector_item(connector_ref, {
        "oauth": {"provider": provider, "authorize_url": "https://example.com/authorize", "token_url": "https://example.com/token"},
    })

    db = SessionLocal()
    try:
        db.add(EcosystemOAuthApp(
            id=str(uuid.uuid4()), org_id=ORG_A, provider=provider, client_id="cid",
            client_secret_ref=_seed_secret_ref(provider), redirect_uri=None, scopes=[], created_by="user-a",
        ))
        db.commit()
    finally:
        db.close()

    from connectors.oauth2 import oauth2_handler as global_oauth2_handler

    state = f"test-state-happy-path-{uuid.uuid4().hex}"
    global_oauth2_handler.save_state(state, "user-a", connector_ref, "verifier123")

    class _FakeTokenSet:
        access_token = "fake-access-token"
        refresh_token = "fake-refresh-token"
        expires_at = 9999999999

    client = _client(ORG_A, user_id="user-a")
    with patch("services.ecosystem.credential_broker_service.oauth2_handler.exchange_code", return_value=_FakeTokenSet()):
        resp = client.post(
            f"/ainxt/v1/api/ecosystem/connections/{connector_ref}/oauth-callback",
            json={"code": "auth-code-123", "state": state, "redirect_uri": "https://frontend.example.com/callback"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected"

    from services.ecosystem.credential_broker_service import get_connection_status

    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        status = get_connection_status(ORG_A, "user-a", connector_ref)
    assert status.status == "connected"


def _seed_secret_ref(provider: str) -> str:
    from store import ecosystem_secret_store as secret_store

    row = secret_store.create_secret(org_id=ORG_A, kind="platform", name=f"oauth_client_secret:{ORG_A}:{provider}", value="shh")
    return row["id"]
