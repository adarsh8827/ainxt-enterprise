# SPDX-License-Identifier: MIT
# ============================================================
# Policy service tests (task B-19). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemReport
from services.ecosystem import installs_service, items_service, policy_service
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_item(legacy_ref: str):
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/policy", item_type="skill", category="general",
        display_name="Policy Test", description="d",
        org_id="org-p", legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    with _mock_ethics_pass():
        version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="content", manifest={})
    return item_id, version_id


def test_share_and_unshare():
    item_id, version_id = _make_item("policy-share")
    install = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-p",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    shared = policy_service.share(install["install_id"], "user", "user-2", caller_org_id="org-p")
    assert shared["shared_with_id"] == "user-2"
    policy_service.unshare(shared["share_id"], caller_org_id="org-p")  # should not raise


def test_unshare_publishes_an_ecosystem_changed_event():
    # Real gap found live (install-state-consistency round, 2026-09-29):
    # unshare() never published ecosystem.changed at all -- a Yours/
    # Discover/Detail screen sitting open elsewhere (or another tab) had
    # no signal that a share it could see just disappeared. Same test
    # convention as test_installs_service_lifecycle.py's own install/
    # uninstall/set_enabled event-publish tests.
    item_id, version_id = _make_item("policy-share-event")
    install = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-p",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    shared = policy_service.share(install["install_id"], "user", "user-2", caller_org_id="org-p")
    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        policy_service.unshare(shared["share_id"], caller_org_id="org-p")
    assert len(captured) == 1
    assert captured[0]["change"] == "updated"
    assert captured[0]["item_id"] == item_id


def test_recipient_own_item_summary_resolves_their_own_share_id():
    """Task 3c fix: the recipient of a share has always had "unshare" in
    their own allowed_actions (install.scope == "shared" is the
    compute_allowed_actions() trigger) but no way to look up the SHARE's
    own id -- items_service._share_id_for_recipient() resolves it now.
    Real, disclosed limitation this doesn't try to fix: the join is by
    caller_org_id (same as policy_service.unshare() itself), so this only
    ever works when the sharer and recipient are in the same org."""
    item_id, version_id = _make_item("policy-share-id")
    sharer_install = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-p",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    shared = policy_service.share(sharer_install["install_id"], "user", "user-2", caller_org_id="org-p")

    # The recipient installs their own copy at scope="shared" -- mirrors
    # what POST /ecosystem/items/{id}/install does for a "Shared with me"
    # item today (routers/ecosystem_router.py's install_item).
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-p",
        installed_by="user-2", installed_for="user-2", surfaces=["chat"],
        scope="shared", origin="shared",
    )

    recipient_view = items_service.get_item(item_id, caller_org_id="org-p", caller_user_id="user-2")
    assert recipient_view["share_id"] == shared["share_id"]
    assert "unshare" in recipient_view["allowed_actions"]

    # And it's genuinely callable with the id this exposes -- the exact
    # thing the recipient couldn't do before this fix.
    policy_service.unshare(recipient_view["share_id"], caller_org_id="org-p")


def test_non_recipient_never_sees_a_share_id():
    """A caller who can see the item's detail at all (e.g. an org admin)
    but who this item was never actually shared with must never get a
    share_id back -- share_id is only ever resolved for the real share
    recipient. (A plain same-org stranger with no such permission now
    gets a 404/None from get_item() entirely -- a stricter, separate
    guarantee added 2026-09-29, see _visible_to_caller_for_detail() --
    so this test uses an admin caller specifically to isolate the
    share_id-leak assertion from that visibility check.)"""
    item_id, version_id = _make_item("policy-share-id-none")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-p",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    admin_view = items_service.get_item(
        item_id, caller_org_id="org-p", caller_user_id="user-99",
        caller_permissions={"marketplace:admin_sources"},
    )
    assert admin_view is not None
    assert admin_view["share_id"] is None


def test_report_below_threshold_stays_open():
    item_id, _ = _make_item("policy-report-1")
    result = policy_service.report(item_id, "reporter-1", "looks suspicious")
    assert result["status"] == "open"


def test_report_at_threshold_auto_hides_all_open_reports():
    item_id, _ = _make_item("policy-report-threshold")
    policy_service.report(item_id, "reporter-1", "reason 1")
    policy_service.report(item_id, "reporter-2", "reason 2")
    policy_service.report(item_id, "reporter-3", "reason 3")  # hits _AUTO_HIDE_REPORT_THRESHOLD=3

    db = SessionLocal()
    try:
        reports = db.query(EcosystemReport).filter(EcosystemReport.item_id == item_id).all()
    finally:
        db.close()
    assert all(r.status == "auto_hidden" for r in reports)


