# SPDX-License-Identifier: MIT
# ============================================================
# well_known adapter tests -- rewritten 2026-09-28 against the REAL Agent
# Skills Discovery format (https://schemas.agentskills.io/discovery/0.2.0/
# schema.json), after live-testing the ORIGINAL adapter against two real
# sites (docs.x.com, supabase.com) found it implemented an invented shape
# neither site actually serves. No live network in these tests
# (connectors.net_relay.relay_request monkeypatched); the SSRF guard is
# bypassed here (dedicated test file covers it).
#
# Several fixtures below are RECORDED from the real, live responses
# (fetched directly, 2026-09-28) rather than invented:
#   - docs.x.com's modern index ($schema 0.2.0, one "x" skill, type
#     skill-md, relative url, real digest) and its real SKILL.md content
#     (genuinely has NO license: field -- used here as the real-world
#     "missing license -> excluded" case, not a fabricated scenario).
#   - docs.x.com's LEGACY index at /.well-known/skills/index.json (a
#     completely different, simpler shape from the modern one: bare
#     name/description/files[], no url/digest at all) -- also real,
#     confirmed live that docs.x.com serves both paths simultaneously.
#   - supabase.com's modern index (type archive, absolute GitHub-release
#     .tar.gz url, real digest) -- the actual downloaded archive's real
#     internal structure (SKILL.md at root + references/*.md tree, MIT
#     license field) is mirrored by _build_test_archive() below with
#     shortened content, since inlining the real ~20KB binary isn't
#     practical in a test file; the STRUCTURE (flat root, SKILL.md +
#     references/) is real, not guessed.
# ============================================================

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters import well_known

# ---------------------------------------------------------------------------
# Recorded fixture: docs.x.com's real modern index shape (verified live,
# 2026-09-28: name "x", type "skill-md", relative url, real digest of the
# real ~8KB SKILL.md). The SKILL.md CONTENT below is shortened for this
# test file -- what's real and load-bearing is the structural fact that
# the live file has NO license: field at all (confirmed by fetching it
# directly), not the exact bytes or digest, which are recomputed fresh
# over this shortened fixture instead of the real file's own digest.
# ---------------------------------------------------------------------------
_DOCSX_SKILL_MD_NO_LICENSE = (
    b"---\nname: x\ndescription: Use when building applications that interact with X data.\n"
    b"metadata:\n    mintlify-proj: x\n    version: \"1.0\"\n---\n\n# X API Skill\n"
)
_DOCSX_MODERN_INDEX = {
    "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
    "skills": [{
        "name": "x",
        "type": "skill-md",
        "description": "Use when building applications that interact with X (formerly Twitter) data.",
        "url": "/.well-known/agent-skills/x/skill.md",
        "digest": f"sha256:{hashlib.sha256(_DOCSX_SKILL_MD_NO_LICENSE).hexdigest()}",
    }],
}

# Recorded: docs.x.com's real LEGACY index shape (different site, same
# domain, the other well-known path).
_DOCSX_LEGACY_INDEX = {"skills": [{"name": "x", "description": "Legacy-path listing.", "files": ["SKILL.md"]}]}


