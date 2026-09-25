# SPDX-License-Identifier: MIT
# ============================================================
# Ecosystem marketplace license-check CI job tests.
#
# Covers docs/ecosystem/SKILLS_PHASE_PLAN.md task B-21 — a fixture PR that
# introduces a disallowed license must fail; one that only touches
# allowlisted files must pass; one that touches packages/ecosystem-ui with
# a banned import must fail regardless of the allowlist.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.ecosystem_license_check import find_violations


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_allowlist(repo_root: Path, files: list[str]) -> None:
    _write(
        repo_root / ".ecosystem-license-allowlist.json",
        json.dumps({"package": "lucide-react", "files": files}),
    )


def test_allowlisted_file_passes(tmp_path: Path):
    _write_allowlist(tmp_path, ["ai-ui/src/components/Old.jsx"])
    _write(tmp_path / "ai-ui/src/components/Old.jsx", 'import { X } from "lucide-react";\n')
    assert find_violations(tmp_path) == []


def test_non_allowlisted_file_in_ai_ui_fails(tmp_path: Path):
    _write_allowlist(tmp_path, ["ai-ui/src/components/Old.jsx"])
    _write(tmp_path / "ai-ui/src/components/New.jsx", 'import { X } from "lucide-react";\n')
    violations = find_violations(tmp_path)
    assert ("ai-ui/src/components/New.jsx", "lucide-react") in violations


def test_ecosystem_ui_never_exempt_even_if_listed(tmp_path: Path):
    # Even if someone mistakenly adds a packages/ecosystem-ui path to the
    # allowlist, it must still fail — new code has no exceptions.
    _write_allowlist(tmp_path, ["packages/ecosystem-ui/src/Icon.tsx"])
    _write(tmp_path / "packages/ecosystem-ui/src/Icon.tsx", 'import { X } from "lucide-react";\n')
    violations = find_violations(tmp_path)
    assert ("packages/ecosystem-ui/src/Icon.tsx", "lucide-react") in violations


def test_file_without_banned_import_passes(tmp_path: Path):
    _write_allowlist(tmp_path, [])
    _write(tmp_path / "ai-ui/src/components/Clean.jsx", 'import { X } from "some-mit-package";\n')
    assert find_violations(tmp_path) == []


def test_missing_allowlist_file_treats_everything_as_non_allowlisted(tmp_path: Path):
    # No .ecosystem-license-allowlist.json at all -> nothing is exempt.
    _write(tmp_path / "ai-ui/src/components/New.jsx", 'import { X } from "lucide-react";\n')
    violations = find_violations(tmp_path)
    assert ("ai-ui/src/components/New.jsx", "lucide-react") in violations
