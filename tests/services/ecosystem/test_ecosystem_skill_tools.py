# SPDX-License-Identifier: MIT
# ============================================================
# Task B-15: mcp/ecosystem_skill_tools.py -- skill_view/read_skill_file.
# Tier-2, real Postgres. Ethics stage mocked for determinism (same
# convention as test_create_service.py).
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.state import AgentState
from mcp.ecosystem_skill_tools import (
    SkillNotFoundError, apply_chat_skill_integration, matches_attached_skill, matches_installed_skill_slash_command,
    read_skill_file, render_skill_index, resolve_pinned_version_id, skill_view,
)
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
    installs_service.set_enabled(install.id, False, caller_org_id="org-tools", caller_user_id="user-disable", caller_permissions=set())
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
    installs_service.update_to_version(install.id, new_version_id, caller_org_id="org-tools", caller_user_id="user-big", caller_permissions=set())

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
    installs_service.update_to_version(install.id, new_version_id, caller_org_id="org-tools", caller_user_id="user-pin", caller_permissions=set())

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
    installs_service.set_enabled(install.id, False, caller_org_id="org-tools", caller_user_id="user-revoke", caller_permissions=set())

    with pytest.raises(SkillNotFoundError):
        skill_view("acme/tool-revoke", org_id="org-tools", user_id="user-revoke", surface="chat", pinned_version_id=pinned)


# ---------------------------------------------------------------------------
# apply_chat_skill_integration -- task B-16's real integration point, called
# from agents/orchestrator.py's run(). Proves the user-visible claim
# ("typing '/name ...' actually uses the skill") at the level that matters:
# the skill's real instructions body enters state.question/raw_question,
# not just that skill_view()/resolve_pinned_version_id() work in isolation
# (already covered above).
# ---------------------------------------------------------------------------

def test_apply_chat_skill_integration_expands_a_slash_command_into_the_skill_body():
    _create_installed_skill(
        org_id="org-tools", user_id="user-slash", namespace="acme/meeting-notes-test",
        instructions="UNIQUE-SKILL-BODY-42: summarize the meeting into decisions, owners, and dates.",
    )
    state = AgentState(question="/meeting-notes-test do it for today's standup")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-slash", surface="chat")

    assert "UNIQUE-SKILL-BODY-42" in state.question
    assert "summarize the meeting into decisions, owners, and dates." in state.question
    # Item, 2026-09-28: labeled block, not a bare "---" separator -- names
    # the skill + version and tells the model to follow it for this request.
    assert "[SKILL: Tool Test (acme/meeting-notes-test), version" in state.question
    assert "Follow these instructions for this request:" in state.question
    assert state.question.endswith("[USER REQUEST]\ndo it for today's standup")
    assert state.raw_question == state.question
    assert state.metadata["ecosystem_skill_used"]["version_id"]  # a real version_id, not just name/display_name


def test_apply_chat_skill_integration_leaves_a_plain_message_untouched():
    _create_installed_skill(org_id="org-tools", user_id="user-slash2", namespace="acme/meeting-notes-test2")
    state = AgentState(question="what's the weather like")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-slash2", surface="chat")

    assert state.question == "what's the weather like"


def test_apply_chat_skill_integration_attached_skill_wins_over_slash_detection():
    # Task, 2026-09-28: chat request's own skills:[namespace] field --
    # attaches a skill WITHOUT the user typing a leading "/name". Checked
    # BEFORE slash detection.
    _create_installed_skill(
        org_id="org-tools", user_id="user-attach", namespace="acme/attach-test",
        instructions="ATTACH-BODY-99",
    )
    state = AgentState(question="fix this email please")
    state.raw_question = state.question

    apply_chat_skill_integration(
        state, org_id="org-tools", user_id="user-attach", surface="chat",
        attached_skill="acme/attach-test",
    )

    assert "ATTACH-BODY-99" in state.question
    assert state.question.endswith("[USER REQUEST]\nfix this email please")
    assert state.metadata["ecosystem_skill_used"]["name"] == "acme/attach-test"


