# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.gate.mcp_connector_stage import run


def test_always_passes_for_skill():
    result = run("skill", {"name": "x", "description": "y"})
    assert result.verdict == "pass"
    assert result.findings == []
