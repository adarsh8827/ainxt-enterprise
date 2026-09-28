# SPDX-License-Identifier: MIT
# ============================================================
# Publisher/namespace service tests (task B-5). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

import pytest

from services.ecosystem.errors import NamespaceInvalidError
from services.ecosystem.publishers_service import (
    _SLUG_RE, derive_caller_publisher_slug, get_publisher, resolve_caller_publisher_slug,
    resolve_publisher, split_namespace,
)


def test_split_namespace_valid():
    assert split_namespace("acme/foo") == ("acme", "foo")


def test_split_namespace_rejects_missing_slash():
    with pytest.raises(NamespaceInvalidError):
        split_namespace("acme-foo")


def test_split_namespace_rejects_extra_slash():
    with pytest.raises(NamespaceInvalidError):
        split_namespace("acme/foo/bar")


def test_split_namespace_rejects_invalid_charset():
    with pytest.raises(NamespaceInvalidError):
        split_namespace("ACME!/foo")


def test_resolve_publisher_auto_provisions_on_first_use():
    slug = resolve_publisher("acme/widget", owner_type="org", owner_ref="org-acme")
    assert slug == "acme"
    row = get_publisher("acme")
    assert row is not None
    assert row["owner_type"] == "org"
    assert row["owner_ref"] == "org-acme"


def test_resolve_publisher_same_owner_reuses_slug():
    resolve_publisher("acme/widget", owner_type="org", owner_ref="org-acme")
    # A second item under the same publisher, same owner -> no error.
    slug = resolve_publisher("acme/gadget", owner_type="org", owner_ref="org-acme")
    assert slug == "acme"


def test_resolve_publisher_rejects_non_owner():
    resolve_publisher("acme/widget", owner_type="org", owner_ref="org-acme")
    with pytest.raises(NamespaceInvalidError):
        resolve_publisher("acme/other-thing", owner_type="org", owner_ref="org-globex")


def test_resolve_publisher_rejects_bad_owner_type():
    with pytest.raises(NamespaceInvalidError):
        resolve_publisher("acme/widget", owner_type="team", owner_ref="org-acme")


def test_get_publisher_missing_returns_none():
    assert get_publisher("does-not-exist") is None


def test_cross_org_namespace_isolation_via_publisher_slugs():
    # Two orgs each using their OWN publisher slug for a same-named item ->
    # no collision, since each org owns a different publisher segment.
    resolve_publisher("acme/foo", owner_type="org", owner_ref="org-acme")
    resolve_publisher("globex/foo", owner_type="org", owner_ref="org-globex")
    assert get_publisher("acme")["owner_ref"] == "org-acme"
    assert get_publisher("globex")["owner_ref"] == "org-globex"


# ---------------------------------------------------------------------------
# derive_caller_publisher_slug / resolve_caller_publisher_slug (task: one-
# click "Copy to my skills" -- no create flow previously had any notion of
# "this caller's own default publisher prefix").
# ---------------------------------------------------------------------------

def test_derive_caller_publisher_slug_is_deterministic():
    assert derive_caller_publisher_slug("user-abc123", "org-a") == derive_caller_publisher_slug("user-abc123", "org-a")


def test_derive_caller_publisher_slug_always_matches_the_slug_charset():
    for raw in ["user-abc123", "John.Doe@example.com", "  MiXeD-Case_ID  ", "12345", "a"]:
        assert _SLUG_RE.match(derive_caller_publisher_slug(raw, "org-a")), raw


def test_derive_caller_publisher_slug_differs_for_different_users_even_with_similar_text():
    # "John.Doe@x.com" and "john_doe@x.com" both sanitize toward the same
    # human-readable text -- the hash suffix is what must keep them apart.
    a = derive_caller_publisher_slug("John.Doe@x.com", "org-a")
    b = derive_caller_publisher_slug("john_doe@x.com", "org-a")
    assert a != b


def test_derive_caller_publisher_slug_differs_across_orgs_for_the_same_user():
    # ecosystem_publishers.slug is globally unique, and every real namespace
    # is provisioned owner_type='org' -- the same user_id active in two
    # different orgs must not derive the same slug (each org would need to
    # "own" it, and only one can).
    a = derive_caller_publisher_slug("user-x", "org-a")
    b = derive_caller_publisher_slug("user-x", "org-b")
    assert a != b


def test_derive_caller_publisher_slug_rejects_empty_user_id():
    with pytest.raises(ValueError):
        derive_caller_publisher_slug("", "org-a")


def test_resolve_caller_publisher_slug_auto_provisions_and_is_idempotent():
    user_id, org_id = "user-caller-provision-test", "org-caller-provision-test"
    slug_first = resolve_caller_publisher_slug(user_id, org_id)
    row = get_publisher(slug_first)
    assert row is not None
    assert row["owner_type"] == "org"
    assert row["owner_ref"] == org_id

    # A second call for the SAME (user, org) returns the same, already-owned
    # slug -- not a collision, not a new row.
    slug_second = resolve_caller_publisher_slug(user_id, org_id)
    assert slug_second == slug_first


def test_resolve_caller_publisher_slug_is_compatible_with_a_real_create_via_write():
    # The real proof this needs to work for: create_via_write()'s own
    # _create_item_and_version() calls resolve_publisher(namespace,
    # owner_type="org", owner_ref=org_id) on whatever namespace it's given
    # -- if resolve_caller_publisher_slug() provisioned its row under a
    # mismatched owner, this would raise NamespaceInvalidError instead of
    # actually creating the copied item.
    from services.ecosystem.create_service import create_via_write

    user_id, org_id = "user-copy-flow-test", "org-copy-flow-test"
    prefix = resolve_caller_publisher_slug(user_id, org_id)
    result = create_via_write(
        org_id=org_id, created_by=user_id, item_type="skill",
        namespace=f"{prefix}/copied-skill", display_name="Copied Skill",
        description="d", category="productivity", tags=[], license="MIT",
        content={"instructions": "Do the thing.", "files": []}, surfaces=["chat"],
    )
    assert result["item_id"]
