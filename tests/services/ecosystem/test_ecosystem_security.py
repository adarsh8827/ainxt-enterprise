# SPDX-License-Identifier: MIT
# ============================================================
# Consolidated security tests for the Ecosystem Marketplace, M5's own
# named requirement (docs/ecosystem/SKILLS_PHASE_PLAN.md's Tests section):
# cross-org isolation, allowed_actions/permission forgery, sandbox escape
# resistance, no skill content ever executing outside the sandbox, and
# license enforcement at every creation boundary.
#
# Reuses existing, already-real coverage where it's already solid rather
# than duplicating it (cited inline per area) and adds new tests only
# where a real gap existed. One genuine, severe gap was found while
# writing this file's first version -- see test_install_lifecycle_
# endpoints_require_authentication below and docs/ecosystem/design/
# CHANGELOG.md's own entry for the fix -- and has since been closed: a
# router-level default-auth dependency plus org/ownership checks in
# services/ecosystem/installs_service.py, versions_service.py,
# gate_service.py, and policy_service.py. These tests now assert the
# fixed (secure) behavior for real, not document a gap.
# ============================================================

from __future__ import annotations

import zipfile
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from routers.ecosystem_router import router as ecosystem_router
from services.ecosystem import create_service, installs_service


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _user_ctx(user_id: str, org_id: str, role: str = "user"):
    return {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": role}


@pytest.fixture
def authed_client():
    """Auth overridden to a fixed identity -- for tests where the identity
    itself isn't the thing under test."""
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: _user_ctx("sec-test-user", "sec-test-org-a")
    return TestClient(app)


@pytest.fixture
def unauthenticated_client():
    """No auth override at all -- exercises the real get_current_user
    dependency exactly as a genuinely unauthenticated request would."""
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    return TestClient(app)


def _create_item(org_id: str, user_id: str, namespace: str, license: str = "MIT") -> dict:
    with _mock_ethics_pass():
        return create_service.create_via_write(
            org_id=org_id, created_by=user_id, item_type="skill", namespace=namespace,
            display_name="Security Test Item", description="d", category="productivity", tags=[],
            license=license, content={"instructions": "x", "files": []}, surfaces=["chat"],
        )


def _install_for(item_id: str, version_id: str, org_id: str, user_id: str) -> dict:
    """_create_item() mocks the ethics stage to always return "pass", which
    means the creator is already auto-installed (gate_service._auto_install,
    task B-10) by the time this is called -- reuse that row rather than
    conflicting with it, same as a real second `install` attempt would
    have to."""
    existing = installs_service.get_install_for_caller(item_id, org_id, user_id)
    if existing is not None:
        from services.ecosystem.installs_service import _row_to_dict

        return _row_to_dict(existing)
    return installs_service.install(
        item_id=item_id, version_id=version_id, org_id=org_id,
        installed_by=user_id, installed_for=user_id, surfaces=["chat"],
        scope="private", origin="added",
    )


# ── 1. Cross-org isolation ───────────────────────────────────────────────
# Items/drafts/skill_tools/publishers already have real cross-org tests:
# test_items_list_get_delete_policy.py::test_get_item_enforces_cross_org_isolation,
# test_publishers_service.py::test_cross_org_namespace_isolation_via_publisher_slugs,
# test_drafts_service.py::test_stream_draft_generation_raises_not_found_for_a_draft_in_another_org,
# test_ecosystem_skill_tools.py::test_skill_view_enforces_cross_org_isolation.
# ecosystem_installs had no such test -- and turned out to have a real,
# severe gap once actually exercised over real HTTP (see the
# authentication test group below, the actual root cause).

def test_installs_service_uninstall_and_set_enabled_take_caller_org_and_identity():
    """Root-cause-level proof for the HTTP-level fix below: the *service*
    functions themselves (services/ecosystem/installs_service.py
    uninstall()/set_enabled()/update_to_version()/rollback()) now require
    caller_org_id/caller_user_id/caller_permissions as keyword-only
    parameters -- there is no way to call them without supplying an
    identity to check against. Before the fix, these had no such
    parameter at all (confirmed by signature inspection at the time)."""
    import inspect

    for fn in (installs_service.uninstall, installs_service.set_enabled, installs_service.update_to_version, installs_service.rollback):
        params = set(inspect.signature(fn).parameters)
        assert {"caller_org_id", "caller_user_id", "caller_permissions"} <= params, f"{fn.__name__} is missing caller-identity parameters"


def test_install_lifecycle_endpoints_require_authentication(unauthenticated_client, authed_client):
    """POST /ecosystem/installs/{id}/uninstall, .../set-enabled, .../update,
    and .../rollback (routers/ecosystem_router.py, task B-10) originally
    declared no `current_user: dict = Depends(get_current_user)` parameter
    at all -- unlike every other mutating endpoint in this router. A
    completely unauthenticated caller could uninstall, disable, re-version,
    or roll back ANY install in ANY org, given only its UUID (returned in
    ordinary API responses, not a secret). Confirmed against a real
    running gateway process during this milestone's own manual
    verification. Fixed via a router-level default `dependencies=
    [Depends(get_current_user)]` (routers/ecosystem_router.py) -- this test
    now asserts the correct, secure behavior for real, covering all four
    endpoints (the original finding only demonstrated two)."""
    item = _create_item("sec-test-org-a", "sec-test-user", "sec-test/auth-gap-item")
    install = _install_for(item["item_id"], item["version_id"], "sec-test-org-a", "sec-test-user")
    install_id = install["install_id"]
    version_id = item["version_id"]

    for path, body in [
        (f"/ecosystem/installs/{install_id}/uninstall", None),
        (f"/ecosystem/installs/{install_id}/set-enabled", {"enabled": False}),
        (f"/ecosystem/installs/{install_id}/update", {"version_id": version_id}),
        (f"/ecosystem/installs/{install_id}/rollback", {"version_id": version_id}),
    ]:
        resp = unauthenticated_client.post(f"/ainxt/v1/api{path}", json=body)
        assert resp.status_code == 401, (
            f"{path} returned {resp.status_code} with ZERO authentication "
            f"(expected 401) -- an unauthenticated caller can mutate any "
            f"install by UUID. Body: {resp.text}"
        )


def test_install_lifecycle_endpoints_enforce_org_ownership_even_when_authenticated(authed_client):
    """A second, narrower check: even a caller authenticated as a
    *different org* must not be able to touch org A's install just by
    knowing its UUID. Fixed via installs_service._authorize_install_
    mutation() -- cross-org raises NotFoundError (404), never revealing
    the install exists to a caller outside its org."""
    item = _create_item("sec-test-org-a", "sec-test-user-a", "sec-test/org-ownership-item")
    install = _install_for(item["item_id"], item["version_id"], "sec-test-org-a", "sec-test-user-a")
    install_id = install["install_id"]

    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: _user_ctx("sec-test-user-b", "sec-test-org-b")
    org_b_client = TestClient(app)

    resp = org_b_client.post(f"/ainxt/v1/api/ecosystem/installs/{install_id}/set-enabled", json={"enabled": False})
    assert resp.status_code in (403, 404), (
        f"org B disabled org A's install by UUID alone -- got {resp.status_code}. Body: {resp.text}"
    )


def test_every_ecosystem_route_requires_authentication(unauthenticated_client):
    """The mechanical backstop for the finding above: enumerates every
    single route actually registered on `routers/ecosystem_router.py`
    (not a hand-picked subset) and asserts each one 401s with zero
    Authorization header -- so a future endpoint added to this router
    without its own (or without inheriting the router-level) auth
    dependency fails this test immediately, rather than shipping silently.
    A missing/placeholder body never masks this: FastAPI resolves the
    router-level auth dependency before validating the endpoint's own
    body/path params (confirmed empirically -- an empty POST body still
    401s, never a 422, against a route requiring one), so this test sends
    no body at all and still gets a clean signal for every route."""
    import re

    placeholder = "11111111-1111-1111-1111-111111111111"
    routes = [
        (method, re.sub(r"\{[^}]+\}", placeholder, route.path))
        for route in ecosystem_router.routes
        for method in route.methods
        if method != "HEAD"
    ]
    assert len(routes) >= 25, f"expected the full route set, got only {len(routes)} -- did route discovery break?"

    for method, path in routes:
        resp = unauthenticated_client.request(method, f"/ainxt/v1/api{path}")
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code} with zero auth (expected 401): {resp.text[:200]}"


