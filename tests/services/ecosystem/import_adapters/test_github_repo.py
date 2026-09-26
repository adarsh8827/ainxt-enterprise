# SPDX-License-Identifier: MIT
# ============================================================
# github_repo adapter tests. No live network: connectors.net_relay.
# relay_request is monkeypatched to return recorded/fabricated fixture
# responses shaped exactly like the real GitHub REST API; the SSRF guard
# is bypassed here (it has its own dedicated test file) since every URL
# in these fixtures is synthetic.
# ============================================================

from __future__ import annotations

import base64
import json

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_repo


def _json_response(status_code: int, payload, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://api.github.com/fixture"),
    )


_SKILL_MD = (
    "---\nname: Hello Skill\ndescription: Says hello politely.\nlicense: MIT\n---\n"
    "Always greet the user warmly.\n"
)


def _content_response(text: str, size: int | None = None) -> httpx.Response:
    return _json_response(200, {
        "type": "file",
        "size": size if size is not None else len(text.encode("utf-8")),
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    })


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(github_repo, "assert_safe_https_url", lambda url: url)


def _install_relay(monkeypatch, responses: dict[str, httpx.Response]):
    """responses keyed by '/commits/' or '/contents/' (checked first,
    since both are unambiguous markers that never appear in the bare
    repo-metadata URL) or the bare repo path (checked last, matching only
    once neither of the more specific markers did) -- the bare repo path
    is itself a prefix substring of the other two URLs, so a plain
    "first-match" or "longest-match" substring search over all three keys
    picks the wrong one; explicit precedence avoids that entirely."""
    def _fake_relay(method, url, **kwargs):
        for marker in ("/commits/", "/contents/"):
            for key, resp in responses.items():
                if marker in key and key in url:
                    return resp
        for key, resp in responses.items():
            if "/commits/" not in key and "/contents/" not in key and key in url:
                return resp
        raise AssertionError(f"no fixture response registered for {url!r}")
    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)


def test_import_clean_mit_skill_succeeds(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/example": _json_response(200, {
            "license": {"spdx_id": "MIT"}, "default_branch": "main",
        }),
        "/commits/main": _json_response(200, {"sha": "a" * 40}),
        "/contents/SKILL.md": _content_response(_SKILL_MD),
    })

    result = github_repo.import_from_github("acme/example")
    assert result["license"] == "MIT"
    assert result["display_name"] == "Hello Skill"
    assert result["resolved_sha"] == "a" * 40
    assert result["source_url"] == "https://github.com/acme/example"
    assert "greet" in result["manifest"]["instructions"]


def test_repo_level_gpl_license_blocks_before_any_content_fetch(monkeypatch):
    calls = []

    def _fake_relay(method, url, **kwargs):
        calls.append(url)
        if "/repos/acme/gpl-repo" in url and "/commits/" not in url and "/contents/" not in url:
            return _json_response(200, {"license": {"spdx_id": "GPL-3.0"}, "default_branch": "main"})
        raise AssertionError(f"should never reach {url!r} once the repo-level license check fails")

    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)

    with pytest.raises(LicenseNotAllowedError, match="GPL-3.0"):
        github_repo.import_from_github("acme/gpl-repo")
    assert len(calls) == 1  # only the repo-metadata call happened


def test_skill_md_own_license_field_also_checked(monkeypatch):
    # Repo is MIT, but the individual SKILL.md declares GPL -- both must pass.
    gpl_skill_md = _SKILL_MD.replace("license: MIT", "license: GPL-3.0-only")
    _install_relay(monkeypatch, {
        "/repos/acme/mixed": _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"}),
        "/commits/main": _json_response(200, {"sha": "b" * 40}),
        "/contents/SKILL.md": _content_response(gpl_skill_md),
    })

    with pytest.raises(LicenseNotAllowedError, match="GPL-3.0-only"):
        github_repo.import_from_github("acme/mixed")


def test_missing_skill_md_raises_fetch_error(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/no-skill": _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"}),
        "/commits/main": _json_response(200, {"sha": "c" * 40}),
        "/contents/SKILL.md": _json_response(404, {"message": "Not Found"}),
    })

    with pytest.raises(ImportFetchError, match="404"):
        github_repo.import_from_github("acme/no-skill")


def test_rate_limit_response_raises_with_retry_after(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/limited": _json_response(
            403, {"message": "API rate limit exceeded"}, headers={"Retry-After": "42"}
        ),
    })

    with pytest.raises(ImportRateLimitedError) as excinfo:
        github_repo.import_from_github("acme/limited")
    assert excinfo.value.retry_after == 42


def test_oversized_skill_md_is_rejected(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/big": _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"}),
        "/commits/main": _json_response(200, {"sha": "d" * 40}),
        "/contents/SKILL.md": _content_response(_SKILL_MD, size=1024 * 1024),
    })

    with pytest.raises(ImportFetchError, match="KB limit"):
        github_repo.import_from_github("acme/big")


def test_repeat_import_of_same_sha_uses_cache_not_a_second_fetch(monkeypatch):
    try:
        from core.config import RDB_CACHE
        from core.kv import get_kv
        get_kv(RDB_CACHE, decode_responses=True).get("probe")
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")

    # A unique repo name per test run -- the fetch cache is Redis-backed
    # with a 24h TTL, so it persists ACROSS test runs (unlike Postgres,
    # which the shared conftest truncates every test); a fixed repo name
    # here would silently hit a leftover cache entry from an earlier run
    # of this exact test and make fetch_count never increment at all.
    import uuid
    repo_slug = f"acme/cached-{uuid.uuid4().hex[:12]}"
    sha = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 40 hex chars, unique per run

    fetch_count = {"contents": 0}

    def _fake_relay(method, url, **kwargs):
        if f"/repos/{repo_slug}" in url and "/commits/" not in url and "/contents/" not in url:
            return _json_response(200, {"license": {"spdx_id": "MIT"}, "default_branch": "main"})
        if "/commits/main" in url:
            return _json_response(200, {"sha": sha})
        if "/contents/SKILL.md" in url:
            fetch_count["contents"] += 1
            return _content_response(_SKILL_MD)
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)

    github_repo.import_from_github(repo_slug)
    github_repo.import_from_github(repo_slug)
    assert fetch_count["contents"] == 1, "SKILL.md should only be fetched once across two imports of the same sha"


def test_ref_with_explicit_branch_is_resolved(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/branchy": _json_response(200, {"license": {"spdx_id": "Apache-2.0"}, "default_branch": "main"}),
        "/commits/feature-x": _json_response(200, {"sha": "f" * 40}),
        "/contents/SKILL.md": _content_response(_SKILL_MD),
    })

    result = github_repo.import_from_github("acme/branchy", "feature-x")
    assert result["resolved_sha"] == "f" * 40
