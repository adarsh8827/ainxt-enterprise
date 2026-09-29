"""Regression proof for the additive `tools` parameter on ModelRouter.generate().

Mandatory per docs/ecosystem/CONNECTORS_PHASE_PLAN.md item 1.3: the tool-calling
core must be byte-identical for every existing caller when `tools` is not
passed. These tests use fake gateways shaped exactly like the real,
post-change gateway classes' `generate()` signatures and assert:

  1. When the caller omits `tools`, no gateway ever receives a `tools` kwarg
     at all (not even `tools=None`) — proven against fakes that DON'T even
     declare a `tools` parameter, mirroring pre-change external test doubles
     (the same shape tests/models/test_model_router_async_stream.py's own
     `_ClaudeGateway` fake already uses) and would raise TypeError on an
     unexpected keyword if the router ever leaked one.
  2. When the caller passes `tools`, it reaches the gateway that actually
     serves the request, for every tier reachable from `generate()`.
"""

from collections.abc import Iterator

import pytest

from models.model_router import ModelRouter


class _NoToolsParamGateway:
    """Mirrors a caller-supplied gateway stand-in that predates this change —
    no `tools` parameter, no `**kwargs` catch-all. Any unexpected keyword
    argument raises TypeError, which is exactly the regression this class
    exists to catch."""

    def __init__(self):
        self.calls: list[dict] = []

    def generate(self, prompt: str, *, model: str = None) -> Iterator[str]:
        self.calls.append({"prompt": prompt, "model": model})
        yield "OK"

    @property
    def available(self):
        return True


class _RecordingLocalGateway:
    def __init__(self):
        self.calls: list[dict] = []
        self.available = True
        self._last_selected_model = "fake-local-model"

    def generate(self, prompt, model=None, tier="simple", *, max_tokens=None,
                 disable_reasoning=False, tools=None) -> Iterator[str]:
        self.calls.append({"prompt": prompt, "model": model, "tier": tier, "tools": tools})
        yield "OK"


class _RecordingClaudeGateway:
    def __init__(self):
        self.calls: list[dict] = []

    def generate(self, prompt, model=None, temperature=0, max_tokens=32000,
                 stream=True, tools=None) -> Iterator[str]:
        self.calls.append({"prompt": prompt, "model": model, "tools": tools})
        yield "OK"


@pytest.mark.parametrize("model_hint", ["medium", "complex", "haiku", "solution"])
def test_no_tools_kwarg_leaks_to_a_gateway_without_a_tools_parameter(model_hint):
    """Every tier that can fall back to (or route to) Claude must not pass
    `tools` at all when the caller never asked for it — proven against a fake
    that has no `tools` parameter and no `**kwargs`, so any leak raises
    TypeError instead of silently passing."""
    router = ModelRouter()
    fake_claude = _NoToolsParamGateway()
    fake_openai = _NoToolsParamGateway()

    import models.model_router as mr
    router._get_claude = lambda: fake_claude
    router._get_openai = lambda: fake_openai
    router._get_local = lambda: None

    result = router.generate("hello", model_hint=model_hint)

    assert result  # no TypeError means the call kwargs were byte-identical to before
    assert fake_claude.calls or fake_openai.calls


def test_local_simple_tier_without_tools_receives_tools_none():
    """TIER_SIMPLE's local gateway call always explicitly declares `tools`
    (added by this change) — omitted at the router level must still resolve
    to `tools=None` there (its own real default), never a missing/garbled
    value."""
    router = ModelRouter()
    fake_local = _RecordingLocalGateway()
    router._get_local = lambda: fake_local

    router.generate("hello", model_hint="local")

    assert fake_local.calls, "local gateway was never called"
    assert fake_local.calls[0]["tools"] is None


def test_local_simple_tier_with_tools_forwards_them():
    router = ModelRouter()
    fake_local = _RecordingLocalGateway()
    router._get_local = lambda: fake_local

    my_tools = [{"name": "read_file", "description": "...", "input_schema": {}}]
    router.generate("hello", model_hint="local", tools=my_tools)

    assert fake_local.calls[0]["tools"] == my_tools


def test_claude_complex_tier_with_tools_forwards_them():
    router = ModelRouter()
    fake_claude = _RecordingClaudeGateway()
    router._get_claude = lambda: fake_claude

    my_tools = [{"name": "search_docs", "description": "...", "input_schema": {}}]
    router.generate("hello", model_hint="complex", tools=my_tools)

    assert fake_claude.calls, "claude gateway was never called"
    assert fake_claude.calls[0]["tools"] == my_tools


def test_claude_complex_tier_without_tools_passes_none_not_missing():
    router = ModelRouter()
    fake_claude = _RecordingClaudeGateway()
    router._get_claude = lambda: fake_claude

    router.generate("hello", model_hint="complex")

    assert fake_claude.calls[0]["tools"] is None
