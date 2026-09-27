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


@pytest.fixture
def normal_user_client():
    """A plain, non-admin caller (role='developer', no marketplace:provision)
    -- for confirming server-side scope enforcement on install()."""
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "http-test-normal-user", "user_id": "http-test-normal-user", "org_id": "http-test-org", "role": "developer",
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
    for key in ("product", "layout", "default_view", "item_types", "route_slugs", "surfaces", "features", "caller_permissions", "policy_summary", "taxonomy", "new_badge_days", "enums_version", "caller_default_namespace_prefix"):
        assert key in body, f"missing {key!r} in GET /ecosystem/config response"


def test_get_config_caller_default_namespace_prefix_is_non_empty_and_stable(client):
    # One-click "Copy to my skills" needs this to always be a real,
    # already-provisioned publisher slug for the authenticated caller.
    first = client.get("/ainxt/v1/api/ecosystem/config").json()["caller_default_namespace_prefix"]
    assert first
    second = client.get("/ainxt/v1/api/ecosystem/config").json()["caller_default_namespace_prefix"]
    assert second == first


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


# ── Scope permission enforcement (found live: a normal user could both
# SEE and SUCCESSFULLY SUBMIT "Everyone in org"/"Required" scope options
# in AddDialog.tsx -- the install endpoint never validated `scope` at all).

def test_get_config_caller_permissions_reflects_the_real_caller_not_a_product_feature_flag(client, normal_user_client):
    admin_resp = client.get("/ainxt/v1/api/ecosystem/config")
    assert admin_resp.status_code == 200, admin_resp.text
    assert admin_resp.json()["caller_permissions"] == {"can_share": True, "can_provision": True}

    normal_resp = normal_user_client.get("/ainxt/v1/api/ecosystem/config")
    assert normal_resp.status_code == 200, normal_resp.text
    # role="developer" has marketplace:share but not marketplace:provision
    # (auth/rbac.py) -- distinct from features.provisioning, which stays
    # true for the whole `enterprise` product regardless of caller.
    assert normal_resp.json()["caller_permissions"] == {"can_share": True, "can_provision": False}
    assert normal_resp.json()["features"]["provisioning"] is True


def test_install_rejects_a_forged_provisioned_or_required_scope_from_a_non_admin_caller(normal_user_client):
    item = _create_item("http-test/scope-forgery-item")

    for forged_scope in ("provisioned", "required", "org"):
        resp = normal_user_client.post(
            f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
            json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": forged_scope, "origin": "added"},
        )
        assert resp.status_code == 403, f"scope={forged_scope!r} should be rejected for a non-admin caller, got {resp.status_code}: {resp.text}"
        assert resp.json()["detail"]["code"] == "POLICY_FORBIDDEN"

    # The UI is bypassed above (a raw API call, no client-side gating at
    # all) -- proves the enforcement is real server-side, not merely
    # AddDialog.tsx hiding the radio button.
    ok_resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "shared", "origin": "added"},
    )
    assert ok_resp.status_code == 201, ok_resp.text


# ── Tiered license policy (task C, ECOSYSTEM_PLAN.md §11.2), Tier 2 at
# install-scope-change time -- not just at creation or policy_service.share().

def test_install_provisioned_scope_blocks_a_disallowed_license_by_default(client):
    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id="http-test-org", created_by="http-test-user", item_type="skill",
            namespace="http-test/install-scope-gpl", display_name="d", description="d",
            category="productivity", tags=[], license="GPL-3.0-only",
            content={"instructions": "x", "files": []}, surfaces=["chat"], license_acknowledged=True,
        )
    resp = client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "provisioned", "origin": "provisioned"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "LICENSE_NOT_ALLOWED_BY_ORG_POLICY"


def test_install_provisioned_scope_allowed_once_org_policy_permits_the_license():
    # A dedicated org_id (not the shared "http-test-org" every other test in
    # this file uses) -- setting allowed_licenses_shared on a shared org
    # would leak across tests and make the "blocks by default" test above
    # order-dependent.
    from services.ecosystem import policy_service

    org_id = "http-test-org-license-permits-gpl"
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "http-test-user", "user_id": "http-test-user", "org_id": org_id, "role": "admin",
    }
    scoped_client = TestClient(app)

    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id=org_id, created_by="http-test-user", item_type="skill",
            namespace="http-test/install-scope-gpl-ok", display_name="d", description="d",
            category="productivity", tags=[], license="GPL-3.0-only",
            content={"instructions": "x", "files": []}, surfaces=["chat"], license_acknowledged=True,
        )
    policy_service.set_policy(org_id, allowed_licenses_shared=["MIT", "Apache-2.0", "GPL-3.0-only"], updated_by="http-test-user")
    resp = scoped_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "provisioned", "origin": "provisioned"},
    )
    assert resp.status_code == 201, resp.text


