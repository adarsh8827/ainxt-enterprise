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

# Chat-skills explain-mode (2026-09-29): matches ONLY when the text typed
# after the chip/slash command is, in its entirety, nothing more than an
# explain/help request -- a whitelist of whole-message phrases, not a
# substring check, so an ordinary task that happens to contain a word like
# "help" (e.g. "help me summarize this doc") is never misclassified. Kept
# deliberately small and literal rather than an LLM judgment call: this
# decides which of two labelled-skill-block templates gets sent, not
# whether to make an extra model call.
_EXPLAIN_ONLY_ALTERNATIVES = (
    r"explain(?: this)?(?: skill)?",
    r"explain it",
    r"what(?:'s| is) this(?: skill)?",
    r"what does this(?: skill)? do",
    r"what can (?:it|this)(?: skill)? do",
    r"help",
    r"how do i use (?:it|this)(?: skill)?",
    r"how (?:do|can) i use (?:it|this)",
    r"how to use (?:it|this|this skill)",
    r"how does this(?: skill)? work",
    r"usage",
    r"describe(?: this)?(?: skill)?",
)
_EXPLAIN_ONLY_RE = re.compile(
    r"^(?:" + "|".join(_EXPLAIN_ONLY_ALTERNATIVES) + r")[\s?!.]*$", re.IGNORECASE
)


def _is_explain_only_request(rest: str) -> bool:
    """True when `rest` (the user's own text after the chip/slash command,
    already stripped of the command token itself) is, in its entirety,
    an explain/help request rather than a real task for the skill to
    perform. Empty `rest` (chip with no further text) is NOT explain-only
    -- that's an ordinary bare invocation, unchanged from today."""
    rest = (rest or "").strip()
    return bool(rest) and bool(_EXPLAIN_ONLY_RE.match(rest))

# Chat-skills task, 2026-09-28 -- render_skill_index()'s own cap on how many
# entries actually get rendered into the prompt (never a cap on how many
# skills are matchable by "/name" -- see that function's docstring).
_SKILL_INDEX_MAX_ENTRIES = 20


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


def matches_attached_skill(attached_skill: str | None, *, org_id: str, user_id: str, surface: str) -> bool:
    """True only when `attached_skill` (the chat request's own `skills:
    [namespace]` field -- the "+" menu picker, or a typed "/name" that the
    chat-input UI has already converted into a chip and stripped from the
    message text) resolves to a real, currently installed+enabled skill
    for this exact org/user/surface. Same purpose as
    matches_installed_skill_slash_command() -- gateway.py's CIL ambiguity-
    clarification gate needs to distinguish "this turn IS a skill
    invocation" from "this turn is genuinely ambiguous free text" -- but
    for the ATTACHED-skill path rather than the leading-slash-text path.

    Real bug this closes (live, 2026-09-29): once the chat-input UI
    started converting a typed "/name" into a chip and removing the
    literal "/name " text from what's actually sent (the chip-cleanup
    fix), matches_installed_skill_slash_command()'s raw-text regex could
    never match again for that flow -- so CIL's ambiguity gate saw only
    the user's own short task text ("dd", "explain this skill") with NO
    skill signal at all, and correctly-by-its-own-logic treated it as too
    vague, firing the "I'm not sure what you'd like me to do" clarify
    response before apply_chat_skill_integration() (which lives further
    down this same request path) ever got a chance to run. This function
    gives the CIL gate the other half of the signal it needs.

    Never raises -- same fail-closed-to-False convention as
    matches_installed_skill_slash_command().
    """
    if not attached_skill:
        return False
    try:
        skills = get_effective_capabilities(org_id, user_id, surface)
        return any(s.get("namespace") == attached_skill for s in skills)
    except Exception:
        return False


