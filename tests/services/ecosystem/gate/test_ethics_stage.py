# SPDX-License-Identifier: MIT
from __future__ import annotations

from unittest.mock import patch

from services.ecosystem.gate.ethics_stage import run

_MANIFEST = {"name": "Harmless Skill", "description": "does something benign", "instructions": "be nice"}


def test_reviewer_pass_verdict():
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        result = run(_MANIFEST)
    assert result.verdict == "pass"
    assert result.findings == []


def test_reviewer_warn_verdict_produces_finding():
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "warn", "reason": "borderline"}'):
        result = run(_MANIFEST)
    assert result.verdict == "warn"
    assert any(f.severity == "warn" for f in result.findings)


def test_reviewer_fail_verdict_blocks():
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "fail", "reason": "harmful"}'):
        result = run(_MANIFEST)
    assert result.verdict == "fail"
    assert any(f.severity == "block" for f in result.findings)


def test_reviewer_error_string_resolves_to_pending_never_pass():
    with patch("models.model_router.model_router.generate", return_value="Error: no gateway available"):
        result = run(_MANIFEST)
    assert result.verdict == "pending"
    assert any(f.code == "REVIEWER_UNAVAILABLE" for f in result.findings)


def test_reviewer_unparseable_response_resolves_to_pending_never_pass():
    with patch("models.model_router.model_router.generate", return_value="I refuse to answer in JSON."):
        result = run(_MANIFEST)
    assert result.verdict == "pending"
    assert any(f.code == "REVIEWER_RESPONSE_UNPARSEABLE" for f in result.findings)


def test_reviewer_none_response_resolves_to_pending_never_pass():
    with patch("models.model_router.model_router.generate", return_value=None):
        result = run(_MANIFEST)
    assert result.verdict == "pending"


def test_reviewer_invalid_verdict_value_resolves_to_pending():
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "maybe", "reason": "?"}'):
        result = run(_MANIFEST)
    assert result.verdict == "pending"