# ── Detail.tsx's installed-state header (kebab + enable/disable toggle):
# "on disabling it should not be visible in chat" -- a real, full round
# trip through install -> capabilities -> disable -> capabilities again,
# not just the pieces (resolver_service's own filter, the toggle UI) each
# tested in isolation. That gap has bitten this session before.

def test_disabling_an_install_removes_it_from_the_chat_capabilities_it_just_appeared_in(client):
    item = _create_item("http-test/disable-removes-from-chat")
    # create_via_write's trigger ("ui_add") auto-installs the creator on a
    # passing gate (gate_service._AUTO_INSTALL_TRIGGERS) -- no separate
    # POST /install call needed to get to "already installed."
    installs = client.get("/ainxt/v1/api/ecosystem/installs").json()["installs"]
    install = next(i for i in installs if i["item"]["id"] == item["item_id"])
    assert install["enabled"] is True

    before = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert before.status_code == 200, before.text
    assert any(s["namespace"] == "http-test/disable-removes-from-chat" for s in before.json()["skills"])

    disable_resp = client.post(f"/ainxt/v1/api/ecosystem/installs/{install['install_id']}/set-enabled", json={"enabled": False})
    assert disable_resp.status_code == 200, disable_resp.text

    after = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert after.status_code == 200, after.text
    assert not any(s["namespace"] == "http-test/disable-removes-from-chat" for s in after.json()["skills"])

    # And re-enabling brings it straight back -- confirms the toggle is a
    # real two-way switch, not a one-shot "hide forever."
    client.post(f"/ainxt/v1/api/ecosystem/installs/{install['install_id']}/set-enabled", json={"enabled": True})
    reenabled = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert any(s["namespace"] == "http-test/disable-removes-from-chat" for s in reenabled.json()["skills"])


def test_get_item_detail_exposes_the_callers_own_install_id_and_enabled_state(client):
    item = _create_item("http-test/item-detail-install-id")
    resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item['item_id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["install_id"], "auto-installed by create_via_write's ui_add trigger -- must not be null"
    assert body["enabled"] is True


# ── Item 6: "Update my <skill>" -- a new version of an EXISTING item ────

def test_new_version_creates_a_second_immutable_version_and_regates_it(client):
    item = _create_item("http-test/update-my-skill")
    item_id, first_version_id = item["item_id"], item["version_id"]

    with _mock_ethics_pass():
        resp = client.post(
            f"/ainxt/v1/api/ecosystem/items/{item_id}/new-version",
            json={"content": {"instructions": "updated instructions", "files": []}},
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["item_id"] == item_id
    assert body["version_id"] != first_version_id
    assert body["status"] == "verifying"

    versions_resp = client.get(f"/ainxt/v1/api/ecosystem/items/{item_id}/versions")
    assert versions_resp.status_code == 200, versions_resp.text
    assert len(versions_resp.json()["versions"]) == 2


def test_new_version_bumps_the_owners_own_install_once_it_passes(client):
    item = _create_item("http-test/update-my-skill-bump")
    item_id, first_version_id = item["item_id"], item["version_id"]

    with _mock_ethics_pass():
        resp = client.post(
            f"/ainxt/v1/api/ecosystem/items/{item_id}/new-version",
            json={"content": {"instructions": "v2 instructions", "files": []}},
        )
    assert resp.status_code == 202, resp.text
    new_version_id = resp.json()["version_id"]

    installs_resp = client.get("/ainxt/v1/api/ecosystem/installs")
    row = next(i for i in installs_resp.json()["installs"] if i["item"]["id"] == item_id)
    # The creator's own auto-install (origin="created") should now point at
    # the new version, not the original one -- "Update my skill" should
    # feel like an update, not a second install the caller has to notice.
    assert row["version_id"] == new_version_id
    assert row["version_id"] != first_version_id


def test_new_version_rejects_a_non_owner_non_admin_caller(client, normal_user_client):
    item = _create_item("http-test/update-not-mine")
    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/new-version",
        json={"content": {"instructions": "hijacked", "files": []}},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "POLICY_FORBIDDEN"


def test_new_version_disallowed_license_requires_acknowledgement(client):
    # Task C (ECOSYSTEM_PLAN.md §11.2): the item from _create_item() is
    # private-only (no shared install anywhere), so this is Tier 3 --
    # requires license_acknowledged, not an outright LICENSE_NOT_ALLOWED
    # the way it used to be.
    item = _create_item("http-test/update-my-skill-gpl")
    resp = client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/new-version",
        json={"content": {"instructions": "x", "files": []}, "license": "GPL-3.0-only"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "LICENSE_ACKNOWLEDGEMENT_REQUIRED"


def test_new_version_disallowed_license_allowed_once_acknowledged(client):
    item = _create_item("http-test/update-my-skill-gpl-acked")
    with _mock_ethics_pass():
        resp = client.post(
            f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/new-version",
            json={"content": {"instructions": "x", "files": []}, "license": "GPL-3.0-only", "license_acknowledged": True},
        )
    assert resp.status_code == 202, resp.text
