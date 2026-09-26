# SPDX-License-Identifier: MIT
# ============================================================
# Config service tests (task B-12, M3). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

import uuid

import pytest

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion, EcosystemOrgProduct, EcosystemPublisher, EcosystemSource
from services.ecosystem import config_service
from services.ecosystem.errors import NotFoundError, PolicyForbiddenError


def _make_builtin_item(namespace: str) -> tuple[str, str]:
    db = SessionLocal()
    try:
        pub_slug = namespace.split("/")[0]
        if db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == pub_slug).first() is None:
            db.add(EcosystemPublisher(slug=pub_slug, owner_type="org", owner_ref="platform"))
        source = EcosystemSource(kind="local", org_id=None, created_by="system")
        db.add(source)
        db.commit()
        db.refresh(source)

        item = EcosystemItem(
            namespace=namespace, item_type="skill", category="general",
            display_name="Builtin Test", description="d", source_id=source.id,
            scope="builtin", org_id=None, trust_tier="builtin", license="MIT",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        version = EcosystemItemVersion(
            item_id=item.id, version="1.0.0", content_hash=uuid.uuid4().hex,
            object_key=uuid.uuid4().hex, license="MIT", attribution="",
            manifest={"name": "Builtin Test", "description": "d", "instructions": "x"},
            gate_verdict="pass",
        )
        db.add(version)
        db.commit()
        return item.id, version.id
    finally:
        db.close()


def test_resolve_product_defaults_to_org_primary_when_header_absent():
    config = config_service.get_effective_config("default", f"user-{uuid.uuid4().hex[:8]}", None)
    assert config["product"] == "enterprise"


def test_resolve_product_falls_back_to_enterprise_for_an_org_with_no_entitlement_row():
    config = config_service.get_effective_config(f"org-no-entitlement-{uuid.uuid4().hex[:8]}", "user-x", None)
    assert config["product"] == "enterprise"


def test_requested_product_with_no_profile_row_is_not_found():
    with pytest.raises(NotFoundError):
        config_service.get_effective_config("default", "user-x", "no-such-product")


def test_requested_product_without_entitlement_is_policy_forbidden():
    with pytest.raises(PolicyForbiddenError):
        config_service.get_effective_config(f"org-unentitled-{uuid.uuid4().hex[:8]}", "user-x", "workspace")


def test_requested_product_with_entitlement_succeeds():
    org_id = f"org-entitled-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(EcosystemOrgProduct(org_id=org_id, product_key="workspace", is_primary=True))
        db.commit()
    finally:
        db.close()

    config = config_service.get_effective_config(org_id, "user-x", "workspace")
    assert config["product"] == "workspace"
    assert config["layout"] == "compact"


def test_config_response_shape_matches_contract():
    config = config_service.get_effective_config("default", f"user-{uuid.uuid4().hex[:8]}", None)
    assert set(config.keys()) == {
        "product", "layout", "default_view", "item_types", "route_slugs", "surfaces",
        "features", "policy_summary", "taxonomy", "new_badge_days", "enums_version",
    }
    types_by_name = {t["type"]: t for t in config["item_types"]}
    assert types_by_name["skill"]["state"] == "available"
    assert types_by_name["plugin"]["state"] == "coming_soon"
    assert {s["key"] for s in config["surfaces"]} == {"chat", "agent_studio", "desktop"}


def test_first_config_call_provisions_every_builtin_item_exactly_once():
    item_id, version_id = _make_builtin_item(f"platform/builtin-{uuid.uuid4().hex[:8]}")
    user_id = f"user-{uuid.uuid4().hex[:8]}"

    config_service.get_effective_config("default", user_id, None)

    db = SessionLocal()
    try:
        installs = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.installed_for == user_id,
        ).all()
    finally:
        db.close()
    assert len(installs) == 1
    assert installs[0].origin == "provisioned"
    assert installs[0].scope == "provisioned"
    assert installs[0].enabled is True
    assert set(installs[0].surfaces) == {"chat", "agent_studio", "desktop"}


def test_second_config_call_creates_no_additional_rows():
    item_id, version_id = _make_builtin_item(f"platform/builtin-{uuid.uuid4().hex[:8]}")
    user_id = f"user-{uuid.uuid4().hex[:8]}"

    config_service.get_effective_config("default", user_id, None)
    config_service.get_effective_config("default", user_id, None)

    db = SessionLocal()
    try:
        count = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.installed_for == user_id,
        ).count()
    finally:
        db.close()
    assert count == 1


def test_a_required_item_provisions_as_required_from_the_very_first_call():
    item_id, version_id = _make_builtin_item(f"platform/builtin-req-{uuid.uuid4().hex[:8]}")
    existing_user = f"user-existing-{uuid.uuid4().hex[:8]}"
    new_user = f"user-new-{uuid.uuid4().hex[:8]}"

    # An existing 'required' install for this item in this org, as if
    # policy_service.require_item() had already run for a different user.
    db = SessionLocal()
    try:
        db.add(EcosystemInstall(
            item_id=item_id, version_id=version_id, org_id="default",
            installed_by="admin", installed_for=existing_user,
            scope="required", origin="required", surfaces=["chat"],
        ))
        db.commit()
    finally:
        db.close()

    config_service.get_effective_config("default", new_user, None)

    db = SessionLocal()
    try:
        new_install = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.installed_for == new_user,
        ).first()
    finally:
        db.close()
    assert new_install is not None
    assert new_install.origin == "required"
    assert new_install.scope == "required"


def test_org_excluded_default_is_never_provisioned():
    from services.ecosystem import policy_service

    item_id, version_id = _make_builtin_item(f"platform/builtin-excl-{uuid.uuid4().hex[:8]}")
    user_id = f"user-{uuid.uuid4().hex[:8]}"

    policy_service.admin_disable_org_default(item_id, "default", "admin-1")

    config_service.get_effective_config("default", user_id, None)

    db = SessionLocal()
    try:
        install = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.installed_for == user_id,
        ).first()
    finally:
        db.close()
    assert install is None
