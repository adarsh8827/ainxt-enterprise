# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.gate.manifest_stage import run


def test_valid_manifest_passes():
    result = run({"name": "Good Skill", "description": "A fine description."}, {})
    assert result.verdict == "pass"


def test_missing_name_fails():
    result = run({"name": "", "description": "d"}, {})
    assert result.verdict == "fail"
    assert any(f.code == "INVALID_NAME" for f in result.findings)


def test_missing_description_fails():
    result = run({"name": "Good Skill", "description": ""}, {})
    assert result.verdict == "fail"
    assert any(f.code == "MISSING_DESCRIPTION" for f in result.findings)


def test_too_many_files_fails():
    files = {f"scripts/f{i}.py": "pass" for i in range(20)}
    result = run({"name": "Good Skill", "description": "d"}, files)
    assert result.verdict == "fail"
    assert any(f.code == "TOO_MANY_FILES" for f in result.findings)


def test_path_traversal_fails():
    result = run({"name": "Good Skill", "description": "d"}, {"../../etc/passwd": "x"})
    assert result.verdict == "fail"
    assert any(f.code == "UNSAFE_PATH" for f in result.findings)


def test_oversized_file_fails():
    result = run({"name": "Good Skill", "description": "d"}, {"scripts/big.py": "x" * (100 * 1024)})
    assert result.verdict == "fail"
    assert any(f.code == "FILE_TOO_LARGE" for f in result.findings)
