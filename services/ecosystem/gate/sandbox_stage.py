# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 5 — hardened sandbox (docs/ecosystem/SKILLS_PHASE_PLAN.md task
# B-9). Precisely scoped for item_type=skill, per that task's own spec:
#
# 1. A syntax/import check of every bundled Python script file — parsed
#    with ast.parse(), every import target checked against a fixed
#    allowlist. A script that fails to parse or imports something
#    unapproved is a fail-severity finding, not a warning.
# 2. If (and only if) the manifest declares a test entrypoint
#    (manifest["test"], e.g. "scripts/verify.py"), that ONE file is
#    actually executed inside sandbox/ecosystem_gate_executor.py's
#    hardened profile (network always off, tmpfs-backed /sandbox,
#    read_only rootfs). No other bundled file is ever executed during
#    gating — an untested script is only ever run later, live, by a real
#    user's tool call, still confined to the same tool boundaries as any
#    other content, not a gate-time guarantee.
#
# Known, disclosed scope limitation: the import-allowlist check only
# applies to Python files (ast.parse() is Python-specific). .sh/.js
# bundled files get no import-graph check this phase — no shell/JS parser
# dependency is added to provide one, since none of this phase's builtin
# skills (task B-22) use non-Python scripts. A later phase adding real
# non-Python skill scripts should close this gap before relying on it.
# ============================================================

from __future__ import annotations

import ast
import sys
from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

# Stdlib modules a skill script may safely import. sys.stdlib_module_names
# (3.10+) is the authoritative list for whatever Python version this
# platform runs — never hand-maintained, so it can't drift from reality.
_STDLIB_MODULES = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

# Already-approved third-party modules a skill script may import, beyond
# the stdlib. Empty for this phase — no builtin skill (task B-22) needs a
# third-party import; extend deliberately, one module at a time, not by
# widening to "anything installed."
_APPROVED_THIRD_PARTY_MODULES: set[str] = set()

_ALL_APPROVED_MODULES = _STDLIB_MODULES | _APPROVED_THIRD_PARTY_MODULES


def _check_python_imports(rel_path: str, content: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(content, filename=rel_path)
    except SyntaxError as exc:
        return [Finding(
            stage="sandbox", severity="block", code="SYNTAX_ERROR",
            message=f"{rel_path} failed to parse: {exc}",
            details={"file": rel_path},
        )]

    for node in ast.walk(tree):
        module_names: list[str] = []
        if isinstance(node, ast.Import):
            module_names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_names = [node.module.split(".")[0]]

        for name in module_names:
            if name not in _ALL_APPROVED_MODULES:
                findings.append(Finding(
                    stage="sandbox", severity="block", code="UNAPPROVED_IMPORT",
                    message=f"{rel_path} imports unapproved module {name!r}",
                    details={"file": rel_path, "module": name},
                ))
    return findings


def run(files: dict[str, str], manifest: dict[str, Any]) -> StageResult:
    findings: list[Finding] = []

    for rel_path, content in files.items():
        if rel_path.endswith(".py"):
            findings.extend(_check_python_imports(rel_path, content))

    test_entrypoint = manifest.get("test")
    if test_entrypoint and test_entrypoint in files:
        from sandbox.ecosystem_gate_executor import ecosystem_gate_executor

        result = ecosystem_gate_executor.execute(
            code=files[test_entrypoint], language="python", network_enabled=False,
        )
        if result.get("image_missing"):
            findings.append(Finding(
                stage="sandbox", severity="warn", code="SANDBOX_IMAGE_MISSING",
                message="test entrypoint execution skipped — sandbox image not available locally",
                details={"entrypoint": test_entrypoint},
            ))
        elif not result["success"]:
            findings.append(Finding(
                stage="sandbox", severity="block", code="TEST_ENTRYPOINT_FAILED",
                message=f"test entrypoint {test_entrypoint!r} exited non-zero",
                details={"entrypoint": test_entrypoint, "output": result["output"][:2000]},
            ))

    verdict = "fail" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return StageResult(verdict=verdict, findings=findings)
