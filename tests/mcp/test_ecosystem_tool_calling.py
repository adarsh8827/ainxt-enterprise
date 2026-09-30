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


def _connector_row(namespace: str, tool_name: str, *, destructive: bool = False, read_only: bool = False):
    fake_manifest = {"tools": [{"name": tool_name, "annotations": {"readOnlyHint": read_only, "destructiveHint": destructive}}]}
    fake_item = MagicMock(namespace=namespace)
    return (MagicMock(), fake_item, fake_manifest)


def _router_returning(*call_sequences):
    """Builds a MockRouter whose fake Claude gateway's _last_tool_calls
    changes across successive generate() calls, one entry per loop round.
    Each element of call_sequences is either a list[dict] (tool calls) or
    [] (model is done)."""
    fake_claude = MagicMock()
    state = {"i": 0}

    def _generate(*_a, **_k):
        idx = min(state["i"], len(call_sequences) - 1)
        fake_claude._last_tool_calls = call_sequences[idx]
        state["i"] += 1

    instance = MagicMock()
    instance._get_claude.return_value = fake_claude
    instance._get_openai.return_value = None
    instance.generate.side_effect = _generate
    return instance


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
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter") as MockRouter:
        instance = MockRouter.return_value
        instance._get_claude.return_value = MagicMock(_last_tool_calls=[])
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")
    # Only skill_view/read_skill_file are always offered -- the model is
    # still asked (schemas is never empty), but the fake router below
    # returns no tool calls, so state must be untouched.
    assert state.question == "hello"


def test_read_tool_executes_immediately_and_result_is_folded_in():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("what does my skill say?")
    router = _router_returning([{"id": "1", "name": "skill_view", "input": {"name": "acme/exec"}}], [])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="Do the thing carefully.") as mock_view:
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_view.assert_called_once_with("acme/exec", org_id="org-a", user_id="u1", surface="chat")
    assert "Do the thing carefully." in state.question
    assert "ecosystem_tool_call_pending" not in state.metadata


def test_write_tool_never_executes_inline_and_creates_a_pending_approval():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("send a slack message")
    fake_row = _connector_row("acme/slack", "slack_post_message")
    router = _router_returning([{"id": "1", "name": "slack_post_message", "input": {"channel": "#eng"}}])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool") as mock_execute:
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

    state = _State("delete my repo")
    fake_row = _connector_row("acme/git", "delete_repo", destructive=True)
    router = _router_returning([{"id": "1", "name": "delete_repo", "input": {}}])

    org_id = f"org-{uuid.uuid4().hex[:8]}"
    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router):
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
    fake_row = _connector_row("acme/slack", "slack_post_message")
    router = _router_returning(
        [{"id": "1", "name": "slack_post_message", "input": {"channel": "#eng"}}], [],
    )

    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool", return_value="posted") as mock_execute:
        apply_chat_tool_calling(state, org_id=f"org-{uuid.uuid4().hex[:8]}", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_called_once()
    assert "ecosystem_tool_call_pending" not in state.metadata
    assert "posted" in state.question
    assert state.metadata.get("ecosystem_tool_call_used_connector", {}).get("name") == "slack_post_message"


def test_resume_delivers_an_approved_result_and_marks_it_delivered():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    resolved = {
        "approval_id": "a1", "status": "approved", "tool_name": "skill_view",
        "kind": "skill_view", "args": {"name": "acme/exec"},
    }
    state = _State("continue")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=resolved), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter") as MockRouter, \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="the real content"):
        instance = MockRouter.return_value
        instance._get_claude.return_value = MagicMock(_last_tool_calls=[])
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    assert "the real content" in state.question
    assert "ecosystem_tool_call_pending" not in state.metadata


def test_resume_delivers_a_denial_without_executing_anything():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    resolved = {"approval_id": "a1", "status": "denied", "tool_name": "delete_repo", "kind": "mcp", "args": {}}
    state = _State("continue")
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=resolved), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter") as MockRouter, \
         patch("mcp.registry.mcp_registry.execute_tool") as mock_execute:
        instance = MockRouter.return_value
        instance._get_claude.return_value = MagicMock(_last_tool_calls=[])
        instance._get_openai.return_value = None
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_not_called()
    assert "denied" in state.question


def test_resume_continues_the_loop_with_a_further_read_call_same_turn():
    """Item 2/3: resume isn't just a single delivery -- the loop keeps
    going afterward, so a resumed write action can be followed by a real
    read call in the same turn."""
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    resolved = {"approval_id": "a1", "status": "approved", "tool_name": "delete_repo", "kind": "mcp", "args": {}}
    state = _State("continue")
    router = _router_returning([{"id": "2", "name": "skill_view", "input": {"name": "acme/exec"}}], [])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=resolved), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool", return_value="deleted") as mock_execute, \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="the skill body") as mock_view:
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_called_once()
    mock_view.assert_called_once()
    assert "deleted" in state.question
    assert "the skill body" in state.question


def test_multi_step_loop_runs_several_read_rounds_in_one_turn():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("look at two things")
    router = _router_returning(
        [{"id": "1", "name": "skill_view", "input": {"name": "a/one"}}],
        [{"id": "2", "name": "skill_view", "input": {"name": "a/two"}}],
        [],
    )
    calls = []

    def _fake_skill_view(name, **kw):
        calls.append(name)
        return f"body of {name}"

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.ecosystem_skill_tools.skill_view", side_effect=_fake_skill_view):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    assert calls == ["a/one", "a/two"]
    assert "body of a/one" in state.question
    assert "body of a/two" in state.question


