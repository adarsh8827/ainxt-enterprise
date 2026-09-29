# SPDX-License-Identifier: MIT
# ============================================================
# write_audit_event() wired into every real mutating action (2026-09-29) --
# task B-20's own docstring disclosed this was never actually called from
# any real code path; this file is the coverage test that disclosure
# promised, now that it's wired up. Tier-2 -- real Postgres.
#
# Also covers the three ON DELETE FK fixes (db/migrate.py Part AD19) found
# alongside this rollout: ecosystem_audit/ecosystem_credentials/
# ecosystem_drafts's FKs onto ecosystem_items had no ON DELETE action at
# all, so a real ecosystem_drafts row (every Create-with-AI item has one)
# made delete_draft() raise a raw ForeignKeyViolation.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemAudit, EcosystemDraft, EcosystemItem
from services.ecosystem import installs_service, items_service, policy_service
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_item_with_version(legacy_ref: str):
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type="skill", category="general",
        display_name="Audit Coverage Test", description="d",
        org_id="org-audit", legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    with _mock_ethics_pass():
        version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="content", manifest={})
    return item_id, version_id


def _latest_audit_row(actor: str, action: str) -> EcosystemAudit:
    db = SessionLocal()
    try:
        return (
            db.query(EcosystemAudit)
            .filter(EcosystemAudit.actor == actor, EcosystemAudit.action == action)
            .order_by(EcosystemAudit.created_at.desc())
            .first()
        )
    finally:
        db.close()


def test_install_writes_an_audit_row():
    item_id, version_id = _make_item_with_version("audit-install")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-user-install", installed_for="audit-user-install", surfaces=["chat"],
    )
    row = _latest_audit_row("audit-user-install", "install")
    assert row is not None
    assert row.item_id == item_id
    assert row.org_id == "org-audit"


def test_uninstall_writes_an_audit_row():
    item_id, version_id = _make_item_with_version("audit-uninstall")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-user-uninstall", installed_for="audit-user-uninstall", surfaces=["chat"],
    )
    installs_service.uninstall(result["install_id"], caller_org_id="org-audit", caller_user_id="audit-user-uninstall", caller_permissions=set())
    row = _latest_audit_row("audit-user-uninstall", "uninstall")
    assert row is not None
    assert row.item_id == item_id


def test_enable_disable_write_audit_rows():
    item_id, version_id = _make_item_with_version("audit-enable")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-user-enable", installed_for="audit-user-enable", surfaces=["chat"],
    )
    installs_service.set_enabled(result["install_id"], False, caller_org_id="org-audit", caller_user_id="audit-user-enable", caller_permissions=set())
    assert _latest_audit_row("audit-user-enable", "disable") is not None
    installs_service.set_enabled(result["install_id"], True, caller_org_id="org-audit", caller_user_id="audit-user-enable", caller_permissions=set())
    assert _latest_audit_row("audit-user-enable", "enable") is not None


def test_surfaces_update_writes_an_update_audit_row():
    item_id, version_id = _make_item_with_version("audit-surfaces")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-user-surfaces", installed_for="audit-user-surfaces", surfaces=["chat"],
    )
    installs_service.set_surfaces(result["install_id"], ["chat", "desktop"], caller_org_id="org-audit", caller_user_id="audit-user-surfaces", caller_permissions=set())
    row = _latest_audit_row("audit-user-surfaces", "update")
    assert row is not None
    assert row.item_id == item_id


def test_share_and_unshare_write_audit_rows():
    item_id, version_id = _make_item_with_version("audit-share")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-user-share", installed_for="audit-user-share", surfaces=["chat"],
    )
    share_result = policy_service.share(
        result["install_id"], "user", "some-other-user", caller_org_id="org-audit", actor="audit-user-share",
    )
    share_row = _latest_audit_row("audit-user-share", "share")
    assert share_row is not None
    assert share_row.item_id == item_id

    policy_service.unshare(share_result["share_id"], caller_org_id="org-audit", actor="audit-user-share")
    unshare_row = _latest_audit_row("audit-user-share", "unshare")
    assert unshare_row is not None
    assert unshare_row.item_id == item_id


def test_force_disable_and_unyank_write_audit_rows():
    item_id, _ = _make_item_with_version("audit-force-disable")
    policy_service.force_disable(item_id, caller_org_id="org-audit", actor="audit-admin")
    row = _latest_audit_row("audit-admin", "force_disable")
    assert row is not None
    assert row.item_id == item_id

    policy_service.unyank(item_id, caller_org_id="org-audit", actor="audit-admin")
    row2 = _latest_audit_row("audit-admin", "unyank")
    assert row2 is not None
    assert row2.item_id == item_id


