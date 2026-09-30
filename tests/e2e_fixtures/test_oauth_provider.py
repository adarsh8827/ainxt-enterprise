# SPDX-License-Identifier: MIT
# ============================================================
# TEST-ONLY OAUTH 2.1 PROVIDER
#
# *** NEVER START THIS IN ANY REAL DEPLOYMENT. ***
# *** NO REAL CREDENTIALS. NO REAL USER DATA. ***
#
# A minimal authorization server for E2E use only, simulating a
# third-party OAuth provider so the real connectors/oauth2.py
# OAuth2Handler / services/ecosystem/credential_broker_service.py flow
# can be exercised end-to-end against something other than a mock.
# Tokens are opaque (not real JWTs -- this is a test double, not a
# security feature) and held only in this process's own memory; nothing
# here is persisted, and every store resets when the process exits.
#
# Endpoints (RFC 6749 / RFC 7636 PKCE / RFC 7009 revocation shapes):
#   GET  /authorize   -- auto-"consents" (no real login UI) and 302s
#                         straight to redirect_uri?code=...&state=...
#   POST /token       -- authorization_code grant, real PKCE S256
#                         verification against the stored challenge
#   POST /revoke      -- RFC 7009 -- marks the token gone from this
#                         process's own store, checkable via
#                         is_token_active() below for real proof a
#                         "disconnect" actually revoked it server-side
#   GET  /.well-known/oauth-protected-resource -- RFC 9728 shape.
#         Disclosed limitation: this metadata endpoint can never be
#         reached through the REAL gate-enforced discovery path
#         (services/ecosystem/credential_broker_service.py's
#         discover_protected_resource_metadata(), called from gate stage
#         7) in this environment, because that path requires a public
#         https:// URL (services/ecosystem/import_adapters/ssrf_guard.py's
#         assert_safe_https_url() has no test-mode bypass, by design --
#         it exists specifically to refuse exactly this class of
#         address). This endpoint exists for completeness/documentation
#         and for a caller that hits it directly, not for a full,
#         gate-mediated remote-MCP-URL E2E round trip.
#
# Registered test app (fixed, for E2E fixture wiring):
#   client_id     = "e2e-test-provider-client"
#   client_secret = "e2e-test-provider-secret"
# ============================================================
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

TEST_CLIENT_ID = "e2e-test-provider-client"
TEST_CLIENT_SECRET = "e2e-test-provider-secret"

app = FastAPI(title="TEST-ONLY OAuth provider -- never deploy this")

# In-memory only. Reset on process restart.
_pending_codes: dict[str, dict] = {}   # code -> {state, code_challenge, redirect_uri, exp}
_tokens: dict[str, dict] = {}          # access_token -> {refresh_token, active, issued_at}
_refresh_tokens: dict[str, str] = {}   # refresh_token -> access_token


def is_token_active(access_token: str) -> bool:
    """Real, checkable proof a token is (or isn't) live server-side --
    the E2E disconnect step asserts against this directly, not just
    against the caller's own local DB row."""
    entry = _tokens.get(access_token)
    return bool(entry and entry["active"])


@app.get("/authorize")
def authorize(
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    response_type: str = Query("code"),
    scope: str = Query(""),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None),
):
    if client_id != TEST_CLIENT_ID:
        return RedirectResponse(f"{redirect_uri}?error=unauthorized_client&state={state}")
    code = secrets.token_urlsafe(24)
    _pending_codes[code] = {
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method or "S256",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "exp": time.time() + 300,
    }
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}")


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == challenge


@app.post("/token")
def token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
):
    # RFC 6749 §5.2: token-endpoint errors are 400, not 200-with-an-
    # "error"-key -- exchange_code()'s own real code calls
    # resp.raise_for_status(), which only fires on a non-2xx status, so a
    # provider that returned 200 here would make every error silently
    # look like a parse failure downstream instead of a clean exception.
    if client_id != TEST_CLIENT_ID or client_secret != TEST_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail={"error": "invalid_client"})

    if grant_type == "refresh_token":
        old_access = _refresh_tokens.get(refresh_token or "")
        if not old_access or not _tokens.get(old_access, {}).get("active"):
            raise HTTPException(status_code=400, detail={"error": "invalid_grant"})
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        _tokens[new_access] = {"refresh_token": new_refresh, "active": True, "issued_at": time.time()}
        _refresh_tokens[new_refresh] = new_access
        _tokens.pop(old_access, None)
        return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer", "expires_in": 3600}

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail={"error": "unsupported_grant_type"})

    entry = _pending_codes.pop(code or "", None)
    if not entry or entry["exp"] < time.time():
        raise HTTPException(status_code=400, detail={"error": "invalid_grant"})
    if redirect_uri != entry["redirect_uri"]:
        raise HTTPException(status_code=400, detail={"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
    if entry["code_challenge"]:
        if not code_verifier or not _verify_pkce(code_verifier, entry["code_challenge"]):
            raise HTTPException(status_code=400, detail={"error": "invalid_grant", "error_description": "PKCE verification failed"})

    access_token = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32)
    _tokens[access_token] = {"refresh_token": refresh, "active": True, "issued_at": time.time()}
    _refresh_tokens[refresh] = access_token
    return {
        "access_token": access_token, "refresh_token": refresh,
        "token_type": "bearer", "expires_in": 3600, "scope": entry.get("scope", ""),
    }


class RevokeRequest(BaseModel):
    token: str


@app.post("/revoke")
def revoke(token: str = Form(...), client_id: Optional[str] = Form(None), client_secret: Optional[str] = Form(None)):
    # RFC 7009: revoke succeeds (200) even for an unknown/already-revoked
    # token -- never leaks whether it existed.
    entry = _tokens.get(token)
    if entry:
        entry["active"] = False
    return {}


@app.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata():
    return {
        "resource": "http://localhost:8099/",
        "authorization_servers": ["http://localhost:8099/"],
        "bearer_methods_supported": ["header"],
    }


def run(port: int = 8099):
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    import sys
    run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8099)
