# SPDX-License-Identifier: MIT
# ============================================================
# compute_allowed_actions() tests — CONTRACTS.md §6's single source of
# truth for server-side action gating. Pure unit tests, no DB.
# ============================================================

from __future__ import annotations

from types import SimpleNamespace

from services.ecosystem.items_service import compute_allowed_actions


def _item(status="active", scope="org_private", org_id="org-a"):
    return SimpleNamespace(status=status, scope=scope, org_id=org_id)


def _install(scope="private", enabled=True):
    return SimpleNamespace(scope=scope, enabled=enabled)


def test_no_install_offers_install_action():
    actions = compute_allowed_actions(
        item=_item(), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
    )
    assert "install" in actions
    assert "uninstall" not in actions


def test_retired_item_never_offers_install():
    for status in ("deprecated", "yanked", "source_unavailable"):
        actions = compute_allowed_actions(
            item=_item(status=status), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
        )
        assert "install" not in actions


def test_existing_install_offers_uninstall_and_disable():
    actions = compute_allowed_actions(
        item=_item(), install=_install(enabled=True), caller_user_id="u1",
        caller_org_id="org-a", caller_permissions=set(),
    )
    assert "uninstall" in actions
    assert "disable" in actions
    assert "enable" not in actions


def test_disabled_install_offers_enable_not_disable():
    actions = compute_allowed_actions(
        item=_item(), install=_install(enabled=False), caller_user_id="u1",
        caller_org_id="org-a", caller_permissions=set(),
    )
    assert "enable" in actions
    assert "disable" not in actions


def test_required_install_never_offers_enable_or_disable():
    actions = compute_allowed_actions(
        item=_item(), install=_install(scope="required", enabled=True), caller_user_id="u1",
        caller_org_id="org-a", caller_permissions=set(),
    )
    assert "enable" not in actions
    assert "disable" not in actions


def test_report_always_present_even_with_zero_permissions():
    actions = compute_allowed_actions(
        item=_item(), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
    )
    assert "report" in actions


def test_delete_draft_only_for_owner_private_zero_other_installs():
    actions = compute_allowed_actions(
        item=_item(scope="org_private", org_id="org-a"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=True, has_other_installs=False,
    )
    assert "delete_draft" in actions


def test_delete_draft_absent_if_other_installs_exist():
    actions = compute_allowed_actions(
        item=_item(scope="org_private", org_id="org-a"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=True, has_other_installs=True,
    )
    assert "delete_draft" not in actions


def test_delete_draft_absent_for_non_owner():
    actions = compute_allowed_actions(
        item=_item(scope="org_private", org_id="org-a"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=False, has_other_installs=False,
    )
    assert "delete_draft" not in actions


def test_forged_admin_permission_not_trusted_beyond_what_caller_actually_has():
    # This is a pure function -- there's nothing to "forge" past it; the
    # real forged-array defense is that the ROUTER always recomputes this
    # server-side rather than trusting a client-supplied allowed_actions
    # array. This test documents that expectation.
    actions_without_admin = compute_allowed_actions(
        item=_item(), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
    )
    actions_with_admin = compute_allowed_actions(
        item=_item(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:admin_sources"},
    )
    assert "force_disable" not in actions_without_admin
    assert "force_disable" in actions_with_admin


def test_deprecate_requires_ownership_or_admin():
    actions = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=False,
    )
    assert "deprecate" not in actions

    actions_owner = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=True,
    )
    assert "deprecate" in actions_owner


def test_share_requires_marketplace_share_permission():
    actions_no_perm = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
    )
    assert "share" not in actions_no_perm

    actions_with_perm = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:share"},
    )
    assert "share" in actions_with_perm


def test_update_and_rollback_flags():
    actions = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), newer_version_available=True, has_multiple_versions=True,
    )
    assert "update" in actions
    assert "rollback" in actions


def test_action_order_is_stable_and_matches_documented_set():
    actions = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:share", "marketplace:admin_sources", "marketplace:admin_policy"},
        newer_version_available=True, has_multiple_versions=True,
    )
    documented_order = [
        "install", "uninstall", "enable", "disable", "update", "rollback",
        "share", "unshare", "report", "deprecate", "delete_draft",
        "force_disable", "unyank", "edit_policy",
    ]
    assert actions == [a for a in documented_order if a in actions]
