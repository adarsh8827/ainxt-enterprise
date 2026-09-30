# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM CHAT TOOL-CALLING (Connectors/Plugins phase, follow-up round 2)
#
# Round 1 (still the base this file extends): a SINGLE round-trip -- one
# cheap-tier model_router.generate() call decided on at most one tool per
# turn. Round 2 (this file) adds:
#   - a real multi-step loop (several tool rounds per turn, bounded by
#     _MAX_CALLS / _TIME_BUDGET_SECONDS / _MAX_WRITE_ACTIONS)
#   - a connect-prompt leg: a connector/mcp tool the model selects but the
#     caller hasn't connected stops the loop and surfaces a marker for
#     ConnectPromptCard, instead of ever attempting the call
#   - a "used connector" marker for UsingConnectorIndicator -- POST-HOC,
#     same honest pattern pipeline.stream_events.SkillUsedMarker already
#     uses (this module is called synchronously and returns before any SSE
#     frame for this turn is emitted, so there is no real mid-call
#     "in-progress" moment to hook into; the indicator reflects "this turn
#     used connector X", shown before the answer streams, not a live
#     progress bar -- disclosed, not a shortcut hiding a gap)
#   - approval-resume now continues the SAME loop (not just a single
#     delivery) so a resumed write action can be followed by further read
#     calls before the turn ends
#
# Still NOT a full agentic loop in the agents/react_orchestrator.py sense
# (that module's generate_with_tools()-based loop is separate, older,
# untouched here, used today by repo-search). This loop is bounded, chat-
# turn-scoped, and every write/destructive call -- on round 1 or round 5 --
# goes through tool_approval_service.request_tool_call() exactly the same
# way; there is no round-number-based bypass anywhere in this file.
# ============================================================

from __future__ import annotations

import time
from typing import Any, Optional

from core.logger import logger

_SKILL_VIEW_SCHEMA = {
    "name": "skill_view",
    "description": "View the full instructions body of an installed, enabled skill by name.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The skill's namespace, e.g. acme/exec-assistant."}},
        "required": ["name"],
    },
}
_READ_SKILL_FILE_SCHEMA = {
    "name": "read_skill_file",
    "description": "Read one bundled file (by relative path) from an installed, enabled skill.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "path": {"type": "string", "description": "Relative path, e.g. references/foo.md"},
        },
        "required": ["name", "path"],
    },
}

# Bounded multi-step loop, per chat turn. Real limits, not a full agentic
# loop -- see module docstring above.
_MAX_CALLS = 5
_TIME_BUDGET_SECONDS = 20.0
_MAX_WRITE_ACTIONS = 2


def _build_registry(org_id: str, user_id: str, surface: str) -> tuple[list[dict], dict[str, dict]]:
    """Returns (anthropic_tool_schemas, tool_index) where tool_index maps
    schema name -> {"kind": "skill_view"|"read_skill_file"|"connector"|"mcp",
    "classification": "read"|"write"|"destructive", "server_ref": str|None}.
    Skill tools are always offered (matching the existing ecosystem_skill_
    index precedent of always being available, not gated on any install) --
    both are read-only by construction (CONTRACTS.md §12), never require
    approval. Connector/MCP tools are offered even when the caller hasn't
    connected yet -- the model's own selection is a far more precise
    "does this turn actually need it" signal than existence-checking every
    installed-but-unconnected connector on every turn; the connection check
    happens AFTER selection, in _apply_inner's loop, not here.
    """
    schemas = [_SKILL_VIEW_SCHEMA, _READ_SKILL_FILE_SCHEMA]
    index: dict[str, dict] = {
        "skill_view": {"kind": "skill_view", "classification": "read", "server_ref": None},
        "read_skill_file": {"kind": "read_skill_file", "classification": "read", "server_ref": None},
    }

    try:
        from services.ecosystem.resolver_service import _get_installed_items_by_type
    except Exception:
        return schemas, index

    from mcp.tool_annotations import classify_tool

    for item_type, kind in (("connector", "connector"), ("mcp_server", "mcp")):
        try:
            rows = _get_installed_items_by_type(org_id, user_id, surface, item_type)
        except Exception as exc:
            logger.warning(f"ecosystem_tool_calling: could not list installed {item_type}s: {exc}")
            continue
        for _install, item, manifest in rows:
            tools = manifest.get("tools") if isinstance(manifest.get("tools"), list) else []
            for tool_def in tools:
                tool_def = tool_def if isinstance(tool_def, dict) else {"name": str(tool_def)}
                name = tool_def.get("name")
                if not name or name in index:
                    continue  # first-registered wins on a name collision; never silently overwrite
                annotation = classify_tool(tool_def)
                schemas.append({
                    "name": name,
                    "description": tool_def.get("description", "") or f"Tool provided by {item.namespace}.",
                    "input_schema": tool_def.get("input_schema") or {"type": "object", "properties": {}},
                })
                index[name] = {"kind": kind, "classification": annotation.classification, "server_ref": item.namespace}
    return schemas, index


