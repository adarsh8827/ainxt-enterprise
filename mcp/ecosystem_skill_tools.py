# SPDX-License-Identifier: MIT
# ============================================================
# Task B-15: skill_view / read_skill_file tool contracts (CONTRACTS.md
# §12). Deliberately a new, isolated module -- NOT added to
# mcp/skill_registry.py (a different concept entirely: composed
# tool-sequence "skills," in-memory, unrelated to the Ecosystem catalog)
# and NOT reusing AgentStudio/backend/app/tools/platform_tools.py's own
# read_skill_file (which queries AgentStudio's own skill_files/
# skills_catalog tables via a sandboxed subprocess -- a different system,
# a different storage layer). This module extends the same progressive-
# disclosure *philosophy* platform-wide, against the Ecosystem catalog's
# own tables and content-hash-addressed object storage, so this phase's
# tool surface stays separately reviewable/removable from either
# pre-existing implementation.
#
# Gated by ECOSYSTEM_CHAT_SKILLS alongside task B-16 -- these tools are
# meaningless with the flag off, since nothing would ever reference them.
# ============================================================

from __future__ import annotations

import re
from typing import Any

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion
from services.ecosystem.resolver_service import get_effective_capabilities
from services.ecosystem.versions_service import decode_envelope
from store.ecosystem_object_storage import get_ecosystem_object_storage

# CONTRACTS.md §12's own size limits.
_SKILL_VIEW_MAX_CHARS = 8_000
_READ_FILE_MAX_BYTES = 256 * 1024

# Task B-16's "/name ..." invocation syntax -- captures the slash-command
# token and the rest of the message (possibly empty, possibly multi-line).
_SLASH_COMMAND_RE = re.compile(r"^/(\S+)\s*(.*)$", re.DOTALL)


class SkillToolError(Exception):
    """Base class -- both tools' only error shape is NOT_FOUND
    (CONTRACTS.md §12): a skill that isn't currently installed+enabled for
    the caller's surface, or a path not in that skill's pinned manifest,
    are both represented identically so a caller can never learn a skill
    exists (or what files it declares) without already being entitled to
    see it."""


class SkillNotFoundError(SkillToolError):
    pass


def resolve_pinned_version_id(name: str, *, org_id: str, user_id: str, surface: str) -> str | None:
    """The resolution task B-16's chat runtime calls exactly ONCE per
    session, when it builds the skill index -- the returned version_id is
    what that session then passes as `pinned_version_id` to every
    subsequent skill_view()/read_skill_file() call for the rest of the
    conversation, so a mid-conversation update to the install's current
    version never changes what a running conversation sees (CONTRACTS.md
    §12's own pinning requirement). Returns None if the named skill isn't
    currently installed+enabled for this surface (never installed/
    enabled/surface state at all -- there is nothing to pin).
    """
    resolved = _resolve_current_install(name, org_id=org_id, user_id=user_id, surface=surface)
    return resolved[2].id if resolved else None


def _resolve_current_install(
    name: str, *, org_id: str, user_id: str, surface: str,
) -> tuple[EcosystemItem, EcosystemInstall, EcosystemItemVersion] | None:
    """name -> namespace-matched item -> the caller's currently
    installed+enabled install for this surface -> that install's CURRENT
    version_id. Resolves fresh every call -- callers needing a pinned
    result across multiple calls must capture resolve_pinned_version_id()'s
    return value once and pass it back via `pinned_version_id` on every
    subsequent skill_view()/read_skill_file() call instead of calling this
    function again.
    """
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.namespace == name).first()
        if item is None:
            return None

        query = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item.id, EcosystemInstall.org_id == org_id,
            EcosystemInstall.enabled.is_(True),
        )
        query = query.filter(EcosystemInstall.installed_for.is_(None)) if not user_id else query.filter(
            EcosystemInstall.installed_for == user_id
        )
        install = query.first()
        if install is None or surface not in (install.surfaces or []):
            return None

        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == install.version_id).first()
        if version is None:
            return None

        db.expunge(item)
        db.expunge(install)
        db.expunge(version)
        return item, install, version
    finally:
        db.close()