def _build_test_archive(skill_md: bytes, extra_files: dict[str, bytes] | None = None) -> bytes:
    """Mirrors the REAL structure downloaded from supabase.com's release
    asset (SKILL.md at archive root, a references/ tree alongside it) --
    shortened content, not the real ~20KB file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("SKILL.md")
        info.size = len(skill_md)
        tf.addfile(info, io.BytesIO(skill_md))
        for name, content in (extra_files or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


_SUPABASE_SKILL_MD = (
    b"---\nname: supabase-postgres-best-practices\ndescription: Postgres best practices.\n"
    b"license: MIT\nmetadata:\n  author: supabase\n  organization: Supabase\n---\n\n# Best practices\n"
)
_SUPABASE_ARCHIVE = _build_test_archive(
    _SUPABASE_SKILL_MD, {"references/query-index-types.md": b"# Index types\nUse the right index.\n"},
)
_SUPABASE_ARCHIVE_DIGEST = hashlib.sha256(_SUPABASE_ARCHIVE).hexdigest()
_SUPABASE_MODERN_INDEX = {
    "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
    "skills": [{
        "name": "supabase-postgres-best-practices",
        "type": "archive",
        "description": "Postgres best practices maintained by Supabase.",
        "url": "https://github.com/supabase/agent-skills/releases/download/v0.1.8/supabase-postgres-best-practices.tar.gz",
        "digest": f"sha256:{_SUPABASE_ARCHIVE_DIGEST}",
    }],
}


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://example.com/fixture"),
    )


def _raw_response(status_code: int, content: bytes) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=content,
        request=httpx.Request("GET", "https://example.com/fixture"),
    )


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(well_known, "assert_safe_https_url", lambda url: url)


@pytest.fixture(autouse=True)
def _isolated_fetch_cache(monkeypatch):
    # The real fetch_cache is Redis-backed with a 24h TTL and persists
    # across test runs (documented gotcha, LLD/external-import.md) --
    # several tests below deliberately reuse the same (domain, skill_slug)
    # pair (docs.x.com/x) with DIFFERENT content to exercise different
    # branches, which would collide against real Redis state left over
    # from an earlier test/run. A fresh, per-test in-memory dict avoids
    # that entirely rather than requiring every fixture identity to be
    # globally unique.
    store: dict[str, bytes] = {}
    monkeypatch.setattr(well_known, "get_cached", lambda identity: store.get(identity))
    monkeypatch.setattr(well_known, "put_cached", lambda identity, content: store.__setitem__(identity, content))


def _install_relay(monkeypatch, routes: dict[str, httpx.Response]):
    def _fake_relay(method, url, **kwargs):
        for fragment, response in routes.items():
            if fragment in url:
                return response
        raise AssertionError(f"unexpected url {url!r} (no route matched)")
    monkeypatch.setattr(well_known, "relay_request", _fake_relay)


# ---------------------------------------------------------------------------
# Modern format, type "skill-md" (docs.x.com's real shape)
# ---------------------------------------------------------------------------

def test_modern_skill_md_with_missing_license_is_blocked_real_docsx_case(monkeypatch):
    # This is docs.x.com's REAL, live index + REAL SKILL.md -- it genuinely
    # has no license: field. Confirms the fix doesn't invent a license
    # where the real source declares none.
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, _DOCSX_MODERN_INDEX),
        "/.well-known/agent-skills/x/skill.md": _raw_response(200, _DOCSX_SKILL_MD_NO_LICENSE),
    })
    with pytest.raises(LicenseNotAllowedError):
        well_known.import_from_well_known("docs.x.com", "x")


def test_modern_skill_md_relative_url_resolved_against_origin(monkeypatch):
    # Same real docs.x.com index -- proves the relative url
    # ("/.well-known/agent-skills/x/skill.md") is actually resolved and
    # fetched (not treated as a bare relative path against nothing).
    skill_md_with_license = _DOCSX_SKILL_MD_NO_LICENSE.replace(b"metadata:", b"license: MIT\nmetadata:")
    digest = hashlib.sha256(skill_md_with_license).hexdigest()
    index = {**_DOCSX_MODERN_INDEX, "skills": [{**_DOCSX_MODERN_INDEX["skills"][0], "digest": f"sha256:{digest}"}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "https://docs.x.com/.well-known/agent-skills/x/skill.md": _raw_response(200, skill_md_with_license),
    })
    result = well_known.import_from_well_known("docs.x.com", "x")
    assert result["license"] == "MIT"
    assert result["display_name"] == "x"
    assert result["source_url"] == "https://docs.x.com"


def test_modern_skill_md_digest_mismatch_is_a_hard_failure(monkeypatch):
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, _DOCSX_MODERN_INDEX),
        "/.well-known/agent-skills/x/skill.md": _raw_response(200, b"tampered content, wrong digest"),
    })
    with pytest.raises(ImportFetchError, match="digest mismatch"):
        well_known.import_from_well_known("docs.x.com", "x")


def test_unsupported_entry_type_is_rejected(monkeypatch):
    index = {**_DOCSX_MODERN_INDEX, "skills": [{**_DOCSX_MODERN_INDEX["skills"][0], "type": "zip"}]}
    _install_relay(monkeypatch, {"/.well-known/agent-skills/index.json": _json_response(200, index)})
    with pytest.raises(ImportFetchError, match="unsupported entry type"):
        well_known.import_from_well_known("docs.x.com", "x")


def test_malformed_digest_is_rejected(monkeypatch):
    index = {**_DOCSX_MODERN_INDEX, "skills": [{**_DOCSX_MODERN_INDEX["skills"][0], "digest": "md5:deadbeef"}]}
    _install_relay(monkeypatch, {"/.well-known/agent-skills/index.json": _json_response(200, index)})
    with pytest.raises(ImportFetchError, match="not.*sha256"):
        well_known.import_from_well_known("docs.x.com", "x")


# ---------------------------------------------------------------------------
# Modern format, type "archive" (supabase.com's real shape)
# ---------------------------------------------------------------------------

def test_modern_archive_extracts_skill_md_and_bundled_files_real_supabase_shape(monkeypatch):
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, _SUPABASE_MODERN_INDEX),
        "github.com/supabase/agent-skills/releases": _raw_response(200, _SUPABASE_ARCHIVE),
    })
    result = well_known.import_from_well_known("supabase.com", "supabase-postgres-best-practices")
    assert result["license"] == "MIT"
    assert result["display_name"] == "supabase-postgres-best-practices"
    assert "references/query-index-types.md" in result["files"]
    assert "Best practices" in result["manifest"]["instructions"]


def test_archive_with_no_skill_md_at_root_is_rejected(monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("references/only.md")
        content = b"no SKILL.md in this archive"
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    bad_archive = buf.getvalue()
    digest = hashlib.sha256(bad_archive).hexdigest()
    index = {**_SUPABASE_MODERN_INDEX, "skills": [{**_SUPABASE_MODERN_INDEX["skills"][0], "digest": f"sha256:{digest}"}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "github.com/supabase/agent-skills/releases": _raw_response(200, bad_archive),
    })
    with pytest.raises(ImportFetchError, match="no SKILL.md at its root"):
        well_known.import_from_well_known("supabase.com", "supabase-postgres-best-practices")


def test_archive_member_with_path_traversal_is_rejected(monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        skill_info = tarfile.TarInfo("SKILL.md")
        skill_info.size = len(_SUPABASE_SKILL_MD)
        tf.addfile(skill_info, io.BytesIO(_SUPABASE_SKILL_MD))
        evil_info = tarfile.TarInfo("../../etc/passwd")
        evil_content = b"malicious"
        evil_info.size = len(evil_content)
        tf.addfile(evil_info, io.BytesIO(evil_content))
    evil_archive = buf.getvalue()
    digest = hashlib.sha256(evil_archive).hexdigest()
    index = {**_SUPABASE_MODERN_INDEX, "skills": [{**_SUPABASE_MODERN_INDEX["skills"][0], "digest": f"sha256:{digest}"}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "github.com/supabase/agent-skills/releases": _raw_response(200, evil_archive),
    })
    with pytest.raises(ImportFetchError, match="unsafe path"):
        well_known.import_from_well_known("supabase.com", "supabase-postgres-best-practices")


def test_archive_member_exceeding_per_file_cap_is_rejected(monkeypatch):
    huge_file = b"x" * (well_known._MAX_ARCHIVE_MEMBER_BYTES + 1)
    archive = _build_test_archive(_SUPABASE_SKILL_MD, {"references/huge.md": huge_file})
    digest = hashlib.sha256(archive).hexdigest()
    index = {**_SUPABASE_MODERN_INDEX, "skills": [{**_SUPABASE_MODERN_INDEX["skills"][0], "digest": f"sha256:{digest}"}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "github.com/supabase/agent-skills/releases": _raw_response(200, archive),
    })
    with pytest.raises(ImportFetchError, match="per-file limit"):
        well_known.import_from_well_known("supabase.com", "supabase-postgres-best-practices")


# ---------------------------------------------------------------------------
# Legacy format (docs.x.com's real /.well-known/skills/index.json shape)
# ---------------------------------------------------------------------------

def test_legacy_format_used_when_modern_index_is_absent(monkeypatch):
    skill_md_with_license = _DOCSX_SKILL_MD_NO_LICENSE.replace(b"metadata:", b"license: Apache-2.0\nmetadata:")
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(404, {"message": "not found"}),
        "/.well-known/skills/index.json": _json_response(200, _DOCSX_LEGACY_INDEX),
        "/.well-known/skills/x/SKILL.md": _raw_response(200, skill_md_with_license),
    })
    result = well_known.import_from_well_known("docs.x.com", "x")
    assert result["license"] == "Apache-2.0"
    assert result["display_name"] == "x"


def test_legacy_format_missing_license_is_blocked(monkeypatch):
    # Real docs.x.com content again -- no license field in either format.
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(404, {"message": "not found"}),
        "/.well-known/skills/index.json": _json_response(200, _DOCSX_LEGACY_INDEX),
        "/.well-known/skills/x/SKILL.md": _raw_response(200, _DOCSX_SKILL_MD_NO_LICENSE),
    })
    with pytest.raises(LicenseNotAllowedError):
        well_known.import_from_well_known("docs.x.com", "x")


def test_legacy_format_unsafe_filename_is_rejected(monkeypatch):
    index = {"skills": [{"name": "x", "description": "d", "files": ["../../etc/passwd"]}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(404, {"message": "not found"}),
        "/.well-known/skills/index.json": _json_response(200, index),
    })
    with pytest.raises(ImportFetchError, match="unsafe filename"):
        well_known.import_from_well_known("docs.x.com", "x")


def test_legacy_format_entry_without_skill_md_in_files_is_rejected(monkeypatch):
    index = {"skills": [{"name": "x", "description": "d", "files": ["README.md"]}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(404, {"message": "not found"}),
        "/.well-known/skills/index.json": _json_response(200, index),
    })
    with pytest.raises(ImportFetchError, match="no SKILL.md"):
        well_known.import_from_well_known("docs.x.com", "x")


# ---------------------------------------------------------------------------
# Shared behavior
# ---------------------------------------------------------------------------

def test_unknown_skill_name_raises_fetch_error(monkeypatch):
    _install_relay(monkeypatch, {"/.well-known/agent-skills/index.json": _json_response(200, _DOCSX_MODERN_INDEX)})
    with pytest.raises(ImportFetchError, match="no entry named"):
        well_known.import_from_well_known("docs.x.com", "does-not-exist")


def test_neither_index_path_exists_raises_fetch_error(monkeypatch):
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(404, {"message": "not found"}),
        "/.well-known/skills/index.json": _json_response(404, {"message": "not found"}),
    })
    with pytest.raises(ImportFetchError, match="no well-known skill index"):
        well_known.import_from_well_known("docs.x.com", "x")


def test_non_json_response_at_modern_path_falls_through_to_legacy(monkeypatch):
    # Real-world case: supabase.com's /.well-known/skills/index.json (the
    # LEGACY path) actually returns a 404 HTML page, not JSON, for that
    # domain (only the modern path exists there). Exercised here the other
    # way around -- an HTML 200 at the MODERN path -- to confirm a
    # non-JSON / wrong-shape response at a candidate path is treated as
    # "try the next path" rather than crashing on a JSON-parse error.
    skill_md_with_license = _DOCSX_SKILL_MD_NO_LICENSE.replace(b"metadata:", b"license: MIT\nmetadata:")
    digest = hashlib.sha256(skill_md_with_license).hexdigest()
    legacy_index = {"skills": [{"name": "x", "description": "d", "files": ["SKILL.md"]}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _raw_response(200, b"<!DOCTYPE html><html>not json</html>"),
        "/.well-known/skills/index.json": _json_response(200, legacy_index),
        "/.well-known/skills/x/SKILL.md": _raw_response(200, skill_md_with_license),
    })
    result = well_known.import_from_well_known("docs.x.com", "x")
    assert result["license"] == "MIT"


def test_domain_with_scheme_prefix_is_normalized(monkeypatch):
    skill_md_with_license = _DOCSX_SKILL_MD_NO_LICENSE.replace(b"metadata:", b"license: MIT\nmetadata:")
    digest = hashlib.sha256(skill_md_with_license).hexdigest()
    index = {**_DOCSX_MODERN_INDEX, "skills": [{**_DOCSX_MODERN_INDEX["skills"][0], "digest": f"sha256:{digest}"}]}
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "skill.md": _raw_response(200, skill_md_with_license),
    })
    result = well_known.import_from_well_known("https://docs.x.com/", "x")
    assert result["source_url"] == "https://docs.x.com"