# Chat-skills UX rework (2026-10-04, ai-ui side): the composer now always
# keeps a literal "/slash-command " prefix in the text alongside the
# explicit attached_skill field -- previously mutually exclusive (the old
# chip-based frontend stripped that text whenever attached_skill was set),
# so `rest = current_question` unconditionally used to be safe. Must not
# leak the raw command token into "[USER REQUEST]" now that both arrive
# together.
def test_apply_chat_skill_integration_attached_skill_strips_its_own_leading_slash_command():
    _create_installed_skill(
        org_id="org-tools", user_id="user-attach6", namespace="acme/attach-slash",
        instructions="ATTACH-SLASH-BODY",
    )
    state = AgentState(question="/attach-slash fix this email please")
    state.raw_question = state.question

    apply_chat_skill_integration(
        state, org_id="org-tools", user_id="user-attach6", surface="chat",
        attached_skill="acme/attach-slash",
    )

    assert "ATTACH-SLASH-BODY" in state.question
    assert state.question.endswith("[USER REQUEST]\nfix this email please")
    assert "/attach-slash" not in state.question.rsplit("[USER REQUEST]", 1)[1]


# A leading slash token that does NOT resolve to this same attached_skill
# (e.g. stale/mismatched text) must not be silently swallowed -- fail open
# by keeping the full text as "rest", same fail-open spirit as everywhere
# else in this function.
def test_apply_chat_skill_integration_attached_skill_keeps_mismatched_leading_slash_text():
    _create_installed_skill(
        org_id="org-tools", user_id="user-attach7", namespace="acme/attach-mismatch",
        instructions="ATTACH-MISMATCH-BODY",
    )
    state = AgentState(question="/some-other-command fix this email please")
    state.raw_question = state.question

    apply_chat_skill_integration(
        state, org_id="org-tools", user_id="user-attach7", surface="chat",
        attached_skill="acme/attach-mismatch",
    )

    assert state.question.endswith("[USER REQUEST]\n/some-other-command fix this email please")


def test_apply_chat_skill_integration_attached_skill_not_installed_falls_back_to_slash_detection():
    _create_installed_skill(
        org_id="org-tools", user_id="user-attach2", namespace="acme/attach-real",
        instructions="REAL-BODY",
    )
    state = AgentState(question="/attach-real do it")
    state.raw_question = state.question

    apply_chat_skill_integration(
        state, org_id="org-tools", user_id="user-attach2", surface="chat",
        attached_skill="acme/does-not-exist",
    )

    # Falls through to slash detection rather than silently dropping the turn.
    assert "REAL-BODY" in state.question


def test_apply_chat_skill_integration_attached_skill_none_behaves_exactly_as_before():
    _create_installed_skill(org_id="org-tools", user_id="user-attach3", namespace="acme/attach-none")
    state = AgentState(question="what's the weather like")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-attach3", surface="chat", attached_skill=None)

    assert state.question == "what's the weather like"


# ---------------------------------------------------------------------------
# Explain mode (2026-09-29): the labelled skill block's content must differ
# for an explain-only message vs. a normal invocation -- same single call,
# same token cost, different instruction text. Chat history/title are
# unaffected by this (see chip-cleanup round's own note) since they're built
# from the user's own literal text elsewhere, not from this expanded prompt.
# ---------------------------------------------------------------------------

def test_apply_chat_skill_integration_explain_only_message_describes_instead_of_applies():
    _create_installed_skill(
        org_id="org-tools", user_id="user-explain1", namespace="acme/explain-test",
        instructions="UNIQUE-EXPLAIN-BODY-1: do the confidential task thing.",
    )
    state = AgentState(question="/explain-test explain this")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-explain1", surface="chat")

    assert "describe this skill to the user" in state.question
    assert "Do NOT follow the instructions below as a task" in state.question
    assert "Follow these instructions for this request:" not in state.question
    # The body is still present as context for the description, but the
    # instruction framing around it changed.
    assert "UNIQUE-EXPLAIN-BODY-1" in state.question


@pytest.mark.parametrize("explain_text", [
    "explain",
    "explain this",
    "explain this skill",
    "what is this",
    "what's this skill",
    "help",
    "how do I use this",
    "how does this work",
    "describe this skill",
])
def test_apply_chat_skill_integration_explain_only_matches_whole_message_variants(explain_text):
    _create_installed_skill(
        org_id="org-tools", user_id="user-explain2", namespace="acme/explain-variants",
        instructions="EXPLAIN-VARIANT-BODY",
    )
    state = AgentState(question=f"/explain-variants {explain_text}")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-explain2", surface="chat")

    assert "describe this skill to the user" in state.question


