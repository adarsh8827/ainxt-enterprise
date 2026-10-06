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


def test_multiple_installed_skills_are_returned_in_stable_namespace_order():
    # Chat-skills task, 2026-09-28: mcp/ecosystem_skill_tools.py's
    # render_skill_index() renders this list verbatim into the chat prompt
    # -- an unstable order (Postgres's own unspecified physical/insertion
    # order, pre-fix) would change that text byte-for-byte between
    # requests even when the installed skill SET hasn't changed, busting
    # prompt-cache reuse. Installed deliberately out of alphabetical order
    # so a stale insertion-order bug would show up as a real failure here.
    for ns, ref in [("acme/zzz-skill", "order-zzz"), ("acme/aaa-skill", "order-aaa"), ("acme/mmm-skill", "order-mmm")]:
        item_id, version_id = _make_item(ns, ref, org_id="org-order")
        installs_service.install(
            item_id=item_id, version_id=version_id, org_id="org-order",
            installed_by="user-order", installed_for="user-order", surfaces=["chat"],
        )
    capabilities = resolver_service.get_effective_capabilities("org-order", "user-order", "chat")
    namespaces = [c["namespace"] for c in capabilities]
    assert namespaces == sorted(namespaces)
    assert namespaces == ["acme/aaa-skill", "acme/mmm-skill", "acme/zzz-skill"]


def test_disabled_install_is_not_resolved():
    item_id, version_id = _make_item("acme/resolver-2", "resolver-2")
    result = installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r2", installed_for="user-r2", surfaces=["chat"],
    )
    installs_service.set_enabled(result["install_id"], False, caller_org_id="org-r", caller_user_id="user-r2", caller_permissions=set())
    capabilities = resolver_service.get_effective_capabilities("org-r", "user-r2", "chat")
    assert capabilities == []


def test_failed_verdict_install_is_not_resolved_even_if_enabled_and_item_active():
    # Real bug found live (2026-10-06, user report): this query used to
    # only check install.enabled + item.status == "active" -- never the
    # SPECIFIC version the install is actually pinned to. A user could see
    # "Blocked" in Yours (driven by item.latest_verdict, the NEWEST
    # version's own verdict -- a completely different signal) while the
    # skill kept working in chat, because this resolver never looked at
    # the installed version's own gate_verdict at all. An install pinned
    # to a version whose gate_verdict is "fail" must never surface here,
    # regardless of item.status or install.enabled.
    from db.database import SessionLocal
    from db.models import EcosystemItemVersion

    item_id, version_id = _make_item("acme/resolver-failed", "resolver-failed")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r-failed", installed_for="user-r-failed", surfaces=["chat"],
    )
    db = SessionLocal()
    try:
        db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).update({"gate_verdict": "fail"})
        db.commit()
    finally:
        db.close()
    assert resolver_service.get_effective_capabilities("org-r", "user-r-failed", "chat") == []


def test_warn_verdict_install_is_still_resolved():
    # The other half of the above: "warn" is still good enough to use,
    # matching the exact bar _auto_install()/_bump_own_install_on_pass()
    # already use elsewhere ("pass"/"warn" both auto-install) -- only a
    # real "fail" should ever hide a skill from chat.
    from db.database import SessionLocal
    from db.models import EcosystemItemVersion

    item_id, version_id = _make_item("acme/resolver-warn", "resolver-warn")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r-warn", installed_for="user-r-warn", surfaces=["chat"],
    )
    db = SessionLocal()
    try:
        db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).update({"gate_verdict": "warn"})
        db.commit()
    finally:
        db.close()
    assert len(resolver_service.get_effective_capabilities("org-r", "user-r-warn", "chat")) == 1


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


# Info-popover fix (2026-09-29): the chat UI's "ⓘ" popover needs
# license/source without a second fetch -- both are plain columns already
# on the same EcosystemItem row this resolver already selects.
def test_capabilities_include_license_and_a_source_label():
    item_id, version_id = _make_item("acme/resolver-8", "resolver-8")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r8", installed_for="user-r8", surfaces=["chat"],
    )
    capabilities = resolver_service.get_effective_capabilities("org-r", "user-r8", "chat")
    assert len(capabilities) == 1
    # upsert_legacy_pointer_item() doesn't pass an explicit license -- the
    # EcosystemItem column's own model default applies; this test's real
    # point is that the KEY is present at all (the resolver's own dict-
    # builder used to omit it entirely), not any specific value.
    assert "license" in capabilities[0]
    # No catalog_pointer on a legacy-pointer item (never synced in from an
    # external source) -- _source_label()'s own "authored directly here"
    # fallback.
    assert capabilities[0]["source"] == "Created in this workspace"


def test_render_skill_index_never_leaks_license_or_source_into_the_model_prompt():
    # render_skill_index() (mcp/ecosystem_skill_tools.py) only ever reads
    # display_name/slash_command/description from this shape -- adding
    # license/source to the resolver's own dict must never change what
    # actually reaches the model prompt.
    from mcp.ecosystem_skill_tools import render_skill_index

    item_id, version_id = _make_item("acme/resolver-9", "resolver-9")
    installs_service.install(
        item_id=item_id, version_id=version_id, org_id="org-r",
        installed_by="user-r9", installed_for="user-r9", surfaces=["chat"],
    )
    capabilities = resolver_service.get_effective_capabilities("org-r", "user-r9", "chat")
    index = render_skill_index(capabilities)
    assert "Created in this workspace" not in index


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
    installs_service.set_enabled(result_1["install_id"], False, caller_org_id="org-r", caller_user_id="user-r7", caller_permissions=set())
    assert resolver_service.get_effective_capabilities("org-r", "user-r7", "chat") == []
