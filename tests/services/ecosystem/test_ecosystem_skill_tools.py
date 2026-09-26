# SPDX-License-Identifier: MIT
# ============================================================
# Task B-15: mcp/ecosystem_skill_tools.py -- skill_view/read_skill_file.
# Tier-2, real Postgres. Ethics stage mocked for determinism (same
# convention as test_create_service.py).
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp.ecosystem_skill_tools import SkillNotFoundError, read_skill_file, resolve_pinned_version_id, skill_view
from services.ecosystem import create_service, installs_service


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _create_installed_skill(*, org_id, user_id, namespace, instructions="do the thing", files=None, surfaces=("chat",)):
    with _mock_ethics_pass():
        result = create_service.create_via_write(
            org_id=org_id, created_by=user_id, item_type="skill", namespace=namespace,
            display_name="Tool Test", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": instructions, "files": list(files or [])},
            surfaces=list(surfaces),
        )
    return result


def test_skill_view_returns_the_installed_versions_instructions():
    _create_installed_skill(org_id="org-tools", user_id="user-a", namespace="acme/tool-basic", instructions="hello from the skill")
    text = skill_view("acme/tool-basic", org_id="org-tools", user_id="user-a", surface="chat")
    assert text == "hello from the skill"


def test_skill_view_truncates_at_8000_characters_with_a_marker():
    long_instructions = "x" * 9_000
    _create_installed_skill(org_id="org-tools", user_id="user-a", namespace="acme/tool-long", instructions=long_instructions)
    text = skill_view("acme/tool-long", org_id="org-tools", user_id="user-a", surface="chat")
    assert len(text) < 9_000
    assert text.startswith("x" * 8000)
    assert "truncated, 1000 characters omitted" in text


def test_skill_view_raises_not_found_for_a_never_installed_skill():
    with pytest.raises(SkillNotFoundError):
        skill_view("acme/does-not-exist", org_id="org-tools", user_id="user-a", surface="chat")


def test_skill_view_raises_not_found_when_disabled():
    result = _create_installed_skill(org_id="org-tools", user_id="user-disable", namespace="acme/tool-disabled")
    install = installs_service.get_install_for_caller(result["item_id"], "org-tools", "user-disable")
    installs_service.set_enabled(install.id, False)
    with pytest.raises(SkillNotFoundError):
        skill_view("acme/tool-disabled", org_id="org-tools", user_id="user-disable", surface="chat")


def test_skill_view_raises_not_found_for_the_wrong_surface():
    _create_installed_skill(org_id="org-tools", user_id="user-surface", namespace="acme/tool-chat-only", surfaces=["chat"])
    with pytest.raises(SkillNotFoundError):
        skill_view("acme/tool-chat-only", org_id="org-tools", user_id="user-surface", surface="agent_studio")


def test_skill_view_enforces_cross_org_isolation():
    _create_installed_skill(org_id="org-tools-a", user_id="user-a", namespace="acme/tool-cross-org")
    with pytest.raises(SkillNotFoundError):
        skill_view("acme/tool-cross-org", org_id="org-tools-b", user_id="user-b", surface="chat")


def test_read_skill_file_returns_declared_file_content():
    _create_installed_skill(
        org_id="org-tools", user_id="user-files", namespace="acme/tool-files",
        files=[{"name": "references/notes.md", "content": "some reference content"}],
    )
    text = read_skill_file("acme/tool-files", "references/notes.md", org_id="org-tools", user_id="user-files", surface="chat")
    assert text == "some reference content"


def test_read_skill_file_not_found_for_undeclared_path_never_a_generic_error():
    _create_installed_skill(
        org_id="org-tools", user_id="user-files2", namespace="acme/tool-files2",
        files=[{"name": "references/real.md", "content": "x"}],
    )
    with pytest.raises(SkillNotFoundError):
        read_skill_file("acme/tool-files2", "../../etc/passwd", org_id="org-tools", user_id="user-files2", surface="chat")
    with pytest.raises(SkillNotFoundError):
        read_skill_file("acme/tool-files2", "references/does-not-exist.md", org_id="org-tools", user_id="user-files2", surface="chat")


