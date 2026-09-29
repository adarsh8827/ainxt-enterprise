# SPDX-License-Identifier: MIT
# ============================================================
# GENERIC OPENAI-COMPATIBLE GATEWAY
#
# Lightweight OpenAI-compatible client for admin-configured "openai_compatible"
# LLM providers (OpenRouter, Together, Groq, or any other custom
# chat-completions-API-shaped provider added via the "LLM Providers" admin
# screen — see core/llm_provider_registry.py).
#
# Unlike gateway_claude.py / gateway_openai.py / gateway_local_llm.py, this is
# NOT a process-wide singleton bound to module-level env-var constants — an
# admin can configure several distinct openai_compatible providers with
# different base_url/api_key pairs, so one instance is built per call from
# core.llm_provider_registry.get_client_for(model_id) (see
# models/model_router.py's TIER_REGISTRY dispatch branch, the only caller).
#
# Deliberately has NO cross-vendor fallback chain, unlike the built-in
# gateways' _try_* methods — an explicitly admin-picked model should surface
# an error if it fails, not silently run a different vendor's model.
# ============================================================

import uuid
from typing import Optional

from openai import OpenAI

from core.logger import logger, get_request_id as _get_request_id


class GenericOpenAIGateway:
    """Matches models/provider_protocol.py's shared generate(prompt, model=None,
    **kwargs) -> Generator[str, None, None] contract."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        if not base_url:
            raise ValueError("GenericOpenAIGateway requires a base_url")
        self.base_url = base_url.rstrip("/")
        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "not-needed")
        self._last_input_tokens = 0
        self._last_output_tokens = 0

    def generate(self, prompt, model: Optional[str] = None, tools: Optional[list] = None, **kwargs):
        """tools: optional tool-schema list in Anthropic format (input_schema
        key), matching the convention used by gateway_claude/openai/gemini —
        converted to OpenAI function-calling shape internally. Omitted/None is
        byte-identical to this parameter not existing. Any tool_calls the
        model emits are captured into self._last_tool_calls (list of
        {id, name, input}), mirroring the other gateways' side channel."""
        if not model:
            yield "Error: GenericOpenAIGateway requires an explicit model"
            return

        self._last_tool_calls: list = []

        if isinstance(prompt, list):
            messages_payload = [
                {"role": m["role"], "content": m.get("content") or ""} for m in prompt
            ]
        else:
            messages_payload = [{"role": "user", "content": prompt}]

        self._last_input_tokens = 0
        self._last_output_tokens = 0

        upstream = _get_request_id()
        request_id = upstream if upstream and upstream != "-" else str(uuid.uuid4())
        logger.info(
            f"[LLM DISPATCH] provider=openai_compatible base_url={self.base_url} "
            f"model={model} request_id={request_id}"
        )

        try:
            _create_kwargs = dict(model=model, messages=messages_payload, stream=True)
            if tools:
                from gateway_openai import _anthropic_to_openai_tools
                _create_kwargs["tools"] = _anthropic_to_openai_tools(tools)
            stream = self._client.chat.completions.create(**_create_kwargs)
            response_buf = []
            _tc_accum: dict = {}
            for chunk in stream:
                if chunk.choices:
                    _delta = chunk.choices[0].delta
                    _tool_call_deltas = getattr(_delta, "tool_calls", None)
                    if _tool_call_deltas:
                        for _tcd in _tool_call_deltas:
                            _idx = _tcd.index
                            _slot = _tc_accum.setdefault(_idx, {"id": None, "name": None, "arguments": ""})
                            if getattr(_tcd, "id", None):
                                _slot["id"] = _tcd.id
                            _fn = getattr(_tcd, "function", None)
                            if _fn is not None:
                                if getattr(_fn, "name", None):
                                    _slot["name"] = _fn.name
                                if getattr(_fn, "arguments", None):
                                    _slot["arguments"] += _fn.arguments
                    _finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                    if _finish_reason == "tool_calls" and _tc_accum:
                        import json as _json
                        for _slot in _tc_accum.values():
                            try:
                                _parsed_input = _json.loads(_slot["arguments"]) if _slot["arguments"] else {}
                            except Exception:
                                _parsed_input = {}
                            self._last_tool_calls.append({
                                "id": _slot["id"], "name": _slot["name"], "input": _parsed_input,
                            })
                        _tc_accum = {}
                    piece = getattr(_delta, "content", None)
                    if piece:
                        response_buf.append(piece)
                        yield piece
                usage = getattr(chunk, "usage", None)
                if usage:
                    self._last_input_tokens = usage.prompt_tokens or 0
                    self._last_output_tokens = usage.completion_tokens or 0

            full_response = "".join(response_buf)
            logger.info(
                f"[OPENAI-COMPAT USAGE] request_id={request_id} base_url={self.base_url} "
                f"model={model} in={self._last_input_tokens} out={self._last_output_tokens} "
                f"response_chars={len(full_response)}"
            )
        except Exception as e:
            logger.error(
                f"[OPENAI-COMPAT ERROR] request_id={request_id} base_url={self.base_url} "
                f"model={model}: {e}"
            )
            yield f"Error: {model} call failed ({e})"


def get_generic_gateway(base_url: str, api_key: Optional[str] = None) -> GenericOpenAIGateway:
    """Factory — intentionally no process-wide caching (unlike
    gateway_local_llm.get_local_gateway()): different registry providers have
    different base_url/api_key pairs, so ModelRouter's TIER_REGISTRY dispatch
    constructs one per call. Cheap — just an SDK client object, no network
    call until .generate() is actually invoked."""
    return GenericOpenAIGateway(base_url=base_url, api_key=api_key)
