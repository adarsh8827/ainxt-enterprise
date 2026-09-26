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
# writing this file -- see test_install_lifecycle_endpoints_require_
# authentication below, and docs/ecosystem/design/CHANGELOG.md's M5
# test-suite entry for the full writeup.
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

def test_installs_service_uninstall_and_set_enabled_do_not_take_a_caller_org_at_all():
    """Root-cause-level proof for the HTTP-level finding below: the
    *service* functions themselves (services/ecosystem/installs_service.py
    uninstall()/set_enabled()) take only an install_id -- no org_id/caller
    identity parameter exists for them to check against at all. This is
    not a missing check inside the function; there is no parameter to
    check. Confirmed by signature inspection rather than a runtime call,
    since calling it for real is exactly what the HTTP-level test below
    does with an actual cross-org attempt."""
    import inspect

    uninstall_params = set(inspect.signature(installs_service.uninstall).parameters)
    set_enabled_params = set(inspect.signature(installs_service.set_enabled).parameters)
    assert "org_id" not in uninstall_params and "caller" not in uninstall_params
    assert "org_id" not in set_enabled_params and "caller" not in set_enabled_params


def test_install_lifecycle_endpoints_require_authentication(unauthenticated_client, authed_client):
    """SEVERITY: high. POST /ecosystem/installs/{id}/uninstall, .../set-enabled,
    .../update, and .../rollback (routers/ecosystem_router.py, task B-10 --
    pre-dates this milestone, out of this task's own scope to fix) declare
    no `current_user: dict = Depends(get_current_user)` parameter at all --
    unlike every other mutating endpoint in this router. A completely
    unauthenticated caller can uninstall, disable, re-version, or roll back
    ANY install in ANY org, given only its UUID (returned in ordinary API
    responses, not a secret). Confirmed against a real running gateway
    process during this milestone's own manual verification before being
    reproduced here. This test currently FAILS -- it asserts the correct,
    secure behavior (401), documenting a real vulnerability rather than
    asserting today's actual (insecure) behavior. Disclosed prominently,
    not fixed here -- fixing routers/ecosystem_router.py is out of this
    task's delegated scope (writing tests), and a change this
    security-sensitive needs its own reviewed commit, not a rider on a
    test-suite change."""
    item = _create_item("sec-test-org-a", "sec-test-user", "sec-test/auth-gap-item")
    install = _install_for(item["item_id"], item["version_id"], "sec-test-org-a", "sec-test-user")
    install_id = install["install_id"]

    for path, body in [
        (f"/ecosystem/installs/{install_id}/uninstall", None),
        (f"/ecosystem/installs/{install_id}/set-enabled", {"enabled": False}),
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
    knowing its UUID. Currently fails for the same root-cause reason as
    the unauthenticated case above (no org check exists in the service
    layer at all) -- kept as a separate test because fixing "requires
    auth" alone would not automatically fix "requires the RIGHT org"."""
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
# create_via_import at the service layer directly (GPL rejected, missing
# frontmatter rejected). This adds the real HTTP-level round trip for
# write + upload specifically (the two boundaries a real client actually
# hits), confirming the router surfaces the same LICENSE_NOT_ALLOWED shape
# consistently regardless of which of the three creation paths was used.

def test_write_endpoint_rejects_gpl_license_over_real_http(authed_client):
    resp = authed_client.post(
        "/ainxt/v1/api/ecosystem/items",
        json={
            "create_via": "write", "item_type": "skill", "namespace": "sec-test/gpl-write",
            "display_name": "d", "description": "d", "category": "productivity", "tags": [],
            "license": "GPL-3.0-only", "content": {"instructions": "x", "files": []}, "surfaces": ["chat"],
        },
    )
    assert resp.status_code in (400, 422)
    assert resp.json()["detail"]["code"] == "LICENSE_NOT_ALLOWED"


def test_upload_endpoint_rejects_gpl_license_over_real_http(authed_client):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: quick-scraper\nlicense: GPL-3.0-only\ndescription: d\n---\nBody.")
    buf.seek(0)

    resp = authed_client.post(
        "/ainxt/v1/api/ecosystem/items/upload",
        files={"file": ("quick-scraper.skill", buf, "application/zip")},
        data={"item_type": "skill", "namespace": "sec-test/gpl-upload", "category": "productivity"},
    )
    assert resp.status_code in (400, 422)
    assert resp.json()["detail"]["code"] == "LICENSE_NOT_ALLOWED"
