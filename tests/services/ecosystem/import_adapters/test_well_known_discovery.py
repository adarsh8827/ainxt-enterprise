# SPDX-License-Identifier: MIT
# ============================================================
# discover_skills_at_well_known() tests -- lists every entry at a
# well-known domain's index without importing/storing any of them,
# mirroring test_github_repo_discovery.py's own style for
# discover_skills_in_repo(). No live network (relay_request monkeypatched).
# ============================================================

from __future__ import annotations

import json

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError
from services.ecosystem.import_adapters import well_known


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://example.com/fixture"),
    )


def _raw_response(status_code: int, content: bytes) -> httpx.Response:
    return httpx.Response(status_code=status_code, content=content, request=httpx.Request("GET", "https://example.com/fixture"))


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(well_known, "assert_safe_https_url", lambda url: url)


@pytest.fixture(autouse=True)
def _isolated_fetch_cache(monkeypatch):
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


def _skill_md(name: str, license_field: str | None) -> bytes:
    license_line = f"license: {license_field}\n" if license_field else ""
    return f"---\nname: {name}\ndescription: A test skill.\n{license_line}---\nDo the thing.\n".encode("utf-8")


def test_discovers_a_mixed_allowed_and_disallowed_modern_index(monkeypatch):
    good = _skill_md("good-skill", "MIT")
    bad = _skill_md("bad-skill", None)
    import hashlib
    index = {
        "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
        "skills": [
            {"name": "good-skill", "type": "skill-md", "description": "Good.", "url": "/skills/good.md",
             "digest": f"sha256:{hashlib.sha256(good).hexdigest()}"},
            {"name": "bad-skill", "type": "skill-md", "description": "Bad.", "url": "/skills/bad.md",
             "digest": f"sha256:{hashlib.sha256(bad).hexdigest()}"},
        ],
    }
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "/skills/good.md": _raw_response(200, good),
        "/skills/bad.md": _raw_response(200, bad),
    })
    candidates = well_known.discover_skills_at_well_known("example.com")
    by_slug = {c["slug"]: c for c in candidates}
    assert by_slug["good-skill"]["allowed"] is True
    assert by_slug["good-skill"]["skill_md_text"] is not None
    assert by_slug["bad-skill"]["allowed"] is False
    assert by_slug["bad-skill"]["skill_md_text"] is None


def test_raises_when_no_index_exists_at_all(monkeypatch):
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": httpx.Response(404, request=httpx.Request("GET", "https://example.com/fixture")),
        "/.well-known/skills/index.json": httpx.Response(404, request=httpx.Request("GET", "https://example.com/fixture")),
    })
    with pytest.raises(ImportFetchError, match="no well-known skill index"):
        well_known.discover_skills_at_well_known("example.com")


def test_falls_back_to_legacy_index_when_modern_is_absent(monkeypatch):
    content = _skill_md("legacy-skill", "Apache-2.0")
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": httpx.Response(404, request=httpx.Request("GET", "https://example.com/fixture")),
        "/.well-known/skills/index.json": _json_response(200, {"skills": [{"name": "legacy-skill", "description": "Legacy.", "files": ["SKILL.md"]}]}),
        "/.well-known/skills/legacy-skill/SKILL.md": _raw_response(200, content),
    })
    candidates = well_known.discover_skills_at_well_known("example.com")
    assert candidates[0]["slug"] == "legacy-skill"
    assert candidates[0]["allowed"] is True


def test_a_per_entry_fetch_failure_is_reported_not_raised(monkeypatch):
    index = {
        "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
        "skills": [{"name": "missing-file", "type": "skill-md", "description": "", "url": "/skills/missing.md", "digest": "sha256:" + "0" * 64}],
    }
    _install_relay(monkeypatch, {
        "/.well-known/agent-skills/index.json": _json_response(200, index),
        "/skills/missing.md": httpx.Response(404, request=httpx.Request("GET", "https://example.com/fixture")),
    })
    candidates = well_known.discover_skills_at_well_known("example.com")
    assert candidates[0]["allowed"] is False
    assert "fetch failed" in candidates[0]["reason"]