def test_apply_chat_skill_integration_explain_word_inside_a_real_task_is_not_explain_mode():
    # The whole-message requirement's own safety property: a real task that
    # happens to mention "help"/"explain" as part of a longer request must
    # NOT be misclassified as explain-only.
    _create_installed_skill(
        org_id="org-tools", user_id="user-explain3", namespace="acme/explain-not-mode",
        instructions="REAL-TASK-BODY",
    )
    state = AgentState(question="/explain-not-mode help me explain this email to my manager")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-explain3", surface="chat")

    assert "Follow these instructions for this request:" in state.question
    assert "describe this skill to the user" not in state.question


def test_apply_chat_skill_integration_explain_only_also_works_via_attached_skill():
    _create_installed_skill(
        org_id="org-tools", user_id="user-explain4", namespace="acme/explain-attached",
        instructions="ATTACHED-EXPLAIN-BODY",
    )
    state = AgentState(question="what is this")
    state.raw_question = state.question

    apply_chat_skill_integration(
        state, org_id="org-tools", user_id="user-explain4", surface="chat",
        attached_skill="acme/explain-attached",
    )

    assert "describe this skill to the user" in state.question


def test_apply_chat_skill_integration_bare_invocation_with_no_text_is_not_explain_mode():
    # A bare chip/slash command with nothing typed after it is an ordinary
    # invocation (today's existing behavior), not explain mode.
    _create_installed_skill(
        org_id="org-tools", user_id="user-explain5", namespace="acme/explain-bare",
        instructions="BARE-BODY",
    )
    state = AgentState(question="/explain-bare")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-explain5", surface="chat")

    assert "Follow these instructions for this request:" in state.question
    assert "describe this skill to the user" not in state.question


def test_render_skill_index_tells_the_model_to_suggest_not_claim_to_apply():
    # Item, 2026-09-28: no chat call site gives the model a way to actually
    # invoke skill_view/read_skill_file (no native tool-calling wired --
    # disclosed gap, planned for the MCP/Connectors phase). The index text
    # itself must not imply otherwise, or the model may hallucinate having
    # already applied a skill it never received the body of.
    index = render_skill_index([{
        "namespace": "acme/demo", "display_name": "Demo Skill",
        "description": "does the demo thing", "slash_command": "/demo",
    }])
    assert "suggest" in index.lower()
    assert "/demo" in index
    assert "skill_view(" not in index  # the old, misleading "call skill_view()" wording is gone


def test_render_skill_index_empty_for_no_skills():
    assert render_skill_index([]) == ""


def _fake_skill(i):
    return {
        "namespace": f"acme/skill-{i:02d}", "display_name": f"Skill {i}",
        "description": f"does thing {i}", "slash_command": f"/skill-{i:02d}",
    }


def test_render_skill_index_caps_at_20_entries_with_an_overflow_note():
    skills = [_fake_skill(i) for i in range(25)]
    index = render_skill_index(skills)
    for i in range(20):
        assert f"Skill {i}" in index
    for i in range(20, 25):
        assert f"Skill {i}" not in index
    assert "and 5 more" in index
    assert 'type "/"' in index


def test_render_skill_index_no_overflow_note_under_the_cap():
    skills = [_fake_skill(i) for i in range(5)]
    index = render_skill_index(skills)
    assert "more" not in index.lower()


def test_apply_chat_skill_integration_sets_the_skill_index_even_for_a_plain_message():
    # Item, 2026-09-28: gateway.py's PIPELINE_V2 fast-path tail relies on
    # this being true unconditionally (not just when a slash command
    # matches) -- it appends state.metadata["ecosystem_skill_index"] to
    # what the model sees for EVERY message, so the model can self-select
    # an installed skill via skill_view() without one being explicitly
    # invoked this turn.
    _create_installed_skill(
        org_id="org-tools", user_id="user-plain-index", namespace="acme/meeting-notes-test-index",
    )
    state = AgentState(question="what's the weather like")
    state.raw_question = state.question

    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-plain-index", surface="chat")

    assert state.question == "what's the weather like"  # unchanged, per the test above
    index = state.metadata.get("ecosystem_skill_index")
    assert index, "ecosystem_skill_index must be set even when no slash command matched"
    assert "Tool Test" in index  # _create_installed_skill's hardcoded display_name
    assert "meeting-notes-test-index" in index


