# SPDX-License-Identifier: MIT
# ============================================================
# Publisher/namespace service tests (task B-5). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

import pytest

from services.ecosystem.errors import NamespaceInvalidError
from services.ecosystem.publishers_service import get_publisher, resolve_publisher, split_namespace


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
