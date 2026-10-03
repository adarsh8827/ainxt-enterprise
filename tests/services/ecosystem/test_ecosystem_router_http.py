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


def test_get_config_caller_permissions_includes_can_admin_surfaces_over_real_http(client, normal_user_client):
    # Regression for a real gap found live (2026-09-30): CallerPermissionsModel
    # only declared can_share/can_provision -- FastAPI's response_model=
    # ConfigResponse silently stripped can_admin_surfaces from the wire even
    # though get_effective_config() always computed it correctly. This is
    # the exact reason Marketplace.tsx's collapseConnectorsAdvanced (the
    # "Connectors tab + Advanced sub-view" restructuring) never activated
    # for a real admin session -- found via a real browser session against
    # a real backend, not a service-layer-only test like most of this file.
    admin_perms = client.get("/ainxt/v1/api/ecosystem/config").json()["caller_permissions"]
    assert admin_perms["can_admin_surfaces"] is True

    dev_perms = normal_user_client.get("/ainxt/v1/api/ecosystem/config").json()["caller_permissions"]
    assert dev_perms["can_admin_surfaces"] is False


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

    # Item 7 fix (M5 UI-parity review, 2026-09-28): a freshly created item
    # is `scope='org_private'` -- it must NOT show up in the list/Discover
    # endpoint, even for its own creator/org (see
    # test_items_list_get_delete_policy.py's own
    # test_list_items_excludes_org_private_from_everyones_discover_feed
    # for the dedicated regression coverage of this). The direct detail
    # read (by id/namespace) is unaffected -- that's what "Yours" and a
    # direct open still use.
    list_resp = client.get("/ainxt/v1/api/ecosystem/items", params={"item_type": "skill"})
    assert list_resp.status_code == 200, list_resp.text
    assert item_id not in [i["id"] for i in list_resp.json()["items"]]

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


def test_deprecate_endpoint_allows_the_items_own_owner_not_just_admins(normal_user_client):
    # Item 9 fix (M5 UI-parity review, 2026-09-28): real bug found live --
    # this endpoint used to 403 EVERY non-admin caller, including the
    # item's own owner, contradicting items_service.compute_allowed_
    # actions() (deprecate is offered to `is_owner or
    # marketplace:admin_sources`, CONTRACTS.md §6) -- a real owner
    # clicking "Retire" on their own item (allowed_actions said they
    # could) got a 403 anyway. normal_user_client's role has no
    # marketplace:admin_sources permission, so this only passes once the
    # endpoint actually checks ownership.
    with _mock_ethics_pass():
        create_resp = normal_user_client.post(
            "/ainxt/v1/api/ecosystem/items",
            json={
                "create_via": "write", "item_type": "skill", "namespace": "sec-test/owner-can-retire",
                "display_name": "Owner Retire", "description": "d", "category": "productivity", "tags": [],
                "license": "MIT", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            },
        )
    assert create_resp.status_code == 202, create_resp.text
    item_id = create_resp.json()["item_id"]

    dep_resp = normal_user_client.post(f"/ainxt/v1/api/ecosystem/items/{item_id}/deprecate")
    assert dep_resp.status_code == 200, dep_resp.text
    assert dep_resp.json()["status"] == "deprecated"


def test_deprecate_endpoint_publishes_an_ecosystem_changed_event(normal_user_client):
    # Real gap found live (install-state-consistency round, 2026-09-29):
    # deprecate/retire never published ecosystem.changed at all -- a
    # Yours/Detail screen sitting open elsewhere (or another tab) had no
    # signal that this item's status just changed underneath it.
    with _mock_ethics_pass():
        create_resp = normal_user_client.post(
            "/ainxt/v1/api/ecosystem/items",
            json={
                "create_via": "write", "item_type": "skill", "namespace": "sec-test/deprecate-event",
                "display_name": "Deprecate Event", "description": "d", "category": "productivity", "tags": [],
                "license": "MIT", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            },
        )
    assert create_resp.status_code == 202, create_resp.text
    item_id = create_resp.json()["item_id"]

    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        dep_resp = normal_user_client.post(f"/ainxt/v1/api/ecosystem/items/{item_id}/deprecate")
    assert dep_resp.status_code == 200, dep_resp.text
    assert len(captured) == 1
    assert captured[0]["change"] == "updated"
    assert captured[0]["item_id"] == item_id


