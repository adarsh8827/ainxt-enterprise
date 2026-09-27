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


def test_edit_content_requires_ownership_or_admin():
    actions = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=False,
    )
    assert "edit_content" not in actions

    actions_owner = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), is_owner=True,
    )
    assert "edit_content" in actions_owner

    actions_admin = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:provision"}, is_owner=False,
    )
    assert "edit_content" in actions_admin

    # deprecate's own admin permission does NOT also unlock edit_content --
    # the two gate on deliberately different permission tiers.
    actions_wrong_admin = compute_allowed_actions(
        item=_item(status="active"), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:admin_sources"}, is_owner=False,
    )
    assert "deprecate" in actions_wrong_admin
    assert "edit_content" not in actions_wrong_admin


def test_edit_content_never_offered_on_a_retired_item_even_for_the_owner():
    for status in ("deprecated", "yanked", "source_unavailable"):
        actions = compute_allowed_actions(
            item=_item(status=status), caller_user_id="u1", caller_org_id="org-a",
            caller_permissions={"marketplace:provision"}, is_owner=True,
        )
        assert "edit_content" not in actions


def test_share_is_policy_driven_not_permission_driven():
    # Sharing is policy-driven (product correction, 2026-09-27):
    # caller_can_share (resolved by the caller from the org's own
    # who_can_share policy, default "all_users") grants "share" with zero
    # RBAC permissions; when the org restricts it (caller_can_share=False,
    # i.e. who_can_share="admins_only"), only marketplace:provision passes.
    actions_default_policy = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a", caller_permissions=set(),
    )
    assert "share" in actions_default_policy  # caller_can_share defaults True

    actions_restricted_no_perm = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions=set(), caller_can_share=False,
    )
    assert "share" not in actions_restricted_no_perm

    actions_restricted_with_provision = compute_allowed_actions(
        item=_item(), install=_install(), caller_user_id="u1", caller_org_id="org-a",
        caller_permissions={"marketplace:provision"}, caller_can_share=False,
    )
    assert "share" in actions_restricted_with_provision  # marketplace:provision always passes regardless of policy


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
        caller_permissions={"marketplace:share", "marketplace:admin_sources", "marketplace:admin_policy", "marketplace:provision"},
        is_owner=True, newer_version_available=True, has_multiple_versions=True,
    )
    documented_order = [
        "install", "uninstall", "enable", "disable", "update", "rollback",
        "share", "unshare", "report", "deprecate", "edit_content", "delete_draft",
        "force_disable", "unyank", "edit_policy",
    ]
    assert actions == [a for a in documented_order if a in actions]
    assert "edit_content" in actions
