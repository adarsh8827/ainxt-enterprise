# SPDX-License-Identifier: MIT
# ============================================================
# import_repo_metadata() / import_activepieces_piece() -- Connectors
# phase Stage 5 additions to the github_repo adapter. Same no-live-
# network, fabricated-httpx-response style as test_github_repo.py.
# ============================================================

from __future__ import annotations

import json

import httpx
import pytest

from services.ecosystem.import_adapters import github_repo


def _json_response(status_code: int, payload) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=json.dumps(payload).encode("utf-8"),
        request=httpx.Request("GET", "https://api.github.com/fixture"),
    )


def _content_response(text: str) -> httpx.Response:
    return httpx.Response(
        status_code=200, content=text.encode("utf-8"),
        request=httpx.Request("GET", "https://raw.githubusercontent.com/fixture"),
    )


_MIT_LICENSE_TEXT = (
    "Copyright (c) 2020 Someone\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    "of this software..."
)


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard(monkeypatch):
    monkeypatch.setattr(github_repo, "assert_safe_https_url", lambda url: url)


def _install_relay(monkeypatch, responses: dict[str, httpx.Response]):
    def _fake_relay(method, url, **kwargs):
        for marker in ("/commits/", "/git/trees/", "/contents/"):
            for key, resp in responses.items():
                if marker in key and key in url:
                    return resp
        for key, resp in responses.items():
            if not any(m in key for m in ("/commits/", "/git/trees/", "/contents/")) and key in url:
                return resp
        raise AssertionError(f"no fixture response registered for {url!r}")
    monkeypatch.setattr(github_repo, "relay_request", _fake_relay)


def test_import_repo_metadata_trusts_a_correct_api_spdx_id(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/clean-repo": _json_response(200, {
            "name": "clean-repo", "description": "A clean repo.",
            "license": {"spdx_id": "MIT"}, "default_branch": "main",
        }),
        "/commits/main": _json_response(200, {"sha": "b" * 40}),
    })
    result = github_repo.import_repo_metadata("acme/clean-repo")
    assert result["license"] == "MIT"
    assert result["license_evidence"] == "GitHub API license detection"
    assert result["resolved_sha"] == "b" * 40


def test_import_repo_metadata_falls_back_to_text_guess_when_api_spdx_is_wrong(monkeypatch):
    # Mirrors the real, live-verified activepieces/activepieces case: the
    # API reports a non-allowed spdx_id ("NOASSERTION") for a repo whose
    # actual root LICENSE text is a real, unmodified MIT body.
    _install_relay(monkeypatch, {
        "/repos/acme/mislabeled-repo": _json_response(200, {
            "name": "mislabeled-repo", "description": "d",
            "license": {"spdx_id": "NOASSERTION"}, "default_branch": "main",
        }),
        "/commits/main": _json_response(200, {"sha": "c" * 40}),
        "/git/trees/": _json_response(200, {"tree": [
            {"path": "LICENSE", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]}),
        "/LICENSE": _content_response(_MIT_LICENSE_TEXT),
    })
    result = github_repo.import_repo_metadata("acme/mislabeled-repo")
    assert result["license"] == "MIT"
    assert "text-guess" in result["license_evidence"]
    assert "NOASSERTION" in result["license_evidence"]


def test_import_repo_metadata_no_license_signal_at_all_stays_disallowed(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/acme/no-license-repo": _json_response(200, {
            "name": "no-license-repo", "description": "d",
            "license": None, "default_branch": "main",
        }),
        "/commits/main": _json_response(200, {"sha": "d" * 40}),
        "/git/trees/": _json_response(200, {"tree": [{"path": "README.md", "type": "blob"}]}),
    })
    result = github_repo.import_repo_metadata("acme/no-license-repo")
    assert result["license"] == ""


def test_import_activepieces_piece_reads_nearest_license_and_package_name(monkeypatch):
    _install_relay(monkeypatch, {
        "/repos/activepieces/activepieces": _json_response(200, {"default_branch": "main"}),
        "/commits/main": _json_response(200, {"sha": "e" * 40}),
        "/git/trees/": _json_response(200, {"tree": [
            {"path": "LICENSE", "type": "blob"},
            {"path": "packages/pieces/community/slack/package.json", "type": "blob"},
            {"path": "packages/pieces/community/slack/src/index.ts", "type": "blob"},
        ]}),
        "/LICENSE": _content_response(_MIT_LICENSE_TEXT),
        "/package.json": _json_response(200, {"name": "@activepieces/piece-slack", "version": "0.21.0"}),
    })
    result = github_repo.import_activepieces_piece("slack")
    assert result["license"] == "MIT"
    assert result["package_name"] == "@activepieces/piece-slack"
    assert "packages/pieces/community/slack" in result["source_url"]


def test_import_activepieces_piece_missing_directory_raises():
    from services.ecosystem.errors import ImportFetchError

    def _fake_relay(method, url, **kwargs):
        if "/commits/" in url:
            return _json_response(200, {"sha": "f" * 40})
        if "/git/trees/" in url:
            return _json_response(200, {"tree": [{"path": "LICENSE", "type": "blob"}]})
        return _json_response(200, {"default_branch": "main"})

    import services.ecosystem.import_adapters.github_repo as gr
    orig_relay = gr.relay_request
    orig_ssrf = gr.assert_safe_https_url
    gr.relay_request = _fake_relay
    gr.assert_safe_https_url = lambda url: url
    try:
        with pytest.raises(ImportFetchError):
            gr.import_activepieces_piece("does-not-exist")
    finally:
        gr.relay_request = orig_relay
        gr.assert_safe_https_url = orig_ssrf