def test_deprecate_endpoint_still_rejects_a_non_owner_non_admin_caller(client, normal_user_client):
    item = _create_item("http-test/deprecate-not-mine")
    resp = normal_user_client.post(f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/deprecate")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "POLICY_FORBIDDEN"


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
    # can_admin_surfaces added below the original two keys this test
    # asserted -- see test_get_config_caller_permissions_includes_can_admin_surfaces_over_real_http
    # for the dedicated regression covering the real bug (response_model
    # silently stripping this field) this fix closed.
    assert admin_resp.json()["caller_permissions"] == {"can_share": True, "can_provision": True, "can_admin_surfaces": True}

    normal_resp = normal_user_client.get("/ainxt/v1/api/ecosystem/config")
    assert normal_resp.status_code == 200, normal_resp.text
    # role="developer" has marketplace:share but not marketplace:provision
    # (auth/rbac.py) -- distinct from features.provisioning, which stays
    # true for the whole `enterprise` product regardless of caller.
    assert normal_resp.json()["caller_permissions"] == {"can_share": True, "can_provision": False, "can_admin_surfaces": False}
    assert normal_resp.json()["features"]["provisioning"] is True


def test_install_rejects_a_forged_provisioned_or_required_scope_from_a_non_admin_caller(normal_user_client):
    item = _create_item("http-test/scope-forgery-item")

    # org-wide provisioning (org/provisioned/required) stays
    # marketplace:provision-only, regardless of who_can_share -- these are
    # two independent policies (product correction, 2026-09-27).
    for forged_scope in ("provisioned", "required", "org"):
        resp = normal_user_client.post(
            f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
            json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": forged_scope, "origin": "added"},
        )
        assert resp.status_code == 403, f"scope={forged_scope!r} should be rejected for a non-admin caller, got {resp.status_code}: {resp.text}"
        assert resp.json()["detail"]["code"] == "POLICY_FORBIDDEN"

    # The UI is bypassed above (a raw API call, no client-side gating at
    # all) -- proves the enforcement is real server-side, not merely
    # AddDialog.tsx hiding the radio button. "private"/"shared" are the
    # scopes a normal user may actually use under the default org policy.
    #
    # A fresh item per scope, not the same `item` reused across both: since
    # BUG-004's fix, scope="shared" stamps installed_for=caller_user_id just
    # like "private" does -- the same caller installing both scopes on the
    # SAME item would now genuinely collide on (item_id, org_id,
    # installed_for), which isn't what this loop is testing (it's checking
    # each scope is independently allowed, not that both coexist for one
    # caller on one item).
    for allowed_scope in ("private", "shared"):
        scoped_item = _create_item(f"http-test/scope-forgery-item-{allowed_scope}")
        ok_resp = normal_user_client.post(
            f"/ainxt/v1/api/ecosystem/items/{scoped_item['item_id']}/install",
            json={"version_id": scoped_item["version_id"], "surfaces": ["chat"], "scope": allowed_scope, "origin": "added"},
        )
        assert ok_resp.status_code == 201, f"scope={allowed_scope!r}: {ok_resp.text}"


def test_install_with_empty_string_version_id_returns_clean_400_not_500(client):
    """BUG-005: InstallRequest.version_id is typed `str | None` -- an empty
    string "" is a valid str (not None), so it used to slip past the
    `if version_id is None:` VERSION_ID_REQUIRED check entirely and reach
    installs_service.install() with a literal empty-string version_id,
    raising a raw DB-level error (500, confirmed live) instead of the same
    clean validated 400 an omitted version_id already got. Empty string is
    now normalized to None before that check runs, so both cases share the
    one validated path."""
    item = _create_item("http-test/empty-version-id-item")
    resp = client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": "", "surfaces": ["chat"], "scope": "private", "origin": "added"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "VERSION_ID_REQUIRED"


def test_install_rejects_shared_scope_when_org_restricts_who_can_share_to_admins(client, normal_user_client):
    # Created by the normal-user identity, not "http-test-user" (client's
    # own identity): BUG-004's fix made scope="shared" stamp
    # installed_for=caller_user_id just like "private" does, so if `client`
    # (admin) were also this item's own creator, create_via_write()'s own
    # auto-install would already own (item_id, org_id, "http-test-user"),
    # and admin's own shared-scope install below would collide with it --
    # a real constraint, just not what this test is about (it's checking
    # the who_can_share policy bypass, not same-user re-install behavior).
    # normal_user_client's own rejected attempt below never reaches an
    # insert either way (403s on the policy check first), so its identity
    # being the creator doesn't matter for that half of the test.
    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id="http-test-org", created_by="http-test-normal-user", item_type="skill",
            namespace="http-test/who-can-share-restricted", display_name="d", description="d",
            category="productivity", tags=[], license="MIT",
            content={"instructions": "x", "files": []}, surfaces=["chat"],
        )
    put_resp = client.put("/ainxt/v1/api/ecosystem/policy", json={"who_can_share": "admins_only"})
    assert put_resp.status_code == 200, put_resp.text
    try:
        resp = normal_user_client.post(
            f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
            json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "shared", "origin": "added"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "POLICY_FORBIDDEN"

        admin_resp = client.post(
            f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
            json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "shared", "origin": "added"},
        )
        assert admin_resp.status_code == 201, admin_resp.text  # marketplace:provision always passes
    finally:
        client.put("/ainxt/v1/api/ecosystem/policy", json={"who_can_share": "all_users"})


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


