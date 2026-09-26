# SPDX-License-Identifier: MIT
# ============================================================
# Small shared helper for importing AgentStudio's skill_factory.pipeline
# module from ecosystem code (task B-6's upload path, task B-22's seeding).
#
# AgentStudio/backend's own modules use bare top-level imports (e.g.
# `from app.core.factory_utils import ...`) that only resolve once
# AgentStudio/backend itself is on sys.path — gateway.py already does this
# once, in-process, for the main application (`gateway.py:1284-1291`'s
# comment: "AgentStudio/backend is added to sys.path so its app.* packages
# resolve without moving any files"). Code paths that run outside gateway.py
# (this module's own callers, and any standalone script) need the exact
# same sys.path insertion — this helper is that insertion, made idempotent
# and reusable rather than duplicated ad hoc at each call site.
# ============================================================

from __future__ import annotations

import os
import sys


def ensure_agentstudio_backend_on_path() -> None:
    backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "AgentStudio", "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)


def parse_skill_md_frontmatter(content: str) -> dict:
    """Thin wrapper around AgentStudio's skill_factory.pipeline.parse_frontmatter
    (never re-derived — see that module's own docstring on why it's
    deliberately PyYAML-free) that ensures the sys.path prerequisite above
    is satisfied first."""
    ensure_agentstudio_backend_on_path()
    from skill_factory.pipeline import parse_frontmatter

    return parse_frontmatter(content)