def _execute_tool(kind: str, name: str, args: dict, *, org_id: str, user_id: str, surface: str) -> str:
    if kind == "skill_view":
        from mcp.ecosystem_skill_tools import SkillNotFoundError, skill_view
        try:
            return skill_view(args.get("name", ""), org_id=org_id, user_id=user_id, surface=surface)
        except SkillNotFoundError:
            return "NOT_FOUND"
    if kind == "read_skill_file":
        from mcp.ecosystem_skill_tools import SkillNotFoundError, read_skill_file
        try:
            return read_skill_file(args.get("name", ""), args.get("path", ""), org_id=org_id, user_id=user_id, surface=surface)
        except SkillNotFoundError:
            return "NOT_FOUND"
    if kind in ("connector", "mcp"):
        from mcp.registry import mcp_registry
        result = mcp_registry.execute_tool(name, **args)
        return getattr(result, "output", str(result))
    return f"ERROR: unknown tool kind {kind!r}"


def _is_connected(org_id: str, user_id: str, server_ref: str) -> bool:
    from services.ecosystem.credential_broker_service import get_connection_status
    return get_connection_status(org_id, user_id, server_ref).status == "connected"


def _find_resolved_undelivered(org_id: str, user_id: str, chat_id: str) -> Optional[dict]:
    if not chat_id:
        return None
    from db.database import SessionLocal
    from db.models import EcosystemToolApproval

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemToolApproval)
            .filter(
                EcosystemToolApproval.org_id == org_id,
                EcosystemToolApproval.user_id == user_id,
                EcosystemToolApproval.status.in_(("approved", "denied")),
            )
            .order_by(EcosystemToolApproval.resolved_at.desc())
            .all()
        )
        for row in rows:
            params = row.params_json or {}
            if params.get("chat_id") == chat_id and not params.get("delivered"):
                out = {
                    "approval_id": str(row.id), "status": row.status, "tool_name": row.tool_name,
                    "kind": params.get("kind"), "args": params.get("args") or {},
                }
                params["delivered"] = True
                row.params_json = params
                db.add(row)
                db.commit()
                return out
        return None
    finally:
        db.close()


def _decide_next_tool_call(question: str, schemas: list[dict]) -> Optional[dict]:
    """One cheap-tier, tools-only model_router.generate() call. Returns the
    first requested tool call (single-tool-per-round design; a model that
    asks for several at once still only advances the loop by one), or None
    if the model didn't ask for anything."""
    from models.model_router import ModelRouter
    router = ModelRouter()
    router.generate(question, model_hint="haiku", tools=schemas)

    for getter in (router._get_claude, router._get_openai):
        try:
            gw = getter()
        except Exception:
            gw = None
        if gw is not None and getattr(gw, "_last_tool_calls", None):
            return gw._last_tool_calls[0]
    return None


