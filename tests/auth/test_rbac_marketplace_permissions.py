# SPDX-License-Identifier: MIT
# ============================================================
# Ecosystem marketplace RBAC permission tests.
#
# Covers docs/ecosystem/SKILLS_PHASE_PLAN.md task B-18 — the 6 new
# marketplace:*/connectors:admin_shared permissions must be present at the
# documented tier, and no existing role's permission set may shrink.
# ============================================================

from __future__ import annotations

from auth.rbac import PERMISSIONS, ROLES, get_all_permissions, has_permission

_NEW_DEVELOPER_PERMS = {"marketplace:add", "marketplace:share"}
_NEW_ADMIN_PERMS = {
    "marketplace:provision",
    "marketplace:admin_sources",
    "marketplace:admin_policy",
    "connectors:admin_shared",
}

# Snapshot of every permission that existed before this task, keyed by role.
# Used only to assert nothing was removed — this list intentionally does not
# grow when new permissions are added elsewhere.
_PRE_EXISTING = {
    "viewer": {
        "chat:read", "agent:read", "skill:read", "workflow:read",
        "project:read", "thread:read", "inbox:read", "metrics:read",
        "health:read",
    },
    "developer": {
        "chat:write", "agent:write", "skill:write", "workflow:write",
        "thread:write",
    },
    "operator": {"project:write", "codebase:write", "mcp:read", "budget:read"},
    "security": {"audit:read", "compliance:read", "user:read"},
    "admin": {"user:write", "budget:write", "mcp:write", "mcp:approve", "admin:all"},
}


def test_developer_gains_marketplace_add_and_share():
    perms = set(get_all_permissions("developer"))
    assert _NEW_DEVELOPER_PERMS <= perms


def test_admin_gains_all_four_admin_tier_permissions():
    perms = set(get_all_permissions("admin"))
    assert _NEW_ADMIN_PERMS <= perms


def test_new_permissions_do_not_collide_with_existing_ones():
    all_existing = {p for perms in _PRE_EXISTING.values() for p in perms}
    all_new = _NEW_DEVELOPER_PERMS | _NEW_ADMIN_PERMS
    assert all_existing.isdisjoint(all_new)


def test_no_existing_permission_was_removed():
    for role, expected in _PRE_EXISTING.items():
        actual = set(get_all_permissions(role))
        assert expected <= actual, f"role {role!r} lost a pre-existing permission"


def test_lower_roles_do_not_inherit_marketplace_provision():
    # marketplace:provision/admin_sources/admin_policy/connectors:admin_shared
    # are admin-only — viewer/developer/operator/security must not have them.
    for role in ("viewer", "developer", "operator", "security"):
        perms = set(get_all_permissions(role))
        assert perms.isdisjoint(_NEW_ADMIN_PERMS), f"role {role!r} should not have admin marketplace perms"


def test_has_permission_helper_reflects_new_grants():
    assert has_permission("developer", "marketplace:add") is True
    assert has_permission("admin", "connectors:admin_shared") is True
    assert has_permission("viewer", "marketplace:provision") is False
