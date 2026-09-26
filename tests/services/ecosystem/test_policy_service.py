# SPDX-License-Identifier: MIT
# ============================================================
# Policy service tests (task B-19). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemReport
from services.ecosystem import installs_service, policy_service
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
    shared = policy_service.share(install["install_id"], "user", "user-2")
    assert shared["shared_with_id"] == "user-2"
    policy_service.unshare(shared["share_id"])  # should not raise


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
    policy_service.force_disable(item_id)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.status == "yanked"


def test_unyank_restores_active_status():
    item_id, _ = _make_item("policy-unyank")
    policy_service.force_disable(item_id)
    policy_service.unyank(item_id)
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
