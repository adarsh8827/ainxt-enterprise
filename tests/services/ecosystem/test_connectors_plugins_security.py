# SPDX-License-Identifier: MIT
# ============================================================
# Security tests for the Connectors+Plugins phase (Stage 5's own security
# list, docs/ecosystem/CONNECTORS_PHASE_PLAN.md). Adds ONLY what Stages
# 1-4's own test files (test_connectors_phase_stage2.py,
# test_plugins_phase_stage4.py, test_mcp_runtime_service.py,
# test_ecosystem_secret_store.py) don't already cover for real -- see each
# section's own comment for what's reused vs new.
# ============================================================

from __future__ import annotations

import logging
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from core.ckms.key_service import KeyService
from routers.ecosystem_connectors_router import router as connectors_router
from services.ecosystem import tool_approval_service

ORG_A, ORG_B = "sec5-test-org-a", "sec5-test-org-b"


@pytest.fixture(autouse=True)
def _install_test_dek():
    KeyService.reset_for_tests()
    KeyService.instance().install(cache={"KEY_CREDS": b"\x33" * 32}, mapping={})
    yield
    KeyService.reset_for_tests()


def _client(org_id: str, user_id: str = "u1", role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": role}
    return TestClient(app)


# ── 1. Route-enumeration auth sweep, extended to the connectors router ──
# tests/services/ecosystem/test_ecosystem_security.py already has
# test_every_ecosystem_route_requires_authentication for
# routers/ecosystem_router.py -- it does NOT cover
# routers/ecosystem_connectors_router.py, a separate router object added
# in Stage 2/3. That router declares dependencies=[Depends(get_current_user)]
# at the router level (not per-endpoint), so this is the mechanical
# backstop proving that declaration actually holds for every real route,
# not just the ones a human happened to hand-test.

def test_every_ecosystem_connectors_route_requires_authentication():
    app = FastAPI()
    app.include_router(connectors_router, prefix="/ainxt/v1/api")
    unauthenticated_client = TestClient(app)

    placeholder = "11111111-1111-1111-1111-111111111111"
    routes = [
        (method, re.sub(r"\{[^}]+\}", placeholder, route.path))
        for route in connectors_router.routes
        for method in route.methods
        if method != "HEAD"
    ]
    assert len(routes) >= 12, f"expected the full connectors-router route set, got only {len(routes)} -- did route discovery break?"

    for method, path in routes:
        resp = unauthenticated_client.request(method, f"/ainxt/v1/api{path}")
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code} with zero auth (expected 401): {resp.text[:200]}"


# ── 2. Destructive tools always require approval ────────────────────────
# test_connectors_phase_stage2.py::test_auto_approve_policy_bypasses_the_
# pending_row already proves auto-approve works for a WRITE-classified
# tool. This proves the real gap found+fixed during this review: before
# the fix, services/ecosystem/tool_approval_service.py's request_tool_call()
# checked _is_auto_approved() for ANY non-read classification, so a
# destructive tool with a (mis-scoped, or maliciously added) auto-approve
# policy row would have skipped human approval entirely. Fixed to gate
# the auto-approve check on classification == "write" specifically.

def test_destructive_tool_is_never_auto_approved_even_with_a_policy_row():
    org_id = f"sec5-destructive-{uuid.uuid4().hex[:8]}"
    from db.database import SessionLocal
    from db.models import EcosystemToolAutoApprovePolicy

    db = SessionLocal()
    try:
        db.add(EcosystemToolAutoApprovePolicy(id=str(uuid.uuid4()), org_id=org_id, tool_name="delete_repo", enabled_by="admin1"))
        db.commit()
    finally:
        db.close()

    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="u1", tool_name="delete_repo",
        tool_def={"name": "delete_repo", "annotations": {"destructiveHint": True}},
    )
    assert result["requires_approval"] is True
    assert result["status"] == "pending"
    pending = tool_approval_service.list_pending(org_id, "u1")
    assert any(p["tool_name"] == "delete_repo" for p in pending), "destructive tool with an auto-approve policy row skipped approval"


# ── 3. Cross-org 404 on /ecosystem/tool-calls/* ──────────────────────────
# test_connectors_phase_stage2.py covers cross-org isolation for
# oauth-apps and the connections list, but not the tool-calls
# approve/deny/pending endpoints added alongside them.

