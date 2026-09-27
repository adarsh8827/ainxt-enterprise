# SPDX-License-Identifier: MIT
# Item 8 (real incident, 2026-09-27): a freshly-started gate-worker's first
# job could hang for RQ's blunt 300s job-level timeout because run_gate()'s
# own module dependency graph (including sandbox_stage.py's deliberately
# LAZY import of sandbox.ecosystem_gate_executor, which itself pulls in the
# real `docker` SDK) was never pre-imported before the worker started
# accepting jobs. workers.start_workers._warmup_gate_modules() fixes this.
from __future__ import annotations

import subprocess
import sys
import time

import pytest


def test_warmup_gate_modules_pulls_in_the_lazy_sandbox_executor_import():
    """The one real gap _warmup_gate_modules() exists to close:
    sandbox_stage.py's own docker-executor import is inside its run()
    function, not at module top level, specifically so that importing
    sandbox_stage alone (as gate_service.py's own top-level import already
    does) never touches Docker. Confirm the warmup function pulls it in
    anyway via its own explicit import."""
    if "sandbox.ecosystem_gate_executor" in sys.modules:
        pytest.skip(
            "another test in this same pytest run already imported this module "
            "(e.g. test_sandbox_stage.py exercising the real sandbox stage) -- "
            "can't prove _warmup_gate_modules() is what pulled it in when run "
            "in this order; run this file in isolation to actually exercise this claim"
        )
    from workers.start_workers import _warmup_gate_modules

    elapsed = _warmup_gate_modules()
    assert isinstance(elapsed, float) and elapsed >= 0
    assert "sandbox.ecosystem_gate_executor" in sys.modules
    assert "services.ecosystem.gate_service" in sys.modules
    assert "workers.ecosystem_gate_worker" in sys.modules


def test_warmup_gate_modules_is_idempotent_and_fast_the_second_time():
    from workers.start_workers import _warmup_gate_modules

    _warmup_gate_modules()  # first call may do real import work
    t0 = time.monotonic()
    elapsed = _warmup_gate_modules()
    wall = time.monotonic() - t0
    assert elapsed < 1.0  # sys.modules-cache hits only, no real re-import
    assert wall < 1.0


@pytest.mark.slow
def test_a_genuinely_cold_process_warms_up_in_a_bounded_time():
    """The real regression proof: a brand-new Python process (not this
    pytest process, which has already imported half the codebase by the
    time any test runs) importing everything run_gate() needs, timed
    end to end. Bounded generously (90s) since this includes real
    interpreter startup + SQLAlchemy ORM model registration + the real
    `docker` SDK import, not just the warmup function's own internal
    timing (measured ~44s on this dev machine) -- the actual claim under
    test is "bounded, finite, and nowhere near the old 300s job-level
    timeout that used to fire mid-job", not a tight specific number.
    """
    script = (
        "import time; t0 = time.monotonic(); "
        "from workers.start_workers import _warmup_gate_modules; "
        "_warmup_gate_modules(); "
        "print(time.monotonic() - t0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60, cwd=None,
    )
    assert result.returncode == 0, result.stderr
    wall_seconds = float(result.stdout.strip().splitlines()[-1])
    assert wall_seconds < 90.0, f"cold warmup took {wall_seconds:.1f}s -- investigate before trusting the fix"
