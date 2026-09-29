# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM CREDENTIAL BROKER
# docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 2. Flag: ECOSYSTEM_CREDENTIAL_BROKER
# (core/config.py, default off).
#
# Read-through for EXISTING native connectors: this service never becomes a
# second source of truth for connectors/registry.py's own state. It calls
# into registry.get_user_status()/list_connected_tools() and translates the
# result into this phase's ConnectionStatus shape (CONTRACTS.md §1).
#
# OAuth 2.1 flows reuse connectors/oauth2.py's OAuth2Handler wholesale — PKCE,
# state/nonce, refresh, revoke are NOT reimplemented here.
#
# Known gap this must NOT inherit: the pre-existing /connectors/execute /
# /connectors/status-for-user impersonation gap noted in ECOSYSTEM_PLAN.md —
# every function below takes the CALLER's own org_id/user_id as an explicit,
# separately-verified argument; it is the router layer's job (not this
# service's) to derive those from the authenticated session, never from a
# request body field a caller could set to someone else's id.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from connectors.oauth2 import OAuth2Handler
from connectors.registry import connector_registry
from core.logger import logger
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from store import ecosystem_secret_store as secret_store

oauth2_handler = OAuth2Handler()


class CredentialBrokerError(Exception):
    """Real broker failure — never used for a plain not-connected/not-found state."""


# ── OAuth app registration (admin) ───────────────────────────────

def register_oauth_app(
    org_id: str,
    provider: str,
    client_id: str,
    client_secret: str,
    created_by: str,
    redirect_uri: Optional[str] = None,
    scopes: Optional[list[str]] = None,
) -> dict:
    """Admin registers a provider's OAuth client id/secret for *org_id*.
    The secret is stored via ecosystem_secret_store (kind='platform'),
    never inline on the ecosystem_oauth_apps row."""
    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    secret_name = f"oauth_client_secret:{org_id}:{provider}"
    secret_row = secret_store.create_secret(
        org_id=org_id, kind="platform", name=secret_name, value=client_secret,
    )

    db = SessionLocal()
    try:
        record = EcosystemOAuthApp(
            org_id=org_id,
            provider=provider,
            client_id=client_id,
            client_secret_ref=secret_row["id"],
            redirect_uri=redirect_uri,
            scopes=scopes or [],
            created_by=created_by,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(f"CredentialBroker: registered OAuth app for org={org_id} provider={provider}")
        return {
            "id": str(record.id), "org_id": record.org_id, "provider": record.provider,
            "client_id": record.client_id, "redirect_uri": record.redirect_uri,
            "scopes": record.scopes, "created_by": record.created_by,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
    finally:
        db.close()


def get_oauth_app_client_secret(org_id: str, provider: str) -> Optional[str]:
    """Resolve a registered OAuth app's client secret for use in a real
    token exchange/refresh call. Callers must audit-log before invoking."""
    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemOAuthApp)
            .filter(EcosystemOAuthApp.org_id == org_id, EcosystemOAuthApp.provider == provider)
            .first()
        )
        if not row:
            return None
        return secret_store.get_secret_value(org_id=org_id, kind="platform", name=f"oauth_client_secret:{org_id}:{provider}")
    finally:
        db.close()


# ── Connection status (read-through for native connectors) ──────

@dataclass
class ConnectionStatusResult:
    connector_ref: str
    status: str  # ConnectionStatus enum value, CONTRACTS.md §1
    last_connected_at: Optional[str] = None
    expires_at: Optional[str] = None


def get_connection_status(org_id: str, user_id: str, connector_ref: str) -> ConnectionStatusResult:
    """Read-through status for a native connector. Delegates to
    connectors/registry.py's get_user_status() — never queries
    ecosystem_connections as the source of truth for these; that table is
    refreshed FROM this call, not read instead of it, for native connectors."""
    native_statuses = connector_registry.get_user_status(user_id)
    for entry in native_statuses:
        if entry.get("name") == connector_ref or entry.get("connector") == connector_ref:
            connected = bool(entry.get("connected"))
            status = "connected" if connected else "not_connected"
            _upsert_connection_cache(org_id, user_id, connector_ref, status)
            return ConnectionStatusResult(connector_ref=connector_ref, status=status)

    # Not a known native connector — fall back to our own cached row (remote
    # MCP servers / connectors added through this phase, not registry-backed).
    cached = _read_connection_cache(org_id, user_id, connector_ref)
    if cached:
        return ConnectionStatusResult(**cached)
    return ConnectionStatusResult(connector_ref=connector_ref, status="not_connected")


def _read_connection_cache(org_id: str, user_id: str, connector_ref: str) -> Optional[dict]:
    from db.database import SessionLocal
    from db.models import EcosystemConnection

    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemConnection)
            .filter(
                EcosystemConnection.org_id == org_id,
                EcosystemConnection.user_id == user_id,
                EcosystemConnection.connector_ref == connector_ref,
            )
            .first()
        )
        if not row:
            return None
        return {
            "connector_ref": row.connector_ref,
            "status": row.status,
            "last_connected_at": row.last_connected_at.isoformat() if row.last_connected_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
    finally:
        db.close()


def _upsert_connection_cache(org_id: str, user_id: str, connector_ref: str, status: str) -> None:
    from datetime import datetime

    from db.database import SessionLocal
    from db.models import EcosystemConnection

    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemConnection)
            .filter(
                EcosystemConnection.org_id == org_id,
                EcosystemConnection.user_id == user_id,
                EcosystemConnection.connector_ref == connector_ref,
            )
            .first()
        )
        now = datetime.utcnow()
        if row:
            row.status = status
            row.updated_at = now
            if status == "connected":
                row.last_connected_at = now
        else:
            row = EcosystemConnection(
                org_id=org_id, user_id=user_id, connector_ref=connector_ref, status=status,
                last_connected_at=now if status == "connected" else None,
            )
            db.add(row)
        db.commit()
    finally:
        db.close()


# ── Remote MCP protected-resource metadata discovery ─────────────
# RFC 9728-shaped `.well-known/oauth-protected-resource` fetch. Genuinely
# new — nothing else in the repo covers remote-MCP OAuth. Operator/admin-
# configured URL, so unlike the offline-bundle-mode path this DOES run
# through the SSRF guard (fetched at runtime, not a static trusted config).

def discover_protected_resource_metadata(resource_url: str) -> dict:
    """Fetch and return the OAuth protected-resource metadata document for
    a remote MCP server's *resource_url*. Raises CredentialBrokerError on
    any failure (non-https, private-address, non-2xx, malformed JSON)."""
    from urllib.parse import urljoin, urlsplit

    assert_safe_https_url(resource_url)
    parsed = urlsplit(resource_url)
    metadata_url = urljoin(f"{parsed.scheme}://{parsed.netloc}/", ".well-known/oauth-protected-resource")
    assert_safe_https_url(metadata_url)

    from connectors.net_relay import relay_request

    try:
        response = relay_request("GET", metadata_url, timeout=15.0)
    except Exception as exc:
        raise CredentialBrokerError(f"protected-resource metadata fetch failed: {exc}") from exc

    if response.status_code != 200:
        raise CredentialBrokerError(
            f"protected-resource metadata fetch returned HTTP {response.status_code} for {metadata_url}"
        )
    try:
        return response.json()
    except Exception as exc:
        raise CredentialBrokerError(f"protected-resource metadata was not valid JSON: {exc}") from exc
