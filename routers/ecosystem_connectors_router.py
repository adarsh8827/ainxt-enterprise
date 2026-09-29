# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM CONNECTORS ROUTER — /ecosystem/connections/*, /ecosystem/admin/
# oauth-apps/*, /ecosystem/tool-calls/* (docs/ecosystem/
# CONNECTORS_PHASE_PLAN.md §1 items 3-4).
#
# For NATIVE connectors (already in connectors/registry.py's
# connector_definitions), connect/disconnect DELEGATE to the existing
# routers/connectors_router.py OAuth flow rather than reimplementing it --
# same real functions, called directly (they are plain async functions,
# not inline-only route closures).
#
# For NEW connector/mcp_server items added through this phase (an
# EcosystemItem whose manifest declares its own oauth config), connect/
# disconnect use credential_broker_service + a DB-backed OAuth2Config
# (connectors/base.py's client_id_value/client_secret_value fields).
#
# Every handler derives org_id/user_id from the AUTHENTICATED caller only
# -- never from a request body/query field -- closing the impersonation
# gap noted against the existing /connectors/execute /
# /connectors/status-for-user endpoints.
# ============================================================

from __future__ import annotations

import secrets as _secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.dependencies import get_current_user
from auth.rbac import get_all_permissions, require_permission
from services.ecosystem import tool_approval_service
from services.ecosystem.credential_broker_service import (
    CredentialBrokerError,
    discover_protected_resource_metadata,
    get_connection_status,
    get_oauth_app_client_secret,
    oauth2_handler,
    register_oauth_app,
)
from services.ecosystem.errors import ImportFetchError, NotFoundError
from services.ecosystem.tool_approval_service import ToolApprovalError

router = APIRouter(tags=["ecosystem-connectors"], dependencies=[Depends(get_current_user)])


def _caller_context(current_user: dict) -> tuple[str, str]:
    user_id = current_user.get("sub") or current_user.get("user_id") or current_user.get("id") or ""
    org_id = current_user.get("org_id") or "default"
    return user_id, org_id


# ── Connector item lookup (non-native connector/mcp_server items) ───────

def _find_connector_item(connector_ref: str) -> Optional[dict]:
    """Look up an EcosystemItem of type connector/mcp_server by namespace,
    returning its latest version's manifest. None if not found or not one
    of those two item types -- callers fall back to treating connector_ref
    as a native connector name in that case."""
    from db.database import SessionLocal
    from db.models import EcosystemItem, EcosystemItemVersion

    db = SessionLocal()
    try:
        item = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.namespace == connector_ref, EcosystemItem.item_type.in_(("connector", "mcp_server")))
            .first()
        )
        if not item:
            return None
        version = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item.id)
            .order_by(EcosystemItemVersion.created_at.desc())
            .first()
        )
        return {"item_id": str(item.id), "manifest": (version.manifest if version else {}) or {}}
    finally:
        db.close()


def _is_native_connector(connector_ref: str) -> bool:
    from routers.connectors_router import _load_definition

    try:
        _load_definition(connector_ref)
        return True
    except ValueError:
        return False


# ── GET /ecosystem/connections ───────────────────────────────────────────

class ConnectionModel(BaseModel):
    connector_ref: str
    item_id: Optional[str] = None
    status: str
    last_connected_at: Optional[str] = None
    expires_at: Optional[str] = None


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionModel]


@router.get("/ecosystem/connections", response_model=ConnectionsResponse)
def list_connections(current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)

    from connectors.registry import connector_registry

    native_statuses = connector_registry.get_user_status(user_id)
    connections = [
        {
            "connector_ref": entry.get("name") or entry.get("connector"),
            "item_id": None,
            "status": "connected" if entry.get("connected") else "not_connected",
            "last_connected_at": None,
            "expires_at": None,
        }
        for entry in native_statuses
    ]

    from db.database import SessionLocal
    from db.models import EcosystemConnection, EcosystemItem

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemConnection, EcosystemItem)
            .outerjoin(EcosystemItem, EcosystemItem.namespace == EcosystemConnection.connector_ref)
            .filter(EcosystemConnection.org_id == org_id, EcosystemConnection.user_id == user_id)
            .all()
        )
    finally:
        db.close()

    seen = {c["connector_ref"] for c in connections}
    for conn, item in rows:
        if conn.connector_ref in seen:
            continue
        connections.append({
            "connector_ref": conn.connector_ref,
            "item_id": str(item.id) if item else None,
            "status": conn.status,
            "last_connected_at": conn.last_connected_at.isoformat() if conn.last_connected_at else None,
            "expires_at": conn.expires_at.isoformat() if conn.expires_at else None,
        })

    return {"connections": connections}


# ── Connect / callback / disconnect / reconnect ──────────────────────────

class ConnectRequest(BaseModel):
    redirect_uri: Optional[str] = None


async def _connect_native_async(connector_ref: str, current_user: dict) -> dict:
    from routers.connectors_router import oauth_start

    result = await oauth_start(connector_ref, request=None, current_user=current_user)
    return {"status": "connecting", "authorize_url": result["authorize_url"]}


