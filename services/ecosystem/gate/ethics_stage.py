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
import re
from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

# Found live during M5's own manual smoke testing: the reviewer model
# reliably wraps its JSON verdict in a markdown code fence (```json ... ```
# or plain ``` ... ```) despite the prompt's explicit "ONLY a JSON object,
# no other text" instruction -- confirmed via direct EcosystemGateFinding.
# details.raw_output inspection, reproducibly, and correlating with
# response length/nuance (short, boilerplate content fenced roughly half
# the time; longer, more nuanced content fenced consistently). Every fence
# was previously an unconditional REVIEWER_RESPONSE_UNPARSEABLE -> stuck in
# "pending" forever (no automatic retry loop exists), making this the
# single highest-impact bug for this milestone's actual usability -- any
# real submission whose ethics review has anything substantive to say
# about it could never resolve.
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

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


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


def _parse_verdict(raw_output: str) -> dict[str, str] | None:
    candidate = _strip_code_fence(raw_output.strip()) if isinstance(raw_output, str) else raw_output
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, AttributeError, TypeError):
        # Last resort: the response has prose around the JSON object (not
        # just a fence) -- extract the outermost {...} span rather than
        # giving up. Still a real, reproducible model-output quirk, not a
        # hypothetical -- kept narrow (a single brace-to-brace slice, no
        # broader text mining) so this never accidentally accepts
        # something that merely *contains* a brace pair.
        start, end = candidate.find("{") if isinstance(candidate, str) else -1, candidate.rfind("}") if isinstance(candidate, str) else -1
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
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