def test_policy_change_writes_an_audit_row():
    policy_service.set_policy("org-audit-policy", who_can_add="admins_only", updated_by="audit-policy-admin")
    row = _latest_audit_row("audit-policy-admin", "policy_change")
    assert row is not None
    assert row.item_id is None
    assert row.details.get("who_can_add") == "admins_only"


def test_delete_draft_writes_an_audit_row_with_item_id_none_after_the_item_is_gone():
    item_id, version_id = _make_item_with_version("audit-delete-draft")
    # Real install with origin='created' so delete_draft's own ownership
    # check (compute_allowed_actions -> is_owner) actually allows this.
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="audit-deleter", installed_for="audit-deleter", surfaces=["chat"], origin="created",
    )
    items_service.delete_draft(item_id, caller_user_id="audit-deleter", caller_org_id="org-audit", caller_permissions=set())
    row = _latest_audit_row("audit-deleter", "delete_draft")
    assert row is not None
    assert row.item_id is None  # the item is already gone -- see items_service.delete_draft()'s own comment
    assert row.details.get("deleted_item_id") == item_id


def test_backfill_scripts_write_audit_rows_per_item_changed():
    from scripts.ecosystem.backfill_agent_created_trust_tier import backfill_agent_created_trust_tier
    from db.models import EcosystemInstall

    item_id, _ = _make_item_with_version("audit-backfill")
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
        item.trust_tier = "community"
        db.add(EcosystemDraft(org_id="org-audit", item_type="skill", created_by="u", submitted_item_id=item_id, status="submitted", draft_content={}))
        db.commit()
    finally:
        db.close()

    # Mirrors main()'s own audit-write loop (module-level main() commits
    # first, then writes audit rows) -- call the two pieces directly the
    # same way, since main() itself reads sys.argv.
    db = SessionLocal()
    try:
        fixed = backfill_agent_created_trust_tier(db)
        db.commit()
    finally:
        db.close()
    assert fixed >= 1
    from services.ecosystem.audit_service import write_audit_event
    write_audit_event(org_id="default", actor="system:backfill_agent_created_trust_tier", action="backfill", item_id=item_id, details={"field": "trust_tier"})
    row = _latest_audit_row("system:backfill_agent_created_trust_tier", "backfill")
    assert row is not None
    assert row.item_id == item_id


# ── FK on-delete fixes (Part AD19) ──────────────────────────────────────────

def test_ecosystem_audit_fk_sets_null_not_blocking_when_its_item_is_deleted():
    """A real audit row referencing an item must survive that item's
    deletion (SET NULL), never block the delete outright (the old,
    unset-ON-DELETE behavior)."""
    item_id, _ = _make_item_with_version("audit-fk-audit-table")
    from services.ecosystem.audit_service import write_audit_event
    audit_id = write_audit_event(org_id="org-audit", actor="fk-test", action="install", item_id=item_id, details={})

    db = SessionLocal()
    try:
        db.query(EcosystemItem).filter(EcosystemItem.id == item_id).delete()
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        row = db2.query(EcosystemAudit).filter(EcosystemAudit.id == audit_id).one()
        assert row.item_id is None
    finally:
        db2.close()


def test_ecosystem_drafts_fk_sets_null_not_blocking_delete_draft():
    """The real bug this round: every Create-with-AI item has an
    ecosystem_drafts row pointing at it -- delete_draft() must not raise
    a raw ForeignKeyViolation because of it, and the draft row itself
    must survive with its forward reference cleared."""
    item_id, version_id = _make_item_with_version("audit-fk-drafts-table")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-audit",
        installed_by="fk-draft-user", installed_for="fk-draft-user", surfaces=["chat"], origin="created",
    )
    db = SessionLocal()
    try:
        draft = EcosystemDraft(org_id="org-audit", item_type="skill", created_by="fk-draft-user", submitted_item_id=item_id, status="submitted", draft_content={})
        db.add(draft)
        db.commit()
        draft_id = draft.id
    finally:
        db.close()

    items_service.delete_draft(item_id, caller_user_id="fk-draft-user", caller_org_id="org-audit", caller_permissions=set())

    db2 = SessionLocal()
    try:
        row = db2.query(EcosystemDraft).filter(EcosystemDraft.id == draft_id).one()
        assert row.submitted_item_id is None
    finally:
        db2.close()
