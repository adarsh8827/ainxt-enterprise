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
        "features", "caller_permissions", "policy_summary", "taxonomy", "new_badge_days", "enums_version",
        "caller_default_namespace_prefix", "build_info", "live_search_enabled",
    }
    # No caller_permissions passed above -> defaults to set() -> no
    # marketplace:provision -> build_info must be None, never sent to a
    # non-admin caller (real incident, 2026-09-27).
    assert config["build_info"] is None
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


# ── resolve_chat_ecosystem_surface (task B-10) ───────────────────────────
# Extracted from gateway.py's own inline chat-streaming logic so the
# desktop-app -> surface="desktop" resolution (x-ainxt-surface: desktop ->
# ClientSourceMiddleware's client_source="desktop" -> this function's
# surface="desktop") can be pinned by a direct unit test instead of only a
# comment claiming it works.

def test_desktop_client_source_always_resolves_to_desktop_surface_regardless_of_product():
    org_id = f"org-desktop-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(EcosystemOrgProduct(org_id=org_id, product_key="workspace", is_primary=True))
        db.commit()
    finally:
        db.close()

    assert config_service.resolve_chat_ecosystem_surface("desktop", org_id) == "desktop"


def test_non_desktop_client_source_resolves_to_chat_for_an_enterprise_org():
    assert config_service.resolve_chat_ecosystem_surface("platform", "default") == "chat"


def test_non_desktop_client_source_resolves_to_workspace_chat_for_a_workspace_org():
    org_id = f"org-workspace-chat-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(EcosystemOrgProduct(org_id=org_id, product_key="workspace", is_primary=True))
        db.commit()
    finally:
        db.close()

    assert config_service.resolve_chat_ecosystem_surface("platform", org_id) == "workspace_chat"


# ── build_info (real incident, 2026-09-27: testing against a stale image,
# no way to tell from the running app) ──────────────────────────────────

def test_build_info_is_none_for_a_caller_without_marketplace_provision(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "deadbeef1234")
    monkeypatch.setenv("BUILD_TIME", "2026-09-27T12:00:00Z")
    result = config_service.get_effective_config("default", "user-no-perms-buildinfo", None, caller_permissions=set())
    assert result["build_info"] is None


def test_build_info_is_present_for_a_caller_with_marketplace_provision(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "deadbeef1234")
    monkeypatch.setenv("BUILD_TIME", "2026-09-27T12:00:00Z")
    result = config_service.get_effective_config(
        "default", "user-admin-buildinfo", None, caller_permissions={"marketplace:provision"},
    )
    assert result["build_info"] == {"commit": "deadbeef1234", "built_at": "2026-09-27T12:00:00Z"}


# ── live_search_enabled (Discover "From the web" UI round, 2026-09-29):
# the real, EFFECTIVE "both ECOSYSTEM_LIVE_SOURCES and this org's own
# live_sources_enabled policy toggle are true" signal, distinct from
# policy_summary's raw live_sources_enabled (the org toggle alone) --
# real gap found and closed this round: the raw toggle was already
# surfaced, but nothing told the frontend whether the INSTANCE-wide flag
# was also on, so a frontend gating on policy_summary alone could show
# the section on an instance where every search silently returns []. ──

def test_live_search_enabled_is_true_only_when_both_gates_are_on(monkeypatch):
    from services.ecosystem import live_search_service
    from services.ecosystem.policy_service import set_policy

    org_id = f"org-config-live-search-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", True)
    set_policy(org_id, live_sources_enabled=True, updated_by="admin-live-search-config")

    result = config_service.get_effective_config(org_id, "user-live-search-config", None)
    assert result["live_search_enabled"] is True


def test_live_search_enabled_is_false_when_the_instance_flag_is_off_even_with_org_policy_on(monkeypatch):
    from services.ecosystem import live_search_service
    from services.ecosystem.policy_service import set_policy

    org_id = f"org-config-live-search-instance-off-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", False)
    set_policy(org_id, live_sources_enabled=True, updated_by="admin-live-search-config")

    result = config_service.get_effective_config(org_id, "user-live-search-config-2", None)
    # The raw org toggle (policy_summary) still reads True -- only the
    # combined, effective signal must be False here. Pinning both proves
    # this new field isn't just a duplicate of the existing one.
    assert result["policy_summary"]["live_sources_enabled"] is True
    assert result["live_search_enabled"] is False


def test_live_search_enabled_is_false_when_the_org_policy_is_off_even_with_instance_flag_on(monkeypatch):
    from services.ecosystem import live_search_service
    from services.ecosystem.policy_service import set_policy

    org_id = f"org-config-live-search-org-off-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(live_search_service, "ECOSYSTEM_LIVE_SOURCES", True)
    set_policy(org_id, live_sources_enabled=False, updated_by="admin-live-search-config")

    result = config_service.get_effective_config(org_id, "user-live-search-config-3", None)
    assert result["policy_summary"]["live_sources_enabled"] is False
    assert result["live_search_enabled"] is False


# ── taxonomy vs. sources.yaml (real incident, 2026-09-29): every category
# docs/ecosystem/catalog/sources.yaml assigns to a crawled repo MUST be a
# real member of this list -- Discover.tsx's own CategorySection rendering
# is `config.taxonomy.categories.filter((category) => byCategory.has(
# category))`, so a category absent from this list is not "shown with 0
# items" but silently invisible, with no error anywhere. "engineering" and
# "security" were both real, heavily-used sources.yaml categories (126 of
# 143 live catalog items between them) that this list never accounted
# for -- confirmed directly against the real DB, root-caused to this exact
# filter. This test encodes the invariant itself (reads sources.yaml for
# real) rather than just pinning the two categories found this time, so a
# future sources.yaml addition using any other new category value fails
# this test immediately instead of silently vanishing from Discover again.
def test_every_sources_yaml_category_is_a_real_taxonomy_category():
    import yaml

    with open("docs/ecosystem/catalog/sources.yaml", encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    used_categories = {entry["category"] for entry in sources.get("github_repos", [])}
    used_categories |= {entry["category"] for entry in sources.get("well_known_sites", [])}

    result = config_service.get_effective_config("default", "user-taxonomy-check", None, caller_permissions=set())
    taxonomy_categories = set(result["taxonomy"]["categories"])

    missing = used_categories - taxonomy_categories
    assert not missing, (
        f"docs/ecosystem/catalog/sources.yaml uses categor(y/ies) {missing!r} not present in "
        f"config_service.py's taxonomy -- every crawled item in these categories is silently "
        f"invisible in Discover, not merely unfiltered"
    )
