# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 2 — license (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-8;
# docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 2; §11.1's license policy).
#
# Pass/block only by default (task mandate, unconditional -- this stage
# alone can never be overridden by --force or admin action for the normal,
# strict path every existing caller uses). The one exception is the
# `relaxed` kwarg added by task C's tiered license policy (§11.2 below) --
# never on by default, only ever set by a caller that has already
# re-validated the license under Tier 2/3's own rules. Checks the item's
# own declared license and every dependency in files/manifest that looks
# like a license declaration (a skill has no real dependency tree this
# phase, but a future plugin/MCP/connector item type will — the shape here
# already accepts an optional `dependencies` list so that extension
# doesn't require a signature change).
# ============================================================

from __future__ import annotations

from typing import Any

from services.ecosystem.gate.types import Finding, StageResult
from services.ecosystem.license_policy import is_allowed_license


def run(license: str, dependencies: list[dict[str, Any]] | None = None, *, relaxed: bool = False) -> StageResult:
    """relaxed=True (docs/ecosystem/ECOSYSTEM_PLAN.md §11.2's tiered policy,
    task C): the item's OWN declared license failing is_allowed_license()
    was already accepted upstream -- either Tier 3 (private scope, caller
    acknowledged) or Tier 2 (org's own allowed_licenses_shared list permits
    it) -- services/ecosystem/gate_service.py resolves which and persists
    it as the gate run's own `license_tier` column, since this stage runs
    async in the gate-worker and can't re-derive that decision itself.
    A 'warn' finding records it either way; only ever set by the caller
    that already re-validated the license, never a default any existing
    caller (import pre-check, catalog sync, CI, builtin/optional seeding)
    opts into. Dependency-license checks below are deliberately NOT
    relaxed by this flag -- Tier 3's spec text covers only "the item's own
    declared license"; a skill has no real dependency tree this phase
    anyway (see module docstring)."""
    findings: list[Finding] = []

    if not is_allowed_license(license):
        if relaxed:
            findings.append(Finding(
                stage="license", severity="warn", code="LICENSE_WARNING_PRIVATE_SCOPE",
                message=f"license {license!r} is not MIT/Apache-2.0-compatible -- allowed here under a tiered exception, not a global pass",
                details={"declared_license": license},
            ))
        else:
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

    if any(f.severity == "block" for f in findings):
        verdict = "fail"
    elif any(f.severity == "warn" for f in findings):
        verdict = "warn"
    else:
        verdict = "pass"
    return StageResult(verdict=verdict, findings=findings)