def test_max_calls_limit_stops_cleanly_with_a_summary():
    from mcp.ecosystem_tool_calling import _MAX_CALLS, apply_chat_tool_calling

    state = _State("keep looking things up")
    # Always offers another read tool call -- would loop forever without
    # the _MAX_CALLS cap.
    router = _router_returning([{"id": "1", "name": "skill_view", "input": {"name": "a/x"}}])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="x"):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    assert f"after {_MAX_CALLS} tool call" in state.question
    assert "tool-call limit" in state.question


def test_time_budget_limit_stops_cleanly_with_a_summary(monkeypatch):
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("keep looking things up")
    router = _router_returning([{"id": "1", "name": "skill_view", "input": {"name": "a/x"}}])

    # Mocked clock: call #1 is `start`; call #2 (round 1's elapsed check)
    # is still under budget, so round 1 executes for real; call #3 (round
    # 2's elapsed check) is over budget -- the loop must stop there, having
    # made exactly one real tool call.
    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type", return_value=[]), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="x"), \
         patch("mcp.ecosystem_tool_calling.time.monotonic", side_effect=[0.0, 5.0, 30.0]):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    assert "time budget" in state.question
    assert "after 1 tool call" in state.question


def test_max_write_actions_limit_stops_cleanly_even_with_calls_remaining():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("do several destructive things")
    fake_row = _connector_row("acme/git", "delete_repo", destructive=True)
    router = _router_returning([{"id": "1", "name": "delete_repo", "input": {}}])

    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router):
        apply_chat_tool_calling(state, org_id=f"org-{uuid.uuid4().hex[:8]}", user_id="u1", surface="chat", chat_id="chat-1")

    # destructive is never auto-approved (Stage 5 gate) -- so the FIRST
    # destructive call always parks a pending approval and the loop stops
    # there, never reaching the write-action cap in this exact scenario.
    # This test's real point (see the next one) is the cap applying when
    # write actions ARE cleared to run without stopping for approval.
    assert state.metadata.get("ecosystem_tool_call_pending") is not None


def test_max_write_actions_limit_stops_cleanly_for_auto_approved_writes():
    from mcp.ecosystem_tool_calling import _MAX_WRITE_ACTIONS, apply_chat_tool_calling

    state = _State("post several times")
    fake_row = _connector_row("acme/slack", "slack_post_message")
    router = _router_returning([{"id": "1", "name": "slack_post_message", "input": {}}])

    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool", return_value="posted"):
        apply_chat_tool_calling(state, org_id=f"org-{uuid.uuid4().hex[:8]}", user_id="u1", surface="chat", chat_id="chat-1")

    assert f"after {_MAX_WRITE_ACTIONS} tool call" in state.question
    assert "write-action limit" in state.question


def test_destructive_call_on_a_later_round_is_still_gated_not_just_round_one():
    """A destructive call on round 3 of the loop must be just as gated as
    one on round 1 -- no round-number-based bypass anywhere in the loop."""
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("look something up then delete it")
    fake_row = _connector_row("acme/git", "delete_repo", destructive=True)
    router = _router_returning(
        [{"id": "1", "name": "skill_view", "input": {"name": "a/x"}}],
        [{"id": "2", "name": "skill_view", "input": {"name": "a/y"}}],
        [{"id": "3", "name": "delete_repo", "input": {}}],
    )

    with patch("services.ecosystem.tool_approval_service._is_auto_approved", return_value=True), \
         patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.ecosystem_skill_tools.skill_view", return_value="ok"):
        apply_chat_tool_calling(state, org_id=f"org-{uuid.uuid4().hex[:8]}", user_id="u1", surface="chat", chat_id="chat-1")

    pending = state.metadata.get("ecosystem_tool_call_pending")
    assert pending is not None
    assert pending["classification"] == "destructive"
    assert pending["tool_name"] == "delete_repo"


def test_unconnected_connector_tool_surfaces_connect_prompt_and_never_executes():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("post to slack for me")
    fake_row = _connector_row("acme/slack", "slack_post_message")
    router = _router_returning([{"id": "1", "name": "slack_post_message", "input": {}}])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=False), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool") as mock_execute:
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    mock_execute.assert_not_called()
    prompt = state.metadata.get("ecosystem_connect_prompt")
    assert prompt is not None
    assert prompt["connector_ref"] == "acme/slack"
    assert prompt["tool_name"] == "slack_post_message"
    assert "ecosystem_tool_call_pending" not in state.metadata


def test_connected_connector_read_tool_sets_used_connector_marker():
    from mcp.ecosystem_tool_calling import apply_chat_tool_calling

    state = _State("check my slack")
    fake_row = _connector_row("acme/slack", "slack_read_channel", read_only=True)
    router = _router_returning([{"id": "1", "name": "slack_read_channel", "input": {}}], [])

    with patch("mcp.ecosystem_tool_calling._find_resolved_undelivered", return_value=None), \
         patch("mcp.ecosystem_tool_calling._is_connected", return_value=True), \
         patch("services.ecosystem.resolver_service._get_installed_items_by_type",
               side_effect=lambda org, user, surface, item_type: [fake_row] if item_type == "connector" else []), \
         patch("models.model_router.ModelRouter", return_value=router), \
         patch("mcp.registry.mcp_registry.execute_tool", return_value="hello there"):
        apply_chat_tool_calling(state, org_id="org-a", user_id="u1", surface="chat", chat_id="chat-1")

    used = state.metadata.get("ecosystem_connect_prompt")
    assert used is None
    marker = state.metadata.get("ecosystem_tool_call_used_connector")
    assert marker is not None
    assert marker["name"] == "slack_read_channel"
    assert marker["target"] == "acme/slack"
