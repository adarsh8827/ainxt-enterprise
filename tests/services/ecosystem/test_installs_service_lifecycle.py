# SPDX-License-Identifier: MIT
# ============================================================
# Install lifecycle tests (task B-10). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from services.ecosystem import installs_service
from services.ecosystem.errors import NotFoundError
from services.ecosystem.installs_service import ConflictError
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_item_with_versions(legacy_ref: str, n_versions: int = 1):
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/lifecycle", item_type="skill", category="general",
        display_name="Lifecycle Test", description="d",
        org_id="org-l", legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    version_ids = []
    with _mock_ethics_pass():
        for i in range(n_versions):
            vid, _ = create_or_refresh_legacy_version(item_id=item_id, content_text=f"version {i} content", manifest={})
            version_ids.append(vid)
    return item_id, version_ids


def test_install_creates_row():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-install")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    assert result["item_id"] == item_id
    assert result["enabled"] is True


def test_install_duplicate_raises_conflict_not_silent_duplicate():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-dup")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    with pytest.raises(ConflictError):
        installs_service.install(
            item_id=item_id, version_id=version_id, org_id="org-l",
            installed_by="user-1", installed_for="user-1", surfaces=["chat"],
        )


def test_uninstall_removes_row_but_not_item():
    from db.database import SessionLocal
    from db.models import EcosystemItem

    item_id, (version_id,) = _make_item_with_versions("lifecycle-uninstall")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    installs_service.uninstall(result["install_id"])

    with pytest.raises(NotFoundError):
        installs_service.get_install(result["install_id"])

    db = SessionLocal()
    try:
        assert db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first() is not None
    finally:
        db.close()


def test_set_enabled_toggles():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-enable")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    disabled = installs_service.set_enabled(result["install_id"], False)
    assert disabled["enabled"] is False
    enabled = installs_service.set_enabled(result["install_id"], True)
    assert enabled["enabled"] is True


def test_required_install_cannot_be_disabled():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-required")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"], scope="required",
    )
    with pytest.raises(Exception):
        installs_service.set_enabled(result["install_id"], False)


def test_required_install_cannot_be_uninstalled():
    # Item 4b (pre-M3): uninstall() previously had no required-check at
    # all -- a required item could be deleted outright even though
    # set_enabled() already refused to merely disable it.
    item_id, (version_id,) = _make_item_with_versions("lifecycle-required-uninstall")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"], scope="required",
    )
    with pytest.raises(Exception):
        installs_service.uninstall(result["install_id"])
    # Still there -- the raise above must not have partially deleted it.
    assert installs_service.get_install(result["install_id"]) is not None


def test_concurrent_first_installs_create_no_duplicates():
    # Item 4c (pre-M3): "concurrent first requests create no duplicates."
    # This exercises the exact mechanism a future ensure_provisioned()
    # (B-12) would rely on -- the real UNIQUE NULLS NOT DISTINCT DB
    # constraint (task B-1) plus install()'s ConflictError translation --
    # by firing install() for the SAME (item_id, org_id, installed_for)
    # from N real threads at once and asserting exactly one wins.
    item_id, (version_id,) = _make_item_with_versions("lifecycle-concurrent")

    def _attempt():
        try:
            installs_service.install(
                item_id=item_id, version_id=version_id, org_id="org-concurrent",
                installed_by="racer", installed_for="racer", surfaces=["chat"],
            )
            return "ok"
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: _attempt(), range(10)))

    assert results.count("ok") == 1, f"expected exactly one winner, got: {results}"
    assert results.count("conflict") == 9

    installs, _ = installs_service.list_installs("org-concurrent", "racer")
    assert len(installs) == 1