def test_tool_calls_pending_list_is_scoped_to_the_callers_org():
    org_id = f"sec5-toolcalls-{uuid.uuid4().hex[:8]}"
    tool_approval_service.request_tool_call(
        org_id=org_id, user_id="user-a", tool_name="send_email",
        tool_def={"name": "send_email", "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    )
    client_a = _client(org_id, user_id="user-a")
    client_b = _client(ORG_B, user_id="user-b")

    resp_a = client_a.get("/ainxt/v1/api/ecosystem/tool-calls/pending")
    assert any(p["tool_name"] == "send_email" for p in resp_a.json()["pending"])

    resp_b = client_b.get("/ainxt/v1/api/ecosystem/tool-calls/pending")
    assert all(p["tool_name"] != "send_email" for p in resp_b.json()["pending"])


def test_approving_another_orgs_pending_tool_call_returns_404():
    org_id = f"sec5-toolcalls-{uuid.uuid4().hex[:8]}"
    result = tool_approval_service.request_tool_call(
        org_id=org_id, user_id="user-a", tool_name="send_email",
        tool_def={"name": "send_email", "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    )
    client_b = _client(ORG_B, user_id="user-b")
    resp = client_b.post(f"/ainxt/v1/api/ecosystem/tool-calls/{result['approval_id']}/approve")
    assert resp.status_code == 404, resp.text


# ── 4. Token isolation ───────────────────────────────────────────────────
# tests/store/test_ecosystem_secret_store.py already proves org isolation
# at the store layer directly. This adds the one missing real-HTTP path:
# GET /ecosystem/connections is already covered
# (test_connections_list_is_scoped_to_the_caller_only) for the *list*; this
# confirms get_connection_status() itself -- the function credential_broker_
# service exposes for a single connector_ref lookup -- also never crosses
# org boundaries, since it's called directly by other services (not just
# the list endpoint) and a regression there wouldn't be caught by the list
# test alone.

def test_get_connection_status_never_crosses_org_boundaries():
    from services.ecosystem.credential_broker_service import _upsert_connection_cache, get_connection_status

    connector_ref = f"sec5-conn-{uuid.uuid4().hex[:8]}"
    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        _upsert_connection_cache(ORG_A, "user-a", connector_ref, "connected")

        same_org = get_connection_status(ORG_A, "user-a", connector_ref)
        assert same_org.status == "connected"

        other_org = get_connection_status(ORG_B, "user-a", connector_ref)
        assert other_org.status == "not_connected", "connection status leaked across org boundary for the same connector_ref/user_id"


# ── 5. Tokens never appear in logs ───────────────────────────────────────
# Verified by direct source inspection first (no logger.* call in
# credential_broker_service.py/store/ecosystem_secret_store.py/
# routers/ecosystem_connectors_router.py ever interpolates a secret/token
# value -- only names, kinds, org/provider identifiers). This proves it
# behaviorally: a real oauth-callback exchange, with caplog capturing
# every log record emitted during it, must never contain the raw token
# string anywhere in any record's message.

def test_oauth_callback_never_logs_the_raw_access_or_refresh_token(caplog):
    from tests.services.ecosystem.test_connectors_phase_stage2 import _create_connector_item

    provider = f"sec5-provider-{uuid.uuid4().hex[:8]}"
    connector_ref = f"conn-test/sec5-logcheck-{uuid.uuid4().hex[:8]}"
    _create_connector_item(connector_ref, {
        "oauth": {"provider": provider, "authorize_url": "https://example.com/authorize",
                  "token_url": "https://example.com/token", "scopes": []},
    })

    from services.ecosystem.credential_broker_service import register_oauth_app

    register_oauth_app(org_id=ORG_A, provider=provider, client_id="cid", client_secret="super-secret-client-secret", created_by="admin")

    from connectors.oauth2 import oauth2_handler as global_oauth2_handler

    state = "sec5-state-token"
    global_oauth2_handler.save_state(state, "user-a", connector_ref, "verifier123")

    SECRET_ACCESS_TOKEN = "sekret-access-token-abc123xyz"
    SECRET_REFRESH_TOKEN = "sekret-refresh-token-def456uvw"

    class _FakeTokenSet:
        access_token = SECRET_ACCESS_TOKEN
        refresh_token = SECRET_REFRESH_TOKEN
        expires_at = None

    caplog.set_level(logging.DEBUG)
    with patch("services.ecosystem.credential_broker_service.oauth2_handler.exchange_code", return_value=_FakeTokenSet()):
        client = _client(ORG_A, user_id="user-a")
        resp = client.post(
            f"/ainxt/v1/api/ecosystem/connections/{connector_ref}/oauth-callback",
            json={"code": "authcode123", "state": state, "redirect_uri": "https://example.com/cb"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected"

    full_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET_ACCESS_TOKEN not in full_log_text, "raw access token appeared in logs"
    assert SECRET_REFRESH_TOKEN not in full_log_text, "raw refresh token appeared in logs"
    assert "super-secret-client-secret" not in full_log_text, "raw OAuth client secret appeared in logs"


# ── 6. SSRF: additional payloads on the remote-MCP metadata discovery ───
# test_connectors_phase_stage2.py already covers gate stage 7's own
# private-address/plain-http rejection for a *manifest* URL. This targets
# credential_broker_service.discover_protected_resource_metadata()
# directly -- the other real SSRF-guarded fetch this phase added.

def test_discover_protected_resource_metadata_rejects_ipv6_loopback():
    from services.ecosystem.credential_broker_service import CredentialBrokerError, discover_protected_resource_metadata

    with pytest.raises(CredentialBrokerError):
        discover_protected_resource_metadata("https://[::1]/mcp")


def test_discover_protected_resource_metadata_does_not_silently_follow_a_redirect():
    """assert_safe_https_url() validates the URL given to it, once, before
    the request is made -- it has no way to inspect a redirect Location
    header. This proves the actual, real reason a redirect chain still
    can't be used to bypass the guard here: connectors/net_relay.py's
    relay_request() calls httpx.request() with no follow_redirects=True,
    and httpx defaults that to False, so a 3xx response comes back
    as-is -- and discover_protected_resource_metadata() treats any
    non-200 status as a hard failure rather than following it further."""
    from services.ecosystem.credential_broker_service import CredentialBrokerError, discover_protected_resource_metadata

    fake_redirect_response = MagicMock()
    fake_redirect_response.status_code = 302
    fake_redirect_response.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

    with patch("connectors.net_relay.relay_request", return_value=fake_redirect_response):
        with pytest.raises(CredentialBrokerError):
            discover_protected_resource_metadata("https://example.com/mcp")


# ── 7. Tool-output injection handling: documented finding, not a fake test ──
# The additive `tools` param on models/model_router.py's generate() (Stage
# 1) and every gateway_*.py adapter is confirmed, by direct source
# inspection, to be OUTGOING-only: it captures a model's tool_use/
# function_call requests into `_last_tool_calls` and returns, with no code
# anywhere feeding a tool's result back into a subsequent model turn (grep
# for "tool_result"/role=="tool" across models/ and the gateway_*.py files
# turns up nothing tied to this passthrough -- the codebase's OWN separate,
# pre-existing generate_with_tools() family on gateway_claude/openai/gemini
# does have a real multi-round loop, but that's a different, already-
# shipped feature (agents/react_orchestrator.py's repo-search tools), not
# this phase's connector/MCP tool-calling). There is therefore no
# tool-result-to-model round trip for THIS feature yet to write an
# injection test against -- a test asserting sanitization of a code path
# that doesn't exist would be a false assurance. Whoever wires connector/
# MCP tool RESULTS back into a chat turn (the multi-round piece explicitly
# flagged as an open design choice when the tools param was added) must
# add real sanitization/delimiting/size-limit tests at that point, not
# before.

def test_tool_calling_passthrough_is_a_distinct_method_from_the_multi_round_loop():
    import inspect

    import gateway_claude

    modules = [gateway_claude]
    # gateway_openai.py/gateway_gemini.py each instantiate a module-level
    # singleton (`openai_gateway = OpenAIGateway()` / `gemini_gateway =
    # GeminiGateway()`) that raises at import time when no OPENAI_API_KEY/
    # GEMINI_API_KEY/admin-registry credential is configured -- an
    # environment/import-order gap (whether this succeeds depends on
    # whether an earlier test in the same process already primed
    # sys.modules with a key set), not something this test itself is
    # checking. Claude alone is enough to prove the real point (distinct
    # methods, single SDK call) -- the other two are a bonus when available.
    for _mod_name in ("gateway_openai", "gateway_gemini"):
        try:
            modules.append(__import__(_mod_name))
        except Exception:
            pass

    for module in modules:
        gw_class = next(v for v in vars(module).values() if isinstance(v, type) and hasattr(v, "generate") and hasattr(v, "generate_with_tools"))
        assert gw_class.generate is not gw_class.generate_with_tools, (
            f"{module.__name__}'s generate() and generate_with_tools() are the same method -- "
            "the new single-turn `tools=` passthrough must stay distinct from the pre-existing "
            "multi-round tool-execution loop, not silently merge into it"
        )
        generate_source = inspect.getsource(gw_class.generate)
        assert "_last_tool_calls" in generate_source, f"{module.__name__}.generate() lost its tool-call capture side channel"
