# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from services.ecosystem.gate.sandbox_stage import run


def test_clean_python_passes():
    result = run({"scripts/hello.py": "import os\nprint(os.getcwd())"}, {})
    assert result.verdict == "pass"


def test_syntax_error_fails():
    result = run({"scripts/bad.py": "def f(:\n  pass"}, {})
    assert result.verdict == "fail"
    assert any(f.code == "SYNTAX_ERROR" for f in result.findings)


def test_unapproved_import_fails():
    result = run({"scripts/net.py": "import requests\nrequests.get('http://evil.com')"}, {})
    assert result.verdict == "fail"
    assert any(f.code == "UNAPPROVED_IMPORT" for f in result.findings)


def test_stdlib_import_allowed():
    result = run({"scripts/ok.py": "import json\nimport re\nimport sys"}, {})
    assert result.verdict == "pass"


def test_non_python_file_skips_import_check():
    # Documented scope limitation: .sh/.js files get no import-graph check.
    result = run({"scripts/hello.sh": "#!/bin/sh\ncurl http://evil.com"}, {})
    assert result.verdict == "pass"


def test_no_test_entrypoint_declared_skips_execution():
    result = run({"scripts/hello.py": "print(1)"}, {})
    assert result.verdict == "pass"
    assert not any(f.code in ("TEST_ENTRYPOINT_FAILED", "SANDBOX_IMAGE_MISSING") for f in result.findings)


@pytest.mark.docker
def test_test_entrypoint_actually_executes():
    files = {"scripts/verify.py": "print('ok')\nimport sys\nsys.exit(0)"}
    manifest = {"test": "scripts/verify.py"}
    result = run(files, manifest)
    # Either it actually ran and passed, or the sandbox image isn't present
    # locally (an infra skip, not a code failure) — both are acceptable
    # outcomes in an environment where the python:3.11-slim image may not
    # be pre-pulled; a real failure (verdict='fail' for a reason other than
    # a missing image) is not.
    if result.verdict == "fail":
        assert any(f.code == "TEST_ENTRYPOINT_FAILED" for f in result.findings)
        pytest.fail(f"test entrypoint execution failed unexpectedly: {result.findings}")
    else:
        assert result.verdict in ("pass", "warn")


@pytest.mark.docker
def test_test_entrypoint_failure_is_blocked():
    files = {"scripts/verify.py": "import sys\nsys.exit(1)"}
    manifest = {"test": "scripts/verify.py"}
    result = run(files, manifest)
    if any(f.code == "SANDBOX_IMAGE_MISSING" for f in result.findings):
        pytest.skip("sandbox image not available locally")
    assert result.verdict == "fail"
    assert any(f.code == "TEST_ENTRYPOINT_FAILED" for f in result.findings)


@pytest.mark.docker
def test_test_entrypoint_cannot_reach_network():
    # Exits 1 (fail) if the network turns out to be reachable, 0 (pass) if
    # it's correctly blocked — so a passing gate verdict here IS the
    # network-isolation assertion, not just "the script ran."
    files = {"scripts/verify.py": (
        "import sys, urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://example.com', timeout=3)\n"
        "    sys.exit(1)  # reachable -- isolation failed\n"
        "except Exception:\n"
        "    sys.exit(0)  # blocked, as expected\n"
    )}
    manifest = {"test": "scripts/verify.py"}
    result = run(files, manifest)
    if any(f.code == "SANDBOX_IMAGE_MISSING" for f in result.findings):
        pytest.skip("sandbox image not available locally")
    assert result.verdict in ("pass", "warn"), (
        f"network isolation test failed -- the sandboxed script reached the network: {result.findings}"
    )
