# SPDX-License-Identifier: MIT
# ============================================================
# Backend prerequisites for task M4 (Frontend): items_service.list_items()/
# get_item() (previously NotImplementedError/minimal stub),
# items_service.delete_draft(), versions_service.list_versions(),
# gate_service.list_gate_runs()/list_recent_findings(), and
# policy_service.get_policy()/set_policy() + create_service's who_can_add
# enforcement. Tier-2 — real Postgres. Ethics stage mocked for determinism,
# same convention as test_create_service.py.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.ecosystem import create_service, gate_service, items_service, policy_service, versions_service
from services.ecosystem.errors import NotFoundError, PolicyForbiddenError


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _create_passing_item(*, org_id, created_by, namespace, **kwargs):
    with _mock_ethics_pass():
        return create_service.create_via_write(
            org_id=org_id, created_by=created_by, item_type="skill", namespace=namespace,
            display_name=kwargs.pop("display_name", "Test Item"), description=kwargs.pop("description", "d"),
            category=kwargs.pop("category", "productivity"), tags=kwargs.pop("tags", []),
            license=kwargs.pop("license", "MIT"),
            content=kwargs.pop("content", {"instructions": "do the thing", "files": []}),
            surfaces=kwargs.pop("surfaces", ["chat"]),
            **kwargs,
        )


# ── list_items / get_item ────────────────────────────────────────────────

def test_get_item_returns_full_detail_by_id_and_by_namespace():
    result = _create_passing_item(org_id="org-list", created_by="user-a", namespace="acme/detail-item")
    item_id = result["item_id"]

    by_id = items_service.get_item(item_id, caller_org_id="org-list", caller_user_id="user-a", caller_permissions=set())
    by_ns = items_service.get_item("acme/detail-item", caller_org_id="org-list", caller_user_id="user-a", caller_permissions=set())

    assert by_id is not None and by_ns is not None
    assert by_id["id"] == by_ns["id"] == item_id
    assert by_id["latest_verdict"] == "pass"
    assert by_id["publisher"]["slug"] == "acme"
    assert "manifest" in by_id and "attribution" in by_id and "source" in by_id
    assert "delete_draft" in by_id["allowed_actions"]  # creator, private, no other installs


def test_get_item_returns_none_for_unknown_id():
    assert items_service.get_item("00000000-0000-0000-0000-000000000000", caller_org_id="org-list") is None


def test_get_item_enforces_cross_org_isolation():
    result = _create_passing_item(org_id="org-list-a", created_by="user-a", namespace="acme/private-to-a")
    item_id = result["item_id"]

    assert items_service.get_item(item_id, caller_org_id="org-list-b", caller_user_id="user-b") is None
    listing_b = items_service.list_items(caller_org_id="org-list-b", caller_user_id="user-b")
    assert item_id not in [i["id"] for i in listing_b["items"]]

    listing_a = items_service.list_items(caller_org_id="org-list-a", caller_user_id="user-a")
    assert item_id in [i["id"] for i in listing_a["items"]]


def test_list_items_filters_by_category_and_status():
    _create_passing_item(org_id="org-filter", created_by="user-a", namespace="acme/finance-item", category="finance")
    _create_passing_item(org_id="org-filter", created_by="user-a", namespace="acme/design-item", category="design")

    finance_only = items_service.list_items(caller_org_id="org-filter", caller_user_id="user-a", category=["finance"])
    namespaces = {i["namespace"] for i in finance_only["items"]}
    assert "acme/finance-item" in namespaces
    assert "acme/design-item" not in namespaces


def test_list_items_verdict_filter_matches_latest_version_gate_verdict():
    _create_passing_item(org_id="org-verdict", created_by="user-a", namespace="acme/verdict-item")

    passing = items_service.list_items(caller_org_id="org-verdict", caller_user_id="user-a", verdict=["pass"])
    failing = items_service.list_items(caller_org_id="org-verdict", caller_user_id="user-a", verdict=["fail"])

    assert "acme/verdict-item" in {i["namespace"] for i in passing["items"]}
    assert "acme/verdict-item" not in {i["namespace"] for i in failing["items"]}


