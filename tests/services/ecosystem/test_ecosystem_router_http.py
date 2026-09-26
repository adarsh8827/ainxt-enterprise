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

import json
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


async def _fake_generate(self, intent):
    from services.ecosystem.skill_factory_adapter import DraftTurn

    yield DraftTurn(stage="intent", text="Understanding...")
    yield DraftTurn(
        stage="assembled", text="Draft ready",
        data={"assembled": {
            "name": "http-draft-skill", "display_name": "HTTP Draft Skill", "description": "d",
            "category": "productivity", "content": intent, "generated": True,
            "tags": [], "bundle_files": [], "quality": {"lint_issues": 0, "issues": []},
        }},
    )


def test_post_drafts_requires_idempotency_key(client):
    resp = client.post("/ainxt/v1/api/ecosystem/drafts", json={"item_type": "skill", "intent": "x"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "BAD_REQUEST"


def _parse_sse_frames(body: str) -> list[dict]:
    frames = []
    for part in body.split("\n\n"):
        line = part.strip()
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: "):]))
    return frames


def test_post_drafts_streams_turns_and_get_patch_submit_round_trip(client):
    with patch("services.ecosystem.skill_factory_adapter.SkillFactoryAdapter.generate", _fake_generate):
        resp = client.post(
            "/ainxt/v1/api/ecosystem/drafts",
            headers={"Idempotency-Key": "draft-http-key-1"},
            json={"item_type": "skill", "intent": "build me a thing"},
        )
    assert resp.status_code == 200, resp.text
    frames = _parse_sse_frames(resp.text)
    stages = [f["stage"] for f in frames]
    # "created" first (carries draft_id -- the client's only way to learn
    # it), then the adapter's own turns, then a final "draft_ready" with
    # the fully-merged draft_content (a different shape from the adapter's
    # own raw "assembled" data -- see routers/ecosystem_router.py's own
    # comment on why a clean re-fetch frame exists at all).
    assert stages[0] == "created"
    assert "intent" in stages and "assembled" in stages
    assert stages[-1] == "draft_ready"

    draft_id = frames[0]["data"]["draft_id"]
    assert frames[-1]["data"]["draft"]["id"] == draft_id
    assert frames[-1]["data"]["draft"]["draft_content"]["display_name"] == "HTTP Draft Skill"

    get_resp = client.get(f"/ainxt/v1/api/ecosystem/drafts/{draft_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "ready"
    assert get_resp.json()["draft_content"]["display_name"] == "HTTP Draft Skill"

    patch_resp = client.patch(f"/ainxt/v1/api/ecosystem/drafts/{draft_id}", json={"namespace": "http-test-org/http-draft-skill"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["draft_content"]["namespace"] == "http-test-org/http-draft-skill"

    with _mock_ethics_pass():
        submit_resp = client.post(
            f"/ainxt/v1/api/ecosystem/drafts/{draft_id}/submit",
            headers={"Idempotency-Key": "draft-submit-key-1"},
        )
    assert submit_resp.status_code == 201, submit_resp.text
    item_id = submit_resp.json()["item_id"]

    # Idempotency: retrying with the same key returns the SAME item, not a
    # second one.
    with _mock_ethics_pass():
        retry_resp = client.post(
            f"/ainxt/v1/api/ecosystem/drafts/{draft_id}/submit",
            headers={"Idempotency-Key": "draft-submit-key-1"},
        )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["item_id"] == item_id


def test_submit_drafts_requires_idempotency_key(client):
    resp = client.post("/ainxt/v1/api/ecosystem/drafts/some-id/submit")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "BAD_REQUEST"


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


# ── GET /ecosystem/installs -- every row must embed `item` (CONTRACTS.md
# §9), for every origin the real app can produce, over real HTTP. This is
# the exact class of bug (`item` silently missing) that no other test in
# this package could catch: every other test calls installs_service
# directly, so it only ever proved the *service* returns whatever the
# service returns, never that the real HTTP response actually conforms to
# the documented schema. A response_model on the route (added alongside
# this test) makes FastAPI itself reject a future regression of this
# exact shape with a real 500, instead of 200'ing with an incomplete body.

def test_installs_embed_item_for_a_freshly_created_item(client):
    with _mock_ethics_pass():
        create_resp = client.post(
            "/ainxt/v1/api/ecosystem/items",
            headers={"Idempotency-Key": "installs-embed-created-key"},
            json={
                "create_via": "write", "item_type": "skill", "namespace": "http-test/installs-embed-created",
                "display_name": "Embed Created", "description": "d", "category": "productivity",
                "tags": [], "license": "MIT", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            },
        )
    assert create_resp.status_code == 202, create_resp.text

    resp = client.get("/ainxt/v1/api/ecosystem/installs")
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["installs"] if i["item"]["namespace"] == "http-test/installs-embed-created")
    assert row["item"]["display_name"] == "Embed Created"
    assert "allowed_actions" in row["item"] and isinstance(row["item"]["allowed_actions"], list)


def test_installs_embed_item_for_a_deprecated_item(client):
    item = _create_item("http-test/installs-embed-deprecated")
    item_id = item["item_id"]
    dep_resp = client.post(f"/ainxt/v1/api/ecosystem/items/{item_id}/deprecate")
    assert dep_resp.status_code == 200, dep_resp.text

    resp = client.get("/ainxt/v1/api/ecosystem/installs")
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["installs"] if i["item"]["id"] == item_id)
    assert row["item"]["status"] == "deprecated"


def test_installs_embed_item_for_a_force_disabled_yanked_item(client):
    item = _create_item("http-test/installs-embed-yanked")
    item_id = item["item_id"]
    fd_resp = client.post(f"/ainxt/v1/api/ecosystem/items/{item_id}/force-disable")
    assert fd_resp.status_code == 200, fd_resp.text

    resp = client.get("/ainxt/v1/api/ecosystem/installs")
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["installs"] if i["item"]["id"] == item_id)
    assert row["item"]["status"] == "yanked"


def test_installs_embed_item_for_a_provisioned_install(client):
    # Simulates the lazy-provisioning shape (task B-12/M3): an install
    # whose `installed_by` is an admin/system identity, provisioned for a
    # teammate other than the item's own creator (the creator already has
    # their own auto-install from _create_item(), origin="created" -- a
    # provisioned row is a distinct one, for a distinct installed_for).
    item = _create_item("http-test/installs-embed-provisioned")
    from services.ecosystem import installs_service

    installs_service.install(
        item_id=item["item_id"], version_id=item["version_id"], org_id="http-test-org",
        installed_by="admin-provisioner", installed_for="http-test-teammate", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )

    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "http-test-teammate", "user_id": "http-test-teammate", "org_id": "http-test-org", "role": "user",
    }
    teammate_client = TestClient(app)

    resp = teammate_client.get("/ainxt/v1/api/ecosystem/installs")
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["installs"] if i["item"]["id"] == item["item_id"] and i["origin"] == "provisioned")
    assert row["item"]["namespace"] == "http-test/installs-embed-provisioned"


def test_installs_item_type_query_param_actually_filters_over_real_http(client):
    _create_item("http-test/installs-type-filter")

    matching = client.get("/ainxt/v1/api/ecosystem/installs", params={"item_type": "skill"})
    assert matching.status_code == 200, matching.text
    assert any(i["item"]["namespace"] == "http-test/installs-type-filter" for i in matching.json()["installs"])

    non_matching = client.get("/ainxt/v1/api/ecosystem/installs", params={"item_type": "plugin"})
    assert non_matching.status_code == 200, non_matching.text
    assert not any(i["item"]["namespace"] == "http-test/installs-type-filter" for i in non_matching.json()["installs"])
