# SPDX-License-Identifier: MIT
# ============================================================
# Stage 4 (Plugins) backend tests -- docs/ecosystem/PLUGINS_PHASE_PLAN.md.
# Covers: plugin_manifest.validate_composition() (missing namespace,
# duplicate, license conflict), the plugin-compose router endpoint,
# install fan-out, the managed-child uninstall refusal (matches the
# existing scope="required" shape), the parent-uninstall cascade
# (exclusive child removed, shared child ownership transferred), and the
# new-version parts diff (removed part freed, added part fanned out).
# ============================================================

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion
from routers.ecosystem_router import router as ecosystem_router
from services.ecosystem import installs_service
from services.ecosystem.errors import EcosystemError
from services.ecosystem.plugin_manifest import CompositionError, validate_composition

ORG_A = "plugin-test-org-a"


def _create_item(namespace: str, item_type: str, *, license: str = "MIT", manifest: dict | None = None) -> str:
    db = SessionLocal()
    try:
        from db.models import EcosystemSource

        source = db.query(EcosystemSource).filter(EcosystemSource.kind == "local").first()
        if not source:
            source = EcosystemSource(id=str(uuid.uuid4()), kind="local", org_id=None, created_by="test-fixture")
            db.add(source)
            db.commit()

        item = EcosystemItem(
            id=str(uuid.uuid4()), namespace=namespace, item_type=item_type, category="productivity",
            display_name=namespace, description="d", source_id=source.id, org_id=ORG_A,
            license=license, status="active", scope="org_private",
        )
        db.add(item)
        db.flush()
        version = EcosystemItemVersion(
            id=str(uuid.uuid4()), item_id=item.id, version="1.0.0", content_hash=uuid.uuid4().hex,
            object_key="test/key", license=license, attribution=license, manifest=manifest or {"name": namespace, "description": "d"},
            gate_verdict="pass",
        )
        db.add(version)
        db.commit()
        return item.id
    finally:
        db.close()


def _make_plugin_version(item_id: str, parts: dict, *, version_str: str | None = None) -> str:
    db = SessionLocal()
    try:
        version = EcosystemItemVersion(
            id=str(uuid.uuid4()), item_id=item_id, version=version_str or f"1.0.0-{uuid.uuid4().hex[:8]}",
            content_hash=uuid.uuid4().hex,
            object_key="test/key", license="MIT", attribution="MIT",
            manifest={"name": "plugin", "description": "d", "parts": parts}, gate_verdict="pass",
        )
        db.add(version)
        db.commit()
        return version.id
    finally:
        db.close()


def _create_plugin_item(parts: dict) -> tuple[str, str]:
    """Returns (item_id, version_id) for a new plugin item whose only
    version already has the given parts -- bypasses the gate/create_service
    entirely (matches _create_connector_item()'s own established pattern
    in test_connectors_phase_stage2.py: direct DB rows for a known-good
    fixture, not a full create-path round trip)."""
    item_id = _create_item(f"plugin-test/plugin-{uuid.uuid4().hex[:8]}", "plugin")
    db = SessionLocal()
    try:
        # Replace the default no-parts version with a real one.
        db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).delete()
        db.commit()
    finally:
        db.close()
    version_id = _make_plugin_version(item_id, parts)
    return item_id, version_id


# ── plugin_manifest.validate_composition() ───────────────────────────────

def test_validate_composition_rejects_a_missing_namespace():
    with pytest.raises(CompositionError) as exc_info:
        validate_composition({"skills": ["plugin-test/does-not-exist"]}, org_id=ORG_A)
    assert exc_info.value.code == "PLUGIN_PART_NOT_FOUND"


def test_validate_composition_rejects_a_namespace_duplicated_across_kinds():
    ns = _create_item(f"plugin-test/skill-{uuid.uuid4().hex[:8]}", "skill")
    real_ns = SessionLocal()
    try:
        namespace = real_ns.query(EcosystemItem).filter(EcosystemItem.id == ns).first().namespace
    finally:
        real_ns.close()
    with pytest.raises(CompositionError) as exc_info:
        validate_composition({"skills": [namespace], "commands": [namespace]}, org_id=ORG_A)
    assert exc_info.value.code == "PLUGIN_DUPLICATE_NAMESPACE"


