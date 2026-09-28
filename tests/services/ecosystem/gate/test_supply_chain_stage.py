# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.gate.supply_chain_stage import run


def test_no_dependencies_passes():
    assert run().verdict == "pass"
    assert run([]).verdict == "pass"


def test_pinned_dependency_passes():
    assert run([{"name": "foo", "version": "1.2.3"}]).verdict == "pass"


def test_unpinned_dependency_fails():
    result = run([{"name": "foo", "version": ">=1.0"}])
    assert result.verdict == "fail"
    assert any(f.code == "UNPINNED_DEPENDENCY" for f in result.findings)


def test_wildcard_dependency_fails():
    result = run([{"name": "foo", "version": "*"}])
    assert result.verdict == "fail"
