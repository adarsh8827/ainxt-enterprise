# SPDX-License-Identifier: MIT
# ============================================================
# agents/secret_detector.py tests. No existing test file for this module
# prior to item 3 (pre-M3, ecosystem marketplace phase) -- added alongside
# the fix that wires iter_env_secret_values() into detect_secrets()
# (agents/secret_detector.py:236-244).
# ============================================================

from __future__ import annotations

from agents.secret_detector import detect_secrets


def test_snake_case_env_var_secret_is_detected():
    # The exact motivating example from this module's own comments above
    # iter_env_secret_values() (agents/secret_detector.py:59) -- previously
    # silently missed because detect_secrets() never called that helper.
    text = "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    findings = detect_secrets(text)
    assert any(f["type"] == "ENV_SECRET" for f in findings)


def test_gitlab_token_env_var_secret_is_detected():
    text = "export GITLAB_TOKEN=glpat-abcdefghijklmnopqrst"
    findings = detect_secrets(text)
    assert any(f["type"] == "ENV_SECRET" for f in findings)


def test_aws_akia_pattern_still_detected():
    # Regression guard: the fix must not disturb the pre-existing patterns.
    findings = detect_secrets('access_key = "AKIAIOSFODNN7EXAMPLE"')
    assert any(f["type"] == "AWS_KEY" for f in findings)


def test_placeholder_env_var_value_is_not_flagged():
    # is_probable_secret_value()'s placeholder/entropy checks must still
    # suppress obvious non-secrets -- the new call must not turn every
    # NAME=value line into a finding.
    findings = detect_secrets("DATABASE_URL=changeme")
    assert not any(f["type"] == "ENV_SECRET" for f in findings)


def test_non_secret_env_var_name_is_not_flagged():
    findings = detect_secrets("LOG_LEVEL=debug")
    assert findings == []


def test_empty_text_returns_empty():
    assert detect_secrets("") == []