def _resolve_version_for_read(
    name: str, *, org_id: str, user_id: str, surface: str, pinned_version_id: str | None,
) -> EcosystemItemVersion | None:
    """Authorization always re-checks the CURRENT install state (a caller
    whose install was disabled/uninstalled/surface-removed since the
    version was pinned must not keep reading content through a stale
    pin) -- only which VERSION's content gets read is allowed to come from
    the pin, and only if that version still belongs to the same item.
    """
    current = _resolve_current_install(name, org_id=org_id, user_id=user_id, surface=surface)
    if current is None:
        return None
    item, _install, current_version = current
    if pinned_version_id is None:
        return current_version

    db = SessionLocal()
    try:
        pinned = db.query(EcosystemItemVersion).filter(
            EcosystemItemVersion.id == pinned_version_id, EcosystemItemVersion.item_id == item.id,
        ).first()
        if pinned is None:
            return None
        db.expunge(pinned)
        return pinned
    finally:
        db.close()


def skill_view(name: str, *, org_id: str, user_id: str, surface: str, pinned_version_id: str | None = None) -> str:
    """CONTRACTS.md §12 -- up to 8,000 characters of the resolved
    version's instructions body, truncated with a trailing marker if
    longer. `pinned_version_id`, when supplied, is what a session-scoped
    caller (task B-16) obtained once from resolve_pinned_version_id() --
    authorization is still re-checked against the current install state
    on every call (see _resolve_version_for_read()); only the version
    actually read is allowed to stay pinned. Raises SkillNotFoundError
    (never any other exception shape) if the named skill isn't currently
    installed+enabled for the caller's surface -- upstream object-storage
    failures degrade to the same NOT_FOUND from the model's perspective
    too, logged server-side for ops visibility, per CONTRACTS.md §12's own
    instruction.
    """
    version = _resolve_version_for_read(name, org_id=org_id, user_id=user_id, surface=surface, pinned_version_id=pinned_version_id)
    if version is None:
        raise SkillNotFoundError(name)

    try:
        store = get_ecosystem_object_storage()
        manifest, _files = decode_envelope(store.get(version.object_key))
    except Exception as exc:
        from core.logger import logger

        logger.warning(f"ecosystem_skill_tools.skill_view: object-storage read failed for {name!r}: {exc}")
        raise SkillNotFoundError(name) from exc

    from core.logger import logger

    # Item 7: structured, content-free usage-proof logging -- name/version/
    # surface only, NEVER the returned instructions body (that's the exact
    # thing a caller must never see logged, per the task's own explicit
    # "no content, no secrets" requirement).
    logger.info(f"ECOSYSTEM_SKILL_VIEW → name={name!r} version={version.id!r} surface={surface!r}")

    instructions = str(manifest.get("instructions", ""))
    if len(instructions) <= _SKILL_VIEW_MAX_CHARS:
        return instructions
    omitted = len(instructions) - _SKILL_VIEW_MAX_CHARS
    return instructions[:_SKILL_VIEW_MAX_CHARS] + f"\n...(truncated, {omitted} characters omitted)"


