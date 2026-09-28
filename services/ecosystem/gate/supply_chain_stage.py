# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 4 — supply chain (docs/ecosystem/SKILLS_PHASE_PLAN.md task
# B-8; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 4).
#
# For item_type=skill this phase: skills declare no real dependency
# manifest (no pip/npm-style requirements), so the only thing to check is
# that any declared dependency (an optional, forward-looking `dependencies`
# field skills may not use) is pinned, not a version range. A known-
# malicious-hash lookup is not implemented this phase — no such hash
# database exists yet in this codebase; disclosed here rather than a
# silent no-op that looks like a real check.
# ============================================================

from __future__ import annotations

import re
from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

_PINNED_VERSION_RE = re.compile(r"^\d+(\.\d+){1,2}$")


def run(dependencies: list[dict[str, Any]] | None = None) -> StageResult:
    findings: list[Finding] = []

    for dep in dependencies or []:
        version = dep.get("version", "")
        if not _PINNED_VERSION_RE.match(version):
            findings.append(Finding(
                stage="supply_chain", severity="block", code="UNPINNED_DEPENDENCY",
                message=f"dependency {dep.get('name')!r} is not pinned to an exact version (got {version!r})",
                details={"dependency": dep.get("name"), "version": version},
            ))

    verdict = "fail" if findings else "pass"
    return StageResult(verdict=verdict, findings=findings)
