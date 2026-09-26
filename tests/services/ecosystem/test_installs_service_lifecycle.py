# SPDX-License-Identifier: MIT
# ============================================================
# Install lifecycle tests (task B-10). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

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