def test_install_lifecycle_endpoints_allow_the_owner_and_reject_a_same_org_non_owner_non_admin(authed_client):
    """Same-org, wrong caller (not the owner, not an org admin) must get a
    real 403 -- not a 404 (the caller is already inside the org boundary,
    so revealing the install exists is not itself a leak) -- while the
    actual owner succeeds."""
    item = _create_item("sec-test-org-a", "sec-test-user", "sec-test/owner-vs-teammate-item")
    install = _install_for(item["item_id"], item["version_id"], "sec-test-org-a", "sec-test-user")
    install_id = install["install_id"]

    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: _user_ctx("sec-test-teammate", "sec-test-org-a")
    teammate_client = TestClient(app)
    resp = teammate_client.post(f"/ainxt/v1/api/ecosystem/installs/{install_id}/set-enabled", json={"enabled": False})
    assert resp.status_code == 403, resp.text

    owner_resp = authed_client.post(f"/ainxt/v1/api/ecosystem/installs/{install_id}/set-enabled", json={"enabled": False})
    assert owner_resp.status_code == 200, owner_resp.text


# ── 2. allowed_actions / permission forgery ──────────────────────────────
# tests/services/ecosystem/test_compute_allowed_actions.py already covers
# this thoroughly at the unit level (test_forged_admin_permission_not_
# trusted_beyond_what_caller_actually_has and the whole file). No endpoint
# accepts an allowed_actions array as *input* at all (grep confirms
# CreateWriteRequest/InstallRequest/SetEnabledRequest/etc. have no such
# field) -- the real forgery surface is a caller sending extra/unexpected
# JSON fields on a real request and confirming the server never reads
# them as an authorization signal.

