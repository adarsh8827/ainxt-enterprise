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
from agents.key_leak_detector import detect_key_leaks
from agents.secret_detector import detect_secrets
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


def _scan_secrets_and_keys_always(texts: dict[str, str]) -> list[Finding]:
    """A real design gap found reviewing this diff: run() below's secret/
    key check goes through agents/compliance_engine.py's analyze(), which
    fails closed to a 'pending' verdict when COMPLIANCE_SERVICE_ENABLED is
    false (the shipped .env.example default) -- a deliberate, correct
    policy for the full async gate (see run()'s own comment: "an unscanned
    item must never look identical to a clean one"), but wrong for task
    D's fast path, whose whole premise is "<2s, no external dependency" --
    making its own success silently depend on an unrelated deployment flag
    would defeat that. detect_secrets()/detect_key_leaks() are themselves
    pure, local regex functions with no service dependency at all --
    compliance_engine.py only gates them behind COMPLIANCE_SERVICE_ENABLED
    as part of that shared engine's own on/off switch for its PII/PCI/ML
    layers, not because this specific detection needs one. Every finding
    here blocks outright -- no configurable block/warn/redact tiering
    (that's compliance_engine's own policy layer, deliberately not
    reproduced here, matching the fast path's own simple, static,
    no-config nature)."""
    findings: list[Finding] = []
    for rel_path, text in texts.items():
        for raw in [*detect_secrets(text), *detect_key_leaks(text)]:
            finding_type = raw.get("type", "SECRET_DETECTED")
            findings.append(Finding(
                stage="static_safety", severity="block", code=finding_type,
                message=f"{finding_type} detected in {rel_path}",
                details={"file": rel_path},
            ))
    return findings


def run_fast_path(files: dict[str, str], manifest_text: str = "") -> StageResult:
    """Task D's own static_safety check for the synchronous fast path --
    deliberately NOT run() below. Always static, always available, never
    'pending': the hidden-text/injection heuristic already has no external
    dependency, and _scan_secrets_and_keys_always() above gives secret/key
    detection the same property, independent of COMPLIANCE_SERVICE_ENABLED.
    The full async gate keeps calling run() below, unchanged -- this
    function's existence doesn't relax that path's own fail-closed policy
    at all, it only stops the fast path from inheriting a dependency it
    was explicitly specified not to have."""
    texts = dict(files)
    if manifest_text:
        texts["<manifest>"] = manifest_text
    findings = _scan_hidden_text_and_injection(texts) + _scan_secrets_and_keys_always(texts)
    verdict = "fail" if any(f.severity == "block" for f in findings) else "pass"
    return StageResult(verdict=verdict, findings=findings)


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

    # Degrade gracefully, not hang forever (product decision, 2026-10-06:
    # no compliance_engine deployment exists or is planned for this
    # install -- COMPLIANCE_SERVICE_ENABLED=false is permanent here, not a
    # transient deployment gap). Previously this resolved to 'pending'
    # unconditionally when the scanner was off, with the stated rationale
    # "an unscanned item must never look identical to a clean one" --
    # correct in principle, but it meant every Upload/Import (never
    # eligible for the write-flow's fast path) could NEVER finish
    # verification in an install with no scanner and no intent to add
    # one, silently stranding the item on "Verifying…" forever with no
    # retry that could ever succeed.
    #
    # The fix: fall back to the same pure, local, no-service-dependency
    # checks run_fast_path() above already uses
    # (_scan_secrets_and_keys_always() -- regex-based secret/key
    # detection, zero dependency on compliance_engine) instead of treating
    # "scanner off" as "nothing was checked at all". This is a real,
    # disclosed, lighter-weight check, not a silent pass: a SCANNER_
    # UNAVAILABLE info finding is still attached either way so the
    # Verification tab always shows explicitly that the full ML-based
    # engine wasn't available, never pretending a full scan happened.
    if not compliance_engine.enabled:
        findings.extend(_scan_secrets_and_keys_always(texts))
        if any(f.severity == "block" for f in findings):
            return StageResult(verdict="fail", findings=findings)
        findings.append(Finding(
            stage="static_safety", severity="info", code="SCANNER_UNAVAILABLE",
            message="Full compliance scanner (COMPLIANCE_SERVICE_ENABLED=false) is not configured in this environment — ran local hidden-text/injection/secret/key checks only, not the full ML-based scan.",
        ))
        return StageResult(verdict="pass", findings=findings)

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
