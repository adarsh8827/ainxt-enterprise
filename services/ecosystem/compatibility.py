# SPDX-License-Identifier: MIT
# ============================================================
# Compatibility tag: whether a skill's own instructions can be followed
# purely through a chat conversation, or assume the caller can run
# shell/git/file-edit steps (needs a tool-capable surface). Explicit
# review request: "Compatibility tag per skill... Default surfaces:
# chat-compatible -> all surfaces; tool-dependent -> Cowork/Desktop (and
# Agent Studio if it has tools), not chat."
#
# Heuristic, not a guarantee -- a skill written cautiously enough to avoid
# every trigger phrase below while still assuming tool access would be
# misclassified as chat-compatible. This is the same class of tradeoff
# every other heuristic classifier in this codebase already accepts
# (models/classifier.py's own complexity/domain classification); disclosed
# here rather than overstated.
# ============================================================

from __future__ import annotations

import re

CHAT = "chat"
TOOL_DEPENDENT = "tool_dependent"

# Fenced shell/terminal code blocks are the strongest signal -- a skill
# telling the reader to literally run something in a shell cannot be
# followed inside a plain chat turn.
_SHELL_FENCE_RE = re.compile(r"```\s*(bash|sh|shell|zsh|powershell|pwsh|cmd|batch)\b", re.IGNORECASE)

# Imperative phrases that assume file-system/terminal/version-control
# access a chat-only surface doesn't have.
_TOOL_PHRASE_PATTERNS = [
    re.compile(r"\bgit\s+(commit|push|pull|clone|checkout|branch|merge|rebase|diff|status|add|log)\b", re.IGNORECASE),
    re.compile(r"\brun\s+(the\s+)?(command|script|following|this)\b", re.IGNORECASE),
    re.compile(r"\bexecute\s+(the\s+)?(command|script)\b", re.IGNORECASE),
    re.compile(r"\b(open|edit|create|save|write to|delete)\s+(a\s+|the\s+)?file\b", re.IGNORECASE),
    re.compile(r"\bterminal\b", re.IGNORECASE),
    re.compile(r"\bcommand[\s-]line\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(install|run|ci)\b", re.IGNORECASE),
    re.compile(r"\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"\binstall\s+(the\s+)?(package|dependency|dependencies|cli)\b", re.IGNORECASE),
    re.compile(r"\brequires?\s+the\s+.{0,40}\bcli\b", re.IGNORECASE),
    re.compile(r"\bmcp\s+server\b", re.IGNORECASE),
]


def classify_compatibility(instructions: str) -> str:
    """Returns CHAT or TOOL_DEPENDENT based on a text-pattern scan of the
    skill's own instructions body. Never raises -- an empty/None body
    classifies as CHAT (nothing tool-shaped to detect)."""
    text = instructions or ""
    if _SHELL_FENCE_RE.search(text):
        return TOOL_DEPENDENT
    for pattern in _TOOL_PHRASE_PATTERNS:
        if pattern.search(text):
            return TOOL_DEPENDENT
    return CHAT


def default_surfaces_for(compatibility: str, *, has_tools: bool = False) -> list[str]:
    """The default surface list for a newly-created item when the caller
    didn't explicitly request a narrower one -- chat-compatible skills are
    useful everywhere; tool-dependent ones are useful only where the
    platform can actually give an agent file/terminal access."""
    if compatibility == TOOL_DEPENDENT:
        return ["cowork", "desktop", "agent_studio"] if has_tools else ["cowork", "desktop"]
    return ["chat", "cowork", "desktop", "agent_studio"]


def enforce_compatibility_on_surfaces(compatibility: str, surfaces: list[str]) -> list[str]:
    """A caller-supplied (non-empty, explicit) surface list is respected,
    EXCEPT that a tool-dependent item can never be handed the `chat`
    surface -- that combination would silently promise chat-only users
    something the skill can't actually do there."""
    if compatibility == TOOL_DEPENDENT:
        return [s for s in surfaces if s != "chat"]
    return surfaces
