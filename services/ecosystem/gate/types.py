# SPDX-License-Identifier: MIT
"""Shared shapes for gate stages (docs/ecosystem/ECOSYSTEM_PLAN.md §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    stage: str
    severity: str  # 'info' | 'warn' | 'block' — matches ecosystem_gate_findings.severity
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    verdict: str  # 'pass' | 'warn' | 'fail' | 'pending'
    findings: list[Finding] = field(default_factory=list)