# ── Item 2 (2026-09-29 live-test round): "Add returns immediately with the
# install/run id; the UI shows status from the server ... never from an
# in-flight browser request." These guard the two backend pieces that fix
# had to change: install_item()'s response is now the SAME async-envelope
# shape GET /ecosystem/jobs/{id} returns (a real, pollable id from the very
# first response), and a resent Idempotency-Key returns the ORIGINAL result
# instead of a false ConflictError.

def test_install_response_is_job_shaped_with_a_real_pollable_job_id(normal_user_client):
    # normal_user_client, not client/creator: create_via_write()'s "ui_add"
    # trigger auto-installs the CREATOR privately on pass (Review round
    # following M1, item E) -- installing again as that same identity
    # would collide with that auto-install's own (item, org, installed_for)
    # row, a real but unrelated conflict. A different installer keeps this
    # test isolated to the one thing it actually checks.
    item = _create_item("http-test/install-job-shape")
    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "private", "origin": "added"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    for key in ("job_id", "status", "item_id", "version_id", "gate_run_id", "error", "install_id"):
        assert key in body, f"missing {key!r} in install_item() response: {body}"
    assert body["job_id"], "install_item() must hand back a real id to poll, not None"
    assert body["item_id"] == item["item_id"]
    assert body["version_id"] == item["version_id"]
    assert body["install_id"]
    # A private install never widens the gate (no NEW run) -- job_id falls
    # back to the version's existing (already-resolved) fast-path run, so
    # this must already read as terminal on the very first response, not
    # "verifying" forever.
    assert body["status"] != "verifying"

    # The job_id handed back is real and independently pollable -- exactly
    # the mechanism the UI must poll instead of trusting its own in-flight
    # POST promise (item 2's whole point).
    job_resp = normal_user_client.get(f"/ainxt/v1/api/ecosystem/jobs/{body['job_id']}")
    assert job_resp.status_code == 200, job_resp.text
    assert job_resp.json()["status"] == body["status"]


def test_install_response_job_id_reflects_a_real_scope_widen_gate_run(client, normal_user_client):
    # A shared/org/provisioned/required install upgrades a fast-pathed
    # version to the full gate (ensure_full_gate_for_scope_widen) -- the
    # NEW gate run it enqueues, not the item's original fast-path run,
    # must be what the client polls. This test's own TestClient call is
    # synchronous end to end (no separate out-of-process worker in this
    # test process), and the ethics stage's real, unmocked LLM call
    # (network-latency-bound, not instant, but still faster than this
    # request's own timeout) can genuinely resolve the widen run to a
    # terminal verdict before install_item() ever returns -- confirmed
    # live, 2026-09-29 (a real `warn` came back, not `verifying`). The
    # actually load-bearing invariant is that the response references
    # the correct NEW gate run, not its exact status at this instant --
    # fixed to assert that instead of a specific, timing-dependent value.
    #
    # Installs as normal_user_client, NOT client (the item's own creator):
    # BUG-004 fix (routers/ecosystem_router.py) made scope="shared" stamp
    # installed_for=caller_user_id like every other personal install (it
    # used to always be None) -- _create_item() already auto-installs its
    # own creator ("http-test-user", client's identity) privately, so
    # client itself installing scope="shared" on its own item now
    # genuinely collides with that pre-existing row on (item_id, org_id,
    # installed_for), a real constraint this test was never exercising
    # before the fix. A different caller accepting/widening scope on
    # someone else's item -- the actual scenario this test is about -- has
    # no such prior install and is unaffected.
    item = _create_item("http-test/install-job-widen")
    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat"], "scope": "shared", "origin": "added"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["gate_run_id"], "a scope widen must report the new gate run it just enqueued"
    assert body["gate_run_id"] != item["gate_run_id"], "must be the NEW widen run, not the original fast-path one"
    assert body["job_id"] == body["gate_run_id"]
    # Exactly _VERDICT_TO_STATUS's real value set (create_service.py):
    # pending->verifying, pass->active, warn->warn, fail->blocked.
    assert body["status"] in ("verifying", "active", "warn", "blocked"), body["status"]


