# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 1 — manifest & structure (docs/ecosystem/SKILLS_PHASE_PLAN.md
# task B-8; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 1).
#
# agentskills.io-style rules for a skill manifest: name/description
# length+charset, no path traversal in bundled file names, size caps.
# ============================================================

from __future__ import annotations

import re
from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{1,63}$")
_MAX_DESCRIPTION_LEN = 1024
_MAX_FILE_COUNT = 8
_MAX_FILE_BYTES = 64 * 1024


def run(manifest: dict[str, Any], files: dict[str, str]) -> StageResult:
    findings: list[Finding] = []

    name = manifest.get("name", "")
    if not _NAME_RE.match(name):
        findings.append(Finding(
            stage="manifest", severity="block", code="INVALID_NAME",
            message="name must be 2-64 chars, alnum/space/hyphen/underscore, starting with alnum",
            details={"name": name},
        ))

    description = manifest.get("description", "")
    if not description:
        findings.append(Finding(
            stage="manifest", severity="block", code="MISSING_DESCRIPTION",
            message="description is required",
        ))
    elif len(description) > _MAX_DESCRIPTION_LEN:
        findings.append(Finding(
            stage="manifest", severity="block", code="DESCRIPTION_TOO_LONG",
            message=f"description exceeds {_MAX_DESCRIPTION_LEN} characters",
            details={"length": len(description)},
        ))

    if len(files) > _MAX_FILE_COUNT:
        findings.append(Finding(
            stage="manifest", severity="block", code="TOO_MANY_FILES",
            message=f"bundle has more than {_MAX_FILE_COUNT} files",
            details={"count": len(files)},
        ))

    for rel_path, content in files.items():
        # Path-traversal guard — this content already passed create_service's
        # own _safe_rel_path at upload time; this is defense in depth for the
        # write/import paths, which don't go through that same guard.
        if ".." in rel_path.split("/") or rel_path.startswith("/"):
            findings.append(Finding(
                stage="manifest", severity="block", code="UNSAFE_PATH",
                message=f"bundled file path {rel_path!r} is not allowed",
            ))
        if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
            findings.append(Finding(
                stage="manifest", severity="block", code="FILE_TOO_LARGE",
                message=f"{rel_path!r} exceeds {_MAX_FILE_BYTES // 1024}KB",
            ))

    verdict = "fail" if any(f.severity == "block" for f in findings) else "pass"
    return StageResult(verdict=verdict, findings=findings)
