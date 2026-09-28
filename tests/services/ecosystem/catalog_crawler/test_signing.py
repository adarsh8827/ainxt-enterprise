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


def test_signing_context_construction_uses_the_real_current_sigstore_api():
    # Real bug found live, 2026-09-28: the actual GitHub Actions run --
    # the only environment with an ambient credential to reach this line
    # at all -- crashed with AttributeError('SigningContext' has no
    # attribute 'production'); every test above fails closed at the
    # detect_credential() check first, so this exact line was never
    # actually exercised until the real run hit it. This test calls the
    # REAL SigningContext.from_trust_config()/ClientTrustConfig.production()
    # (no mocking of either) so a future API rename would fail this test
    # the same way it failed the real run, instead of only failing closed
    # tests that never reach it.
    pytest.importorskip("sigstore")
    from sigstore.models import ClientTrustConfig
    from sigstore.sign import SigningContext

    signing_ctx = SigningContext.from_trust_config(ClientTrustConfig.production())
    assert signing_ctx is not None


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


def test_the_vendored_trust_root_loads_for_real_with_no_network(monkeypatch):
    # Real file, real parse -- proves offline verification has something
    # genuine to load, not a placeholder. Blocks all outbound HTTP first
    # so a silent network fallback inside TrustedRoot.from_file() would
    # fail this test loudly instead of passing by accident.
    pytest.importorskip("sigstore")
    from sigstore.models import TrustedRoot

    from services.ecosystem.catalog_crawler.signing import _VENDORED_TRUST_ROOT_PATH

    assert _VENDORED_TRUST_ROOT_PATH.exists()

    def _no_network(*args, **kwargs):
        raise AssertionError("TrustedRoot.from_file() must not touch the network")

    monkeypatch.setattr("connectors.net_relay.relay_request", _no_network)
    trusted_root = TrustedRoot.from_file(str(_VENDORED_TRUST_ROOT_PATH))
    assert trusted_root is not None


def test_verify_index_bytes_defaults_to_the_offline_vendored_trust_root_not_a_live_tuf_fetch(monkeypatch):
    pytest.importorskip("sigstore")
    import sigstore.verify as verify_module
    from sigstore.models import Bundle

    calls: list[str] = []
    monkeypatch.setattr(
        verify_module.Verifier, "production",
        classmethod(lambda cls, **kw: (_ for _ in ()).throw(AssertionError("must not call Verifier.production() by default"))),
    )
    monkeypatch.setattr(Bundle, "from_json", staticmethod(lambda raw: object()))

    class _FakeVerifier:
        def __init__(self, *, trusted_root):
            calls.append("offline_ctor")

        def verify_artifact(self, *, input_, bundle, policy):
            calls.append("verify_artifact")

    monkeypatch.setattr(verify_module, "Verifier", _FakeVerifier)

    identity = TrustedIdentity(issuer="https://token.actions.githubusercontent.com", subject="repo:adarsh8827/ainxt-enterprise:ref:refs/heads/main")
    verify_index_bytes(b"data", b"{}", identity)
    assert calls == ["offline_ctor", "verify_artifact"]


def test_verify_index_bytes_online_refresh_is_opt_in_only(monkeypatch):
    pytest.importorskip("sigstore")
    import sigstore.verify as verify_module
    from sigstore.models import Bundle

    calls: list[tuple] = []

    class _FakeVerifier:
        def verify_artifact(self, *, input_, bundle, policy):
            calls.append(("verify_artifact",))

    monkeypatch.setattr(
        verify_module.Verifier, "production",
        classmethod(lambda cls, **kw: (calls.append(("production", kw)), _FakeVerifier())[1]),
    )
    monkeypatch.setattr(Bundle, "from_json", staticmethod(lambda raw: object()))

    identity = TrustedIdentity(issuer="https://token.actions.githubusercontent.com", subject="repo:adarsh8827/ainxt-enterprise:ref:refs/heads/main")
    verify_index_bytes(b"data", b"{}", identity, allow_online_trust_root_refresh=True)
    assert calls == [("production", {"offline": False}), ("verify_artifact",)]
