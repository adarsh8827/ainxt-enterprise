# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 2 — license (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-8;
# docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 2; §11.1's license policy).
#
# Pass/block only, no warn tier (task mandate, unconditional — this stage
# alone can never be overridden by --force or admin action). Checks the
# item's own declared license and every dependency in files/manifest that
# looks like a license declaration (a skill has no real dependency tree
# this phase, but a future plugin/MCP/connector item type will — the shape
# here already accepts an optional `dependencies` list so that extension
# doesn't require a signature change).
# ============================================================

from __future__ import annotations

from typing import Any

from services.ecosystem.gate.types import Finding, StageResult
from services.ecosystem.license_policy import is_allowed_license


def run(license: str, dependencies: list[dict[str, Any]] | None = None) -> StageResult:
    findings: list[Finding] = []

    if not is_allowed_license(license):
        findings.append(Finding(
            stage="license", severity="block", code="LICENSE_NOT_ALLOWED",
            message=f"license {license!r} is not MIT/Apache-2.0-compatible",
            details={"declared_license": license},
        ))

    for dep in dependencies or []:
        dep_license = dep.get("license")
        if not is_allowed_license(dep_license):
            findings.append(Finding(
                stage="license", severity="block", code="LICENSE_NOT_ALLOWED",
                message=f"dependency {dep.get('name')!r} has disallowed license {dep_license!r}",
                details={"dependency": dep.get("name"), "declared_license": dep_license},
            ))

    verdict = "fail" if findings else "pass"
    return StageResult(verdict=verdict, findings=findings)