def test_install_retried_with_the_same_idempotency_key_returns_the_original_result_not_a_conflict(normal_user_client):
    # The real bug this guards: a caller that lost track of an in-flight
    # Add (e.g. a client remount losing local state, item 2's own report)
    # and resubmits with the SAME Idempotency-Key must get back the
    # original success, never installs_service.install()'s own
    # ConflictError from the (item, org, installed_for) UNIQUE constraint.
    # normal_user_client (not the creator) for the same reason as the
    # job-shape test above -- isolates this from create_via_write()'s own
    # auto-install-the-creator side effect.
    item = _create_item("http-test/install-idempotent-retry")
    idempotency_key = "test-idem-key-install-retry-1"
    payload = {"version_id": item["version_id"], "surfaces": ["chat"], "scope": "private", "origin": "added"}

    first = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json=payload, headers={"Idempotency-Key": idempotency_key},
    )
    assert first.status_code == 201, first.text

    second = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json=payload, headers={"Idempotency-Key": idempotency_key},
    )
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


def test_install_without_an_idempotency_key_still_conflicts_on_a_genuine_duplicate(normal_user_client):
    # No key sent at all (an older/other caller) -- behavior unchanged from
    # before this fix: a real second install attempt for the same (item,
    # org, installed_for) still surfaces as a real conflict, since there is
    # no key for the server to recognize this as a retry of the same call.
    item = _create_item("http-test/install-no-idem-key-conflict")
    payload = {"version_id": item["version_id"], "surfaces": ["chat"], "scope": "private", "origin": "added"}

    first = normal_user_client.post(f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install", json=payload)
    assert first.status_code == 201, first.text

    second = normal_user_client.post(f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install", json=payload)
    assert second.status_code == 409, second.text


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




# ── Task 4 (live user report): "surface checkboxes can't be toggled" --
# no endpoint existed to change an install's surfaces before this. Same
# real-HTTP-round-trip rigor as the disable-removes-from-chat test above:
# a live capabilities check, not just the pieces in isolation.

def test_set_surfaces_owner_can_toggle_and_it_is_reflected_live_in_chat_capabilities(client):
    item = _create_item("http-test/set-surfaces-owner")
    installs = client.get("/ainxt/v1/api/ecosystem/installs").json()["installs"]
    install = next(i for i in installs if i["item"]["id"] == item["item_id"])
    assert install["surfaces"] == ["chat"]

    before = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert any(s["namespace"] == "http-test/set-surfaces-owner" for s in before.json()["skills"])

    resp = client.post(f"/ainxt/v1/api/ecosystem/installs/{install['install_id']}/set-surfaces", json={"surfaces": []})
    assert resp.status_code == 200, resp.text
    assert resp.json()["surfaces"] == []

    after = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert not any(s["namespace"] == "http-test/set-surfaces-owner" for s in after.json()["skills"])

    # And adding it back brings it straight back -- a real two-way switch.
    client.post(f"/ainxt/v1/api/ecosystem/installs/{install['install_id']}/set-surfaces", json={"surfaces": ["chat"]})
    reenabled = client.get("/ainxt/v1/api/ecosystem/capabilities", params={"surface": "chat"})
    assert any(s["namespace"] == "http-test/set-surfaces-owner" for s in reenabled.json()["skills"])


def test_set_surfaces_rejects_a_same_org_non_owner_non_admin(normal_user_client, client):
    item = _create_item("http-test/set-surfaces-forbidden")
    installs = client.get("/ainxt/v1/api/ecosystem/installs").json()["installs"]
    install = next(i for i in installs if i["item"]["id"] == item["item_id"])

    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/installs/{install['install_id']}/set-surfaces", json={"surfaces": []},
    )
    assert resp.status_code == 403, resp.text


def test_set_surfaces_refuses_to_change_a_required_installs_surfaces(client):
    item = _create_item("http-test/set-surfaces-required")
    # _create_item()'s own trigger already auto-installs "http-test-user"
    # privately for this item -- installing again for the SAME
    # (item, org, installed_for) hits the real UNIQUE constraint (409), so
    # a distinct installed_for is used here, same fix as this session's
    # other provisioned-install test bug.
    from services.ecosystem import installs_service

    required_install = installs_service.install(
        item_id=item["item_id"], version_id=item["version_id"], org_id="http-test-org",
        installed_by="http-test-user", installed_for="http-test-required-teammate",
        surfaces=["chat"], scope="required", origin="required",
    )
    patch_resp = client.post(
        f"/ainxt/v1/api/ecosystem/installs/{required_install['install_id']}/set-surfaces",
        json={"surfaces": ["chat", "desktop"]},
    )
    assert patch_resp.status_code == 400, patch_resp.text  # plain EcosystemError falls through to BAD_REQUEST


# ── Per-surface toggles round (2026-09-29): the manual Chat/Agent Studio/
# Desktop toggle UI is gone for normal users -- set-surfaces is now
# admin-only end-to-end (RBAC, not just ownership), a fresh install with no
# explicit surfaces defaults to the org's product-profile-allowed set, and
# the file/terminal-tools compatibility exception is enforced at install
# time too (a real, pre-existing gap: it used to only ever run at item-
# CREATE time).

def test_set_surfaces_now_requires_admin_permission_even_for_the_installs_own_owner():
    # Before this round, ownership alone was enough (see the "owner can
    # toggle" test above, which happens to also be an admin -- this test
    # isolates the ownership-without-admin case that changed). A plain
    # developer-role caller who genuinely owns the install must now also
    # be refused: the toggle is admin-only, full stop, not "admin OR owner".
    # Setup goes straight through installs_service.install() (same
    # convention test_set_surfaces_refuses_to_change_a_required_installs_surfaces
    # above uses) rather than the real async gate -- what's under test is
    # the RBAC gate on set-surfaces, not gate/creation behavior.
    item = _create_item("http-test/set-surfaces-owner-nonadmin")
    from services.ecosystem import installs_service

    own_install = installs_service.install(
        item_id=item["item_id"], version_id=item["version_id"], org_id="http-test-org",
        installed_by="http-test-owner-nonadmin", installed_for="http-test-owner-nonadmin",
        surfaces=["chat"], scope="private", origin="added",
    )

    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "http-test-owner-nonadmin", "user_id": "http-test-owner-nonadmin",
        "org_id": "http-test-org", "role": "developer",
    }
    owner_client = TestClient(app)

    resp = owner_client.post(
        f"/ainxt/v1/api/ecosystem/installs/{own_install['install_id']}/set-surfaces", json={"surfaces": []},
    )
    assert resp.status_code == 403, resp.text


