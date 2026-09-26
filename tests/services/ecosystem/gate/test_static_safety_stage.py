# SPDX-License-Identifier: MIT
# ============================================================
# tests/services/ecosystem/conftest.py's package-wide autouse fixture
# forces compliance_engine.enabled=True for every test here except the
# scanner-disabled test below, which explicitly overrides it back to
# False for itself -- decouples these tests from whatever
# COMPLIANCE_SERVICE_ENABLED (default false, never set in CI) happens to
# be set to in the ambient environment.
# ============================================================

from __future__ import annotations

from services.ecosystem.gate.static_safety_stage import run


def test_clean_content_passes():
    result = run({"scripts/hello.py": "print('hello world')"})
    assert result.verdict == "pass"


def test_secret_containing_content_is_flagged():
    # A real AWS access-key-ID shape (AKIA + 16 alnum chars).
    files = {"scripts/config.py": 'access_key = "AKIAIOSFODNN7EXAMPLE"'}
    result = run(files)
    assert result.verdict in ("warn", "fail")
    assert len(result.findings) > 0


def test_snake_case_env_var_secret_assignment_is_flagged():
    # Item 3 (pre-M3): agents/secret_detector.py's detect_secrets() never
    # called its own iter_env_secret_values() helper, despite that file's
    # comments describing exactly this shape (a SNAKE_CASE env-var
    # assignment, e.g. AWS_SECRET_ACCESS_KEY=...) as the motivation for
    # writing it -- a real, pre-existing gap the gate's static_safety
    # stage inherited. Fixed in agents/secret_detector.py's detect_secrets()
    # (agents/secret_detector.py:236-244); this proves the fix reaches all
    # the way through compliance_engine.analyze() to this gate stage, not
    # just secret_detector.py in isolation.
    files = {"scripts/config.py": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}
    result = run(files)
    assert result.verdict in ("warn", "fail")
    assert any(f.code == "ENV_SECRET" for f in result.findings), (
        f"expected an ENV_SECRET finding, got: {result.findings}"
    )


def test_scanner_disabled_resolves_to_pending_never_pass(monkeypatch):
    # Fail-closed check (follow-up to item 3, pre-M3): with the scanner
    # off, this must never look identical to "scanned and clean".
    from services.ecosystem.gate import static_safety_stage

    monkeypatch.setattr(static_safety_stage.compliance_engine, "enabled", False)

    result = run({"scripts/config.py": 'access_key = "AKIAIOSFODNN7EXAMPLE"'})
    assert result.verdict == "pending"
    assert any(f.code == "SCANNER_UNAVAILABLE" for f in result.findings)


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
