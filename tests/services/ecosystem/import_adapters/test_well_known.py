# SPDX-License-Identifier: MIT
# ============================================================
# well_known adapter tests. No live network: connectors.net_relay.
# relay_request is monkeypatched to return fabricated fixture responses;
# the SSRF guard is bypassed here (dedicated test file covers it).
# ============================================================

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters import well_known

_SKILL_MD = b"---\nname: Weather Skill\ndescription: Gets the weather.\n---\nFetch and summarize.\n"
_SKILL_SHA = hashlib.sha256(_SKILL_MD).hexdigest()


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


def _index(skills: list[dict]) -> dict:
    return {"schema_version": "0.2.0", "skills": skills}


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(well_known, "assert_safe_https_url", lambda url: url)


def test_import_clean_mit_skill_succeeds(monkeypatch):
    index = _index([{
        "slug": "weather", "name": "Weather Skill", "description": "Gets the weather.",
        "download_url": "https://example.com/skills/weather/SKILL.md",
        "sha256": _SKILL_SHA, "license": "MIT",
    }])

    def _fake_relay(method, url, **kwargs):
        if "/.well-known/agent-skills/index.json" in url:
            return _json_response(200, index)
        if "/skills/weather/SKILL.md" in url:
            return _raw_response(200, _SKILL_MD)
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(well_known, "relay_request", _fake_relay)

    result = well_known.import_from_well_known("example.com", "weather")
    assert result["license"] == "MIT"
    assert result["display_name"] == "Weather Skill"
    assert result["resolved_sha"] == _SKILL_SHA
    assert result["source_url"] == "https://example.com"


def test_falls_back_to_legacy_skills_index_path(monkeypatch):
    index = _index([{
        "slug": "weather", "name": "Weather Skill", "description": "d",
        "download_url": "https://example.com/skills/weather/SKILL.md",
        "sha256": _SKILL_SHA, "license": "Apache-2.0",
    }])

    def _fake_relay(method, url, **kwargs):
        if "/.well-known/agent-skills/index.json" in url:
            return _json_response(404, {"message": "not found"})
        if "/.well-known/skills/index.json" in url:
            return _json_response(200, index)
        if "/skills/weather/SKILL.md" in url:
            return _raw_response(200, _SKILL_MD)
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(well_known, "relay_request", _fake_relay)

    result = well_known.import_from_well_known("example.com", "weather")
    assert result["license"] == "Apache-2.0"


def test_index_entry_with_missing_license_is_blocked(monkeypatch):
    index = _index([{
        "slug": "no-license", "name": "No License Skill", "description": "d",
        "download_url": "https://example.com/skills/no-license/SKILL.md",
        "sha256": _SKILL_SHA,
    }])
    monkeypatch.setattr(well_known, "relay_request", lambda method, url, **kw: _json_response(200, index))

    with pytest.raises(LicenseNotAllowedError):
        well_known.import_from_well_known("example.com", "no-license")


def test_sha256_mismatch_is_a_hard_failure(monkeypatch):
    wrong_hash = "0" * 64
    index = _index([{
        "slug": "weather", "name": "Weather Skill", "description": "d",
        "download_url": "https://example.com/skills/weather/SKILL.md",
        "sha256": wrong_hash, "license": "MIT",
    }])

    def _fake_relay(method, url, **kwargs):
        if "index.json" in url:
            return _json_response(200, index)
        return _raw_response(200, _SKILL_MD)

    monkeypatch.setattr(well_known, "relay_request", _fake_relay)

    with pytest.raises(ImportFetchError, match="sha256 mismatch"):
        well_known.import_from_well_known("example.com", "weather")


def test_unknown_slug_raises_fetch_error(monkeypatch):
    index = _index([{"slug": "other", "name": "x", "description": "d",
                      "download_url": "https://example.com/x", "sha256": "a" * 64, "license": "MIT"}])
    monkeypatch.setattr(well_known, "relay_request", lambda method, url, **kw: _json_response(200, index))

    with pytest.raises(ImportFetchError, match="no entry with slug"):
        well_known.import_from_well_known("example.com", "weather")


def test_neither_index_path_exists_raises_fetch_error(monkeypatch):
    monkeypatch.setattr(
        well_known, "relay_request",
        lambda method, url, **kw: _json_response(404, {"message": "not found"}),
    )
    with pytest.raises(ImportFetchError, match="no well-known skill index"):
        well_known.import_from_well_known("example.com", "weather")


def test_domain_with_scheme_prefix_is_normalized(monkeypatch):
    index = _index([{
        "slug": "weather", "name": "Weather Skill", "description": "d",
        "download_url": "https://example.com/skills/weather/SKILL.md",
        "sha256": _SKILL_SHA, "license": "MIT",
    }])

    def _fake_relay(method, url, **kwargs):
        if "index.json" in url:
            return _json_response(200, index)
        return _raw_response(200, _SKILL_MD)

    monkeypatch.setattr(well_known, "relay_request", _fake_relay)

    result = well_known.import_from_well_known("https://example.com/", "weather")
    assert result["source_url"] == "https://example.com"
