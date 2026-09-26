# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 3 — static safety scan (docs/ecosystem/SKILLS_PHASE_PLAN.md
# task B-8; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 3).
#
# Reuses agents/compliance_engine.py's analyze() (the same engine already
# proven for chat-message PII/secret scanning), narrowed to only the
# secret/key-leak finding types — the PCI/Indian-ID detector types are
# irrelevant to a skill bundle and would just be noise here.
# ============================================================

from __future__ import annotations

from agents.compliance_engine import compliance_engine
from services.ecosystem.gate.types import Finding, StageResult

# Filtered by CATEGORY, not the more granular "type" field — verified
# directly against agents/compliance_engine.py's analyze() output (not the
# ECOSYSTEM_PLAN.md task text's own named list, which cites type-looking
# strings — SECRET/API_KEY/ACCESS_TOKEN/PRIVATE_KEY_LEAK/CERTIFICATE_LEAK/
# SSH_KEY_LEAK/KEY_ASSIGNMENT_LEAK — that don't all actually match what the
# underlying detectors emit as "type": detect_secrets() tags findings
# AWS_KEY/JWT_TOKEN/API_KEY/BEARER_TOKEN/STRIPE_KEY/PRIVATE_KEY under
# category="SECRET"; detect_key_leaks() tags PRIVATE_KEY_LEAK/
# CERTIFICATE_LEAK/SSH_KEY_LEAK/KEY_ASSIGNMENT_LEAK under category="KEY".
# Filtering on category="SECRET"|"KEY" captures the full, correct set the
# task actually intends (every secret/key-leak type) without depending on
# exact "type" spellings that may not match reality one-for-one, and
# without needing to enumerate every current and future type string by hand.
_RELEVANT_CATEGORIES = {"SECRET", "KEY"}


def run(files: dict[str, str], manifest_text: str = "") -> StageResult:
    # Fail-closed, not fail-open (follow-up to item 3, pre-M3): when the
    # underlying scanner is off (COMPLIANCE_SERVICE_ENABLED=false, default
    # -- core/config.py, checked via compliance_engine.enabled, e.g.
    # agents/compliance_engine.py:167/281), compliance_engine.analyze()
    # returns [] unconditionally (agents/compliance_engine.py:410-412),
    # which this stage's own verdict logic (findings empty -> "pass",
    # below) previously could not tell apart from "scanned and clean".
    # An unscanned item must never look identical to a clean one -- same
    # rule ethics_stage.py already applies when its reviewer is
    # unavailable: resolve to 'pending' with a clear finding, never an
    # implicit 'pass'. Does not change COMPLIANCE_SERVICE_ENABLED's
    # default; a deployment that wants this stage to scan anything still
    # has to turn that flag on itself (docs/ecosystem/design/LLD/gate.md).
    if not compliance_engine.enabled:
        return StageResult(verdict="pending", findings=[Finding(
            stage="static_safety", severity="info", code="SCANNER_UNAVAILABLE",
            message="safety scanner unavailable (COMPLIANCE_SERVICE_ENABLED=false) — pending retry, not a pass",
        )])

    findings: list[Finding] = []

    texts = dict(files)
    if manifest_text:
        texts["<manifest>"] = manifest_text

    for rel_path, text in texts.items():
        for raw_finding in compliance_engine.analyze(text):
            if raw_finding.get("category") not in _RELEVANT_CATEGORIES:
                continue
            severity = "block" if raw_finding.get("blocked") else "warn"
            findings.append(Finding(
                stage="static_safety", severity=severity, code=raw_finding["type"],
                message=f"{raw_finding['type']} detected in {rel_path}",
                details={"file": rel_path, "category": raw_finding.get("category")},
            ))

    if any(f.severity == "block" for f in findings):
        verdict = "fail"
    elif findings:
        verdict = "warn"
    else:
        verdict = "pass"
    return StageResult(verdict=verdict, findings=findings)