def _apply_inner(state, *, org_id: str, user_id: str, surface: str, chat_id: str) -> None:
    from services.ecosystem import tool_approval_service

    calls_used = 0
    writes_used = 0
    summary: list[str] = []
    used_connector: Optional[dict] = None

    # 1. Resume: deliver an already-resolved approval into THIS turn first,
    #    then keep looping -- a resumed write action can be followed by
    #    further read calls in the same turn, not just a single delivery.
    resolved = _find_resolved_undelivered(org_id, user_id, chat_id)
    if resolved is not None:
        if resolved["status"] == "denied":
            note = f"[Tool call to {resolved['tool_name']} was denied by the user. Proceed without it.]"
            state.question = f"{state.question}\n\n{note}"
            summary.append(f"{resolved['tool_name']}: denied")
        else:
            result = _execute_tool(resolved["kind"], resolved["tool_name"], resolved["args"], org_id=org_id, user_id=user_id, surface=surface)
            note = f"[Result of the previously-approved tool call {resolved['tool_name']}: {result}]"
            state.question = f"{state.question}\n\n{note}"
            summary.append(f"{resolved['tool_name']}: {result}")
            calls_used += 1
            writes_used += 1  # the resumed call was itself write/destructive
            if resolved.get("kind") in ("connector", "mcp"):
                used_connector = {"name": resolved["tool_name"], "target": None}

    schemas, index = _build_registry(org_id, user_id, surface)
    if not schemas:
        if used_connector:
            state.metadata["ecosystem_tool_call_used_connector"] = used_connector
        return

    start = time.monotonic()
    limit_hit: Optional[str] = None

    while True:
        if calls_used >= _MAX_CALLS:
            limit_hit = f"tool-call limit ({_MAX_CALLS} calls)"
            break
        if (time.monotonic() - start) >= _TIME_BUDGET_SECONDS:
            limit_hit = f"time budget ({_TIME_BUDGET_SECONDS:.0f}s)"
            break

        call = _decide_next_tool_call(state.question, schemas)
        if call is None:
            break  # model is done -- not a limit, nothing to summarize

        name = call.get("name")
        meta = index.get(name)
        if meta is None:
            logger.warning(f"ecosystem_tool_calling: model requested unknown tool {name!r}, ignoring")
            break

        # Connect-prompt gating: a connector/mcp tool the caller hasn't
        # connected never gets attempted -- the model's own selection
        # already proved this turn needs it, so this is a real, specific
        # ConnectPromptCard trigger, not a blanket per-turn check.
        server_ref = meta.get("server_ref")
        if meta["kind"] in ("connector", "mcp") and server_ref and not _is_connected(org_id, user_id, server_ref):
            state.metadata["ecosystem_connect_prompt"] = {"connector_ref": server_ref, "tool_name": name}
            state.question = (
                f"{state.question}\n\n[The tool {name} needs a connection to {server_ref} that the user "
                f"hasn't set up yet. Tell them you need them to connect it first before you can continue.]"
            )
            if used_connector:
                state.metadata["ecosystem_tool_call_used_connector"] = used_connector
            return

        if meta["classification"] == "read":
            result = _execute_tool(meta["kind"], name, call.get("input") or {}, org_id=org_id, user_id=user_id, surface=surface)
            state.question = f"{state.question}\n\n[Tool result for {name}: {result}]"
            summary.append(f"{name}: ok")
            calls_used += 1
            if meta["kind"] in ("connector", "mcp"):
                used_connector = {"name": name, "target": server_ref}
            continue

        # write/destructive -- capped separately and tighter than the
        # overall call limit; every call still goes through
        # request_tool_call() regardless of round number.
        if writes_used >= _MAX_WRITE_ACTIONS:
            limit_hit = f"write-action limit ({_MAX_WRITE_ACTIONS} write/destructive calls)"
            break

        decision = tool_approval_service.request_tool_call(
            org_id=org_id, user_id=user_id, tool_name=name,
            tool_def={"name": name, "annotations": {"destructiveHint": meta["classification"] == "destructive"}},
            params={"chat_id": chat_id, "kind": meta["kind"], "args": call.get("input") or {}},
            target=server_ref,
        )
        if decision.get("requires_approval"):
            state.metadata["ecosystem_tool_call_pending"] = {
                "approval_id": decision["approval_id"], "tool_name": name,
                "classification": meta["classification"], "target": server_ref,
            }
            state.question = (
                f"{state.question}\n\n[A tool call to {name} requires the user's approval before it can run. "
                f"Tell the user you're waiting on their approval for this action; do not claim it already ran.]"
            )
            if used_connector:
                state.metadata["ecosystem_tool_call_used_connector"] = used_connector
            return

        # decision["status"] == "auto_approved" (never reachable for
        # "destructive" -- request_tool_call()'s own write-only gate).
        result = _execute_tool(meta["kind"], name, call.get("input") or {}, org_id=org_id, user_id=user_id, surface=surface)
        state.question = f"{state.question}\n\n[Tool result for {name}: {result}]"
        summary.append(f"{name}: ok")
        calls_used += 1
        writes_used += 1
        if meta["kind"] in ("connector", "mcp"):
            used_connector = {"name": name, "target": server_ref}

    if limit_hit and calls_used > 0:
        state.question = (
            f"{state.question}\n\n[Reached the {limit_hit} for this turn after {calls_used} tool call(s). "
            f"Summary of what was gathered: {'; '.join(summary)}. Answer using only what was actually "
            f"gathered above; do not claim any further tool call happened.]"
        )
    if used_connector:
        state.metadata["ecosystem_tool_call_used_connector"] = used_connector


def apply_chat_tool_calling(state, *, org_id: str, user_id: str, surface: str, chat_id: str = "") -> None:
    """Additive, flag-gated. Never raises -- callers need no try/except,
    matching apply_chat_skill_integration()'s own contract. With
    ECOSYSTEM_TOOL_CALLING off (default), returns immediately -- state is
    byte-identical to before this module existed."""
    from core.config import ECOSYSTEM_TOOL_CALLING
    if not ECOSYSTEM_TOOL_CALLING:
        return
    try:
        _apply_inner(state, org_id=org_id, user_id=user_id, surface=surface, chat_id=chat_id)
    except Exception as exc:
        logger.warning(f"ecosystem tool-calling failed, continuing without it: {exc}")
