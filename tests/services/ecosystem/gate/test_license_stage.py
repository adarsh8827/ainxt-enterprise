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


def test_no_warn_tier_ever_by_default():
    # License stage is pass/block only for every existing caller (task
    # mandate) -- relaxed=False is the default, never opted into silently.
    for license in ("MIT", "GPL-3.0", "", "Apache-2.0"):
        assert run(license).verdict in ("pass", "fail")


# ── relaxed=True (task C, ECOSYSTEM_PLAN.md §11.2's tiered license policy) ──
# Only ever set by gate_service.run_gate() when the gate run's own
# license_tier column says 'relaxed' -- i.e. create_service.py already
# re-validated a disallowed license under Tier 2/3's own rules. Never a
# default any existing caller opts into.

def test_relaxed_allowed_license_still_just_passes():
    assert run("MIT", relaxed=True).verdict == "pass"


def test_relaxed_disallowed_license_warns_not_fails():
    result = run("GPL-3.0-only", relaxed=True)
    assert result.verdict == "warn"
    assert any(f.code == "LICENSE_WARNING_PRIVATE_SCOPE" and f.severity == "warn" for f in result.findings)
    assert not any(f.severity == "block" for f in result.findings)


def test_relaxed_still_fails_for_a_disallowed_dependency():
    # Tier 3's relaxation is scoped to the item's OWN declared license only
    # (ECOSYSTEM_PLAN.md §11.2) -- a bundled dependency's own disallowed
    # license still blocks even when the caller's own license is relaxed.
    result = run("GPL-3.0-only", dependencies=[{"name": "bad-dep", "license": "AGPL-3.0"}], relaxed=True)
    assert result.verdict == "fail"
    assert any(f.severity == "block" and "bad-dep" in f.message for f in result.findings)