def test_forged_permissions_field_in_request_body_is_never_read_as_authorization(authed_client):
    """A caller sending a forged `permissions`/`allowed_actions`/`role`
    field directly in a mutating request body must have zero effect --
    authorization only ever comes from get_current_user's own resolved
    identity, never from caller-supplied body fields. FastAPI/Pydantic
    models ignore unknown fields by default, but this proves it for real
    over HTTP rather than assuming the framework default holds forever."""
    resp = authed_client.post(
        "/ainxt/v1/api/ecosystem/items",
        headers={"Idempotency-Key": "forged-permissions-key"},
        json={
            "create_via": "write", "item_type": "skill", "namespace": "sec-test/forged-perms",
            "display_name": "d", "description": "d", "category": "productivity", "tags": [],
            "license": "MIT", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            # Forged fields a real attacker might try -- none of these are
            # declared on CreateWriteRequest, so Pydantic drops them silently;
            # this test proves that silence doesn't leak into behavior.
            "permissions": ["marketplace:admin_sources", "marketplace:admin_policy"],
            "allowed_actions": ["force_disable", "unyank", "delete_draft"],
            "role": "admin",
        },
    )
    assert resp.status_code == 202, resp.text
    # provision_scope was never granted (caller_permissions resolved from
    # get_current_user, not from the forged "permissions" field) --
    # confirmed by the create succeeding as an ordinary private-scope
    # write, not by any admin-only side effect firing.
    assert resp.json()["provision_scope"] in (None, "private")


# ── 3. Sandbox escape resistance ─────────────────────────────────────────
# tests/services/ecosystem/gate/test_sandbox_stage.py already has 9 real
# tests: clean code passes, syntax errors fail, unapproved imports fail,
# stdlib imports are allowed. Confirming the sandbox stage is actually
# wired into the real gate pipeline (not bypassable by skipping it) and
# that it's off by default outside the dedicated gate-worker.

def test_sandbox_stage_is_part_of_the_real_gate_pipeline_not_a_standalone_check():
    import inspect

    import services.ecosystem.gate_service as gate_service_module

    source = inspect.getsource(gate_service_module)
    assert "sandbox_stage.run(" in source, "run_gate() no longer calls sandbox_stage.run — the sandbox stage would be dead code, silently skipped"


def test_sandbox_execution_is_never_allowed_outside_the_dedicated_gate_worker_process(monkeypatch):
    """ECOSYSTEM_GATE_SANDBOX_ALLOWED (raw os.environ, checked by
    sandbox/ecosystem_gate_executor.py's own _assert_gate_worker_process()
    -- deliberately not core/config.py, so no other process's config
    caching can ever paper over this) gates the Docker-sandbox stage.
    Unset (the default for every process except the dedicated gate-worker
    container) must mean the sandbox refuses to run at all -- never
    silently degrading to "skip the check" (which would be fail-open)."""
    from sandbox.ecosystem_gate_executor import EcosystemGateProcessNotAllowedError, _assert_gate_worker_process

    monkeypatch.delenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", raising=False)
    with pytest.raises(EcosystemGateProcessNotAllowedError):
        _assert_gate_worker_process()

    monkeypatch.setenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", "true")
    _assert_gate_worker_process()  # does not raise once explicitly granted