def read_skill_file(
    name: str, path: str, *, org_id: str, user_id: str, surface: str, pinned_version_id: str | None = None,
) -> str:
    """CONTRACTS.md §12 -- fetches one bundled file by relative path,
    resolved only against the resolved version's own manifest file list
    (no path traversal, no access to any file not explicitly declared
    there). 256KB limit; longer text content is truncated with a marker.
    `pinned_version_id` behaves exactly as documented on skill_view().

    Every bundled file in this platform's current creation pipeline
    (create_service.py's write/upload/import payloads, versions_service's
    encode_envelope) is stored as text -- there is no binary-file creation
    path yet, so CONTRACTS.md §12's "FILE_TOO_LARGE-shaped error for
    binary files" branch is currently unreachable; disclosed here rather
    than implemented against a case that can't occur, per the standing
    "don't validate scenarios that can't happen" rule. If a binary
    creation path is added later, this function needs a real binary-size
    branch before that path can rely on it.
    """
    version = _resolve_version_for_read(name, org_id=org_id, user_id=user_id, surface=surface, pinned_version_id=pinned_version_id)
    if version is None:
        raise SkillNotFoundError(name)

    try:
        store = get_ecosystem_object_storage()
        _manifest, files = decode_envelope(store.get(version.object_key))
    except Exception as exc:
        from core.logger import logger

        logger.warning(f"ecosystem_skill_tools.read_skill_file: object-storage read failed for {name!r}: {exc}")
        raise SkillNotFoundError(name) from exc

    if path not in files:
        # NOT_FOUND, never a generic 403 -- a path outside the declared set
        # must look identical to a path that was never bundled at all.
        raise SkillNotFoundError(name)

    from core.logger import logger

    # Item 7: same rule as skill_view() above -- name/path/surface only,
    # never the file content itself.
    logger.info(f"ECOSYSTEM_READ_SKILL_FILE → name={name!r} version={version.id!r} path={path!r} surface={surface!r}")

    content = files[path]
    encoded_len = len(content.encode("utf-8"))
    if encoded_len <= _READ_FILE_MAX_BYTES:
        return content

    # Truncate on a UTF-8-safe character boundary rather than a raw byte
    # offset, which could split a multi-byte character mid-sequence.
    truncated = content.encode("utf-8")[:_READ_FILE_MAX_BYTES].decode("utf-8", errors="ignore")
    omitted = encoded_len - len(truncated.encode("utf-8"))
    return truncated + f"\n...(truncated, {omitted} bytes omitted)"


def apply_chat_skill_integration(state: Any, *, org_id: str, user_id: str, surface: str) -> None:
    """Task B-16's own integration point, kept here (not inline in
    agents/orchestrator.py's run()) so it has a directly-testable surface
    that doesn't require mocking run()'s entire pipeline (compliance
    scanning, model routing, real LLM calls).

    Mutates `state` (an agents.state.AgentState -- typed Any here to avoid
    this module importing agents.state, which would be a backwards
    dependency: agents/ is a caller of mcp/, never the other way around)
    in place:
      - state.metadata["ecosystem_skill_index"]: always set (possibly ""),
        for agents/tools.py's generate_answer_tool to append to its own
        prompt.
      - state.question / state.raw_question: rewritten ONLY when the
        caller's current question is a recognized "/name ..." invocation
        of an installed+enabled+surface-matching skill -- the skill body
        replaces the slash-command trigger, injected as a user message
        (never a system-prompt mutation, so per-skill content never rides
        in the cacheable, stable part of the prompt -- CONFIG_AND_PRODUCTS.md
        §9's cache-safety rationale, extended here). Left untouched for
        every other message.

    Never raises -- an ecosystem lookup failure must never break the live
    chat path; the caller (agents/orchestrator.py) doesn't need its own
    try/except because this function already swallows and logs internally.
    """
    try:
        skills = get_effective_capabilities(org_id, user_id, surface)
        state.metadata["ecosystem_skill_index"] = render_skill_index(skills)

        current_question = (getattr(state, "raw_question", None) or getattr(state, "question", None) or "").strip()
        slash_match = _SLASH_COMMAND_RE.match(current_question)
        from core.logger import logger as _diag_logger

        if not slash_match:
            # Diagnostic only (never the message text) -- a real live bug
            # (a skill silently not applying) was previously undiagnosable
            # because this early-return path never logged anything at all.
            _diag_logger.info(
                f"ECOSYSTEM_SKILL_NOT_A_SLASH_COMMAND → surface={surface!r} org_id={org_id!r} "
                f"starts_with_slash={current_question.startswith('/')!r} len={len(current_question)}"
            )
            return

        token = slash_match.group(1)
        namespace = build_slash_command_lookup(skills).get(f"/{token}")
        if not namespace:
            _diag_logger.info(
                f"ECOSYSTEM_SKILL_SLASH_TOKEN_NOT_INSTALLED → token={token!r} surface={surface!r} "
                f"org_id={org_id!r} user_id={user_id!r} installed_slash_commands={[s.get('slash_command') for s in skills]!r}"
            )
            return

        pinned_version_id = resolve_pinned_version_id(namespace, org_id=org_id, user_id=user_id, surface=surface)
        from core.logger import logger as _logger

        # Item 7 (usage proof): resolved name/version/surface only, never
        # the message text or skill content.
        _logger.info(f"ECOSYSTEM_SKILL_RESOLVED → name={namespace!r} version={pinned_version_id!r} surface={surface!r}")

        body = skill_view(namespace, org_id=org_id, user_id=user_id, surface=surface, pinned_version_id=pinned_version_id)
        rest = slash_match.group(2).strip()
        expanded = f"{body}\n\n---\n\nUser request: {rest}" if rest else body
        state.question = expanded
        state.raw_question = expanded
        display_name = next((s.get("display_name", "") for s in skills if s.get("namespace") == namespace), "")
        state.metadata["ecosystem_skill_used"] = {"name": namespace, "display_name": display_name}
        _logger.info(f"ECOSYSTEM_SKILL_INJECTED_AS_USER_MESSAGE → name={namespace!r}")
    except Exception as exc:
        from core.logger import logger

        logger.warning(f"ecosystem_skill_tools.apply_chat_skill_integration failed, continuing without it: {exc}")


