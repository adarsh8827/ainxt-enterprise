# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 6 — ethics & policy (docs/ecosystem/SKILLS_PHASE_PLAN.md task
# B-9; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 6/§11.1).
#
# A fresh-context call via models/model_router.py — never the same
# model/context that authored or reviewed the item. If the reviewer is
# unavailable (the router's generate() never raises; failure is signaled
# by the returned text being an "Error: ..." string), OR its response
# can't be parsed into a clear verdict, this resolves to 'pending' with a
# retry scheduled — never an implicit 'pass' (M0-review correction,
# applies identically to task B-22's builtin-skill seeding).
# ============================================================

from __future__ import annotations

import json
from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

_REVIEW_PROMPT_TEMPLATE = """You are reviewing an AI-platform skill for a marketplace gate. \
Assess it for harmful/deceptive/discriminatory intent, mismatch between its stated behavior \
and its description, overly broad trigger conditions, and excessive requested permissions.

Skill name: {name}
Skill description: {description}
Skill instructions:
{instructions}

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"verdict": "pass" | "warn" | "fail", "reason": "one sentence"}}
"""


def _build_prompt(manifest: dict[str, Any]) -> str:
    return _REVIEW_PROMPT_TEMPLATE.format(
        name=manifest.get("name", ""),
        description=manifest.get("description", ""),
        instructions=manifest.get("instructions", "")[:4000],
    )


def _parse_verdict(raw_output: str) -> dict[str, str] | None:
    try:
        parsed = json.loads(raw_output.strip())
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("verdict") not in ("pass", "warn", "fail"):
        return None
    return parsed


def run(manifest: dict[str, Any]) -> StageResult:
    from models.model_router import model_router

    prompt = _build_prompt(manifest)
    raw_output = model_router.generate(prompt)

    if not isinstance(raw_output, str) or raw_output.startswith("Error"):
        return StageResult(verdict="pending", findings=[Finding(
            stage="ethics", severity="info", code="REVIEWER_UNAVAILABLE",
            message="ethics reviewer model call failed — pending retry, not a pass",
            details={"raw_output": str(raw_output)[:500]},
        )])

    parsed = _parse_verdict(raw_output)
    if parsed is None:
        return StageResult(verdict="pending", findings=[Finding(
            stage="ethics", severity="info", code="REVIEWER_RESPONSE_UNPARSEABLE",
            message="ethics reviewer response could not be parsed into a verdict — pending retry, not a pass",
            details={"raw_output": raw_output[:500]},
        )])

    verdict = parsed["verdict"]
    findings = []
    if verdict != "pass":
        severity = "block" if verdict == "fail" else "warn"
        findings.append(Finding(
            stage="ethics", severity=severity, code="ETHICS_REVIEW_FLAGGED",
            message=parsed.get("reason", "flagged by ethics review"),
        ))
    return StageResult(verdict=verdict, findings=findings)
