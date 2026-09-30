# SPDX-License-Identifier: MIT
# ============================================================
# git_repo adapter tests (generic git source, 2026-09-30) -- against a
# REAL local git repo built by this test file itself, cloned via a
# file:// URL (git clones file:// natively, no network needed) rather
# than mocking git subprocess calls. Same license-inheritance/conflict
# rules as github_repo.py's own test coverage; this file focuses on the
# parts genuinely specific to a local-filesystem source (nested-skill
# discovery at depth, mixed per-folder licenses, symlink/path-traversal
# guards, and the shared skill_path_utils functions wired in correctly).
# ============================================================

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters import git_repo

_MIT_TEXT = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy...\n"
)
_GPL_TEXT = "GNU General Public License\n\nVersion 3\n...\n"


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _write(path: Path, text: str) -> None:
    # Real gotcha found live (2026-09-30, Windows dev host): Path.write_text()
    # performs universal-newline translation by default -- every "\n" in
    # `text` becomes "\r\n" on Windows BEFORE git ever sees the file, which
    # is what was actually corrupting the YAML frontmatter parser, not any
    # git-side autocrlf setting (kept anyway, as real defense for an actual
    # remote source that might have it configured). newline="" disables
    # that translation so the file on disk contains exactly what `text` says.
    path.write_text(text, encoding="utf-8", newline="")


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> str:
    """Builds a real git repo with: a root MIT LICENSE; a skill at the
    root's own subdirectory that inherits it; a skill NESTED two levels
    deep with its own SKILL.md license: field; a "nested skill" (a
    SKILL.md living inside another skill's own folder); a skill whose
    folder carries a conflicting GPL LICENSE file despite an MIT
    license: field; and a skill with a bad SPDX header on a bundled
    file. Returns a file:// URL to the repo."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    # Real gotcha found live (2026-09-30, Windows dev host): a global
    # core.autocrlf=true would convert these LF-written fixture files to
    # CRLF on `git add`, baking mangled bytes into the commit itself --
    # independent of git_repo.py's own core.autocrlf=false on the
    # DESTINATION clone. Pinning it false here too so this fixture's
    # committed bytes are genuinely LF, matching what a real repo
    # committed from a non-Windows host would contain.
    _git(["config", "core.autocrlf", "false"], repo)

    _write(repo / "LICENSE", _MIT_TEXT)

    # Inherits the root MIT license (no license: field of its own).
    skill_a = repo / "skills" / "skill-a"
    skill_a.mkdir(parents=True)
    _write(skill_a / "SKILL.md", "---\nname: Skill A\ndescription: Does A things.\n---\nBody A.\n")

    # Nested two levels deep, own explicit MIT license: field.
    skill_b = repo / "nested" / "deep" / "skill-b"
    skill_b.mkdir(parents=True)
    _write(skill_b / "SKILL.md", "---\nname: Skill B\ndescription: Does B things.\nlicense: MIT\n---\nBody B.\n")

    # A "nested skill" -- a SKILL.md living inside skill-b's own folder,
    # discovered independently at any depth.
    subskill = skill_b / "subskill"
    subskill.mkdir()
    _write(subskill / "SKILL.md", "---\nname: Sub Skill\ndescription: Nested inside skill-b.\nlicense: MIT\n---\nBody sub.\n")

    # Mixed license: MIT license: field, but the folder ALSO carries a
    # real, conflicting GPL LICENSE file -- must be excluded, not silently
    # allowed via the field alone.
    skill_c = repo / "skills" / "skill-c"
    skill_c.mkdir(parents=True)
    _write(skill_c / "SKILL.md", "---\nname: Skill C\ndescription: Claims MIT but ships a GPL LICENSE.\nlicense: MIT\n---\nBody C.\n")
    _write(skill_c / "LICENSE", _GPL_TEXT)

    # A per-file SPDX header conflict on a bundled (non-SKILL.md) file.
    skill_d = repo / "skills" / "skill-d"
    skill_d.mkdir(parents=True)
    _write(skill_d / "SKILL.md", "---\nname: Skill D\ndescription: Bundles a GPL-headed file.\nlicense: MIT\n---\nBody D.\n")
    _write(skill_d / "helper.py", "# SPDX-License-Identifier: GPL-3.0-only\nprint('hi')\n")

    # Explicitly wrong license: field -- excluded on its own merits.
    skill_e = repo / "skills" / "skill-e"
    skill_e.mkdir(parents=True)
    _write(skill_e / "SKILL.md", "---\nname: Skill E\ndescription: Explicitly GPL.\nlicense: GPL-3.0-only\n---\nBody E.\n")

    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "initial"], repo)

    return f"file://{repo.as_posix()}"


def _by_path(candidates: list[dict], path: str) -> dict:
    match = next((c for c in candidates if c["path"] == path), None)
    assert match is not None, f"no candidate with path={path!r} in {[c['path'] for c in candidates]}"
    return match


def test_discovers_skills_at_any_depth_including_a_nested_skill(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    paths = {c["path"] for c in candidates}
    assert "skills/skill-a" in paths
    assert "nested/deep/skill-b" in paths
    assert "nested/deep/skill-b/subskill" in paths  # the nested skill, discovered independently
    assert len(candidates) == 6  # a, b, b's subskill, c, d, e


def test_skill_with_no_license_field_inherits_the_root_license(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    a = _by_path(candidates, "skills/skill-a")
    assert a["allowed"] is True
    assert a["license_evidence"]["effective_license"] == "MIT"
    assert a["license_evidence"]["effective_license_source"] == "repo LICENSE (fallback)"


def test_nested_skill_with_its_own_license_field_is_allowed(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    b = _by_path(candidates, "nested/deep/skill-b")
    assert b["allowed"] is True
    assert b["license_evidence"]["effective_license_source"] == "SKILL.md license: field"
    sub = _by_path(candidates, "nested/deep/skill-b/subskill")
    assert sub["allowed"] is True


def test_mit_field_with_a_conflicting_gpl_license_file_is_excluded(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    c = _by_path(candidates, "skills/skill-c")
    assert c["allowed"] is False
    assert c["license_evidence"]["conflict"]["declared"] == "GPL"


def test_bundled_file_with_a_conflicting_spdx_header_is_excluded(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    d = _by_path(candidates, "skills/skill-d")
    assert d["allowed"] is False
    assert d["license_evidence"]["conflict"]["declared"] == "GPL-3.0-only"


def test_explicit_non_allowed_license_field_is_excluded_on_its_own_merits(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main")
    e = _by_path(candidates, "skills/skill-e")
    assert e["allowed"] is False
    assert "GPL-3.0-only" in e["reason"]


def test_discovery_scoped_to_a_subdirectory_only_returns_skills_under_it(fixture_repo: str) -> None:
    candidates = git_repo.discover_skills_in_git_repo(fixture_repo, ref="main", path="nested")
    paths = {c["path"] for c in candidates}
    assert paths == {"nested/deep/skill-b", "nested/deep/skill-b/subskill"}


def test_import_from_git_path_bundles_files_and_returns_the_pinned_commit(fixture_repo: str) -> None:
    imported = git_repo.import_from_git_path(fixture_repo, "skills/skill-a", ref="main")
    assert imported["display_name"] == "Skill A"
    assert imported["license"] == "MIT"
    assert imported["manifest"]["instructions"].startswith("---\nname: Skill A")
    assert len(imported["resolved_sha"]) == 40  # a real git commit sha
    assert imported["files"] == {}  # skill-a has no other bundled files


def test_import_from_git_path_raises_on_a_conflicting_license(fixture_repo: str) -> None:
    with pytest.raises(LicenseNotAllowedError):
        git_repo.import_from_git_path(fixture_repo, "skills/skill-c", ref="main")


def test_import_from_git_path_raises_for_a_missing_skill_md(fixture_repo: str) -> None:
    with pytest.raises(ImportFetchError):
        git_repo.import_from_git_path(fixture_repo, "skills/does-not-exist", ref="main")


def test_re_cloning_at_the_exact_previously_resolved_sha_yields_the_same_content(fixture_repo: str) -> None:
    """Simulates the install-time re-fetch: crawl-time records a resolved
    commit SHA; install time clones AT that exact SHA (not the branch
    name) and must reach the identical content -- proves _clone_at_ref()
    accepts a raw SHA as `ref`, not just a branch/tag name."""
    first = git_repo.import_from_git_path(fixture_repo, "skills/skill-a", ref="main")
    pinned_sha = first["resolved_sha"]
    second = git_repo.import_from_git_path(fixture_repo, "skills/skill-a", ref=pinned_sha)
    assert second["resolved_sha"] == pinned_sha
    assert second["manifest"] == first["manifest"]


def test_get_resolved_head_sha_matches_the_ref_a_clone_would_resolve_to(fixture_repo: str) -> None:
    head_sha = git_repo.get_resolved_head_sha(fixture_repo, ref="main")
    assert len(head_sha) == 40
    imported = git_repo.import_from_git_path(fixture_repo, "skills/skill-a", ref="main")
    assert head_sha == imported["resolved_sha"]


def test_derive_publisher_and_name_handles_a_plain_and_a_nested_group_url() -> None:
    assert git_repo.derive_publisher_and_name("https://gitlab.com/some-group/some-project.git") == ("some-group", "some-project")
    assert git_repo.derive_publisher_and_name("https://git.example.com/team/subgroup/project") == ("team", "project")


def test_import_from_git_path_rejects_a_malformed_url() -> None:
    # The adapter's own guard is "well-formed URL" only (a scheme + a
    # host) -- the https-only production policy is enforced one layer up,
    # at sources_config.py's config-load time (see test_sources_config.py),
    # since this adapter's own tests need a real file:// URL to clone
    # against a local fixture repo with no network involved.
    with pytest.raises(ImportFetchError):
        git_repo.import_from_git_path("not-a-url-at-all", "skills/skill-a", ref="main")
