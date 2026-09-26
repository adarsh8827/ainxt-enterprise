# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.gate.license_stage import run


def test_mit_passes():
    assert run("MIT").verdict == "pass"


def test_apache_passes():
    assert run("Apache-2.0").verdict == "pass"


def test_gpl_fails():
    result = run("GPL-3.0-only")
    assert result.verdict == "fail"
    assert any(f.code == "LICENSE_NOT_ALLOWED" for f in result.findings)


def test_dual_license_with_mit_option_passes():
    assert run("MIT OR GPL-3.0-or-later").verdict == "pass"


def test_missing_license_fails():
    assert run("").verdict == "fail"


def test_own_license_passes_but_dependency_fails():
    result = run("MIT", dependencies=[{"name": "bad-dep", "license": "AGPL-3.0"}])
    assert result.verdict == "fail"
    assert any("bad-dep" in f.message for f in result.findings)


def test_no_warn_tier_ever():
    # License stage is pass/block only, never warn (task mandate).
    for license in ("MIT", "GPL-3.0", "", "Apache-2.0"):
        assert run(license).verdict in ("pass", "fail")
