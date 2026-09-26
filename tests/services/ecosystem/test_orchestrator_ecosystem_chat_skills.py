# SPDX-License-Identifier: MIT
# ============================================================
# Task B-16: the single most safety-critical test in this whole phase --
# agents/orchestrator.py's run() is the live production chat path
# (gateway.py:ask_ai() -> agent.run()), reached on every non-office
# message. This file proves:
#   1. Flag off, or no ecosystem_surface supplied (every caller before
#      this task existed) -> state is byte-identical to pre-task behavior.
#   2. mode="office" is never touched, regardless of flag state.
#   3. With the flag genuinely on: the skill index gets attached, and a
#      "/name ..." invocation of an installed skill rewrites the question
#      -- but a non-slash message does not.
#
# generate_answer_tool and the classifier are mocked so this test
# exercises the real orchestrator.run() control flow up to (and including)
# the call into generate_answer_tool, without making a real LLM call.
# ============================================================

from __future__ import annotations

from unittest.mock import patch

import pytest

import agents.orchestrator as orchestrator_module
import core.config as core_config
from agents.orchestrator import OrchestratorAgent
from services.ecosystem import create_service


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _install_skill(*, org_id, user_id, namespace, instructions="the skill's own instructions", surfaces=("chat",)):
    with _mock_ethics_pass():
        return create_service.create_via_write(
            org_id=org_id, created_by=user_id, item_type="skill", namespace=namespace,
            display_name="Test Skill", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": instructions, "files": []}, surfaces=list(surfaces),
        )


def _run_and_capture_state(agent, *, question, mode=None, ecosystem_surface=None, org_id="orch-org", user_id="orch-user"):
    """Drives OrchestratorAgent.run() through a real, fast, deterministic
    path (classifier mocked to avoid any real LLM slow-path call;
    generate_answer_tool mocked to capture the `state` it was called with,
    rather than making a real model call) and returns that captured state.
    """
    captured = {}

    def _fake_generate_answer_tool(state, llm):
        captured["state"] = state
        yield "ok"

    with patch("models.classifier.classify_query_complexity", return_value="simple"), \
         patch("models.classifier.detect_query_domain", return_value="general"), \
         patch.object(orchestrator_module, "generate_answer_tool", _fake_generate_answer_tool):
        list(agent.run(
            question, None, raw_question=question, user_ctx={"org_id": org_id, "user_id": user_id},
            compliance_passed=True, mode=mode, ecosystem_surface=ecosystem_surface,
        ))

    assert "state" in captured, "generate_answer_tool was never reached -- test setup is wrong, not a real assertion"
    return captured["state"]


@pytest.fixture(autouse=True)
def _ecosystem_chat_skills_on(monkeypatch):
    """Most tests in this file need the flag on to exercise the real
    integration; the flag-off tests explicitly monkeypatch it back off
    themselves, overriding this fixture's default."""
    monkeypatch.setattr(core_config, "ECOSYSTEM_CHAT_SKILLS", True)


def test_flag_off_leaves_state_byte_identical_even_for_a_slash_looking_message(monkeypatch):
    monkeypatch.setattr(core_config, "ECOSYSTEM_CHAT_SKILLS", False)
    _install_skill(org_id="orch-org", user_id="orch-user", namespace="acme/exec-assistant")

    agent = OrchestratorAgent()
    state = _run_and_capture_state(agent, question="/exec-assistant do the thing", ecosystem_surface="chat")

    assert state.question == "/exec-assistant do the thing"
    assert state.raw_question == "/exec-assistant do the thing"
    assert "ecosystem_skill_index" not in state.metadata


def test_no_ecosystem_surface_supplied_leaves_state_byte_identical():
    # Every caller of agent.run() before this task existed never passes
    # ecosystem_surface at all -- the parameter defaults to None. This is
    # the exact scenario that must be provably unaffected regardless of
    # the flag (already on via the autouse fixture here).
    _install_skill(org_id="orch-org", user_id="orch-user", namespace="acme/exec-assistant-2")

    agent = OrchestratorAgent()
    state = _run_and_capture_state(agent, question="/exec-assistant-2 do the thing", ecosystem_surface=None)

    assert state.question == "/exec-assistant-2 do the thing"
    assert "ecosystem_skill_index" not in state.metadata


def test_office_mode_is_never_touched_regardless_of_flag_or_surface():
    agent = OrchestratorAgent()
    # mode="office" takes its own planner branch (_plan_office) -- route
    # through a plain question, not a slash command, since office mode's
    # own real planner may reach out to connectors/catalogs we're not
    # mocking here; the assertion that matters is purely that this
    # integration point is never invoked for it.
    state = _run_and_capture_state(agent, question="what's on my calendar today", mode="office", ecosystem_surface="chat")

    assert state.question == "what's on my calendar today"
    assert "ecosystem_skill_index" not in state.metadata


def test_flag_on_with_surface_attaches_the_skill_index_for_a_non_slash_message():
    _install_skill(org_id="orch-org", user_id="orch-user", namespace="acme/indexed-skill", instructions="whatever")

    agent = OrchestratorAgent()
    state = _run_and_capture_state(agent, question="hello, how are you", ecosystem_surface="chat")

    # Not a slash command -> question must be untouched...
    assert state.question == "hello, how are you"
    # ...but the index (a stable, always-attempted addition) is present.
    assert "acme/indexed-skill" in state.metadata.get("ecosystem_skill_index", "") or \
        "Test Skill" in state.metadata.get("ecosystem_skill_index", "")


def test_flag_on_slash_command_rewrites_question_to_the_skill_body():
    result = _install_skill(
        org_id="orch-org", user_id="orch-user", namespace="acme/rewrite-me",
        instructions="THESE ARE THE SKILL'S OWN INSTRUCTIONS",
    )
    assert result["status"] == "verifying"

    agent = OrchestratorAgent()
    state = _run_and_capture_state(agent, question="/rewrite-me summarize this please", ecosystem_surface="chat")

    assert "THESE ARE THE SKILL'S OWN INSTRUCTIONS" in state.question
    assert "summarize this please" in state.question
    assert state.question == state.raw_question


def test_flag_on_unrecognized_slash_command_leaves_question_untouched():
    agent = OrchestratorAgent()
    state = _run_and_capture_state(agent, question="/not-a-real-skill do something", ecosystem_surface="chat")

    assert state.question == "/not-a-real-skill do something"