def matches_installed_skill_slash_command(question: str, *, org_id: str, user_id: str, surface: str) -> bool:
    """True only when `question` starts with "/token ..." AND `token`
    resolves to a real, currently installed+enabled skill for this exact
    org/user/surface (task: gateway.py's CIL ambiguity-clarification gate,
    2026-09-27 -- a caller there must distinguish "this is genuinely a
    skill invocation" from "this merely starts with a slash character",
    since the latter includes a user's own typo, a reference to an
    unrelated slash command, or free text that happens to start with '/'
    for some other reason -- none of which should ever bypass that gate's
    normal ambiguity check). Never raises -- same fail-closed-to-False
    convention as apply_chat_skill_integration() itself; a lookup failure
    here must fall back to the CIL gate's normal behavior, not silently
    skip it.

    Deliberately does NOT reuse apply_chat_skill_integration() itself for
    this check -- that function's job is mutation (rewrite state.question)
    plus logging the resolution as a real usage event; calling it purely
    to test membership would double-log a resolution that hasn't actually
    been "used" yet at the point the CIL gate runs, before the orchestrator/
    fast-path tail's own real integration call.
    """
    try:
        match = _SLASH_COMMAND_RE.match((question or "").strip())
        if not match:
            return False
        skills = get_effective_capabilities(org_id, user_id, surface)
        return f"/{match.group(1)}" in build_slash_command_lookup(skills)
    except Exception:
        return False


