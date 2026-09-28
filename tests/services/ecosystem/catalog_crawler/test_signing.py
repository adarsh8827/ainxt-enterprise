# SPDX-License-Identifier: MIT
# ============================================================
# signing.py tests. sign_index_bytes()/verify_index_bytes() only do
# anything real inside a GitHub Actions job (ambient OIDC credential) --
# these tests exercise the REAL sigstore import + the real, documented
# fail-closed behavior outside that environment, rather than mocking the
# library's internals (which would just test the mock). Skipped outright
# if the `sigstore` package isn't installed in this environment (it's a
# real dependency of the crawl workflow's own runner, not of every dev
# environment that merely imports this module).
# ============================================================

from __future__ import annotations

import pytest

from services.ecosystem.catalog_crawler.signing import (
    SigningIdentityMismatchError,
    TrustedIdentity,
    sign_index_bytes,
    verify_index_bytes,
)


def test_trusted_identity_is_a_simple_immutable_pair():
    identity = TrustedIdentity(issuer="https://token.actions.githubusercontent.com", subject="repo:adarsh8827/ainxt-enterprise:ref:refs/heads/main")
    assert identity.issuer == "https://token.actions.githubusercontent.com"
    with pytest.raises(Exception):
        identity.issuer = "changed"  # frozen dataclass


def test_signing_identity_mismatch_error_is_a_plain_exception():
    err = SigningIdentityMismatchError("mismatch")
    assert str(err) == "mismatch"


def test_sign_index_bytes_fails_closed_without_an_ambient_oidc_credential():
    pytest.importorskip("sigstore")
    # This test runs outside any GitHub Actions job, so there is
    # genuinely no ambient OIDC credential to detect -- the real,
    # documented fail-closed path, not a simulated one.
    with pytest.raises(RuntimeError, match="ambient OIDC credential"):
        sign_index_bytes(b"index contents")


def test_verify_index_bytes_rejects_a_malformed_bundle():
    pytest.importorskip("sigstore")
    identity = TrustedIdentity(issuer="https://token.actions.githubusercontent.com", subject="repo:adarsh8827/ainxt-enterprise:ref:refs/heads/main")
    with pytest.raises(Exception):
        verify_index_bytes(b"index contents", b"not a real sigstore bundle", identity)
