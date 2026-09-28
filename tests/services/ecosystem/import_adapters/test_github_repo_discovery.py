# SPDX-License-Identifier: MIT
# ============================================================
# github_repo adapter -- subdirectory discovery/import extension
# (discover_skills_in_repo / import_from_github_path). No live network:
# connectors.net_relay.relay_request is monkeypatched to an ordered list
# of (predicate, response) fixtures, since these tests need to distinguish
# many more distinct URLs (repo meta, commit, git tree, several distinct
# /contents/<path> fetches) than a simple substring-precedence dispatcher
# (test_github_repo.py's own _install_relay) comfortably supports.
# ============================================================

from __future__ import annotations

import base64
import json

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_repo


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://api.github.com/fixture"),
    )


def _content_response(text: str) -> httpx.Response:
    return _json_response(200, {
        "type": "file",
        "size": len(text.encode("utf-8")),
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    })


def _skill_md(name: str, license_field: str = "MIT") -> str:
    return f"---\nname: {name}\ndescription: A test skill.\nlicense: {license_field}\n---\nDo the thing.\n"


_MIT_LICENSE_TEXT = (
    "MIT License\n\nCopyright (c) 2026 Example\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy...\n"
)


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(github_repo, "assert_safe_https_url", lambda url: url)


@pytest.fixture(autouse=True)
def _bypass_fetch_cache(monkeypatch):
    # These tests care about which URLs get hit; the Redis-backed fetch
    # cache is orthogonal (already covered by test_github_repo.py's own
    # cache test) and would make repeated content fetches across the
    # git-tree + per-skill-file calls order-dependent on prior test runs.
    monkeypatch.setattr(github_repo, "get_cached", lambda identity: None)
    monkeypatch.setattr(github_repo, "put_cached", lambda identity, content: None)


def _install_relay(monkeypatch, rules: list[tuple[str, httpx.Response]]):
    """rules: ordered list of (substring, response) -- first substring
    match (checked longest-first to avoid a short path like '/contents/x'
    shadowing '/contents/x/y') wins. Raises if nothing matches, so a typo'd
    fixture URL fails loudly instead of silently returning the wrong body.
    """
    ordered = sorted(rules, key=lambda r: -len(r[0]))

    def _fake_relay(method, url, **kwargs):
        for substring, resp in ordered:
            if substring in url:
                return resp
        raise AssertionError(f"no fixture response registered for {url!r}")

    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)


def _no_calls_allowed(monkeypatch):
    def _fake_relay(method, url, **kwargs):
        raise AssertionError(f"no network call should happen for a rejected path, got {url!r}")

    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)