def test_apply_chat_skill_integration_ignores_a_disabled_skills_slash_command():
    result = _create_installed_skill(org_id="org-tools", user_id="user-slash3", namespace="acme/meeting-notes-test3", instructions="SHOULD-NOT-APPEAR")
    install = installs_service.get_install_for_caller(result["item_id"], "org-tools", "user-slash3")
    installs_service.set_enabled(install.id, False, caller_org_id="org-tools", caller_user_id="user-slash3", caller_permissions=set())

    state = AgentState(question="/meeting-notes-test3 anything")
    state.raw_question = state.question
    apply_chat_skill_integration(state, org_id="org-tools", user_id="user-slash3", surface="chat")

    assert state.question == "/meeting-notes-test3 anything"
    assert "SHOULD-NOT-APPEAR" not in state.question


def test_apply_chat_skill_integration_logs_resolution_and_injection_without_leaking_content():
    # Item 7 (usage proof): structured, content-free logging -- resolved
    # name/version/surface and an injected-as-user-message confirmation,
    # but the real skill body/marker text must NEVER appear in a log line.
    # core.logger.logger is a structlog logger, not a plain stdlib one, so
    # patch it directly rather than relying on caplog's stdlib-only capture
    # (no existing convention for this in the test suite to follow).
    secret_marker = "UNIQUE-SKILL-BODY-LOGGING-TEST-99"
    result = _create_installed_skill(
        org_id="org-tools", user_id="user-log-test", namespace="acme/log-test-skill",
        instructions=f"{secret_marker}: do the confidential thing.",
    )
    state = AgentState(question="/log-test-skill go")
    state.raw_question = state.question

    with patch("core.logger.logger.info") as mock_info:
        apply_chat_skill_integration(state, org_id="org-tools", user_id="user-log-test", surface="chat")

    all_log_text = " ".join(str(call.args[0]) if call.args else "" for call in mock_info.call_args_list)
    assert "ECOSYSTEM_SKILL_RESOLVED" in all_log_text
    assert "ECOSYSTEM_SKILL_INJECTED_AS_USER_MESSAGE" in all_log_text
    assert "acme/log-test-skill" in all_log_text
    assert secret_marker not in all_log_text
    assert "confidential" not in all_log_text
    # The real proof this worked at all -- the body DID land in the question,
    # just never in a log line.
    assert secret_marker in state.question


def test_skill_view_logs_resolution_without_leaking_the_returned_body():
    result = _create_installed_skill(
        org_id="org-tools", user_id="user-log-test2", namespace="acme/log-test-skill2",
        instructions="TOP-SECRET-BODY-MARKER: never log this.",
    )
    with patch("core.logger.logger.info") as mock_info:
        body = skill_view("acme/log-test-skill2", org_id="org-tools", user_id="user-log-test2", surface="chat")

    assert "TOP-SECRET-BODY-MARKER" in body  # sanity: the real call still returns real content
    all_log_text = " ".join(str(call.args[0]) if call.args else "" for call in mock_info.call_args_list)
    assert "ECOSYSTEM_SKILL_VIEW" in all_log_text
    assert "acme/log-test-skill2" in all_log_text
    assert "TOP-SECRET-BODY-MARKER" not in all_log_text


# ---------------------------------------------------------------------------
# matches_installed_skill_slash_command -- the real membership check used to
# scope the CIL-gate bypass and the PIPELINE_V2 fast-path skill injection in
# gateway.py's ask_ai(). Must fail closed to False for anything that is not
# a currently installed+enabled skill's slash command for this exact
# org/user/surface -- that is the whole safety property being tested here:
# any other slash command or plain message must go through the CIL gate
# exactly as before.
# ---------------------------------------------------------------------------

def test_matches_installed_skill_slash_command_true_for_a_real_installed_enabled_skill():
    _create_installed_skill(org_id="org-tools", user_id="user-match1", namespace="acme/match-test-1")
    assert matches_installed_skill_slash_command(
        "/match-test-1 do the thing please", org_id="org-tools", user_id="user-match1", surface="chat",
    ) is True


def test_matches_installed_skill_slash_command_false_for_a_plain_non_slash_message():
    _create_installed_skill(org_id="org-tools", user_id="user-match2", namespace="acme/match-test-2")
    assert matches_installed_skill_slash_command(
        "can you help me with something", org_id="org-tools", user_id="user-match2", surface="chat",
    ) is False


def test_matches_installed_skill_slash_command_false_for_a_slash_token_that_is_not_any_installed_skill():
    # The core safety property: a slash-shaped message that does NOT
    # resolve to a real installed skill must go through the CIL gate
    # exactly as before -- e.g. a saved-prompt-style command the user typed
    # by hand, or a typo'd skill name.
    _create_installed_skill(org_id="org-tools", user_id="user-match3", namespace="acme/match-test-3")
    assert matches_installed_skill_slash_command(
        "/not-a-real-skill do something", org_id="org-tools", user_id="user-match3", surface="chat",
    ) is False


