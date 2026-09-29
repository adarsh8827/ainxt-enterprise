# SPDX-License-Identifier: MIT
# ============================================================
# services/ecosystem/credential_broker_service.py — Connectors/Plugins
# phase. Real DB tests (ainxt_test) for OAuth-app registration + the
# native-connector read-through path; a real SSRF-guard test against the
# actual assert_safe_https_url() used by discover_protected_resource_metadata.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from core.ckms.key_service import KeyService
from services.ecosystem import credential_broker_service as broker


@pytest.fixture(autouse=True)
def _test_key_service():
    KeyService.reset_for_tests()
    KeyService.instance().install(cache={"KEY_CREDS": b"\x22" * 32}, mapping={})
    yield
    KeyService.reset_for_tests()


@pytest.fixture
def org_id():
    return f"org-{uuid.uuid4().hex[:8]}"


def test_register_and_resolve_oauth_app_client_secret(org_id):
    app = broker.register_oauth_app(
        org_id=org_id, provider="test-provider", client_id="client-123",
        client_secret="super-secret-client-value", created_by="admin-1",
        redirect_uri="https://app.example.com/callback", scopes=["read"],
    )
    assert app["provider"] == "test-provider"
    assert app["client_id"] == "client-123"
    assert "client_secret" not in app  # never returned inline

    resolved = broker.get_oauth_app_client_secret(org_id, "test-provider")
    assert resolved == "super-secret-client-value"


def test_get_connection_status_read_through_delegates_to_native_registry(org_id, monkeypatch):
    """The broker must not invent its own connection state for a native
    connector — it must call connectors/registry.py's get_user_status()
    and translate the result, not read/write a second copy."""
    calls = []

    def fake_get_user_status(user_id):
        calls.append(user_id)
        return [{"name": "gitlab", "connected": True, "connected_as": "alice@example.com"}]

    monkeypatch.setattr(broker.connector_registry, "get_user_status", fake_get_user_status)

    result = broker.get_connection_status(org_id, "user-1", "gitlab")
    assert calls == ["user-1"]
    assert result.status == "connected"
    assert result.connector_ref == "gitlab"


def test_get_connection_status_not_connected_when_registry_says_no(org_id, monkeypatch):
    monkeypatch.setattr(
        broker.connector_registry, "get_user_status",
        lambda user_id: [{"name": "gitlab", "connected": False}],
    )
    result = broker.get_connection_status(org_id, "user-1", "gitlab")
    assert result.status == "not_connected"


def test_get_connection_status_falls_back_to_cache_for_unknown_connector(org_id, monkeypatch):
    """A connector_ref that isn't a native connector (e.g. a remote MCP
    server added via this phase) has no registry entry at all — must fall
    back to the ecosystem_connections cache, defaulting to not_connected."""
    monkeypatch.setattr(broker.connector_registry, "get_user_status", lambda user_id: [])
    result = broker.get_connection_status(org_id, "user-1", "remote-mcp-server-xyz")
    assert result.status == "not_connected"


def test_discover_protected_resource_metadata_rejects_non_https(org_id):
    with pytest.raises(Exception):
        broker.discover_protected_resource_metadata("http://example.com")


def test_discover_protected_resource_metadata_rejects_private_address(org_id):
    """Real SSRF-guard behavior: a resource URL resolving to a private/
    loopback address must be refused before any request is attempted."""
    with pytest.raises(Exception):
        broker.discover_protected_resource_metadata("https://127.0.0.1")


def test_discover_protected_resource_metadata_rejects_localhost_hostname(org_id):
    with pytest.raises(Exception):
        broker.discover_protected_resource_metadata("https://localhost")