def test_list_items_pagination_cursor_advances():
    for n in range(3):
        _create_passing_item(org_id="org-page", created_by="user-a", namespace=f"acme/page-item-{n}")

    page1 = items_service.list_items(caller_org_id="org-page", caller_user_id="user-a", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = items_service.list_items(caller_org_id="org-page", caller_user_id="user-a", limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 1
    ids_page1 = {i["id"] for i in page1["items"]}
    ids_page2 = {i["id"] for i in page2["items"]}
    assert not (ids_page1 & ids_page2)


# ── versions / gate-runs ─────────────────────────────────────────────────

def test_list_versions_orders_newest_first_and_marks_current():
    result = _create_passing_item(org_id="org-ver", created_by="user-a", namespace="acme/versioned-item")
    versions = versions_service.list_versions(result["item_id"], caller_org_id="org-ver")
    assert len(versions) == 1
    assert versions[0]["is_current"] is True
    assert versions[0]["gate_verdict"] == "pass"


def test_list_gate_runs_returns_findings_shape():
    result = _create_passing_item(org_id="org-gate", created_by="user-a", namespace="acme/gate-run-item")
    runs = gate_service.list_gate_runs(result["item_id"], caller_org_id="org-gate")
    assert len(runs) == 1
    assert runs[0]["verdict"] == "pass"
    assert runs[0]["trigger"] == "ui_add"
    assert isinstance(runs[0]["findings"], list)


def test_list_recent_findings_scoped_to_org_and_builtin():
    _create_passing_item(org_id="org-findings-a", created_by="user-a", namespace="acme/findings-item-a")
    findings_a = gate_service.list_recent_findings(org_id="org-findings-a")
    findings_b = gate_service.list_recent_findings(org_id="org-findings-b")
    # A cross-org admin must never see another org's items' findings history.
    a_item_ids = {f["item_id"] for f in findings_a}
    b_item_ids = {f["item_id"] for f in findings_b}
    assert not (a_item_ids & b_item_ids) or not a_item_ids  # disjoint (or empty if no findings at all)


# ── delete_draft ─────────────────────────────────────────────────────────

def test_delete_draft_removes_owner_private_zero_install_item():
    result = _create_passing_item(org_id="org-del", created_by="owner-1", namespace="acme/deletable-item")
    item_id = result["item_id"]

    items_service.delete_draft(item_id, caller_user_id="owner-1", caller_org_id="org-del", caller_permissions=set())

    assert items_service.get_item(item_id, caller_org_id="org-del", caller_user_id="owner-1") is None
    # Deleted -> not just empty, genuinely not found (the item itself is gone,
    # not merely version-less/run-less) -- matches list_versions()/
    # list_gate_runs()'s own new visibility check raising rather than
    # silently returning [].
    with pytest.raises(NotFoundError):
        versions_service.list_versions(item_id, caller_org_id="org-del")
    with pytest.raises(NotFoundError):
        gate_service.list_gate_runs(item_id, caller_org_id="org-del")


def test_delete_draft_rejects_non_owner():
    result = _create_passing_item(org_id="org-del2", created_by="owner-2", namespace="acme/not-your-draft")
    item_id = result["item_id"]

    with pytest.raises(PolicyForbiddenError):
        items_service.delete_draft(item_id, caller_user_id="someone-else", caller_org_id="org-del2", caller_permissions=set())

    # Rejected, not partially applied — the item must still exist afterwards.
    assert items_service.get_item(item_id, caller_org_id="org-del2", caller_user_id="owner-2") is not None


def test_delete_draft_rejects_when_another_install_exists():
    result = _create_passing_item(org_id="org-del3", created_by="owner-3", namespace="acme/shared-draft")
    item_id, version_id = result["item_id"], result["version_id"]

    from services.ecosystem.installs_service import install

    install(
        item_id=item_id, version_id=version_id, org_id="org-del3",
        installed_by="teammate-1", installed_for="teammate-1", surfaces=["chat"],
        scope="shared", origin="shared",
    )

    with pytest.raises(PolicyForbiddenError):
        items_service.delete_draft(item_id, caller_user_id="owner-3", caller_org_id="org-del3", caller_permissions=set())


# ── policy_service ────────────────────────────────────────────────────────

def test_get_policy_returns_documented_defaults_for_a_new_org():
    policy = policy_service.get_policy("org-never-configured")
    assert policy == {
        "org_id": "org-never-configured", "who_can_add": "all_users",
        "allowed_sources": ["central_index"], "auto_update_default": False,
    }


def test_set_policy_partial_update_preserves_other_fields():
    policy_service.set_policy("org-policy-partial", auto_update_default=True, updated_by="admin-1")
    updated = policy_service.set_policy("org-policy-partial", who_can_add="admins_only", updated_by="admin-1")
    assert updated["who_can_add"] == "admins_only"
    assert updated["auto_update_default"] is True  # not reset by the second, unrelated update


def test_set_policy_rejects_invalid_who_can_add():
    from services.ecosystem.errors import EcosystemError

    with pytest.raises(EcosystemError):
        policy_service.set_policy("org-policy-invalid", who_can_add="nonsense", updated_by="admin-1")


def test_who_can_add_admins_only_narrows_create_service_on_next_request():
    # This is the exact test B-19's own module docstring said didn't exist
    # yet ("a policy-change test confirming who_can_add actually narrows
    # create_service's behavior on the next request") -- closed now that
    # the backing table exists.
    policy_service.set_policy("org-narrow", who_can_add="admins_only", updated_by="admin-1")

    with pytest.raises(PolicyForbiddenError):
        with _mock_ethics_pass():
            create_service.create_via_write(
                org_id="org-narrow", created_by="regular-user", item_type="skill", namespace="acme/blocked-by-policy",
                display_name="Blocked", description="d", category="productivity", tags=[],
                license="MIT", content={"instructions": "x", "files": []}, surfaces=[],
                caller_permissions=set(),
            )

    # An admin-permissioned caller is unaffected by the same policy.
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-narrow", created_by="admin-user", item_type="skill", namespace="acme/allowed-by-policy",
            display_name="Allowed", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": "x", "files": []}, surfaces=[],
            caller_permissions={"marketplace:admin_policy"},
        )
    assert result["status"] == "verifying"


def test_who_can_add_all_users_default_does_not_block_anyone():
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-default-policy", created_by="regular-user", item_type="skill", namespace="acme/default-policy-item",
            display_name="Fine", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": "x", "files": []}, surfaces=[],
            caller_permissions=set(),
        )
    assert result["status"] == "verifying"
