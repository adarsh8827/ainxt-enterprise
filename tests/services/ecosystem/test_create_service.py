# SPDX-License-Identifier: MIT
# ============================================================
# Creation service tests (task B-6). Tier-2 — real Postgres. Ethics stage
# mocked for determinism, same as test_gate_service_orchestrator.py.
# ============================================================

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion
from services.ecosystem import create_service
from services.ecosystem.errors import LicenseNotAllowedError, PolicyForbiddenError


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _zip_with_skill_md(license="MIT", name="Test Skill", description="does a thing", extra_files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", f"---\nname: {name}\nlicense: {license}\ndescription: {description}\n---\nBody text.")
        for rel, content in (extra_files or {}).items():
            zf.writestr(rel, content)
    return buf.getvalue()


def test_create_via_write_creates_item_and_version_and_gate_run():
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-w", created_by="user-w", item_type="skill", namespace="acme/write-test",
            display_name="Write Test", description="d", category="general", tags=["x"],
            license="MIT", content={"instructions": "do the thing", "files": []}, surfaces=["chat"],
        )
    assert result["status"] == "verifying"
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == result["item_id"]).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == result["version_id"]).one()
    finally:
        db.close()
    assert item.namespace == "acme/write-test"
    assert item.license == "MIT"
    assert version.item_id == item.id


def test_create_via_write_rejects_disallowed_license_before_anything_else():
    with pytest.raises(LicenseNotAllowedError):
        create_service.create_via_write(
            org_id="org-w", created_by="user-w", item_type="skill", namespace="acme/write-bad-license",
            display_name="Bad", description="d", category="general", tags=[],
            license="GPL-3.0-only", content={"instructions": "x", "files": []}, surfaces=[],
        )
    db = SessionLocal()
    try:
        count = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/write-bad-license").count()
    finally:
        db.close()
    assert count == 0  # rejected before any item row was created


def test_create_via_write_auto_installs_creator_on_pass():
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-ai", created_by="user-ai", item_type="skill", namespace="acme/auto-install-test",
            display_name="Auto Install Test", description="d", category="general", tags=[],
            license="MIT", content={"instructions": "safe content", "files": []}, surfaces=["chat"],
        )
    db = SessionLocal()
    try:
        installs = db.query(EcosystemInstall).filter(EcosystemInstall.item_id == result["item_id"]).all()
    finally:
        db.close()
    assert len(installs) == 1
    assert installs[0].installed_by == "user-ai"
    assert installs[0].origin == "created"
    assert installs[0].scope == "private"


def test_create_via_write_provision_scope_requires_permission():
    with pytest.raises(PolicyForbiddenError):
        create_service.create_via_write(
            org_id="org-w", created_by="user-w", item_type="skill", namespace="acme/no-perm",
            display_name="No Perm", description="d", category="general", tags=[],
            license="MIT", content={"instructions": "x", "files": []}, surfaces=[],
            provision_scope="required", caller_permissions=set(),
        )


def test_create_via_write_provision_scope_org_default_on_with_permission():
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id="org-prov", created_by="admin-1", item_type="skill", namespace="acme/org-default-on",
            display_name="Org Default", description="d", category="general", tags=[],
            license="MIT", content={"instructions": "safe", "files": []}, surfaces=["chat"],
            provision_scope="org_default_on", caller_permissions={"marketplace:provision"},
        )
    db = SessionLocal()
    try:
        installs = db.query(EcosystemInstall).filter(EcosystemInstall.item_id == result["item_id"]).all()
    finally:
        db.close()
    assert len(installs) == 1
    assert installs[0].scope == "provisioned"
    assert installs[0].origin == "provisioned"


def test_create_via_upload_parses_skill_md_and_creates_item():
    zip_bytes = _zip_with_skill_md()
    with _mock_ethics_pass():
        result = create_service.create_via_upload(
            org_id="org-u", created_by="user-u", item_type="skill", namespace="acme/upload-test",
            category="general", zip_bytes=zip_bytes, surfaces=["chat"],
        )
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == result["item_id"]).one()
    finally:
        db.close()
    assert item.display_name == "Test Skill"
    assert item.license == "MIT"


def test_create_via_upload_missing_license_frontmatter_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: No License\ndescription: d\n---\nBody.")
    with pytest.raises(LicenseNotAllowedError):
        create_service.create_via_upload(
            org_id="org-u", created_by="user-u", item_type="skill", namespace="acme/upload-no-license",
            category="general", zip_bytes=buf.getvalue(), surfaces=[],
        )


def test_create_via_upload_rejects_zip_bomb_declared_size():
    # A real, highly-compressible zip bomb: a tiny compressed archive whose
    # declared inflated size exceeds the 8MB cap — checked against the
    # DECLARED size (zi.file_size) before anything is decompressed, so this
    # must be rejected fast without ever actually inflating 9MB in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "---\nname: X\nlicense: MIT\ndescription: d\n---\nBody.")
        zf.writestr("scripts/bomb.py", "0" * (9 * 1024 * 1024))
    with pytest.raises(create_service.EcosystemError):
        create_service.create_via_upload(
            org_id="org-u", created_by="user-u", item_type="skill", namespace="acme/zipbomb",
            category="general", zip_bytes=buf.getvalue(), surfaces=[],
        )


def test_create_via_upload_path_traversal_entries_are_skipped_not_fatal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: X\nlicense: MIT\ndescription: d\n---\nBody.")
        zf.writestr("../../etc/passwd", "malicious")
    with _mock_ethics_pass():
        result = create_service.create_via_upload(
            org_id="org-u", created_by="user-u", item_type="skill", namespace="acme/traversal-test",
            category="general", zip_bytes=buf.getvalue(), surfaces=[],
        )
    assert result["status"] == "verifying"  # the traversal entry was silently skipped, not fatal


def test_create_via_import_rejects_disallowed_license_before_fetch():
    with pytest.raises(LicenseNotAllowedError):
        create_service.create_via_import(
            org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/import-test",
            category="general", kind="url", ref="https://example.com/skill.zip", license="GPL-3.0-only",
        )