def apply_chat_skill_integration(
    state: Any, *, org_id: str, user_id: str, surface: str, attached_skill: str | None = None,
) -> None:
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
      - state.question / state.raw_question: rewritten ONLY when a skill
        is actually resolved (see below) -- the skill body replaces the
        slash-command trigger (or is prepended to the message verbatim,
        for an explicit attachment), injected as a user message (never a
        system-prompt mutation, so per-skill content never rides in the
        cacheable, stable part of the prompt -- CONFIG_AND_PRODUCTS.md
        §9's cache-safety rationale, extended here). Left untouched for
        every other message.

    `attached_skill` (task, 2026-09-28): an explicit namespace from the
    chat request's own `skills: [namespace]` field (the "+" menu's "Use a
    skill" picker, or a clicked "Use <skill>" suggestion chip) -- attaches
    a skill WITHOUT the user typing a leading "/name". Checked BEFORE
    leading-slash detection; if it resolves to a real installed+enabled
    skill for this surface, the ENTIRE message text (no slash token to
    strip) becomes the "rest" appended after the skill body. Falls back to
    slash-command detection when `attached_skill` is None or doesn't
    resolve (never silently drops the message in that case -- same
    fail-open behavior as an unrecognized slash token below).

    Never raises -- an ecosystem lookup failure must never break the live
    chat path; the caller (agents/orchestrator.py) doesn't need its own
    try/except because this function already swallows and logs internally.
    """
    try:
        skills = get_effective_capabilities(org_id, user_id, surface)
        state.metadata["ecosystem_skill_index"] = render_skill_index(skills)

        current_question = (getattr(state, "raw_question", None) or getattr(state, "question", None) or "").strip()
        from core.logger import logger as _diag_logger

        namespace: str | None = None
        rest: str = ""
        slash_match = None

        if attached_skill:
            if any(s.get("namespace") == attached_skill for s in skills):
                namespace = attached_skill
                rest = current_question
            else:
                _diag_logger.info(
                    f"ECOSYSTEM_SKILL_ATTACHED_NOT_INSTALLED → namespace={attached_skill!r} surface={surface!r} "
                    f"org_id={org_id!r} user_id={user_id!r} installed_namespaces={[s.get('namespace') for s in skills]!r}"
                )

        if namespace is None:
            slash_match = _SLASH_COMMAND_RE.match(current_question)
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
            rest = slash_match.group(2).strip()

        pinned_version_id = resolve_pinned_version_id(namespace, org_id=org_id, user_id=user_id, surface=surface)
        from core.logger import logger as _logger

        # Item 7 (usage proof): resolved name/version/surface only, never
        # the message text or skill content.
        _logger.info(f"ECOSYSTEM_SKILL_RESOLVED → name={namespace!r} version={pinned_version_id!r} surface={surface!r}")

        body = skill_view(namespace, org_id=org_id, user_id=user_id, surface=surface, pinned_version_id=pinned_version_id)
        display_name = next((s.get("display_name", "") for s in skills if s.get("namespace") == namespace), "")
        # Item, 2026-09-28: a bare "---" separator gave the model no signal
        # that what follows is a platform-injected skill body rather than
        # more of the user's own message, and no way to tell the model
        # (or a human reading raw logs/transcripts) which skill/version
        # this actually was. A clearly labeled block fixes both.
        _skill_label = f"[SKILL: {display_name} ({namespace}), version {pinned_version_id}]"
        # Explain mode (2026-09-29): the user attached the skill but only
        # asked to have it explained (see _is_explain_only_request above)
        # -- same labelled block, same single model call, but the
        # instruction line asks the model to DESCRIBE the skill (purpose,
        # when to use it, expected input, an example invocation) instead of
        # applying its instructions to a task. Chat history/title are
        # unaffected -- this only changes the text handed to the model for
        # this one turn, not what gets persisted (that's built from the
        # user's own literal text + skill reference elsewhere, unchanged).
        if _is_explain_only_request(rest):
            expanded = (
                f"{_skill_label}\n"
                "The user attached this skill but is only asking ABOUT it, not asking you to "
                "perform it. Do NOT follow the instructions below as a task. Instead, describe "
                "this skill to the user in your reply: its purpose, when someone would use it, "
                "what input it expects, and a short example of invoking it (its slash command is "
                f"{namespace!r}'s own, shown to the user as \"{next((s.get('slash_command', '') for s in skills if s.get('namespace') == namespace), '')}\"). "
                f"Use the instructions below only as context for writing that description, never execute them.\n\n{body}"
                + (f"\n\n[USER REQUEST]\n{rest}" if rest else "")
            )
        else:
            expanded = (
                f"{_skill_label}\nFollow these instructions for this request:\n\n{body}"
                + (f"\n\n[USER REQUEST]\n{rest}" if rest else "")
            )
        state.question = expanded
        state.raw_question = expanded
        state.metadata["ecosystem_skill_used"] = {
            "name": namespace, "display_name": display_name, "version_id": pinned_version_id,
        }
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

    Item, 2026-09-28: the header used to tell the model to "Call
    skill_view(name)" -- misleading, since skill_view is a Python
    function this module exposes for the SLASH-COMMAND path
    (apply_chat_skill_integration), not a tool the model can actually
    invoke -- no chat call site wires real model tool-calling for these
    (disclosed gap; native tool-calling is planned for the MCP/Connectors
    phase, designed once for every tool type together, not here). The
    header now asks the model to merely SUGGEST the slash command when a
    skill clearly fits, and explicitly not claim to have already applied
    one it never actually received the body of.
    """
    if not skills:
        return ""
    lines = [
        "## Skills", "",
        "These are skills installed for this conversation. You have NOT been given "
        "their full instructions and must not claim to have applied one. If one of "
        "these clearly fits the user's request, briefly say so and suggest the exact "
        "slash command shown in parentheses (e.g. \"You can use `/name` for this\") "
        "so the user can invoke it.",
    ]
    # Item, 2026-09-28: capped, on the already-stably-ordered (namespace,
    # resolver_service.get_effective_capabilities()'s own ORDER BY) list --
    # an unbounded index grows the prompt (and its cost) with every skill a
    # user installs, and a cap on an UNSTABLE order would itself bust the
    # prompt cache by showing a different subset each call. Every skill
    # (shown or not) stays invocable by its own "/name" -- the cap is
    # purely about what's rendered in the index text, never about
    # build_slash_command_lookup()'s matching.
    shown = skills[:_SKILL_INDEX_MAX_ENTRIES]
    for skill in shown:
        lines.append(f"- **{skill['display_name']}** (`{skill['slash_command']}`): {skill['description']}")
    omitted = len(skills) - len(shown)
    if omitted > 0:
        lines.append(f"\n…and {omitted} more — type \"/\" to see the rest.")
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