def test_set_surfaces_still_enforces_the_compatibility_exception_for_an_admin(client):
    # Not a manual toggle escape hatch: even an admin explicitly using the
    # "Advanced" override cannot hand a tool-dependent skill the chat
    # surface -- this is a computed constraint, not something the removed
    # (or the admin-only replacement) UI is allowed to override. Setup goes
    # straight through create_service (for a real manifest with
    # compatibility stamped) + installs_service.install() directly, same
    # gate-bypass convention as the test above.
    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id="http-test-org", created_by="http-test-user", item_type="skill",
            namespace="http-test/set-surfaces-tool-dependent", display_name="d", description="d",
            category="productivity", tags=[], license="MIT",
            content={"instructions": "```bash\nls -la\n```", "files": []}, surfaces=["cowork", "desktop"],
        )
    from services.ecosystem import installs_service

    install_row = installs_service.install(
        item_id=item["item_id"], version_id=item["version_id"], org_id="http-test-org",
        installed_by="http-test-user", installed_for="http-test-tool-dep-owner",
        surfaces=["cowork", "desktop"], scope="private", origin="added",
    )

    resp = client.post(
        f"/ainxt/v1/api/ecosystem/installs/{install_row['install_id']}/set-surfaces",
        json={"surfaces": ["chat", "desktop"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["surfaces"] == ["desktop"]  # "chat" silently dropped, not rejected outright


def test_install_without_explicit_surfaces_defaults_to_the_product_profiles_enabled_surfaces(normal_user_client):
    # normal_user_client, not client/creator: _create_item()'s own "ui_add"
    # trigger already auto-installs the creator ("http-test-user")
    # privately with surfaces=["chat"] (that's create-time enforcement,
    # unrelated to what's under test here) -- a distinct installer avoids
    # colliding with that row and actually exercises the install
    # endpoint's own new default. http-test-org has no explicit
    # entitlement row -- _resolve_product() falls back to the seeded
    # 'enterprise' profile, whose enabled_surfaces is
    # ["chat", "agent_studio", "desktop"] (db/migrate.py Part AD1).
    item = _create_item("http-test/install-default-surfaces")
    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "scope": "private", "origin": "added"},
    )
    assert resp.status_code == 201, resp.text
    installs = normal_user_client.get("/ainxt/v1/api/ecosystem/installs").json()["installs"]
    install = next(i for i in installs if i["item"]["id"] == item["item_id"])
    assert sorted(install["surfaces"]) == sorted(["chat", "agent_studio", "desktop"])


def test_install_never_lands_a_tool_dependent_skill_on_the_chat_surface_even_if_explicitly_requested(normal_user_client):
    # normal_user_client, not client/creator: create_via_write()'s "ui_add"
    # trigger already auto-installs the creator ("http-test-user")
    # privately -- installing again as that same identity would collide
    # with that auto-install's own (item, org, installed_for) row (same
    # convention test_install_response_is_job_shaped_with_a_real_pollable_job_id
    # above uses this fixture for, and for the same reason).
    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id="http-test-org", created_by="http-test-user", item_type="skill",
            namespace="http-test/install-tool-dependent-chat-blocked", display_name="d", description="d",
            category="productivity", tags=[], license="MIT",
            content={"instructions": "run the following command to set things up", "files": []},
            surfaces=["cowork", "desktop"],
        )
    resp = normal_user_client.post(
        f"/ainxt/v1/api/ecosystem/items/{item['item_id']}/install",
        json={"version_id": item["version_id"], "surfaces": ["chat", "desktop"], "scope": "private", "origin": "added"},
    )
    assert resp.status_code == 201, resp.text
    installs = normal_user_client.get("/ainxt/v1/api/ecosystem/installs").json()["installs"]
    install = next(i for i in installs if i["item"]["id"] == item["item_id"])
    assert "chat" not in install["surfaces"]
    assert "desktop" in install["surfaces"]