# ── 4. No skill content ever executes outside the sandbox ───────────────

def test_skill_view_and_read_skill_file_source_never_calls_eval_exec_or_a_shell():
    """skill_view()/read_skill_file() (mcp/ecosystem_skill_tools.py, tasks
    B-15/B-16) are the only way chat-invoked skill content reaches a model
    -- confirming by source inspection that neither function (nor the
    module as a whole) contains eval(/exec(/os.system(/subprocess. --
    they only ever read and return text, never execute it."""
    import inspect

    import mcp.ecosystem_skill_tools as tools_module

    source = inspect.getsource(tools_module)
    for banned in ("eval(", "exec(", "os.system(", "subprocess.run(", "subprocess.Popen(", "subprocess.call("):
        assert banned not in source, f"found {banned!r} in mcp/ecosystem_skill_tools.py"


def test_skill_view_return_type_is_always_text():
    import inspect

    from mcp.ecosystem_skill_tools import read_skill_file, skill_view

    assert inspect.signature(skill_view).return_annotation in (str, "str")
    # read_skill_file's own docstring/CONTRACTS.md §12 allow bytes for a
    # binary path, but no binary-file creation path exists yet (every
    # bundled file this pipeline can create is stored as text) -- so in
    # practice this is str-only today too; not asserted as a hard type
    # check here since the annotation itself documents the union.


# ── 5. License enforcement at every creation boundary ────────────────────
# test_create_service.py already covers create_via_write/create_via_upload/
# create_via_import at the service layer directly. This adds the real
# HTTP-level round trip for write + upload specifically (the two
# boundaries a real client actually hits). Since task C's tiered license
# policy (ECOSYSTEM_PLAN.md §11.2), a default (private-scope) write/upload
# with a disallowed license is no longer a silent pass-through OR an
# outright block -- it requires explicit acknowledgement, confirmed below
# alongside proof that a non-private (org-wide) creation is still hard-
# blocked by default with no acknowledgement able to bypass it.

def test_write_endpoint_requires_acknowledgement_for_gpl_license_over_real_http(authed_client):
    resp = authed_client.post(
        "/ainxt/v1/api/ecosystem/items",
        json={
            "create_via": "write", "item_type": "skill", "namespace": "sec-test/gpl-write",
            "display_name": "d", "description": "d", "category": "productivity", "tags": [],
            "license": "GPL-3.0-only", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "LICENSE_ACKNOWLEDGEMENT_REQUIRED"


def test_upload_endpoint_requires_acknowledgement_for_gpl_license_over_real_http(authed_client):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: quick-scraper\nlicense: GPL-3.0-only\ndescription: d\n---\nBody.")
    buf.seek(0)

    resp = authed_client.post(
        "/ainxt/v1/api/ecosystem/items/upload",
        files={"file": ("quick-scraper.skill", buf, "application/zip")},
        data={"item_type": "skill", "namespace": "sec-test/gpl-upload", "category": "productivity"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "LICENSE_ACKNOWLEDGEMENT_REQUIRED"


def test_write_endpoint_org_wide_gpl_license_still_hard_blocked_with_no_acknowledgement_bypass():
    # provision_scope != private -- Tier 2, not Tier 3. license_acknowledged
    # is Tier 3's own knob and must NOT let a caller bypass Tier 2's org
    # policy just by setting it (the default policy has no GPL entry).
    # Needs marketplace:provision (an admin role) to even reach the license
    # check -- authed_client's role='user' would 403 first, which isn't
    # what this test is proving.
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: _user_ctx("sec-test-admin", "sec-test-org-gpl-block", role="admin")
    admin_client = TestClient(app)
    resp = admin_client.post(
        "/ainxt/v1/api/ecosystem/items",
        json={
            "create_via": "write", "item_type": "skill", "namespace": "sec-test/gpl-write-org-wide",
            "display_name": "d", "description": "d", "category": "productivity", "tags": [],
            "license": "GPL-3.0-only", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
            "provision_scope": "org_default_on", "license_acknowledged": True,
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "LICENSE_NOT_ALLOWED_BY_ORG_POLICY"