def render_skill_index(skills: list[dict[str, Any]]) -> str:
    """Task B-16: renders the "## Skills" system-prompt section from
    resolver_service.get_effective_capabilities()'s own Capabilities.skills
    shape (namespace/display_name/description/slash_command) -- matching
    AgentStudio/backend/app/core/skill_manifest.py:131's existing
    progressive-disclosure pattern (a short index entry per skill, full
    content fetched on demand via skill_view/read_skill_file) extended
    platform-wide, rather than a second, competing rendering convention.
    Returns "" (never a "## Skills" header with no entries) when the list
    is empty, so a caller can safely always append the result.
    """
    if not skills:
        return ""
    lines = ["## Skills", "", "Installed skills you can use. Call skill_view(name) for full instructions."]
    for skill in skills:
        lines.append(f"- **{skill['display_name']}** (`{skill['slash_command']}`): {skill['description']}")
    return "\n".join(lines)


def build_slash_command_lookup(skills: list[dict[str, Any]]) -> dict[str, str]:
    """slash_command -> namespace, for task B-16's "/name" handling."""
    return {skill["slash_command"]: skill["namespace"] for skill in skills}


# Tool-schema shape mirrors the existing convention in
# AgentStudio/backend/app/tools/platform_tools.py's PLATFORM_TOOLS list
# (name/description/input_schema) for consistency -- this module doesn't
# import or depend on that file, it just doesn't reinvent the shape.
# Wiring these into the actual chat runtime (adding org_id/user_id/surface
# from request context, session-level version pinning) is task B-16's job.
ECOSYSTEM_SKILL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "skill_view",
        "description": (
            "View the full instructions for an installed skill referenced in the "
            "skill index. Call this when a skill is relevant beyond its one-line "
            "index entry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The skill's namespace, e.g. 'acme/exec-assistant'."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "read_skill_file",
        "description": (
            "Fetch a specific bundled file (references/, scripts/, etc.) from an "
            "installed skill by relative path. Only request paths listed in that "
            "skill's own manifest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The skill's namespace, e.g. 'acme/exec-assistant'."},
                "path": {"type": "string", "description": "Relative path as declared in the skill's manifest."},
            },
            "required": ["name", "path"],
        },
    },
]