@router.post("/ecosystem/connections/{connector_ref:path}/connect")
async def connect(connector_ref: str, body: ConnectRequest = ConnectRequest(), current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)

    if _is_native_connector(connector_ref):
        try:
            return await _connect_native_async(connector_ref, current_user)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"code": "CONNECT_FAILED", "message": str(exc), "retryable": True})

    found = _find_connector_item(connector_ref)
    if not found:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"connector {connector_ref!r} not found", "retryable": False})

    oauth_cfg = (found["manifest"] or {}).get("oauth")
    if not oauth_cfg:
        # API-key/header connector with no OAuth step -- nothing further
        # to do here; a real API-key connect path is a Stage 3 concern
        # (custom MCP URL with header auth) not yet built.
        return {"status": "connected"}

    if not body.redirect_uri:
        raise HTTPException(status_code=400, detail={"code": "REDIRECT_URI_REQUIRED", "message": "redirect_uri is required to connect a non-native OAuth connector", "retryable": False})

    provider = oauth_cfg.get("provider") or connector_ref
    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    db = SessionLocal()
    try:
        app_row = (
            db.query(EcosystemOAuthApp)
            .filter(EcosystemOAuthApp.org_id == org_id, EcosystemOAuthApp.provider == provider)
            .first()
        )
    finally:
        db.close()
    if not app_row:
        raise HTTPException(status_code=422, detail={"code": "OAUTH_APP_NOT_REGISTERED", "message": f"no OAuth app registered for provider {provider!r} in this org", "retryable": False})

    client_secret = get_oauth_app_client_secret(org_id, provider)

    from connectors.base import OAuth2Config

    config = OAuth2Config(
        authorize_url=oauth_cfg.get("authorize_url", ""),
        token_url=oauth_cfg.get("token_url", ""),
        client_id_env="", client_secret_env="",
        scopes=oauth_cfg.get("scopes", []),
        revoke_url=oauth_cfg.get("revoke_url"),
        client_id_value=app_row.client_id,
        client_secret_value=client_secret,
    )
    state = _secrets.token_urlsafe(32)
    try:
        authorize_url, pkce_verifier = oauth2_handler.generate_authorize_url(config, body.redirect_uri, state)
        oauth2_handler.save_state(state, user_id, connector_ref, pkce_verifier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "CONNECT_FAILED", "message": str(exc), "retryable": True})

    return {"status": "connecting", "authorize_url": authorize_url}


@router.post("/ecosystem/connections/{connector_ref:path}/reconnect")
async def reconnect(connector_ref: str, body: ConnectRequest = ConnectRequest(), current_user: dict = Depends(get_current_user)):
    return await connect(connector_ref, body, current_user)


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: Optional[str] = None


@router.post("/ecosystem/connections/{connector_ref:path}/oauth-callback")
def oauth_callback(connector_ref: str, body: OAuthCallbackRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)

    state_data = oauth2_handler.load_state(body.state)
    if not state_data or state_data.get("connector_name") != connector_ref or state_data.get("user_id") != user_id:
        return {"status": "error", "code": "INVALID_STATE"}

    found = _find_connector_item(connector_ref)
    if not found or not (found["manifest"] or {}).get("oauth"):
        return {"status": "error", "code": "NOT_FOUND"}

    oauth_cfg = found["manifest"]["oauth"]
    provider = oauth_cfg.get("provider") or connector_ref

    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    db = SessionLocal()
    try:
        app_row = (
            db.query(EcosystemOAuthApp)
            .filter(EcosystemOAuthApp.org_id == org_id, EcosystemOAuthApp.provider == provider)
            .first()
        )
    finally:
        db.close()
    if not app_row:
        return {"status": "error", "code": "OAUTH_APP_NOT_REGISTERED"}

    from connectors.base import OAuth2Config

    config = OAuth2Config(
        authorize_url=oauth_cfg.get("authorize_url", ""),
        token_url=oauth_cfg.get("token_url", ""),
        client_id_env="", client_secret_env="",
        scopes=oauth_cfg.get("scopes", []),
        revoke_url=oauth_cfg.get("revoke_url"),
        client_id_value=app_row.client_id,
        client_secret_value=get_oauth_app_client_secret(org_id, provider),
    )

    try:
        token_set = oauth2_handler.exchange_code(
            config, body.code, body.redirect_uri or "", state_data.get("pkce_verifier", ""),
        )
    except Exception as exc:
        return {"status": "needs_reauth", "code": "EXCHANGE_FAILED", "message": str(exc)}

    from datetime import datetime

    from store import ecosystem_secret_store as secret_store

    secret_name = f"oauth_tokens:{connector_ref}"
    payload = {"access_token": token_set.access_token, "refresh_token": token_set.refresh_token, "expires_at": token_set.expires_at}
    import json as _json
    existing = secret_store.get_secret(org_id=org_id, kind="per_user", name=secret_name, user_id=user_id)
    if existing:
        secret_store.update_secret(org_id=org_id, kind="per_user", name=secret_name, value=_json.dumps(payload), user_id=user_id)
    else:
        secret_store.create_secret(org_id=org_id, kind="per_user", name=secret_name, value=_json.dumps(payload), user_id=user_id)

    from services.ecosystem.credential_broker_service import _upsert_connection_cache

    _upsert_connection_cache(org_id, user_id, connector_ref, "connected")
    return {"status": "connected"}


