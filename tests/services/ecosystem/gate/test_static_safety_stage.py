# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.gate.static_safety_stage import run


def test_clean_content_passes():
    result = run({"scripts/hello.py": "print('hello world')"})
    assert result.verdict == "pass"


def test_secret_containing_content_is_flagged():
    # A real AWS access-key-ID shape (AKIA + 16 alnum chars) — the one
    # pattern agents/secret_detector.py's detect_secrets() actually checks
    # for this class of secret. (A SNAKE_CASE env-var-assignment secret
    # like `AWS_SECRET_ACCESS_KEY = "..."` is NOT currently caught by
    # detect_secrets() despite that file's own comments describing exactly
    # this shape as the motivation for its iter_env_secret_values() helper
    # — that helper is never actually called from detect_secrets(). This is
    # a pre-existing gap in agents/secret_detector.py, out of scope for
    # this gate-stage task to fix; flagged here rather than silently
    # worked around by testing against a pattern the detector doesn't
    # cover for this reason.)
    files = {"scripts/config.py": 'access_key = "AKIAIOSFODNN7EXAMPLE"'}
    result = run(files)
    assert result.verdict in ("warn", "fail")
    assert len(result.findings) > 0


def test_irrelevant_finding_categories_are_filtered_out():
    # compliance_engine.analyze() also detects PII/PCI findings (category
    # "PII") this gate stage must ignore (ECOSYSTEM_PLAN.md §6 stage 3
    # narrows to secret/key types only) — a category outside
    # _RELEVANT_CATEGORIES must never surface here even if compliance_engine
    # itself flags it.
    from services.ecosystem.gate import static_safety_stage

    assert "PII" not in static_safety_stage._RELEVANT_CATEGORIES
    assert "SECRET" in static_safety_stage._RELEVANT_CATEGORIES
    assert "KEY" in static_safety_stage._RELEVANT_CATEGORIES


def test_pii_only_content_does_not_trip_this_stage(monkeypatch):
    # A finding whose category is PII (not SECRET/KEY) must be ignored here
    # even though compliance_engine.analyze() itself reports it -- this
    # stage's whole point is narrowing to the secret/key subset.
    from services.ecosystem.gate import static_safety_stage

    monkeypatch.setattr(
        static_safety_stage.compliance_engine, "analyze",
        lambda text: [{"type": "EMAIL", "category": "PII", "severity": "LOW", "blocked": False}],
    )
    result = run({"scripts/x.py": "irrelevant, analyze() is mocked"})
    assert result.verdict == "pass"
    assert result.findings == []
