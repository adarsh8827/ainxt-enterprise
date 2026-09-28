# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 7 — MCP/connector checks (docs/ecosystem/SKILLS_PHASE_PLAN.md
# task B-9; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 7).
#
# Always-pass no-op for item_type=skill, wired but inert — this closes the
# gap of "silently skipping a stage" vs. "explicitly always-passing one":
# the stage runs, is recorded, and its verdict is visible in gate_findings
# exactly like every other stage, it just has no skill-relevant checks yet.
# Real HTTPS/OAuth/tool-annotation checks land when ECOSYSTEM_TYPE_MCP or
# ECOSYSTEM_TYPE_CONNECTOR flip on ("Next phases" 3/4 in
# docs/ecosystem/SKILLS_PHASE_PLAN.md).
# ============================================================

from __future__ import annotations

from typing import Any

from services.ecosystem.gate.types import StageResult


def run(item_type: str, manifest: dict[str, Any]) -> StageResult:
    return StageResult(verdict="pass", findings=[])
