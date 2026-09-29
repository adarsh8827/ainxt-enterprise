# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM CHAT TOOL-CALLING (Connectors/Plugins phase, follow-up round)
#
# Closes the gap: Stage 1's `tools=` passthrough on model_router.generate()
# was never actually wired into a real chat turn -- no chat path attached a
# tool registry or did anything with a gateway's `_last_tool_calls`. This
# module is the first real integration, additive and flag-gated
# (ECOSYSTEM_TOOL_CALLING, default off), sibling to
# mcp.ecosystem_skill_tools.apply_chat_skill_integration() and called
# immediately after it from the SAME two real call sites
# (agents/orchestrator.py's run(), gateway.py's fast-path tail) -- same
# "mutate state.question in place, never raise" contract.
#
# Design, disclosed: this is a SINGLE round trip per chat turn, not a full
# multi-round agentic loop (agents/react_orchestrator.py's own
# generate_with_tools()-based loop already exists for that, used today by
# repo-search -- a different, older mechanism, untouched by this module).
# One extra, cheap-tier model_router.generate() call decides whether a tool
# is worth calling at all; if so, a READ-classified tool is executed
# immediately and its result is folded into the SAME turn's real answer
# (mirrors the existing ecosystem_skill_index text-injection pattern, but
# with a REAL tool execution behind it instead of a text hint). A
# WRITE/DESTRUCTIVE tool is never executed inline -- a pending approval row
# is created (services/ecosystem/tool_approval_service.py) and this turn's
# state.metadata carries a marker the caller (gateway.py/agents/orchestrator.py)
# can use to tell the frontend to render ToolApprovalCard. The user's NEXT
# message in the same chat, before anything else happens, checks for an
# already-resolved (approved/denied) approval for this chat and delivers its
# real result (or a "denied" notice) into that turn -- this is how "resume
# after approval" is achieved without restructuring any existing loop.
# ============================================================

from __future__ import annotations

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


def _build_registry(org_id: str, user_id: str, surface: str) -> tuple[list[dict], dict[str, dict]]:
    """Returns (anthropic_tool_schemas, tool_index) where tool_index maps
    schema name -> {"kind": "skill_view"|"read_skill_file"|"connector"|"mcp",
    "classification": "read"|"write"|"destructive", "server_ref": str|None}.
    Skill tools are always offered (matching the existing ecosystem_skill_
    index precedent of always being available, not gated on any install) --
    both are read-only by construction (CONTRACTS.md §12), never require
    approval.
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


def _apply_inner(state, *, org_id: str, user_id: str, surface: str, chat_id: str) -> None:
    from services.ecosystem import tool_approval_service

    # 1. Resume: deliver an already-resolved approval into THIS turn first,
    #    before considering any new tool call -- one tool interaction per
    #    turn, matching the single-round-trip design documented above.
    resolved = _find_resolved_undelivered(org_id, user_id, chat_id)
    if resolved is not None:
        if resolved["status"] == "denied":
            note = f"[Tool call to {resolved['tool_name']} was denied by the user. Proceed without it.]"
        else:
            result = _execute_tool(resolved["kind"], resolved["tool_name"], resolved["args"], org_id=org_id, user_id=user_id, surface=surface)
            note = f"[Result of the previously-approved tool call {resolved['tool_name']}: {result}]"
        state.question = f"{state.question}\n\n{note}"
        return

    # 2. New tool decision -- one cheap-tier call, tools-only, no side effects
    #    if the model doesn't ask for anything.
    schemas, index = _build_registry(org_id, user_id, surface)
    if not schemas:
        return

    from models.model_router import ModelRouter
    router = ModelRouter()
    router.generate(state.question, model_hint="haiku", tools=schemas)

    tool_calls = []
    for getter in (router._get_claude, router._get_openai):
        try:
            gw = getter()
        except Exception:
            gw = None
        if gw is not None and getattr(gw, "_last_tool_calls", None):
            tool_calls = gw._last_tool_calls
            break
    if not tool_calls:
        return

    call = tool_calls[0]  # single-round design: at most one tool per turn
    name = call.get("name")
    meta = index.get(name)
    if meta is None:
        logger.warning(f"ecosystem_tool_calling: model requested unknown tool {name!r}, ignoring")
        return

    if meta["classification"] == "read":
        result = _execute_tool(meta["kind"], name, call.get("input") or {}, org_id=org_id, user_id=user_id, surface=surface)
        state.question = f"{state.question}\n\n[Tool result for {name}: {result}]"
        return

    # write/destructive -- never executed inline.
    decision = tool_approval_service.request_tool_call(
        org_id=org_id, user_id=user_id, tool_name=name,
        tool_def={"name": name, "annotations": {"destructiveHint": meta["classification"] == "destructive"}},
        params={"chat_id": chat_id, "kind": meta["kind"], "args": call.get("input") or {}},
        target=meta.get("server_ref"),
    )
    if decision.get("requires_approval"):
        state.metadata["ecosystem_tool_call_pending"] = {
            "approval_id": decision["approval_id"], "tool_name": name,
            "classification": meta["classification"], "target": meta.get("server_ref"),
        }
        state.question = (
            f"{state.question}\n\n[A tool call to {name} requires the user's approval before it can run. "
            f"Tell the user you're waiting on their approval for this action; do not claim it already ran.]"
        )
        return

    # decision["status"] == "auto_approved" -- a write tool with an org
    # auto-approve policy row (request_tool_call() already guarantees this
    # branch is unreachable for "destructive", see its own write-only gate).
    # Real bug found on review: this branch previously did nothing at all --
    # requires_approval=False was treated as "no action needed" instead of
    # "cleared to run", so an auto-approved tool call was silently dropped
    # every time, never executed, no result, no explanation. Auto-approve's
    # whole point is to run without friction, same as a read tool.
    result = _execute_tool(meta["kind"], name, call.get("input") or {}, org_id=org_id, user_id=user_id, surface=surface)
    state.question = f"{state.question}\n\n[Tool result for {name}: {result}]"


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