def test_list_items_etag_round_trip_304_on_repeat_request_no_change(client):
    # Catalog-checking round (2026-09-28), section 6: a client sending
    # back the ETag it was just given gets a 304 with no body, for the
    # exact same query/caller -- real bandwidth savings for a client
    # re-polling Discover with nothing changed.
    first = client.get("/ainxt/v1/api/ecosystem/items", params={"item_type": "skill"})
    assert first.status_code == 200, first.text
    etag = first.headers.get("etag")
    assert etag, "GET /ecosystem/items must set an ETag response header"
    assert "private" in first.headers.get("cache-control", "")

    second = client.get(
        "/ainxt/v1/api/ecosystem/items", params={"item_type": "skill"}, headers={"If-None-Match": etag},
    )
    assert second.status_code == 304, second.text
    assert second.content in (b"", None)


def test_list_items_etag_reflects_real_content_change(client):
    # The ETag has to be a real hash of the response body, not a constant
    # per-endpoint value -- proven by seeding a directly-visible
    # (central_index) item between two otherwise-identical requests and
    # confirming the ETag actually moves.
    before = client.get("/ainxt/v1/api/ecosystem/items", params={"item_type": "skill", "sort": "newest"})
    etag_before = before.headers.get("etag")

    from db.database import SessionLocal
    from db.models import EcosystemItem
    from services.ecosystem.items_service import get_or_create_import_source

    db = SessionLocal()
    try:
        source_id = get_or_create_import_source(
            kind="github_repo", url="https://github.com/acme/etag-test",
            created_by="http-test-user", tos_notes="test",
        )
        db.add(EcosystemItem(
            namespace="acme/etag-test", item_type="skill", category="general", tags=[],
            display_name="ETag Test Skill", description="d", source_id=source_id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT", status="active",
        ))
        db.commit()
    finally:
        db.close()

    after = client.get("/ainxt/v1/api/ecosystem/items", params={"item_type": "skill", "sort": "newest"})
    assert after.headers.get("etag") != etag_before
