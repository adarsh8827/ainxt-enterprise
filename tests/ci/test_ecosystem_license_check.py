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
import subprocess
from pathlib import Path

import pytest

from scripts.ci.ecosystem_license_check import find_dependency_violations, find_violations


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


# ============================================================
# Dependency-manifest diff checks (task B-21, M0-fix item 3): a dependency
# newly added to requirements.txt/package.json since a base git ref must be
# recorded in the compliance TSV under an MIT/Apache-2.0-compatible license.
# ============================================================


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    return tmp_path


def _commit_base_state(repo_root: Path, requirements: str = "", compliance_tsv: str = "name\tversion\tlicense\n") -> None:
    _write(repo_root / "requirements.txt", requirements)
    _write(repo_root / "compliance/python-components.tsv", compliance_tsv)
    _git(repo_root, "add", "-A")
    _git(repo_root, "commit", "-q", "-m", "base")


def test_new_mit_dependency_passes(git_repo: Path):
    _commit_base_state(git_repo)
    _write(git_repo / "requirements.txt", "somepkg==1.0.0\n")
    _write(git_repo / "compliance/python-components.tsv", "name\tversion\tlicense\nsomepkg\t1.0.0\tMIT\n")
    assert find_dependency_violations(git_repo, base_ref="HEAD") == []


def test_new_apache_dependency_passes(git_repo: Path):
    _commit_base_state(git_repo)
    _write(git_repo / "requirements.txt", "somepkg==1.0.0\n")
    _write(git_repo / "compliance/python-components.tsv", "name\tversion\tlicense\nsomepkg\t1.0.0\tApache-2.0\n")
    assert find_dependency_violations(git_repo, base_ref="HEAD") == []


def test_new_gpl_dependency_fails(git_repo: Path):
    _commit_base_state(git_repo)
    _write(git_repo / "requirements.txt", "somepkg==1.0.0\n")
    _write(git_repo / "compliance/python-components.tsv", "name\tversion\tlicense\nsomepkg\t1.0.0\tGPL-3.0-only\n")
    violations = find_dependency_violations(git_repo, base_ref="HEAD")
    assert any(v[0] == "requirements.txt" and v[1] == "somepkg" for v in violations)


def test_new_dependency_missing_from_compliance_fails_closed(git_repo: Path):
    _commit_base_state(git_repo)
    _write(git_repo / "requirements.txt", "somepkg==1.0.0\n")
    # compliance TSV not updated at all -> fails closed, not a silent pass.
    violations = find_dependency_violations(git_repo, base_ref="HEAD")
    assert any(v[0] == "requirements.txt" and v[1] == "somepkg" and "no compliance record" in v[2] for v in violations)


def test_preexisting_dependency_unchanged_is_not_flagged(git_repo: Path):
    _commit_base_state(
        git_repo,
        requirements="somepkg==1.0.0\n",
        compliance_tsv="name\tversion\tlicense\nsomepkg\t1.0.0\tGPL-3.0-only\n",
    )
    # Not newly added since base_ref -> not this check's concern, even
    # though its license would fail the "new dependency" bar.
    assert find_dependency_violations(git_repo, base_ref="HEAD") == []


def test_new_dual_licensed_dependency_with_mit_option_passes(git_repo: Path):
    _commit_base_state(git_repo)
    _write(git_repo / "requirements.txt", "somepkg==1.0.0\n")
    _write(git_repo / "compliance/python-components.tsv", "name\tversion\tlicense\nsomepkg\t1.0.0\tMIT OR GPL-3.0-or-later\n")
    assert find_dependency_violations(git_repo, base_ref="HEAD") == []


def test_new_npm_dependency_checked_against_node_compliance_tsv(git_repo: Path):
    _write(git_repo / "ai-ui/package.json", json.dumps({"dependencies": {}}))
    _write(git_repo / "compliance/node-components.tsv", "name\tversion\tlicense\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "base")

    _write(git_repo / "ai-ui/package.json", json.dumps({"dependencies": {"some-npm-pkg": "^2.0.0"}}))
    _write(git_repo / "compliance/node-components.tsv", "name\tversion\tlicense\nsome-npm-pkg\t2.0.0\tISC\n")
    violations = find_dependency_violations(git_repo, base_ref="HEAD")
    assert any(v[0] == "ai-ui/package.json" and v[1] == "some-npm-pkg" for v in violations)
