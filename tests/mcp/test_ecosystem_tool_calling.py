# SPDX-License-Identifier: MIT
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


class _State:
    def __init__(self, question: str):
        self.question = question
        self.metadata: dict = {}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr("core.config.ECOSYSTEM_TOOL_CALLING", True)
    yield


def test_flag_off_is_a_real_no_op(monkeypatch):
    monkeypatch.setattr("core.config.ECOSYSTEM_TOOL_CALLING", False)
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("hello")
    with patch("models.model_router.ModelRouter") as MockRouter:
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")
        MockRouter.assert_not_called()
    assert state.question == "hello"
    assert state.metadata == {}


def test_never_raises_on_internal_error(monkeypatch):
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("hello")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", side_effect=RuntimeError("boom")):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")
    assert state.question == "hello"  # untouched -- the exception was swallowed, not propagated


def test_no_tools_available_is_a_no_op():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("hello")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")
    # Only skill_view/read_skill_file are always offered -- the model is
    # still asked (schemas is never empty), but the fake router below
    # returns no tool calls, so state must be untouched.
    assert state.question == "hello"


def test_read_tool_executes_immediately_and_result_is_folded_in():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("what does my skill say?")
    fake_claude = MagicMock()
    fake_claude._last_tool_calls = [{"id": "1", "name": "skill_view", "input": {"name": "acme/exec"}}]

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter") as MockRouter, \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="Do the thing carefully.") as mock_view:
        instance = MockRouter.return_value
        instance._get_claude.return_value = fake_claude
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_view.assert_called_once_with("acme/exec", org_id="org-a", user_id="u1", surface="chat")
    assert "Do the thing carefully." in state.question
    assert "ecosystem_tool_call_pending" not in state.metadata


def test_write_tool_never_executes_inline_and_creates_a_pending_approval():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("send a slack message")
    fake_claude = MagicMock()
    fake_claude._last_tool_calls = [{"id": "1", "name": "slack_post_message", "input": {"channel": "#eng"}}]

    fake_manifest = {"tools": [{"name": "slack_post_message", "annotations": {"readOnlyHint": False, "destructiveHint": False}}]}
    fake_item = MagicMock(namespace="acme/slack")
    fake_row = (MagicMock(), fake_item, fake_manifest)

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter") as MockRouter, \
         patch("mcp.registry.mcp_registry.execute_tool") as mock_execute:
        instance = MockRouter.return_value
        instance._get_claude.return_value = fake_claude
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_not_called()  # never executed inline
    pending = state.metadata.get("ecosystem_tool_call_pending")
    assert pending is not None
    assert pending["tool_name"] == "slack_post_message"
    assert pending["classification"] == "write"
    assert "waiting on their approval" in state.question


def test_destructive_tool_still_creates_pending_even_with_auto_approve_policy():
    """Regression for the Stage 5 fix (tool_approval_service's
    write-only auto-approve gate) -- this NEW call site must not
    reintroduce a bypass by, say, pre-filtering destructive tools out
    before request_tool_call() ever sees them."""
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling
    from services.ecosystem import tool_approval_service

    state = _State("delete my repo")
    fake_claude = MagicMock()
    fake_claude._last_tool_calls = [{"id": "1", "name": "delete_repo", "input": {}}]
    fake_manifest = {"tools": [{"name": "delete_repo", "annotations": {"destructiveHint": True}}]}
    fake_item = MagicMock(namespace="acme/git")
    fake_row = (MagicMock(), fake_item, fake_manifest)

    org_id = f"org-{uuid.uuid4().hex[:8]}"
    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter") as MockRouter:
        instance = MockRouter.return_value
        instance._get_claude.return_value = fake_claude
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id=org_id, user_id="u1", surface="chat", chat_id="chat-1")

    pending = state.metadata.get("ecosystem_tool_call_pending")
    assert pending is not None
    assert pending["classification"] == "destructive"


def test_auto_approved_write_tool_actually_executes_not_silently_dropped():
    """Regression: request_tool_call() returns requires_approval=False for
    BOTH the read case and the auto_approved case -- a naive `if
    decision.get("requires_approval")` treats "no approval needed" and "no
    action needed" as the same thing, silently dropping an auto-approved
    write tool call instead of running it. This must actually execute."""
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("post to slack")
    fake_claude = MagicMock()
    fake_claude._last_tool_calls = [{"id": "1", "name": "slack_post_message", "input": {"channel": "#eng"}}]
    fake_manifest = {"tools": [{"name": "slack_post_message", "annotations": {"readOnlyHint": False, "destructiveHint": False}}]}
    fake_item = MagicMock(namespace="acme/slack")
    fake_row = (MagicMock(), fake_item, fake_manifest)

    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter") as MockRouter, \
         patch("mcp.registry.mcp_registry.execute_tool", return_value="posted") as mock_execute:
        instance = MockRouter.return_value
        instance._get_claude.return_value = fake_claude
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id=f"org-{uuid.uuid4().hex[:8]}", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_called_once()
    assert "ecosystem_tool_call_pending" not in state.metadata
    assert "posted" in state.question


def test_resume_delivers_an_approved_result_and_marks_it_delivered():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    resolved = {
        "approval_id": "a1", "status": "approved", "tool_name": "skill_view",
        "kind": "skill_view", "args": {"name": "acme/exec"},
    }
    state = _State("continue")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=resolved), \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="the real content"):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    assert "the real content" in state.question
    assert "ecosystem_tool_call_pending" not in state.metadata


def test_resume_delivers_a_denial_without_executing_anything():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    resolved = {"approval_id": "a1", "status": "denied", "tool_name": "delete_repo", "kind": "mcp", "args": {}}
    state = _State("continue")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=resolved), \
         patch("mcp.registry.mcp_registry.execute_tool") as mock_execute:
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_not_called()
    assert "denied" in state.question