def test_force_disable_sets_yanked_status():
    item_id, _ = _make_item("policy-force-disable")
    policy_service.force_disable(item_id, caller_org_id="org-p")
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.status == "yanked"


def test_unyank_restores_active_status():
    item_id, _ = _make_item("policy-unyank")
    policy_service.force_disable(item_id, caller_org_id="org-p")
    policy_service.unyank(item_id, caller_org_id="org-p")
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.status == "active"


def test_featured_override_set_and_delete():
    item_id, _ = _make_item("policy-featured")
    policy_service.set_featured_override("org-p", item_id, True, "admin-1")
    policy_service.delete_featured_override("org-p", item_id)  # should not raise


def test_require_promotes_provisioned_to_required():
    item_id, version_id = _make_item("policy-require")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-req",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )
    count = policy_service.require_item(item_id, "org-req")
    assert count == 1

    installs, _ = installs_service.list_installs("org-req", "user-1")
    assert installs[0]["scope"] == "required"
    assert installs[0]["origin"] == "required"


def test_unrequire_demotes_required_to_provisioned():
    item_id, version_id = _make_item("policy-unrequire")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-unreq",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
        scope="required", origin="required",
    )
    count = policy_service.unrequire_item(item_id, "org-unreq")
    assert count == 1

    installs, _ = installs_service.list_installs("org-unreq", "user-1")
    assert installs[0]["scope"] == "provisioned"


def test_admin_disable_org_default_disables_all_existing_users_immediately():
    # Item 4a (pre-M3): "applies to all users immediately" -- two already-
    # provisioned users, both disabled by one admin call, no per-user loop
    # the caller has to drive.
    item_id, version_id = _make_item("policy-org-default-disable")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-default",
        installed_by="admin", installed_for="user-1", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-default",
        installed_by="admin", installed_for="user-2", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )

    result = policy_service.admin_disable_org_default(item_id, "org-default", "admin-1")
    assert result["installs_disabled"] == 2
    assert result["excluded"] is True

    for user in ("user-1", "user-2"):
        installs, _ = installs_service.list_installs("org-default", user)
        assert installs[0]["enabled"] is False

    assert policy_service.is_org_default_excluded(item_id, "org-default") is True


def test_admin_disable_org_default_also_disables_required_rows():
    # An admin explicitly removing a default overrides the required-lock
    # that only exists to stop a normal user's own disable action.
    item_id, version_id = _make_item("policy-org-default-required")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-default-req",
        installed_by="admin", installed_for="user-1", surfaces=["chat"],
        scope="required", origin="required",
    )
    result = policy_service.admin_disable_org_default(item_id, "org-default-req", "admin-1")
    assert result["installs_disabled"] == 1
    installs, _ = installs_service.list_installs("org-default-req", "user-1")
    assert installs[0]["enabled"] is False


def test_admin_disable_org_default_is_idempotent():
    item_id, version_id = _make_item("policy-org-default-idempotent")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-default-idem",
        installed_by="admin", installed_for="user-1", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )
    policy_service.admin_disable_org_default(item_id, "org-default-idem", "admin-1")
    # Second call must not error (e.g. a duplicate-key crash on the
    # exclusion insert), must not create a second exclusion row, and
    # reports 0 newly-disabled rows since everything is already disabled.
    result = policy_service.admin_disable_org_default(item_id, "org-default-idem", "admin-1")
    assert result["installs_disabled"] == 0
    assert policy_service.is_org_default_excluded(item_id, "org-default-idem") is True

    from db.database import SessionLocal
    from db.models import EcosystemOrgExcludedDefault
    db = SessionLocal()
    try:
        count = db.query(EcosystemOrgExcludedDefault).filter(
            EcosystemOrgExcludedDefault.org_id == "org-default-idem",
            EcosystemOrgExcludedDefault.item_id == item_id,
        ).count()
    finally:
        db.close()
    assert count == 1


