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

from pathlib import Path

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
    source_repository_uri="https://github.com/adarsh8827/ainxt-enterprise",
)

# A REAL Sigstore bundle, not a synthetic/mocked one -- pulled from the
# actual signed `ecosystem-index` branch output of workflow run
# 36447819183 (commit 5baad066, 2026-09-28), the first run to exercise
# the fixed SigningContext.from_trust_config() + TrustedSigner/AllOf
# policy end to end in real GitHub Actions. Checked in once as a fixture
# so this exact "does a real installer actually verify this" round trip
# has permanent regression coverage without a live network call in CI.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_REAL_SIGNED_DATA = (_FIXTURES_DIR / "real_signed_mcp_server.json").read_bytes()
_REAL_SIGNED_BUNDLE = (_FIXTURES_DIR / "real_signed_mcp_server.json.sigstore").read_bytes()


def test_trusted_signer_is_a_simple_immutable_struct():
    assert _A_SIGNER.issuer == "https://token.actions.githubusercontent.com"
    with pytest.raises(Exception):
        _A_SIGNER.issuer = "changed"  # frozen dataclass


def test_signing_identity_mismatch_error_is_a_plain_exception():
    err = SigningIdentityMismatchError("mismatch")
    assert str(err) == "mismatch"


def test_trusted_signer_from_env_parses_the_json_form():
    signer = trusted_signer_from_env(
        '{"issuer": "https://token.actions.githubusercontent.com", '
        '"source_repository_uri": "https://github.com/adarsh8827/ainxt-enterprise"}'
    )
    assert signer == _A_SIGNER


def test_trusted_signer_from_env_parses_the_optional_build_config_uri():
    signer = trusted_signer_from_env(
        '{"issuer": "https://token.actions.githubusercontent.com", '
        '"source_repository_uri": "https://github.com/adarsh8827/ainxt-enterprise", '
        '"build_config_uri": "https://github.com/adarsh8827/ainxt-enterprise/.github/workflows/'
        'ecosystem-catalog-crawl.yml@refs/heads/main"}'
    )
    assert signer.build_config_uri == (
        "https://github.com/adarsh8827/ainxt-enterprise/.github/workflows/"
        "ecosystem-catalog-crawl.yml@refs/heads/main"
    )


def test_trusted_signer_from_env_accepts_a_gitlab_shaped_config_too():
    # Provider-agnostic redesign (porting-pack round): the exact same
    # field names work for a GitLab CI signer -- issuer is the GitLab
    # instance's own URL, source_repository_uri is the project's URL.
    # No real GitLab-signed bundle exists to verify end-to-end here (this
    # repo's own crawl runs on GitHub Actions), but the parsing/shape
    # must not be GitHub-specific.
    signer = trusted_signer_from_env(
        '{"issuer": "https://gitlab.example.com", '
        '"source_repository_uri": "https://gitlab.example.com/group/project"}'
    )
    assert signer.issuer == "https://gitlab.example.com"
    assert signer.source_repository_uri == "https://gitlab.example.com/group/project"


@pytest.mark.parametrize("bad_json", [
    "{}",
    '{"issuer": "x"}',
    '{"issuer": "", "source_repository_uri": "https://github.com/a/b"}',
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


def test_verify_index_bytes_policy_checks_issuer_and_source_repository_uri_not_ref(monkeypatch):
    # The real point of this review round's redesign: confirm the actual
    # policy object built is an AllOf of exactly these two, provider-
    # agnostic extension checks, with no ref/subject check anywhere -- a
    # ref change (e.g. this workflow moving from a feature branch to
    # main) must never break verification.
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
    assert kinds == {policy_module.OIDCIssuer, policy_module.OIDCSourceRepositoryURI}


def test_verify_index_bytes_policy_adds_build_config_uri_check_only_when_configured(monkeypatch):
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

    signer_with_build_config = TrustedSigner(
        issuer=_A_SIGNER.issuer, source_repository_uri=_A_SIGNER.source_repository_uri,
        build_config_uri="https://github.com/adarsh8827/ainxt-enterprise/.github/workflows/x.yml@refs/heads/main",
    )
    verify_index_bytes(b"data", b"{}", signer_with_build_config)

    kinds = {type(child) for child in captured_policy["policy"]._children}
    assert kinds == {policy_module.OIDCIssuer, policy_module.OIDCSourceRepositoryURI, policy_module.OIDCBuildConfigURI}


def test_verify_index_bytes_accepts_the_real_bundle_the_workflow_actually_produced():
    # The real end-to-end proof this whole redesign was for: an
    # installation pointed at this fork's catalog must actually be able
    # to verify what the fixed workflow produces, not just satisfy a
    # mocked-out unit test.
    pytest.importorskip("sigstore")
    verify_index_bytes(_REAL_SIGNED_DATA, _REAL_SIGNED_BUNDLE, _A_SIGNER)


def test_verify_index_bytes_rejects_the_real_bundle_if_the_data_was_tampered_with():
    pytest.importorskip("sigstore")
    tampered = bytearray(_REAL_SIGNED_DATA)
    tampered[100] ^= 0xFF
    with pytest.raises(Exception):
        verify_index_bytes(bytes(tampered), _REAL_SIGNED_BUNDLE, _A_SIGNER)


def test_verify_index_bytes_rejects_the_real_bundle_against_a_different_build_config():
    pytest.importorskip("sigstore")
    wrong_signer = TrustedSigner(
        issuer=_A_SIGNER.issuer,
        source_repository_uri=_A_SIGNER.source_repository_uri,
        build_config_uri="https://github.com/adarsh8827/ainxt-enterprise/.github/workflows/some-other.yml@refs/heads/main",
    )
    with pytest.raises(Exception):
        verify_index_bytes(_REAL_SIGNED_DATA, _REAL_SIGNED_BUNDLE, wrong_signer)


def test_verify_index_bytes_rejects_the_real_bundle_against_a_different_repository():
    # The whole point of installation-side signer separation: verifying
    # a fork's index against a DIFFERENT repo's trusted signer (e.g. an
    # installation still pointed at upstream while fetching a fork's
    # catalog by mistake) must fail, never silently pass.
    pytest.importorskip("sigstore")
    wrong_signer = TrustedSigner(
        issuer=_A_SIGNER.issuer,
        source_repository_uri="https://github.com/some-other-org/ainxt-enterprise",
    )
    with pytest.raises(Exception):
        verify_index_bytes(_REAL_SIGNED_DATA, _REAL_SIGNED_BUNDLE, wrong_signer)