@router.post("/ecosystem/connections/{connector_ref:path}/disconnect")
async def disconnect(connector_ref: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)

    if _is_native_connector(connector_ref):
        from routers.connectors_router import disconnect as native_disconnect

        await native_disconnect(connector_ref, current_user)
        return {"status": "not_connected"}

    found = _find_connector_item(connector_ref)
    oauth_cfg = (found["manifest"] or {}).get("oauth") if found else None
    if oauth_cfg and oauth_cfg.get("revoke_url"):
        from store import ecosystem_secret_store as secret_store

        import json as _json

        token_secret = secret_store.get_secret_value(org_id=org_id, kind="per_user", name=f"oauth_tokens:{connector_ref}", user_id=user_id)
        if token_secret:
            try:
                access_token = _json.loads(token_secret).get("access_token", "")
                provider = oauth_cfg.get("provider") or connector_ref
                from db.database import SessionLocal
                from db.models import EcosystemOAuthApp

                db = SessionLocal()
                try:
                    app_row = (
                        db.query(EcosystemOAuthApp)
                        .filter(EcosystemOAuthApp.org_id == org_id, EcosystemOAuthApp.provider == provider)
                        .first()
                    )
                finally:
                    db.close()
                if app_row:
                    from connectors.base import OAuth2Config

                    config = OAuth2Config(
                        authorize_url="", token_url="", client_id_env="", client_secret_env="",
                        scopes=[], revoke_url=oauth_cfg["revoke_url"],
                        client_id_value=app_row.client_id,
                        client_secret_value=get_oauth_app_client_secret(org_id, provider),
                    )
                    oauth2_handler.revoke_token(config, access_token)
            except Exception:
                pass  # revoke is best-effort, same convention as OAuth2Handler.revoke_token itself

    from services.ecosystem.credential_broker_service import _upsert_connection_cache

    _upsert_connection_cache(org_id, user_id, connector_ref, "not_connected")
    return {"status": "not_connected"}


# ── Admin: OAuth app registration ────────────────────────────────────────

class RegisterOAuthAppRequest(BaseModel):
    provider: str
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None
    scopes: list[str] = []


@router.get("/ecosystem/admin/oauth-apps")
def list_oauth_apps(current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    _, org_id = _caller_context(current_user)
    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    db = SessionLocal()
    try:
        rows = db.query(EcosystemOAuthApp).filter(EcosystemOAuthApp.org_id == org_id).all()
        return {"apps": [
            {
                "id": str(r.id), "org_id": r.org_id, "provider": r.provider, "client_id": r.client_id,
                "redirect_uri": r.redirect_uri, "scopes": r.scopes, "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]}
    finally:
        db.close()


@router.post("/ecosystem/admin/oauth-apps", status_code=201)
def create_oauth_app(body: RegisterOAuthAppRequest, current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    user_id, org_id = _caller_context(current_user)
    result = register_oauth_app(
        org_id=org_id, provider=body.provider, client_id=body.client_id, client_secret=body.client_secret,
        created_by=user_id, redirect_uri=body.redirect_uri, scopes=body.scopes,
    )
    result.pop("client_secret", None)
    return result


@router.delete("/ecosystem/admin/oauth-apps/{app_id}", status_code=204)
def delete_oauth_app(app_id: str, current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    _, org_id = _caller_context(current_user)
    from db.database import SessionLocal
    from db.models import EcosystemOAuthApp

    db = SessionLocal()
    try:
        row = db.query(EcosystemOAuthApp).filter(EcosystemOAuthApp.id == app_id, EcosystemOAuthApp.org_id == org_id).first()
        if not row:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "oauth app not found", "retryable": False})
        db.delete(row)
        db.commit()
    finally:
        db.close()


# ── Tool-call approvals ───────────────────────────────────────────────────

@router.get("/ecosystem/tool-calls/pending")
def list_pending_tool_calls(current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)
    return {"pending": tool_approval_service.list_pending(org_id, user_id)}


@router.post("/ecosystem/tool-calls/{approval_id}/approve")
def approve_tool_call(approval_id: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)
    try:
        return tool_approval_service.approve(org_id, user_id, approval_id)
    except ToolApprovalError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc), "retryable": False})


@router.post("/ecosystem/tool-calls/{approval_id}/deny")
def deny_tool_call(approval_id: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id = _caller_context(current_user)
    try:
        return tool_approval_service.deny(org_id, user_id, approval_id)
    except ToolApprovalError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc), "retryable": False})
