# SPDX-License-Identifier: MIT
# ============================================================
# services/ecosystem/compatibility.py -- the chat-vs-tool-dependent
# heuristic classifier and its default-surfaces/enforcement helpers.
# Pure functions, no DB/network -- no fixtures needed.
# ============================================================

from __future__ import annotations

from services.ecosystem.compatibility import (
    CHAT, TOOL_DEPENDENT, classify_compatibility, default_surfaces_for, enforce_compatibility_on_surfaces,
)


def test_plain_guidance_text_classifies_as_chat():
    text = "Review the diff for correctness, style, and test coverage. Summarize findings by severity."
    assert classify_compatibility(text) == CHAT


def test_shell_fenced_code_block_classifies_as_tool_dependent():
    text = "Run this to check formatting:\n```bash\nruff check .\n```\n"
    assert classify_compatibility(text) == TOOL_DEPENDENT


def test_git_command_mention_classifies_as_tool_dependent():
    text = "Use `git commit` to create small, focused commits as you go."
    assert classify_compatibility(text) == TOOL_DEPENDENT


def test_file_edit_imperative_classifies_as_tool_dependent():
    text = "Create a file named CONSTRAINTS.md and record every threshold the user names."
    assert classify_compatibility(text) == TOOL_DEPENDENT


def test_cli_install_instruction_classifies_as_tool_dependent():
    text = "Install the CLI first: `npm install -g @acme/tool`, then configure your token."
    assert classify_compatibility(text) == TOOL_DEPENDENT


def test_empty_or_none_instructions_classify_as_chat():
    assert classify_compatibility("") == CHAT
    assert classify_compatibility(None) == CHAT


def test_mentioning_terminal_as_a_concept_still_counts_as_tool_dependent():
    # Deliberately permissive heuristic -- even a passing mention is
    # enough to flag for review rather than silently under-flagging.
    text = "If the error only reproduces in a terminal session, capture the exact output."
    assert classify_compatibility(text) == TOOL_DEPENDENT


def test_default_surfaces_for_chat_is_all_surfaces():
    assert default_surfaces_for(CHAT) == ["chat", "cowork", "desktop", "agent_studio"]


def test_default_surfaces_for_tool_dependent_excludes_chat():
    surfaces = default_surfaces_for(TOOL_DEPENDENT)
    assert "chat" not in surfaces
    assert "cowork" in surfaces
    assert "desktop" in surfaces


def test_default_surfaces_for_tool_dependent_with_tools_includes_agent_studio():
    surfaces = default_surfaces_for(TOOL_DEPENDENT, has_tools=True)
    assert "agent_studio" in surfaces
    assert "chat" not in surfaces


def test_enforce_strips_chat_from_an_explicit_tool_dependent_surface_list():
    result = enforce_compatibility_on_surfaces(TOOL_DEPENDENT, ["chat", "cowork", "desktop"])
    assert result == ["cowork", "desktop"]


def test_enforce_leaves_a_chat_compatible_surface_list_untouched():
    result = enforce_compatibility_on_surfaces(CHAT, ["chat"])
    assert result == ["chat"]
