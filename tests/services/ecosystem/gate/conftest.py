# SPDX-License-Identifier: MIT
# ============================================================
# Every test under this directory exercises gate stage logic directly, in
# the same role the dedicated gate-worker process plays in production
# (docker-compose.yml's gate-worker service, workers/ecosystem_gate_worker.py).
# EcosystemGateExecutor refuses to touch Docker unless
# ECOSYSTEM_GATE_SANDBOX_ALLOWED is set (sandbox/ecosystem_gate_executor.py) —
# set it for this directory's tests so they exercise the real sandbox
# behavior rather than universally hitting the refusal path.
# ============================================================

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_gate_sandbox(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_GATE_SANDBOX_ALLOWED", "true")
