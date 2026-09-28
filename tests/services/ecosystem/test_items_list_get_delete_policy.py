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


def _create_discoverable_item(*, namespace, category="productivity", gate_verdict="pass"):
    """Item 7 fix (M5 UI-parity review, 2026-09-28): `_create_passing_item()`
    above always creates a `scope='org_private'` item, which — correctly,
    as of this fix — never shows up in `list_items()`/Discover for anyone.
    The category/verdict/pagination filter tests below only care about
    those filters, not about org_private visibility, so they need a
    fixture that actually appears in `list_items()`: a `scope='builtin'`
    item (global, no org_id), built the same way
    `scripts/ecosystem/backfill_legacy_items.py`-style seeding does via
    `items_service.upsert_builtin_item()` + a real version. gate_verdict
    defaults to 'pass' (set directly — `create_version_for_content()`
    itself always leaves a fresh version at its own 'pending' default,
    since there's no gate run wired up on this path)."""
    item_id, _ = items_service.upsert_builtin_item(
        namespace=namespace, item_type="skill", category=category,
        display_name="Discoverable Item", description="d",
    )
    version_id = versions_service.create_version_for_content(
        item_id=item_id, content=f"content for {namespace}".encode(), manifest={"name": namespace}, license="MIT",
    )
    from db.database import SessionLocal
    from db.models import EcosystemItemVersion

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
        version.gate_verdict = gate_verdict
        db.commit()
    finally:
        db.close()
    return {"item_id": item_id, "version_id": version_id}


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
    # "Delete permanently" UI review (2026-09-28): the frontend can't tell
    # "delete_draft absent because shared/installed elsewhere" apart from
    # "absent because not owner/built-in/required" without this -- exposed
    # in the response for exactly that reason, not just used internally.
    assert by_id["has_other_installs"] is False


