# SPDX-License-Identifier: MIT
# ============================================================
# Router-level HTTP tests for routers/ecosystem_router.py -- every other
# test in this package (tests/services/ecosystem/) calls the service layer
# directly, which is exactly why the bug this file guards against was
# invisible until a real HTTP round-trip was tried by hand: Starlette/
# uvicorn decode a URL-encoded %2F into a literal "/" *before* route
# matching, so GET /ecosystem/items/{item_id} with a plain (non-`:path`)
# path parameter 404s at the routing layer -- before ever reaching the
# handler -- for any namespace containing a slash, i.e. every real
# namespace (they're all `publisher/name`-shaped). Confirmed against a
# real uvicorn server on a real port during this milestone's own manual
# verification, then reproduced here with FastAPI's TestClient so it's a
# permanent regression test, not a one-off manual check.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from routers.ecosystem_router import router as ecosystem_router
from services.ecosystem import create_service


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "http-test-user", "user_id": "http-test-user", "org_id": "http-test-org", "role": "admin",
    }
    return TestClient(app)


def _create_item(namespace: str) -> dict:
    with _mock_ethics_pass():
        return create_service.create_via_write(
            org_id="http-test-org", created_by="http-test-user", item_type="skill", namespace=namespace,
            display_name="HTTP Test", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": "x", "files": []}, surfaces=["chat"],
        )


def test_get_item_by_namespace_containing_a_slash_returns_200_not_404(client):
    # The exact scenario that was broken: every real namespace is
    # publisher/name-shaped -- literally every Detail-page navigation in
    # ecosystem-ui's real app flow (Marketplace.tsx -> detailPath()) hits
    # this path, URL-encoding the slash as %2F.
    result = _create_item("http-test/slash-namespace")
    item_id = result["item_id"]

    resp = client.get("/ainxt/v1/api/ecosystem/items/http-test%2Fslash-namespace")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == item_id
    assert resp.json()["namespace"] == "http-test/slash-namespace"


def test_get_item_by_uuid_still_works(client):
    result = _create_item("http-test/uuid-lookup")
    item_id = result["item_id"]

    resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == item_id


def test_versions_and_gate_runs_subroutes_are_not_shadowed_by_the_greedy_detail_route(client):
    # The fix uses a greedy {item_id:path} converter on the detail route --
    # this test guards against that converter's registration order
    # accidentally swallowing GET .../versions and GET .../gate-runs
    # (both also GET, both also under /ecosystem/items/{item_id}/...).
    result = _create_item("http-test/subroute-check")
    item_id = result["item_id"]

    versions_resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item_id}/versions")
    assert versions_resp.status_code == 200, versions_resp.text
    assert "versions" in versions_resp.json()
    assert len(versions_resp.json()["versions"]) == 1

    gate_runs_resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item_id}/gate-runs")
    assert gate_runs_resp.status_code == 200, gate_runs_resp.text
    assert "gate_runs" in gate_runs_resp.json()
    assert len(gate_runs_resp.json()["gate_runs"]) == 1


def test_unknown_namespace_404s_with_the_documented_not_found_shape(client):
    resp = client.get("/ainxt/v1/api/ecosystem/items/nope%2Fnothing-here")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


def test_get_config_real_http_round_trip_matches_the_documented_shape(client):
    resp = client.get("/ainxt/v1/api/ecosystem/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("product", "layout", "default_view", "item_types", "route_slugs", "surfaces", "features", "policy_summary", "taxonomy", "new_badge_days", "enums_version"):
        assert key in body, f"missing {key!r} in GET /ecosystem/config response"


def test_create_then_list_then_get_full_round_trip_over_real_http(client):
    with _mock_ethics_pass():
        create_resp = client.post(
            "/ainxt/v1/api/ecosystem/items",
            headers={"Idempotency-Key": "http-round-trip-key"},
            json={
                "create_via": "write", "item_type": "skill", "namespace": "http-test/round-trip",
                "display_name": "Round Trip", "description": "d", "category": "productivity",
                "tags": [], "license": "MIT", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            },
        )
    assert create_resp.status_code == 202, create_resp.text
    item_id = create_resp.json()["item_id"]

    list_resp = client.get("/ainxt/v1/api/ecosystem/items", params={"item_type": "skill"})
    assert list_resp.status_code == 200, list_resp.text
    assert item_id in [i["id"] for i in list_resp.json()["items"]]

    detail_resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["namespace"] == "http-test/round-trip"