def test_validate_composition_rejects_an_unknown_part_kind():
    with pytest.raises(CompositionError) as exc_info:
        validate_composition({"widgets": ["x"]}, org_id=ORG_A)
    assert exc_info.value.code == "PLUGIN_UNKNOWN_PART_KIND"


def test_validate_composition_rejects_a_disallowed_license():
    item_id = _create_item(f"plugin-test/gpl-skill-{uuid.uuid4().hex[:8]}", "skill", license="GPL-3.0")
    db = SessionLocal()
    try:
        namespace = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first().namespace
    finally:
        db.close()
    with pytest.raises(CompositionError) as exc_info:
        validate_composition({"skills": [namespace]}, org_id=ORG_A)
    assert exc_info.value.code == "PLUGIN_LICENSE_NOT_ALLOWED"


def test_validate_composition_accepts_shape_only_for_commands_agents_hooks():
    # Real, disclosed scope boundary (CONTRACTS.md §20): no backing
    # EcosystemItem item_type exists for these three kinds yet.
    validate_composition({"commands": ["anything/goes-here"], "agents": ["also/fine"], "hooks": ["fine/too"]}, org_id=ORG_A)


def test_validate_composition_accepts_a_real_valid_composition():
    skill_id = _create_item(f"plugin-test/valid-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        namespace = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    validate_composition({"skills": [namespace]}, org_id=ORG_A)  # must not raise


# ── plugin-compose router endpoint ────────────────────────────────────────

def _client(org_id: str, user_id: str = "u1", role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": role}
    return TestClient(app)


def test_plugin_compose_rejects_a_missing_namespace_with_the_documented_shape():
    item_id, _ = _create_plugin_item({})
    client = _client(ORG_A, user_id="owner")
    resp = client.post(
        f"/ainxt/v1/api/ecosystem/items/{item_id}/plugin-compose",
        json={"parts": {"skills": ["plugin-test/nope"]}},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "PLUGIN_COMPOSE_INVALID"
    assert resp.json()["detail"]["details"]["reason_code"] == "PLUGIN_PART_NOT_FOUND"


def test_plugin_compose_accepts_a_valid_composition_and_dispatches_the_gate():
    skill_id = _create_item(f"plugin-test/compose-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        namespace = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    item_id, _ = _create_plugin_item({})

    # add_version_to_existing_item() requires owner-or-admin; the item's
    # own org_id must match the caller's for _require_owner_or_admin to
    # allow it (read create_service.py's own helper for the exact rule).
    client = _client(ORG_A, user_id="owner", role="admin")
    resp = client.post(
        f"/ainxt/v1/api/ecosystem/items/{item_id}/plugin-compose",
        json={"parts": {"skills": [namespace]}},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["item_id"] == item_id
    assert body["status"] == "verifying"


# ── Install fan-out / uninstall cascade ───────────────────────────────────

def _install(item_id: str, version_id: str, *, installed_for: str = "user-a", managed_by_plugin_install_id=None) -> dict:
    return installs_service.install(
        item_id=item_id, version_id=version_id, org_id=ORG_A, installed_by=installed_for,
        installed_for=installed_for, surfaces=["chat"], scope="private", origin="added",
        managed_by_plugin_install_id=managed_by_plugin_install_id,
    )


def _uninstall(install_id: str, *, caller_user_id: str = "user-a"):
    installs_service.uninstall(
        install_id, caller_org_id=ORG_A, caller_user_id=caller_user_id, caller_permissions=set(),
    )


def test_installing_a_plugin_fans_out_correctly_tagged_child_installs():
    skill_id = _create_item(f"plugin-test/fanout-skill-{uuid.uuid4().hex[:8]}", "skill")
    connector_id = _create_item(f"plugin-test/fanout-conn-{uuid.uuid4().hex[:8]}", "connector")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
        conn_ns = db.query(EcosystemItem).filter(EcosystemItem.id == connector_id).first().namespace
    finally:
        db.close()
    plugin_id, plugin_version_id = _create_plugin_item({"skills": [skill_ns], "connectors": [conn_ns]})

    parent = _install(plugin_id, plugin_version_id, installed_for="fanout-user")

    db = SessionLocal()
    try:
        children = db.query(EcosystemInstall).filter(
            EcosystemInstall.managed_by_plugin_install_id == parent["install_id"]
        ).all()
        child_item_ids = {c.item_id for c in children}
    finally:
        db.close()
    assert child_item_ids == {skill_id, connector_id}


def test_managed_by_plugin_install_id_survives_the_wire_on_installs_and_item_detail():
    # Regression: response_model=InstallModel/ItemSummaryModel silently
    # strips any field they don't declare (the exact class of bug
    # CONTRACTS.md §9 already documents once for Install.version_id) --
    # every other test in this file asserts against the DB/service layer
    # directly, which would never catch this. This one goes through the
    # real HTTP layer.
    skill_id = _create_item(f"plugin-test/wire-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    plugin_id, plugin_version_id = _create_plugin_item({"skills": [skill_ns]})
    parent = _install(plugin_id, plugin_version_id, installed_for="wire-user")

    client = _client(ORG_A, user_id="wire-user")

    installs_resp = client.get("/ainxt/v1/api/ecosystem/installs")
    assert installs_resp.status_code == 200, installs_resp.text
    rows = installs_resp.json()["installs"]
    parent_row = next(r for r in rows if r["install_id"] == parent["install_id"])
    child_row = next(r for r in rows if r["item"]["id"] == skill_id)
    assert parent_row["managed_by_plugin_install_id"] is None
    assert child_row["managed_by_plugin_install_id"] == parent["install_id"]
    assert child_row["item"]["managed_by_plugin_install_id"] == parent["install_id"]

    detail_resp = client.get(f"/ainxt/v1/api/ecosystem/items/{skill_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["managed_by_plugin_install_id"] == parent["install_id"]


def test_uninstalling_a_managed_child_directly_is_refused_like_a_required_install():
    skill_id = _create_item(f"plugin-test/refuse-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    plugin_id, plugin_version_id = _create_plugin_item({"skills": [skill_ns]})
    parent = _install(plugin_id, plugin_version_id, installed_for="refuse-user")

    db = SessionLocal()
    try:
        child = db.query(EcosystemInstall).filter(
            EcosystemInstall.managed_by_plugin_install_id == parent["install_id"]
        ).first()
    finally:
        db.close()
    assert child is not None

    with pytest.raises(EcosystemError) as exc_info:
        _uninstall(child.id, caller_user_id="refuse-user")
    assert "managed by plugin install" in str(exc_info.value)
    # Not a typed subclass -- same generic shape as the existing
    # scope="required" refusal (both plain EcosystemError -> §3 BAD_REQUEST).
    assert type(exc_info.value) is EcosystemError


def test_uninstalling_the_parent_removes_an_exclusively_owned_child():
    skill_id = _create_item(f"plugin-test/exclusive-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    plugin_id, plugin_version_id = _create_plugin_item({"skills": [skill_ns]})
    parent = _install(plugin_id, plugin_version_id, installed_for="exclusive-user")

    _uninstall(parent["install_id"], caller_user_id="exclusive-user")

    db = SessionLocal()
    try:
        remaining = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == skill_id, EcosystemInstall.installed_for == "exclusive-user",
        ).first()
    finally:
        db.close()
    assert remaining is None


def test_uninstalling_one_of_two_plugins_sharing_a_part_transfers_ownership_not_deletes():
    skill_id = _create_item(f"plugin-test/shared-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()
    plugin_a_id, plugin_a_version = _create_plugin_item({"skills": [skill_ns]})
    plugin_b_id, plugin_b_version = _create_plugin_item({"skills": [skill_ns]})

    parent_a = _install(plugin_a_id, plugin_a_version, installed_for="shared-user")
    parent_b = _install(plugin_b_id, plugin_b_version, installed_for="shared-user")

    db = SessionLocal()
    try:
        child = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == skill_id, EcosystemInstall.installed_for == "shared-user",
        ).first()
        child_id = child.id
        owner_before = child.managed_by_plugin_install_id
    finally:
        db.close()
    assert owner_before == parent_a["install_id"]  # plugin A installed first, claimed it

    _uninstall(parent_a["install_id"], caller_user_id="shared-user")

    db = SessionLocal()
    try:
        child_after_a = db.query(EcosystemInstall).filter(EcosystemInstall.id == child_id).first()
    finally:
        db.close()
    assert child_after_a is not None, "shared child must not be deleted while plugin B still needs it"
    assert child_after_a.managed_by_plugin_install_id == parent_b["install_id"]

    _uninstall(parent_b["install_id"], caller_user_id="shared-user")

    db = SessionLocal()
    try:
        child_after_b = db.query(EcosystemInstall).filter(EcosystemInstall.id == child_id).first()
    finally:
        db.close()
    assert child_after_b is None, "no plugin still needs it -- must actually be uninstalled now"


def test_new_version_diff_frees_a_removed_part_and_adds_a_newly_included_one():
    old_skill_id = _create_item(f"plugin-test/diff-old-skill-{uuid.uuid4().hex[:8]}", "skill")
    new_skill_id = _create_item(f"plugin-test/diff-new-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        old_ns = db.query(EcosystemItem).filter(EcosystemItem.id == old_skill_id).first().namespace
        new_ns = db.query(EcosystemItem).filter(EcosystemItem.id == new_skill_id).first().namespace
    finally:
        db.close()
    plugin_id, v1 = _create_plugin_item({"skills": [old_ns]})
    parent = _install(plugin_id, v1, installed_for="diff-user")

    v2 = _make_plugin_version(plugin_id, {"skills": [new_ns]})
    installs_service.update_to_version(
        parent["install_id"], v2, caller_org_id=ORG_A, caller_user_id="diff-user", caller_permissions=set(),
    )

    db = SessionLocal()
    try:
        old_child = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == old_skill_id, EcosystemInstall.installed_for == "diff-user",
        ).first()
        new_child = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == new_skill_id, EcosystemInstall.installed_for == "diff-user",
        ).first()
    finally:
        db.close()
    assert old_child is None, "removed part must be freed/uninstalled, not left dangling"
    assert new_child is not None and new_child.managed_by_plugin_install_id == parent["install_id"]


def test_an_unrelated_standalone_install_of_the_same_item_is_never_touched():
    skill_id = _create_item(f"plugin-test/standalone-skill-{uuid.uuid4().hex[:8]}", "skill")
    db = SessionLocal()
    try:
        skill_ns = db.query(EcosystemItem).filter(EcosystemItem.id == skill_id).first().namespace
    finally:
        db.close()

    db = SessionLocal()
    try:
        v = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == skill_id).first()
        standalone_version_id = v.id
    finally:
        db.close()

    # A DIFFERENT user installs the skill standalone -- must never be
    # touched by another user's plugin fan-out/uninstall for the "same"
    # item (different installed_for -- these are genuinely separate rows).
    standalone = _install(skill_id, standalone_version_id, installed_for="standalone-user")

    plugin_id, plugin_version_id = _create_plugin_item({"skills": [skill_ns]})
    parent = _install(plugin_id, plugin_version_id, installed_for="plugin-fanout-user")
    _uninstall(parent["install_id"], caller_user_id="plugin-fanout-user")

    db = SessionLocal()
    try:
        still_there = db.query(EcosystemInstall).filter(EcosystemInstall.id == standalone["install_id"]).first()
    finally:
        db.close()
    assert still_there is not None
    assert still_there.managed_by_plugin_install_id is None
