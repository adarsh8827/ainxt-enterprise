# SPDX-License-Identifier: MIT
# ============================================================
# Resolver service tests (task B-11, M3). Tier-2 — real Postgres (+ Redis
# for the cache-invalidation tests; the resolve-correctness tests below
# don't need Redis at all, since a cache miss/unavailable-cache both fall
# through to a fresh DB query).
# ============================================================

from __future__ import annotations

import json
from unittest.mock import patch

from services.ecosystem import installs_service, resolver_service
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_item(namespace: str, legacy_ref: str, org_id: str = "org-r"):
    item_id, _ = upsert_legacy_pointer_item(
        namespace=namespace, item_type="skill", category="general",
        display_name="Resolver Test", description="d",
        org_id=org_id, legacy_source="skills_pg", legacy_ref=legacy_ref,
    )
    with _mock_ethics_pass():
        version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    return item_id, version_id


def test_installed_enabled_surface_matching_skill_is_resolved():
    item_id, version_id = _make_item("acme/resolver-1", "resolver-1")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r1", installed_for="user-r1", surfaces=["chat"],
    )
    capabilities = resolver_service.get_effective_capabilities("org-r", "user-r1", "chat")
    assert len(capabilities) == 1
    assert capabilities[0]["namespace"] == "acme/resolver-1"
    assert capabilities[0]["slash_command"] == "/resolver-1"


def test_disabled_install_is_not_resolved():
    item_id, version_id = _make_item("acme/resolver-2", "resolver-2")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r2", installed_for="user-r2", surfaces=["chat"],
    )
    installs_service.set_enabled(result["install_id"], False)
    capabilities = resolver_service.get_effective_capabilities("org-r", "user-r2", "chat")
    assert capabilities == []


def test_wrong_surface_is_not_resolved():
    item_id, version_id = _make_item("acme/resolver-3", "resolver-3")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r3", installed_for="user-r3", surfaces=["agent_studio"],
    )
    assert resolver_service.get_effective_capabilities("org-r", "user-r3", "chat") == []
    assert len(resolver_service.get_effective_capabilities("org-r", "user-r3", "agent_studio")) == 1


def test_never_installed_item_is_not_resolved_even_if_gate_passed():
    # A backfilled-but-never-installed legacy item must not appear --
    # confirms there is no separate "legacy merge" leaking un-installed
    # content into live capabilities.
    _make_item("acme/resolver-4", "resolver-4")
    assert resolver_service.get_effective_capabilities("org-r", "user-r4", "chat") == []


def test_a_different_users_install_is_not_resolved_for_this_user():
    item_id, version_id = _make_item("acme/resolver-5", "resolver-5")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r5a", installed_for="user-r5a", surfaces=["chat"],
    )
    assert resolver_service.get_effective_capabilities("org-r", "user-r5b", "chat") == []


def test_disabling_the_installed_item_type_via_flag_excludes_it(monkeypatch):
    import core.config as cfg
    monkeypatch.setattr(cfg, "ECOSYSTEM_TYPE_SKILL", False)

    item_id, version_id = _make_item("acme/resolver-6", "resolver-6")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r6", installed_for="user-r6", surfaces=["chat"],
    )
    assert resolver_service.get_effective_capabilities("org-r", "user-r6", "chat") == []


def test_result_is_cached_and_invalidated_on_the_next_mutation():
    try:
        cache = resolver_service._get_cache()
        if cache is None:
            raise RuntimeError("no cache")
        cache.ping()
    except Exception:
        import pytest
        pytest.skip("Redis not reachable")

    item_id, version_id = _make_item("acme/resolver-7", "resolver-7")
    result_1 = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r7", installed_for="user-r7", surfaces=["chat"],
    )
    first = resolver_service.get_effective_capabilities("org-r", "user-r7", "chat")
    assert len(first) == 1

    # Confirm it's actually served from cache: directly poison the cache
    # entry with an impossible value, then verify the poisoned (not the
    # real, freshly-queried) value comes back -- proving a cache hit
    # occurred, not a coincidental match with the real state.
    key = resolver_service._cache_key("org-r", "user-r7", "chat")
    poisoned = [{"namespace": "not/real", "display_name": "x", "description": "x", "slash_command": "/x"}]
    cache.setex(key, 60, json.dumps(poisoned))
    assert resolver_service.get_effective_capabilities("org-r", "user-r7", "chat") == poisoned

    # Disabling the install must invalidate the cache -- the very next
    # call must reflect the real, current (disabled) state, not the
    # poisoned cached value.
    installs_service.set_enabled(result_1["install_id"], False)
    assert resolver_service.get_effective_capabilities("org-r", "user-r7", "chat") == []