def test_read_skill_file_truncates_large_text_content():
    # A real, disclosed interaction between two limits that were designed
    # independently: the gate's own manifest_stage.py rejects any bundled
    # file over 64KB (task B-8) -- strictly smaller than this tool's own
    # 256KB read limit (CONTRACTS.md §12). That means no file that ever
    # actually passes the gate can be large enough to exercise this
    # function's truncation branch through the real create_via_write ->
    # gate -> install pipeline; nothing above 64KB can ever become an
    # installed, readable file in the first place. To still exercise the
    # truncation code path for real, this test writes the version/object-
    # storage rows directly (bypassing create_service/the gate entirely,
    # the same direct-DB-setup convention test_items_versions_gate_service.py
    # already uses) rather than fabricate a scenario the real pipeline
    # could never produce.
    result = _create_installed_skill(org_id="org-tools", user_id="user-big", namespace="acme/tool-big-file")
    item_id = result["item_id"]

    from services.ecosystem.versions_service import create_version_for_content

    big_content = "y" * (300 * 1024)
    payload = f'{{"manifest": {{"instructions": "x"}}, "files": {{"references/big.md": "{big_content}"}}}}'.encode("utf-8")
    new_version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest={"instructions": "x", "files": {"references/big.md": big_content}},
        license="MIT",
    )
    install = installs_service.get_install_for_caller(item_id, "org-tools", "user-big")
    installs_service.update_to_version(install.id, new_version_id)

    text = read_skill_file("acme/tool-big-file", "references/big.md", org_id="org-tools", user_id="user-big", surface="chat")
    assert len(text.encode("utf-8")) < len(big_content.encode("utf-8"))
    assert "truncated" in text


def test_pinned_version_id_keeps_returning_old_content_after_the_install_is_updated_to_a_new_version():
    # This is exactly CONTRACTS.md §12's own requirement: "a mid-conversation
    # update landing during the same session doesn't change skill_view's
    # output until a new session." Session-level pinning itself is task
    # B-16's job (this module has no session concept) -- what THIS module
    # must guarantee is that a caller holding a pinned_version_id keeps
    # reading that exact version's content even after the install's
    # current version_id has moved on.
    result = _create_installed_skill(org_id="org-tools", user_id="user-pin", namespace="acme/tool-pinned", instructions="version one content")
    item_id = result["item_id"]

    pinned = resolve_pinned_version_id("acme/tool-pinned", org_id="org-tools", user_id="user-pin", surface="chat")
    assert pinned == result["version_id"]

    # Simulate a new version landing and the install moving to it.
    from services.ecosystem.versions_service import create_version_for_content

    new_version_id = create_version_for_content(
        item_id=item_id, content=b'{"manifest": {"instructions": "version two content"}, "files": {}}',
        manifest={"instructions": "version two content"}, license="MIT",
    )
    install = installs_service.get_install_for_caller(item_id, "org-tools", "user-pin")
    installs_service.update_to_version(install.id, new_version_id)

    # Pinned caller still sees the old content.
    pinned_text = skill_view("acme/tool-pinned", org_id="org-tools", user_id="user-pin", surface="chat", pinned_version_id=pinned)
    assert pinned_text == "version one content"

    # A fresh (unpinned) call sees the new, current content -- a genuinely
    # new session would call resolve_pinned_version_id() again and get this.
    fresh_text = skill_view("acme/tool-pinned", org_id="org-tools", user_id="user-pin", surface="chat")
    assert fresh_text == "version two content"


def test_pinned_version_id_still_re_checks_current_authorization():
    # A stale pin must not keep working once the caller's install is
    # disabled/uninstalled -- only the CONTENT VERSION is allowed to stay
    # pinned, never the authorization decision itself.
    result = _create_installed_skill(org_id="org-tools", user_id="user-revoke", namespace="acme/tool-revoke")
    pinned = resolve_pinned_version_id("acme/tool-revoke", org_id="org-tools", user_id="user-revoke", surface="chat")
    assert pinned is not None

    install = installs_service.get_install_for_caller(result["item_id"], "org-tools", "user-revoke")
    installs_service.set_enabled(install.id, False)

    with pytest.raises(SkillNotFoundError):
        skill_view("acme/tool-revoke", org_id="org-tools", user_id="user-revoke", surface="chat", pinned_version_id=pinned)