def test_discovers_multiple_skills_across_subdirectories(monkeypatch):
    sha = "1" * 40
    tree = {
        "truncated": False,
        "tree": [
            {"path": "skills/alpha/SKILL.md", "type": "blob"},
            {"path": "skills/alpha/LICENSE", "type": "blob"},
            {"path": "skills/beta/SKILL.md", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ],
    }
    _install_relay(monkeypatch, [
        ("/repos/acme/collection/git/trees/", _json_response(200, tree)),
        ("/repos/acme/collection/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/collection", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/skills/alpha/SKILL.md?ref={sha}", _content_response(_skill_md("Alpha Skill"))),
        (f"/contents/skills/alpha/LICENSE?ref={sha}", _content_response(_MIT_LICENSE_TEXT)),
        (f"/contents/skills/beta/SKILL.md?ref={sha}", _content_response(_skill_md("Beta Skill"))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/collection")

    assert {c["path"] for c in candidates} == {"skills/alpha", "skills/beta"}
    assert all(c["allowed"] for c in candidates)
    assert all(c["resolved_sha"] == sha for c in candidates)


def test_folder_mit_license_overrides_gpl_repo_license(monkeypatch):
    # No SKILL.md license: field -- isolates the folder-LICENSE-vs-repo-
    # license fallback behavior (a present field would win outright per
    # the inheritance order and never even consult either of these).
    sha = "2" * 40
    tree = {"truncated": False, "tree": [
        {"path": "tools/one/SKILL.md", "type": "blob"},
        {"path": "tools/one/LICENSE", "type": "blob"},
    ]}
    _install_relay(monkeypatch, [
        ("/repos/acme/gpl-with-mit-skill/git/trees/", _json_response(200, tree)),
        ("/repos/acme/gpl-with-mit-skill/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/gpl-with-mit-skill", _json_response(200, {"license": {"spdx_id": "GPL-3.0"}, "default_branch": "main"})),
        (f"/contents/tools/one/SKILL.md?ref={sha}", _content_response(_skill_md("One", license_field=""))),
        (f"/contents/tools/one/LICENSE?ref={sha}", _content_response(_MIT_LICENSE_TEXT)),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/gpl-with-mit-skill")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is True
    assert c["license_evidence"]["effective_license_source"] == "LICENSE file at 'tools/one/LICENSE'"
    assert c["license_evidence"]["effective_license"] == "MIT"
    assert c["license_evidence"]["repo_license"] == "GPL-3.0"


def test_falls_back_to_repo_license_when_no_folder_license_and_repo_is_mit(monkeypatch):
    sha = "3" * 40
    tree = {"truncated": False, "tree": [{"path": "tools/two/SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/mit-repo-no-folder-license/git/trees/", _json_response(200, tree)),
        ("/repos/acme/mit-repo-no-folder-license/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/mit-repo-no-folder-license", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/tools/two/SKILL.md?ref={sha}", _content_response(_skill_md("Two", license_field=""))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/mit-repo-no-folder-license")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is True
    assert c["license_evidence"]["effective_license_source"] == "repo LICENSE (fallback)"
    assert c["license_evidence"]["effective_license"] == "MIT"


def test_excluded_when_no_folder_license_and_repo_is_gpl(monkeypatch):
    sha = "4" * 40
    tree = {"truncated": False, "tree": [{"path": "tools/three/SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/all-gpl/git/trees/", _json_response(200, tree)),
        ("/repos/acme/all-gpl/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/all-gpl", _json_response(200, {"license": {"spdx_id": "GPL-3.0"}, "default_branch": "main"})),
        (f"/contents/tools/three/SKILL.md?ref={sha}", _content_response(_skill_md("Three", license_field=""))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/all-gpl")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is False
    assert "effective license" in c["reason"]
    assert "GPL-3.0" in c["reason"]


def test_included_when_repo_is_mit_and_skill_md_has_no_license_field_at_all(monkeypatch):
    # The real live finding this whole inheritance rewrite was for: a
    # genuinely-MIT repo whose SKILL.md files never bothered with a
    # redundant per-skill `license:` field must NOT be rejected just for
    # that omission -- confirmed live against a real 25-skill MIT repo
    # before this fix landed (every one of the 25 was wrongly excluded).
    sha = "b" * 40
    tree = {"truncated": False, "tree": [{"path": "skills/no-field/SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/real-world-mit-collection/git/trees/", _json_response(200, tree)),
        ("/repos/acme/real-world-mit-collection/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/real-world-mit-collection", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/skills/no-field/SKILL.md?ref={sha}", _content_response(_skill_md("NoField", license_field=""))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/real-world-mit-collection")

    assert len(candidates) == 1
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license_source"] == "repo LICENSE (fallback)"


def test_excluded_when_skill_md_license_field_is_gpl_despite_mit_folder_and_repo(monkeypatch):
    sha = "5" * 40
    tree = {"truncated": False, "tree": [{"path": "tools/four/SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/mixed-skill-license/git/trees/", _json_response(200, tree)),
        ("/repos/acme/mixed-skill-license/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/mixed-skill-license", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/tools/four/SKILL.md?ref={sha}", _content_response(_skill_md("Four", license_field="GPL-3.0-only"))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/mixed-skill-license")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is False
    assert "SKILL.md license: field" in c["reason"]
    assert "GPL-3.0-only" in c["reason"]


def test_excluded_when_skill_md_field_is_mit_but_its_own_folder_license_file_is_gpl(monkeypatch):
    # The field "wins" per the inheritance order, but a REAL, concrete
    # conflict sitting right alongside it (its own folder's actual LICENSE
    # file) must still block the skill -- otherwise a skill could declare
    # "license: MIT" in frontmatter while shipping an actual GPL LICENSE
    # file in the same folder, uncaught.
    sha = "c" * 40
    tree = {"truncated": False, "tree": [
        {"path": "tools/five/SKILL.md", "type": "blob"},
        {"path": "tools/five/LICENSE", "type": "blob"},
    ]}
    _install_relay(monkeypatch, [
        ("/repos/acme/field-says-mit-folder-says-gpl/git/trees/", _json_response(200, tree)),
        ("/repos/acme/field-says-mit-folder-says-gpl/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/field-says-mit-folder-says-gpl", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/tools/five/SKILL.md?ref={sha}", _content_response(_skill_md("Five", license_field="MIT"))),
        (f"/contents/tools/five/LICENSE?ref={sha}", _content_response("GNU GENERAL PUBLIC LICENSE\nVersion 3\n")),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/field-says-mit-folder-says-gpl")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is False
    assert "tools/five/LICENSE" in c["reason"]
    assert "GPL" in c["reason"]


def test_path_traversal_in_scope_path_is_rejected_with_no_network_call(monkeypatch):
    _no_calls_allowed(monkeypatch)

    with pytest.raises(ImportFetchError, match="invalid or traversal"):
        github_repo.discover_skills_in_repo("acme/whatever", path="../../etc")


def test_truncated_tree_response_is_surfaced_not_silently_ignored(monkeypatch):
    sha = "6" * 40
    tree = {"truncated": True, "tree": [{"path": "SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/huge-repo/git/trees/", _json_response(200, tree)),
        ("/repos/acme/huge-repo/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/huge-repo", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
    ])

    with pytest.raises(ImportFetchError, match="truncated"):
        github_repo.discover_skills_in_repo("acme/huge-repo")


def test_import_from_github_path_bundles_only_its_own_folders_files(monkeypatch):
    sha = "7" * 40
    tree = {"truncated": False, "tree": [
        {"path": "skills/full/SKILL.md", "type": "blob"},
        {"path": "skills/full/references/notes.md", "type": "blob"},
        {"path": "skills/full/scripts/run.py", "type": "blob"},
        {"path": "skills/other/SKILL.md", "type": "blob"},
        {"path": "skills/other/data.txt", "type": "blob"},
    ]}
    _install_relay(monkeypatch, [
        ("/repos/acme/bundle-repo/git/trees/", _json_response(200, tree)),
        ("/repos/acme/bundle-repo/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/bundle-repo", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/skills/full/SKILL.md?ref={sha}", _content_response(_skill_md("Full"))),
        (f"/contents/skills/full/references/notes.md?ref={sha}", _content_response("some reference notes")),
        (f"/contents/skills/full/scripts/run.py?ref={sha}", _content_response("print('hi')")),
    ])

    result = github_repo.import_from_github_path("acme/bundle-repo", "skills/full")

    assert result["resolved_sha"] == sha
    assert result["license"] == "MIT"
    assert set(result["files"].keys()) == {"references/notes.md", "scripts/run.py"}
    assert result["files"]["references/notes.md"] == "some reference notes"
    assert "other" not in json.dumps(result["files"])
    assert result["source_url"] == f"https://github.com/acme/bundle-repo/tree/{sha}/skills/full"


def test_import_from_github_path_blocks_on_gpl_folder_license(monkeypatch):
    sha = "8" * 40
    tree = {"truncated": False, "tree": [
        {"path": "skills/blocked/SKILL.md", "type": "blob"},
        {"path": "skills/blocked/LICENSE", "type": "blob"},
    ]}
    _install_relay(monkeypatch, [
        ("/repos/acme/blocked-repo/git/trees/", _json_response(200, tree)),
        ("/repos/acme/blocked-repo/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/blocked-repo", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/skills/blocked/SKILL.md?ref={sha}", _content_response(_skill_md("Blocked", license_field=""))),
        (f"/contents/skills/blocked/LICENSE?ref={sha}", _content_response("GNU GENERAL PUBLIC LICENSE\nVersion 3\n")),
    ])

    with pytest.raises(LicenseNotAllowedError):
        github_repo.import_from_github_path("acme/blocked-repo", "skills/blocked")


def test_dual_licensed_skill_md_field_is_allowed_when_one_option_is_mit(monkeypatch):
    sha = "d" * 40
    tree = {"truncated": False, "tree": [{"path": "skills/dual/SKILL.md", "type": "blob"}]}
    _install_relay(monkeypatch, [
        ("/repos/acme/dual-license/git/trees/", _json_response(200, tree)),
        ("/repos/acme/dual-license/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/dual-license", _json_response(200, {"license": {"spdx_id": "GPL-3.0"}, "default_branch": "main"})),
        (f"/contents/skills/dual/SKILL.md?ref={sha}", _content_response(_skill_md("Dual", license_field="MIT OR GPL-3.0"))),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/dual-license")

    assert len(candidates) == 1
    assert candidates[0]["allowed"] is True
    assert candidates[0]["license_evidence"]["effective_license"] == "MIT OR GPL-3.0"


def test_excluded_when_a_bundled_files_own_spdx_header_names_a_different_license(monkeypatch):
    # No SKILL.md field, no folder LICENSE -- effective license inherits
    # from the MIT repo and would otherwise be allowed, but one of the
    # skill's own bundled files carries a machine-readable
    # SPDX-License-Identifier header naming a different, disallowed
    # license -- that explicit per-file declaration must still block it.
    sha = "e" * 40
    tree = {"truncated": False, "tree": [
        {"path": "skills/spdx-conflict/SKILL.md", "type": "blob", "size": 50},
        {"path": "skills/spdx-conflict/scripts/helper.py", "type": "blob", "size": 60},
    ]}
    _install_relay(monkeypatch, [
        ("/repos/acme/spdx-conflict-repo/git/trees/", _json_response(200, tree)),
        ("/repos/acme/spdx-conflict-repo/commits/main", _json_response(200, {"sha": sha})),
        ("/repos/acme/spdx-conflict-repo", _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})),
        (f"/contents/skills/spdx-conflict/SKILL.md?ref={sha}", _content_response(_skill_md("SpdxConflict", license_field=""))),
        (f"/contents/skills/spdx-conflict/scripts/helper.py?ref={sha}",
         _content_response("# SPDX-License-Identifier: GPL-3.0-only\nprint('hi')\n")),
    ])

    candidates = github_repo.discover_skills_in_repo("acme/spdx-conflict-repo")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["allowed"] is False
    assert "scripts/helper.py" in c["reason"]
    assert "GPL-3.0-only" in c["reason"]
