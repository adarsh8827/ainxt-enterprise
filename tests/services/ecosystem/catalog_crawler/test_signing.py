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
    TrustedSigner,
    sign_index_bytes,
    trusted_signer_from_env,
    verify_index_bytes,
)

_A_SIGNER = TrustedSigner(
    issuer="https://token.actions.githubusercontent.com",
    repository="adarsh8827/ainxt-enterprise",
    workflow_name="Ecosystem catalog crawl",
)


def test_trusted_signer_is_a_simple_immutable_triple():
    assert _A_SIGNER.issuer == "https://token.actions.githubusercontent.com"
    with pytest.raises(Exception):
        _A_SIGNER.issuer = "changed"  # frozen dataclass


def test_signing_identity_mismatch_error_is_a_plain_exception():
    err = SigningIdentityMismatchError("mismatch")
    assert str(err) == "mismatch"


def test_trusted_signer_from_env_parses_the_json_form():
    signer = trusted_signer_from_env(
        '{"issuer": "https://token.actions.githubusercontent.com", '
        '"repository": "adarsh8827/ainxt-enterprise", "workflow_name": "Ecosystem catalog crawl"}'
    )
    assert signer == _A_SIGNER


@pytest.mark.parametrize("bad_json", [
    "{}",
    '{"issuer": "x"}',
    '{"issuer": "", "repository": "a/b", "workflow_name": "w"}',
    "not json at all",
])
def test_trusted_signer_from_env_fails_closed_on_malformed_input(bad_json):
    with pytest.raises((ValueError, Exception)):
        trusted_signer_from_env(bad_json)


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
    with pytest.raises(Exception):
        verify_index_bytes(b"index contents", b"not a real sigstore bundle", _A_SIGNER)


def test_the_vendored_trust_root_loads_for_real():
    # Real file, real parse (TrustedRoot.from_file() is pure local file
    # I/O -- there's no network call on this path to block) -- proves
    # offline verification has something genuine to load, not a
    # placeholder.
    pytest.importorskip("sigstore")
    from sigstore.models import TrustedRoot

    from services.ecosystem.catalog_crawler.signing import _VENDORED_TRUST_ROOT_PATH

    assert _VENDORED_TRUST_ROOT_PATH.exists()
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

    verify_index_bytes(b"data", b"{}", _A_SIGNER)
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

    verify_index_bytes(b"data", b"{}", _A_SIGNER, allow_online_trust_root_refresh=True)
    assert calls == [("production", {"offline": False}), ("verify_artifact",)]


def test_verify_index_bytes_policy_checks_issuer_repository_and_workflow_name_not_ref(monkeypatch):
    # The real point of this review round's redesign: confirm the actual
    # policy object built is an AllOf of exactly these three extension
    # checks, with no ref/subject check anywhere -- a ref change (e.g.
    # this workflow moving from a feature branch to main) must never
    # break verification.
    pytest.importorskip("sigstore")
    import sigstore.verify as verify_module
    import sigstore.verify.policy as policy_module
    from sigstore.models import Bundle

    captured_policy = {}

    class _FakeVerifier:
        def __init__(self, *, trusted_root):
            pass

        def verify_artifact(self, *, input_, bundle, policy):
            captured_policy["policy"] = policy

    monkeypatch.setattr(verify_module, "Verifier", _FakeVerifier)
    monkeypatch.setattr(Bundle, "from_json", staticmethod(lambda raw: object()))

    verify_index_bytes(b"data", b"{}", _A_SIGNER)

    policy = captured_policy["policy"]
    assert isinstance(policy, policy_module.AllOf)
    kinds = {type(child) for child in policy._children}
    assert kinds == {policy_module.OIDCIssuer, policy_module.GitHubWorkflowRepository, policy_module.GitHubWorkflowName}