def test_matches_installed_skill_slash_command_false_for_a_disabled_install():
    result = _create_installed_skill(org_id="org-tools", user_id="user-match4", namespace="acme/match-test-4")
    install = installs_service.get_install_for_caller(result["item_id"], "org-tools", "user-match4")
    installs_service.set_enabled(install.id, False, caller_org_id="org-tools", caller_user_id="user-match4", caller_permissions=set())
    assert matches_installed_skill_slash_command(
        "/match-test-4 anything", org_id="org-tools", user_id="user-match4", surface="chat",
    ) is False


def test_matches_installed_skill_slash_command_false_for_the_wrong_surface():
    _create_installed_skill(org_id="org-tools", user_id="user-match5", namespace="acme/match-test-5", surfaces=["chat"])
    assert matches_installed_skill_slash_command(
        "/match-test-5 anything", org_id="org-tools", user_id="user-match5", surface="agent_studio",
    ) is False


def test_matches_installed_skill_slash_command_false_for_a_different_users_installed_skill():
    # Cross-user isolation: user-match6b must not be able to bypass the CIL
    # gate using a slash command that only user-match6a has installed.
    _create_installed_skill(org_id="org-tools", user_id="user-match6a", namespace="acme/match-test-6")
    assert matches_installed_skill_slash_command(
        "/match-test-6 anything", org_id="org-tools", user_id="user-match6b", surface="chat",
    ) is False


def test_matches_installed_skill_slash_command_false_for_empty_or_whitespace_input():
    assert matches_installed_skill_slash_command("", org_id="org-tools", user_id="user-match7", surface="chat") is False
    assert matches_installed_skill_slash_command("   ", org_id="org-tools", user_id="user-match7", surface="chat") is False


# ---------------------------------------------------------------------------
# matches_attached_skill() -- real live bug, 2026-09-29: once the chat-input
# UI started converting a typed "/name" into a chip and stripping the
# literal "/name " text from what's actually sent, matches_installed_skill_
# slash_command()'s raw-text regex could never match again for that flow,
# so gateway.py's CIL ambiguity gate saw only the user's own short task text
# with no skill signal at all and fired "I'm not sure what you'd like me to
# do" before apply_chat_skill_integration() ever ran, for EVERY chip-based
# invocation with an ambiguous-looking task ("explain this skill", "dd").
# This is the other half of the signal the CIL gate needs -- same fail-
# closed-to-False safety property as the slash-command version above.
# ---------------------------------------------------------------------------

def test_matches_attached_skill_true_for_a_real_installed_enabled_skill():
    _create_installed_skill(org_id="org-tools", user_id="user-attach1", namespace="acme/attach-test-1")
    assert matches_attached_skill("acme/attach-test-1", org_id="org-tools", user_id="user-attach1", surface="chat") is True


def test_matches_attached_skill_false_for_none_or_empty():
    assert matches_attached_skill(None, org_id="org-tools", user_id="user-attach2", surface="chat") is False
    assert matches_attached_skill("", org_id="org-tools", user_id="user-attach2", surface="chat") is False


def test_matches_attached_skill_false_for_a_namespace_that_is_not_any_installed_skill():
    _create_installed_skill(org_id="org-tools", user_id="user-attach3", namespace="acme/attach-test-3")
    assert matches_attached_skill("acme/not-installed", org_id="org-tools", user_id="user-attach3", surface="chat") is False


def test_matches_attached_skill_false_for_a_disabled_install():
    result = _create_installed_skill(org_id="org-tools", user_id="user-attach4", namespace="acme/attach-test-4")
    install = installs_service.get_install_for_caller(result["item_id"], "org-tools", "user-attach4")
    installs_service.set_enabled(install.id, False, caller_org_id="org-tools", caller_user_id="user-attach4", caller_permissions=set())
    assert matches_attached_skill("acme/attach-test-4", org_id="org-tools", user_id="user-attach4", surface="chat") is False


def test_matches_attached_skill_false_for_a_different_users_installed_skill():
    _create_installed_skill(org_id="org-tools", user_id="user-attach5a", namespace="acme/attach-test-5")
    assert matches_attached_skill("acme/attach-test-5", org_id="org-tools", user_id="user-attach5b", surface="chat") is False
