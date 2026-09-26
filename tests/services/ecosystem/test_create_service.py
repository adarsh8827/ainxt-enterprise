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


# ── Item I (pre-M3): github_repo / well_known import adapters ───────────
# The adapters' own HTTP-layer behavior (fixtures, no live network) is
# covered by tests/services/ecosystem/import_adapters/ -- these tests
# mock the adapter's top-level import_from_*() function directly and
# verify create_via_import() wires the result into a real item+version+
# gate-run, exactly like create_via_write/upload's own tests do.

def test_create_via_import_github_repo_creates_item_and_enqueues_gate():
    fake_result = {
        "manifest": {"name": "Hello Skill", "description": "d", "instructions": "..."},
        "files": {}, "license": "MIT", "display_name": "Hello Skill", "description": "d",
        "resolved_sha": "a" * 40, "source_url": "https://github.com/acme/hello",
    }
    with _mock_ethics_pass(), patch(
        "services.ecosystem.import_adapters.github_repo.import_from_github", return_value=fake_result
    ):
        result = create_service.create_via_import(
            org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/gh-import-test",
            category="general", kind="github_repo", ref="acme/hello", surfaces=["chat"],
        )
    assert result["status"] == "verifying"

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == result["version_id"]).one()
        item = db.query(EcosystemItem).filter(EcosystemItem.id == result["item_id"]).one()
    finally:
        db.close()
    assert version.license == "MIT"
    assert version.attribution == "github_repo:acme/hello@" + "a" * 40
    assert item.display_name == "Hello Skill"

    # Auto-installed for the importing user, same as write/upload.
    db = SessionLocal()
    try:
        install = (
            db.query(EcosystemInstall)
            .filter(EcosystemInstall.item_id == result["item_id"], EcosystemInstall.installed_for == "user-i")
            .first()
        )
    finally:
        db.close()
    assert install is not None


def test_create_via_import_well_known_creates_item_and_enqueues_gate():
    fake_result = {
        "manifest": {"name": "Weather Skill", "description": "d", "instructions": "..."},
        "files": {}, "license": "Apache-2.0", "display_name": "Weather Skill", "description": "d",
        "resolved_sha": "b" * 64, "source_url": "https://example.com",
    }
    with _mock_ethics_pass(), patch(
        "services.ecosystem.import_adapters.well_known.import_from_well_known", return_value=fake_result
    ):
        result = create_service.create_via_import(
            org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/wk-import-test",
            category="general", kind="well_known", ref="example.com/weather", surfaces=["chat"],
        )
    assert result["status"] == "verifying"

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == result["version_id"]).one()
    finally:
        db.close()
    assert version.license == "Apache-2.0"
    assert version.attribution == "well_known:example.com/weather#" + "b" * 64


def test_create_via_import_github_repo_propagates_license_not_allowed():
    from services.ecosystem.errors import LicenseNotAllowedError as _LNA

    with patch(
        "services.ecosystem.import_adapters.github_repo.import_from_github",
        side_effect=_LNA("repo license not allowed", stage="import_precheck", declared_license="GPL-3.0"),
    ):
        with pytest.raises(LicenseNotAllowedError):
            create_service.create_via_import(
                org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/gh-bad-license",
                category="general", kind="github_repo", ref="acme/gpl-repo",
            )


def test_create_via_import_reuses_the_same_source_row_across_two_imports_from_the_same_repo():
    from db.models import EcosystemSource

    fake_result_1 = {
        "manifest": {"name": "Skill One", "description": "d", "instructions": "..."},
        "files": {}, "license": "MIT", "display_name": "Skill One", "description": "d",
        "resolved_sha": "c" * 40, "source_url": "https://github.com/acme/shared-repo",
    }
    fake_result_2 = {**fake_result_1, "display_name": "Skill Two", "manifest": {**fake_result_1["manifest"], "name": "Skill Two"}}

    with _mock_ethics_pass(), patch(
        "services.ecosystem.import_adapters.github_repo.import_from_github",
        side_effect=[fake_result_1, fake_result_2],
    ):
        r1 = create_service.create_via_import(
            org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/shared-repo-1",
            category="general", kind="github_repo", ref="acme/shared-repo",
        )
        r2 = create_service.create_via_import(
            org_id="org-i", created_by="user-i", item_type="skill", namespace="acme/shared-repo-2",
            category="general", kind="github_repo", ref="acme/shared-repo",
        )

    db = SessionLocal()
    try:
        item1 = db.query(EcosystemItem).filter(EcosystemItem.id == r1["item_id"]).one()
        item2 = db.query(EcosystemItem).filter(EcosystemItem.id == r2["item_id"]).one()
        source_count = db.query(EcosystemSource).filter(
            EcosystemSource.kind == "github_repo", EcosystemSource.url == "https://github.com/acme/shared-repo",
        ).count()
    finally:
        db.close()
    assert item1.source_id == item2.source_id
    assert source_count == 1
