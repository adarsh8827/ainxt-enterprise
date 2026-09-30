# SPDX-License-Identifier: MIT
# ============================================================
# Regression tests for a real, live-found bug (2026-09-30): every native
# connector's Discover/detail card calls connect()/disconnect() with the
# bridged EcosystemItem's namespace (e.g. "default/jira"), never the bare
# connector_definitions.name ("jira") that connectors_router.py's own
# _load_definition()/oauth_start() look up by. Because of that mismatch,
# _is_native_connector(connector_ref) was ALWAYS False for a namespaced
# ref, so connect() fell through to the generic "no oauth key in the
# manifest -> already-connected API-key connector" branch and returned
# {"status": "connected"} immediately for every native connector, with no
# real auth step at all. Confirmed live against the local dev stack before
# this fix: every one of the 13 seeded native connectors showed
# "Connected" the instant "+ add" was clicked.
# ============================================================

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from db.database import SessionLocal
from routers.ecosystem_connectors_router import _resolve_native_connector_name, router as connectors_router
from services.ecosystem import items_service, versions_service

ORG = "native-bridge-test-org"


def _client(user_id: str = "u1", role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": ORG, "role": role}
    return TestClient(app)


def _seed_connector_definition(name: str, auth_type: str) -> None:
    db = SessionLocal()
    try:
        db.execute(
            sa.text(
                "INSERT INTO ainxt.connector_definitions "
                "(name, display_name, description, category, auth_type, auth_config, tools, is_builtin, is_active) "
                "VALUES (:name, :display_name, 'test connector', 'general', :auth_type, '{}'::jsonb, '[]'::jsonb, TRUE, TRUE) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": name, "display_name": name, "auth_type": auth_type},
        )
        db.commit()
    finally:
        db.close()


def _seed_bridged_item(name: str) -> str:
    """Mirrors exactly what scripts/ecosystem/backfill_legacy_items.py's
    _backfill_native_connectors() does: an EcosystemItem pointer with
    legacy_source="connector_definitions"/legacy_ref=<bare name>, a
    manifest with no "oauth" key (real bridge manifests never declare one)."""
    namespace = f"{ORG}/{name}"
    item_id, _ = items_service.upsert_legacy_pointer_item(
        namespace=namespace, item_type="connector", category="general",
        display_name=name, description="test connector", org_id=ORG,
        legacy_source="connector_definitions", legacy_ref=name,
        trust_tier="builtin", scope="builtin",
    )
    versions_service.create_or_refresh_legacy_version(
        item_id=item_id, content_text="test connector", manifest={"name": name, "legacy_source": "connector_definitions"},
    )
    return namespace


# ── Unit: the resolver itself ────────────────────────────────────────────

def test_resolver_prefers_the_bridges_own_legacy_ref_over_the_raw_ref():
    found = {"legacy_source": "connector_definitions", "legacy_ref": "jira"}
    assert _resolve_native_connector_name("default/jira", found) == "jira"


def test_resolver_falls_back_to_treating_the_ref_itself_as_a_bare_native_name():
    with patch("routers.connectors_router._load_definition", return_value={}):
        assert _resolve_native_connector_name("jira", None) == "jira"


def test_resolver_returns_none_for_a_genuine_non_native_item():
    found = {"legacy_source": "skills_pg", "legacy_ref": "some-skill"}
    with patch("routers.connectors_router._load_definition", side_effect=ValueError("not found")):
        assert _resolve_native_connector_name("acme/some-skill", found) is None


# ── Integration: the real live bug, end to end ───────────────────────────

def test_connecting_a_bridged_pat_connector_does_not_silently_report_connected():
    name = f"pat-conn-{uuid.uuid4().hex[:8]}"
    _seed_connector_definition(name, "pat")
    namespace = _seed_bridged_item(name)

    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        resp = _client().post(f"/ainxt/v1/api/ecosystem/connections/{namespace.replace('/', '%2F')}/connect", json={})

    assert resp.status_code == 400, resp.text
    body = resp.json()["detail"]
    assert body["code"] == "MANUAL_SETUP_REQUIRED"
    assert "status" not in resp.json()  # never a top-level {"status": "connected"} shape


def test_connecting_a_bridged_oauth2_connector_reaches_the_real_oauth_flow_not_the_fake_connected_path():
    name = f"oauth-conn-{uuid.uuid4().hex[:8]}"
    _seed_connector_definition(name, "oauth2")
    namespace = _seed_bridged_item(name)

    with patch("connectors.registry.connector_registry.get_user_status", return_value=[]):
        resp = _client().post(f"/ainxt/v1/api/ecosystem/connections/{namespace.replace('/', '%2F')}/connect", json={})

    # No OAuth client_id_env is configured for this throwaway connector, so
    # the REAL oauth_start() path correctly 400s -- the key assertion is
    # that it is THIS error (proof the real OAuth branch was reached) and
    # not a silent {"status": "connected"}.
    assert resp.status_code == 400, resp.text
    assert "not configured" in resp.text.lower()


def test_bridged_pat_connector_reports_real_connected_status_once_a_token_exists():
    name = f"pat-conn-connected-{uuid.uuid4().hex[:8]}"
    _seed_connector_definition(name, "pat")
    namespace = _seed_bridged_item(name)

    with patch(
        "connectors.registry.connector_registry.get_user_status",
        return_value=[{"name": name, "connected": True}],
    ):
        resp = _client().post(f"/ainxt/v1/api/ecosystem/connections/{namespace.replace('/', '%2F')}/connect", json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected"


def test_list_connections_maps_native_status_onto_the_bridged_namespace():
    name = f"listed-conn-{uuid.uuid4().hex[:8]}"
    _seed_connector_definition(name, "oauth2")
    namespace = _seed_bridged_item(name)

    with patch(
        "connectors.registry.connector_registry.get_user_status",
        return_value=[{"name": name, "connected": True}],
    ):
        resp = _client().get("/ainxt/v1/api/ecosystem/connections")

    assert resp.status_code == 200, resp.text
    by_ref = {c["connector_ref"]: c for c in resp.json()["connections"]}
    assert namespace in by_ref, f"expected {namespace!r} in {list(by_ref)}"
    assert by_ref[namespace]["status"] == "connected"