def test_cleanup_installs_for_inactive_users_dry_run_then_real():
    # Item 4d (pre-M3): row-growth cleanup for a deactivated user's
    # lazily-provisioned installs.
    import uuid

    from db.database import SessionLocal
    from db.models import User

    item_id, (version_id,) = _make_item_with_versions("lifecycle-cleanup")

    user_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(User(
            id=user_id, email=f"{user_id}@example.test", name="Deactivated Test User",
            is_active=False,
        ))
        db.commit()
    finally:
        db.close()

    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-cleanup",
        installed_by="admin", installed_for=user_id, surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )

    dry = installs_service.cleanup_installs_for_inactive_users(org_id="org-cleanup", dry_run=True)
    assert dry["candidates"] == 1
    assert dry["deleted"] == 0
    # dry_run must not have actually deleted anything.
    installs, has_any = installs_service.list_installs("org-cleanup", user_id)
    assert has_any is True

    real = installs_service.cleanup_installs_for_inactive_users(org_id="org-cleanup", dry_run=False)
    assert real["candidates"] == 1
    assert real["deleted"] == 1

    installs, has_any = installs_service.list_installs("org-cleanup", user_id)
    assert has_any is False


def test_cleanup_installs_for_inactive_users_leaves_active_users_alone():
    import uuid

    from db.database import SessionLocal
    from db.models import User

    item_id, (version_id,) = _make_item_with_versions("lifecycle-cleanup-active")

    user_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(User(id=user_id, email=f"{user_id}@example.test", name="Active User", is_active=True))
        db.commit()
    finally:
        db.close()

    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-cleanup-active",
        installed_by="admin", installed_for=user_id, surfaces=["chat"],
        scope="provisioned", origin="provisioned",
    )

    result = installs_service.cleanup_installs_for_inactive_users(org_id="org-cleanup-active", dry_run=False)
    assert result["candidates"] == 0

    _, has_any = installs_service.list_installs("org-cleanup-active", user_id)
    assert has_any is True


def test_install_publishes_an_installed_event():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-event-install")
    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        installs_service.install(
            item_id=item_id, version_id=version_id, org_id="org-l",
            installed_by="user-1", installed_for="user-1", surfaces=["chat"],
        )
    assert len(captured) == 1
    assert captured[0]["change"] == "installed"
    assert captured[0]["item_id"] == item_id
    assert captured[0]["scope"] == "private"


def test_uninstall_publishes_an_uninstalled_event():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-event-uninstall")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        installs_service.uninstall(result["install_id"])
    assert len(captured) == 1
    assert captured[0]["change"] == "uninstalled"


def test_set_enabled_publishes_enabled_and_disabled_events():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-event-enable")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        installs_service.set_enabled(result["install_id"], False)
        installs_service.set_enabled(result["install_id"], True)
    assert [c["change"] for c in captured] == ["disabled", "enabled"]


def test_update_to_version_publishes_an_updated_event():
    item_id, (v1, v2) = _make_item_with_versions("lifecycle-event-update", n_versions=2)
    result = installs_service.install(
        item_id=item_id, version_id=v1, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    captured = []
    with patch("services.ecosystem.events_service.publish_ecosystem_changed", side_effect=lambda *a, **kw: captured.append(kw)):
        installs_service.update_to_version(result["install_id"], v2)
    assert len(captured) == 1
    assert captured[0]["change"] == "updated"
    assert captured[0]["version"] == "legacy-2"  # create_or_refresh_legacy_version's own numbering for the 2nd version


def test_update_to_version_moves_pointer():
    item_id, (v1, v2) = _make_item_with_versions("lifecycle-update", n_versions=2)
    result = installs_service.install(
        item_id=item_id, version_id=v1, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    updated = installs_service.update_to_version(result["install_id"], v2)
    assert updated["version_id"] == v2


def test_rollback_to_earlier_version():
    item_id, (v1, v2) = _make_item_with_versions("lifecycle-rollback", n_versions=2)
    result = installs_service.install(
        item_id=item_id, version_id=v2, org_id="org-l",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    rolled_back = installs_service.rollback(result["install_id"], v1)
    assert rolled_back["version_id"] == v1


def test_list_installs_has_any_true_when_present():
    item_id, (version_id,) = _make_item_with_versions("lifecycle-list")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-list-1",
        installed_by="user-1", installed_for="user-1", surfaces=["chat"],
    )
    installs, has_any = installs_service.list_installs("org-list-1", "user-1")
    assert has_any is True
    assert len(installs) >= 1


def test_list_installs_has_any_false_when_empty():
    installs, has_any = installs_service.list_installs("org-empty-xyz", "user-nobody")
    assert has_any is False
    assert installs == []