def test_get_item_exposes_item_scope_and_never_fakes_pending_for_a_catalog_item_with_no_version():
    # Round 4 fix (2026-09-29, backend team's own real-Chrome screenshot,
    # docs/ecosystem/design/LLD/gate.md's catalog-checking round): a
    # not-yet-added catalog item (scope="central_index", no
    # EcosystemItemVersion created yet -- materialize_from_catalog()
    # hasn't run) needs item_scope exposed on the wire so the frontend
    # can tell this state apart from one genuinely mid-verification --
    # both used to collapse into the same latest_verdict="pending"
    # fallback with no way to distinguish them.
    from db.database import SessionLocal
    from db.models import EcosystemItem, EcosystemPublisher, EcosystemSource

    db = SessionLocal()
    try:
        if db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == "crawled-pub").first() is None:
            db.add(EcosystemPublisher(slug="crawled-pub", owner_type="org", owner_ref="platform"))
        source = EcosystemSource(kind="local", org_id=None, created_by="system")
        db.add(source)
        db.commit()
        db.refresh(source)

        item = EcosystemItem(
            namespace="crawled-pub/not-yet-added", item_type="skill", category="general",
            display_name="Crawled Item", description="d", source_id=source.id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
    finally:
        db.close()

    result = items_service.get_item(item_id, caller_org_id="org-list", caller_user_id="user-a", caller_permissions=set())
    assert result is not None
    assert result["item_scope"] == "central_index"
    assert result["latest_version"] is None
    # allowed_actions still offers "install" (compute_allowed_actions() is
    # purely status-based, unaffected by whether a version exists yet) --
    # the frontend's own not-yet-added detection is item_scope +
    # latest_version together, never allowed_actions.
    assert "install" in result["allowed_actions"]


def test_get_item_returns_none_for_unknown_id():
    assert items_service.get_item("00000000-0000-0000-0000-000000000000", caller_org_id="org-list") is None


def test_get_item_enforces_cross_org_isolation():
    result = _create_passing_item(org_id="org-list-a", created_by="user-a", namespace="acme/private-to-a")
    item_id = result["item_id"]

    assert items_service.get_item(item_id, caller_org_id="org-list-b", caller_user_id="user-b") is None
    listing_b = items_service.list_items(caller_org_id="org-list-b", caller_user_id="user-b")
    assert item_id not in [i["id"] for i in listing_b["items"]]

    # get_item() (the direct-by-id/namespace detail read) still resolves
    # an org_private item for a caller inside its own org -- only the
    # *list* (Discover) surface excludes it now, see the test right below
    # this one for that narrower assertion (item 7 fix, 2026-09-28).
    assert items_service.get_item(item_id, caller_org_id="org-list-a", caller_user_id="user-a") is not None


def test_list_items_excludes_org_private_from_everyones_discover_feed():
    # Item 7 (M5 UI-parity review, 2026-09-28) -- real bug found live: a
    # caller's own private (org_private) skill/creation was showing up in
    # Discover for the caller AND for every other member of the same org.
    # Discover is the browse-the-catalog surface; an org_private item must
    # never appear there for ANYONE -- not the owner, not a same-org
    # teammate, not a different org -- only in Yours (the owner's own
    # installs) or via a direct share/detail link (get_item(), unaffected
    # by this fix -- see test_get_item_enforces_cross_org_isolation above).
    result = _create_passing_item(org_id="org-list-private", created_by="owner-priv", namespace="acme/owners-private-item")
    item_id = result["item_id"]

    owners_own_discover = items_service.list_items(caller_org_id="org-list-private", caller_user_id="owner-priv")
    assert item_id not in [i["id"] for i in owners_own_discover["items"]]

    teammates_discover = items_service.list_items(caller_org_id="org-list-private", caller_user_id="teammate-in-same-org")
    assert item_id not in [i["id"] for i in teammates_discover["items"]]

    other_org_discover = items_service.list_items(caller_org_id="org-list-private-other", caller_user_id="stranger")
    assert item_id not in [i["id"] for i in other_org_discover["items"]]

    # But the owner's own creation still shows up in Yours (an install
    # exists with origin="created" for the owner from the fast-path
    # auto-install) -- this is the "Created by me" surface's data source.
    from db.database import SessionLocal
    from db.models import EcosystemInstall

    db = SessionLocal()
    try:
        own_install = (
            db.query(EcosystemInstall)
            .filter(EcosystemInstall.item_id == item_id, EcosystemInstall.installed_by == "owner-priv")
            .first()
        )
    finally:
        db.close()
    assert own_install is not None
    assert own_install.origin == "created"


def test_list_items_filters_by_category_and_status():
    # Item 7 fix (2026-09-28): org_private items no longer show in
    # list_items()/Discover for anyone, so this filter-only test (unrelated
    # to visibility) uses the builtin-scope fixture instead of
    # _create_passing_item()'s org_private one.
    _create_discoverable_item(namespace="acme/finance-item", category="finance")
    _create_discoverable_item(namespace="acme/design-item", category="design")

    finance_only = items_service.list_items(caller_org_id="org-filter", caller_user_id="user-a", category=["finance"])
    namespaces = {i["namespace"] for i in finance_only["items"]}
    assert "acme/finance-item" in namespaces
    assert "acme/design-item" not in namespaces


def test_list_items_verdict_filter_matches_latest_version_gate_verdict():
    _create_discoverable_item(namespace="acme/verdict-item", gate_verdict="pass")

    passing = items_service.list_items(caller_org_id="org-verdict", caller_user_id="user-a", verdict=["pass"])
    failing = items_service.list_items(caller_org_id="org-verdict", caller_user_id="user-a", verdict=["fail"])

    assert "acme/verdict-item" in {i["namespace"] for i in passing["items"]}
    assert "acme/verdict-item" not in {i["namespace"] for i in failing["items"]}


def test_list_items_pagination_cursor_advances():
    for n in range(3):
        _create_discoverable_item(namespace=f"acme/page-item-{n}")

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


def test_delete_draft_publishes_an_uninstalled_event_and_invalidates_the_capabilities_cache():
    # Item 9 fix (M5 UI-parity review, 2026-09-28): real gap found live --
    # unlike every install-lifecycle mutation (installs_service.py's own
    # install()/uninstall()/set_enabled()/etc., all of which publish via
    # installs_service._publish_change()), delete_draft() used to
    # bulk-delete the EcosystemInstall row directly and never told anyone
    # -- a deleted skill kept showing up in chat's skill menu (stale
    # resolver_service capabilities cache) until that cache happened to
    # expire on its own, and no ecosystem.changed-subscribed client ever
    # heard about the deletion. Same assertion shape as
    # test_installs_service_lifecycle.py's own
    # test_uninstall_publishes_an_uninstalled_event.
    result = _create_passing_item(org_id="org-del-event", created_by="owner-event", namespace="acme/deletable-event-item")
    item_id = result["item_id"]

    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)), \
         patch("services.ecosystem.resolver_service.invalidate_capabilities_cache") as mock_invalidate:
        items_service.delete_draft(item_id, caller_user_id="owner-event", caller_org_id="org-del-event", caller_permissions=set())

    assert len(captured) == 1
    assert captured[0]["change"] == "uninstalled"
    assert captured[0]["item_id"] == item_id
    mock_invalidate.assert_called_once_with("org-del-event", "owner-event")


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

    # "Delete permanently" UI review (2026-09-28): the owner's own detail
    # response must reflect this too -- has_other_installs=True is what
    # tells the frontend to offer Retire+explanation instead of a delete
    # option that would just 403.
    detail = items_service.get_item(item_id, caller_org_id="org-del3", caller_user_id="owner-3", caller_permissions=set())
    assert detail is not None
    assert detail["has_other_installs"] is True
    assert "delete_draft" not in detail["allowed_actions"]
    assert "deprecate" in detail["allowed_actions"]


# ── policy_service ────────────────────────────────────────────────────────

def test_get_policy_returns_documented_defaults_for_a_new_org():
    policy = policy_service.get_policy("org-never-configured")
    assert policy == {
        "org_id": "org-never-configured", "who_can_add": "all_users",
        "allowed_sources": ["central_index"], "auto_update_default": False,
        # Task C, ECOSYSTEM_PLAN.md §11.2's Tier 2 default.
        "allowed_licenses_shared": ["MIT", "Apache-2.0"],
        # Sharing-policy correction (2026-09-27): normal users can share by
        # default, same "all_users"/"admins_only" shape as who_can_add.
        "who_can_share": "all_users",
        # Catalog-checking round (2026-09-28) defaults.
        "ethics_review_policy": "scripts_or_noncatalog",
        "gate_precheck_enabled": False, "gate_precheck_cap_per_hour": 20,
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
    assert result["status"] == "active"


def test_who_can_add_all_users_default_does_not_block_anyone():
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-default-policy", created_by="regular-user", item_type="skill", namespace="acme/default-policy-item",
            display_name="Fine", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": "x", "files": []}, surfaces=[],
            caller_permissions=set(),
        )
    assert result["status"] == "active"
