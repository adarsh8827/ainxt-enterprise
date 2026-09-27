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

import re
import unicodedata

from agents.compliance_engine import compliance_engine
from services.ecosystem.gate.types import Finding, StageResult

# Hidden-text / prompt-injection heuristic (task D, the gate's fast-path
# subset -- deliberately static/regex-only, no model call, so it stays
# fast enough for the <2s synchronous fast path AND runs unconditionally
# here (independent of COMPLIANCE_SERVICE_ENABLED, unlike the secret/key
# scan below) since it needs no external service. A first-pass heuristic,
# disclosed as such -- not a claim of catching every injection technique,
# matching this module's own documented style for scoped simplifications.
#
# Unicode category "Cf" (format) covers the common hidden-text vectors:
# zero-width space/joiner/non-joiner (U+200B-U+200D), word joiner
# (U+2060), BOM (U+FEFF), and the bidi override/isolate controls
# (U+202A-U+202E, U+2066-U+2069) attackers use to make text read
# differently to a human skimming it than to the model actually
# processing it.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore (all|any|the)?\s*(previous|prior|above)\s*instructions",
        r"disregard (all|any|the)?\s*(previous|prior|above)",
        r"you are (now|in) (developer|debug|jailbreak) mode",
        r"reveal (your|the) system prompt",
        r"do anything now\b",
    )
]


def _scan_hidden_text_and_injection(texts: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path, text in texts.items():
        hidden = sorted({c for c in text if unicodedata.category(c) == "Cf"})
        if hidden:
            findings.append(Finding(
                stage="static_safety", severity="block", code="HIDDEN_TEXT_DETECTED",
                message=f"hidden/invisible Unicode character(s) detected in {rel_path}",
                details={"file": rel_path, "codepoints": [f"U+{ord(c):04X}" for c in hidden]},
            ))
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                findings.append(Finding(
                    stage="static_safety", severity="block", code="PROMPT_INJECTION_PATTERN",
                    message=f"a known prompt-injection phrase was detected in {rel_path}",
                    details={"file": rel_path},
                ))
                break  # one finding per file for this check is enough signal
    return findings

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
    texts = dict(files)
    if manifest_text:
        texts["<manifest>"] = manifest_text

    # Always on, independent of COMPLIANCE_SERVICE_ENABLED -- a pure static
    # check with no external service dependency (task D's fast-path
    # requirement: this must be safe to run synchronously in the request
    # even when the deployment hasn't turned on the compliance service).
    findings: list[Finding] = _scan_hidden_text_and_injection(texts)

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
    # A hidden-text/injection finding above still fails outright even with
    # the secret/key scanner off -- that check never depended on it.
    if not compliance_engine.enabled:
        if any(f.severity == "block" for f in findings):
            return StageResult(verdict="fail", findings=findings)
        findings.append(Finding(
            stage="static_safety", severity="info", code="SCANNER_UNAVAILABLE",
            message="safety scanner unavailable (COMPLIANCE_SERVICE_ENABLED=false) — pending retry, not a pass",
        ))
        return StageResult(verdict="pending", findings=findings)

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