def test_admin_restore_org_default_clears_exclusion_but_not_enabled_flag():
    item_id, version_id = _make_item("policy-org-default-restore")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-default-restore",
        installed_by="admin", installed_for="user-1", surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )
    policy_service.admin_disable_org_default(item_id, "org-default-restore", "admin-1")
    assert policy_service.is_org_default_excluded(item_id, "org-default-restore") is True

    result = policy_service.admin_restore_org_default(item_id, "org-default-restore")
    assert result["excluded"] is False
    assert result["was_excluded"] is True
    assert policy_service.is_org_default_excluded(item_id, "org-default-restore") is False

    # Disclosed limitation: restore does not retroactively re-enable.
    installs, _ = installs_service.list_installs("org-default-restore", "user-1")
    assert installs[0]["enabled"] is False


def test_is_org_default_excluded_false_when_never_excluded():
    item_id, _ = _make_item("policy-org-default-never")
    assert policy_service.is_org_default_excluded(item_id, "org-never-excluded") is False


# ── Tiered license policy (task C, ECOSYSTEM_PLAN.md §11.2), Tier 2 ────────

def test_get_policy_defaults_include_allowed_licenses_shared():
    policy = policy_service.get_policy("org-never-configured-license-policy")
    assert policy["allowed_licenses_shared"] == ["MIT", "Apache-2.0"]


def test_set_policy_updates_allowed_licenses_shared_without_resetting_other_fields():
    org_id = "policy-license-partial-update"
    policy_service.set_policy(org_id, who_can_add="admins_only", updated_by="admin-1")
    updated = policy_service.set_policy(org_id, allowed_licenses_shared=["MIT", "Apache-2.0", "GPL-3.0-only"], updated_by="admin-1")
    assert updated["allowed_licenses_shared"] == ["MIT", "Apache-2.0", "GPL-3.0-only"]
    assert updated["who_can_add"] == "admins_only"  # untouched by the partial update above


def test_set_policy_can_clear_allowed_licenses_shared_to_empty():
    # BUG-09 fix: _policy_to_dict() used to return `row.allowed_licenses_
    # shared or ["MIT", "Apache-2.0"]` -- a falsy check that silently
    # resurrected the default every time this was read back, even though
    # set_policy() itself always persisted the real (possibly empty) value
    # correctly. An admin clearing this field to lock sharing down to
    # ONLY the always-allowed MIT/Apache-2.0 tier had no way to do so.
    org_id = "policy-license-clear-to-empty"
    policy_service.set_policy(org_id, allowed_licenses_shared=["MIT", "Apache-2.0", "GPL-3.0-only"], updated_by="admin-1")
    cleared = policy_service.set_policy(org_id, allowed_licenses_shared=[], updated_by="admin-1")
    assert cleared["allowed_licenses_shared"] == []
    # And a fresh read (not just the mutation's own return value) agrees.
    assert policy_service.get_policy(org_id)["allowed_licenses_shared"] == []


def test_share_blocks_a_disallowed_license_by_default():
    from services.ecosystem.errors import LicenseNotAllowedByOrgPolicyError

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/policy-gpl", item_type="skill", category="general",
        display_name="GPL Item", description="d", org_id="org-share-gpl",
        legacy_source="skills_pg", legacy_ref="policy-share-gpl", license="GPL-3.0-only",
    )
    with _mock_ethics_pass():
        version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="content", manifest={})
    install = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-share-gpl",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    import pytest as _pytest

    with _pytest.raises(LicenseNotAllowedByOrgPolicyError):
        policy_service.share(install["install_id"], "user", "user-2", caller_org_id="org-share-gpl")

    from db.database import SessionLocal as _SessionLocal
    from db.models import EcosystemShare as _EcosystemShare
    db = _SessionLocal()
    try:
        count = db.query(_EcosystemShare).filter(_EcosystemShare.install_id == install["install_id"]).count()
    finally:
        db.close()
    assert count == 0  # never created


def test_share_allowed_once_org_policy_permits_the_license():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/policy-gpl-permitted", item_type="skill", category="general",
        display_name="GPL Item Permitted", description="d", org_id="org-share-gpl-ok",
        legacy_source="skills_pg", legacy_ref="policy-share-gpl-ok", license="GPL-3.0-only",
    )
    with _mock_ethics_pass():
        version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="content", manifest={})
    install = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-share-gpl-ok",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    policy_service.set_policy("org-share-gpl-ok", allowed_licenses_shared=["MIT", "Apache-2.0", "GPL-3.0-only"], updated_by="admin-1")
    shared = policy_service.share(install["install_id"], "user", "user-2", caller_org_id="org-share-gpl-ok")
    assert shared["shared_with_id"] == "user-2"
