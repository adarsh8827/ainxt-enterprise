# SPDX-License-Identifier: MIT
# ============================================================
# Keyless signing/verification for the built index.json (or per-shard
# index files) on the `ecosystem-index` branch
# (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §2).
#
# Decision: Sigstore keyless signing via the crawl job's own ambient CI
# OIDC identity (the `sigstore` package, Apache-2.0) rather than minisign
# -- no long-lived private key to generate, store, or rotate ourselves;
# the signer's identity is the exact workflow/pipeline file + repo that
# ran it, verifiable independently through Rekor's public transparency
# log. `sign_index_bytes()`'s own `detect_credential()` call is already
# provider-agnostic (sigstore-python natively detects GitHub Actions AND
# GitLab CI's own ambient OIDC token, among others) -- this repo's own
# crawl workflow happens to run on GitHub Actions, but nothing here is
# GitHub-specific; see TrustedSigner's own docstring for the matching
# provider-agnostic verification side. `sigstore` is imported lazily
# (inside these two functions, not at module load) so importing this
# module never requires the package to be installed in every environment
# that merely reads pointer/catalog code -- only the machine actually
# signing (the crawl job's runner) or verifying (an instance's sync
# worker) needs it installed.
#
# Verification is OFFLINE BY DEFAULT (real review requirement: air-gapped/
# firewalled installs and offline snapshot imports must be able to verify
# with zero network calls). `vendor/sigstore_trusted_root.json` is a
# pinned, checked-in copy of Sigstore's public production trust root
# (Fulcio/Rekor/CT public keys) -- fetched once (2026-09-28) via a real
# TUF refresh and vendored here, not regenerated at runtime. Confirmed
# directly against sigstore-python 4.5.0's own source
# (sigstore/verify/verifier.py's Verifier.verify_artifact(), called with
# a `Verifier(trusted_root=...)` built from a local file): the actual
# verification path performs signature/hash/Merkle-inclusion-proof checks
# entirely against the bundle's own embedded data and the trusted root's
# public keys -- the `RekorClient` it constructs is never invoked
# (grepped for `self._rekor.` -- zero call sites) as long as the bundle
# carries its own embedded log-inclusion proof, which every bundle
# sign_index_bytes() produces does. `allow_online_trust_root_refresh=True`
# is the one opt-in exception (documented on verify_index_bytes() below)
# -- egress hosts by mode:
#   - Signing (CI only, inherently online): fulcio.sigstore.dev (cert
#     issuance), rekor.sigstore.dev (log submission),
#     token.actions.githubusercontent.com (the ambient OIDC token itself).
#   - Verification, default (offline): none.
#   - Verification, allow_online_trust_root_refresh=True: tuf-repo-
#     cdn.sigstore.dev only (refreshes the trust root itself; still no
#     Rekor/Fulcio call for the artifact-verification step itself).
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_VENDORED_TRUST_ROOT_PATH = Path(__file__).parent / "vendor" / "sigstore_trusted_root.json"


class SigningIdentityMismatchError(Exception):
    """Raised by verify_index_bytes() when the bundle's signer identity
    doesn't match the caller's configured trusted signer -- fail-closed,
    never a partial-trust fallback."""


@dataclass(frozen=True)
class TrustedSigner:
    """Who a verifier trusts to have signed the index -- matched on the
    OIDC issuer + the CI project/repo's own URI, deliberately NOT the
    branch ref (review decision, 2026-09-28, superseding the original
    issuer+subject design): a ref-based match would break every time the
    workflow moves branches (e.g. a fork's temporary default-branch
    switch for validation, or the eventual move from a feature branch to
    `main`), even though it's still provably the same workflow file in
    the same repo.

    Provider-agnostic redesign (porting-pack round): originally matched
    on GitHub-specific Fulcio certificate extensions
    (`GitHubWorkflowRepository`/`GitHubWorkflowName`), which only a
    GitHub-Actions-issued certificate populates. Fulcio ALSO embeds a
    parallel set of generic, provider-agnostic extensions for every OIDC
    issuer (GitHub Actions, GitLab CI, or otherwise) -- `OIDCIssuer`
    (already used) and `OIDCSourceRepositoryURI` (confirmed empirically
    against this package's own real, checked-in GitHub Actions fixture
    bundle: OID 1.3.6.1.4.1.57264.1.12 carries
    "https://github.com/<owner>/<repo>" on that real cert). Using these
    two lets the exact same verification code trust either a GitHub
    Actions signer (`source_repository_uri="https://github.com/owner/
    repo"`) or a future GitLab CI signer (`source_repository_uri=
    "https://gitlab.example.com/group/project"`, `issuer=` the GitLab
    instance's own URL) with no provider-specific branching anywhere in
    this module.

    `ECOSYSTEM_CATALOG_TRUSTED_SIGNER` (env var, JSON string) is this
    struct's serialized form: `{"issuer": "...", "source_repository_uri":
    "https://github.com/owner/repo"}` (`build_config_uri` optional). A
    fork MUST set its own -- there is no default that trusts every
    possible signer.
    """
    issuer: str
    source_repository_uri: str    # e.g. "https://github.com/owner/repo" or "https://gitlab.example.com/group/project" -- the project the workflow/pipeline ran in, not necessarily this installation's own repo
    # Optional, stricter check: the exact build-config file Fulcio recorded
    # (OIDCBuildConfigURI -- e.g. "https://github.com/owner/repo/.github/
    # workflows/crawl.yml@refs/heads/main" or GitLab's ".gitlab-ci.yml"
    # equivalent). None (the default) means "trust any workflow/pipeline
    # in that repo with that issuer" -- set this to additionally pin the
    # specific CI config file allowed to sign.
    build_config_uri: str | None = None


def sign_index_bytes(data: bytes) -> bytes:
    """Signs `data` using the ambient GitHub Actions OIDC credential
    (sigstore.oidc.detect_credential()) -- only succeeds when actually
    running inside a GitHub Actions job with `id-token: write` permission.
    Returns the serialized Sigstore bundle (JSON bytes) meant to be
    committed alongside the signed file as `<file>.sigstore`.
    """
    from sigstore.models import ClientTrustConfig
    from sigstore.oidc import IdentityError, IdentityToken, detect_credential
    from sigstore.sign import SigningContext

    # detect_credential() doesn't just return None/falsy when there's no
    # credential -- found live, 2026-10-04: inside a REAL GitHub Actions job
    # that merely lacks `permissions: id-token: write` (e.g. this repo's own
    # CI Tier 2 test job), it recognizes the GITHUB_ACTIONS=true environment
    # and actively tries to fetch a token, raising sigstore.oidc.IdentityError
    # ("missing or insufficient OIDC token permissions") when that fetch
    # fails -- a different case from truly running outside any CI (a dev's
    # own machine, this repo's own test suite run locally), where it quietly
    # returns None. Both are exactly the same "no usable ambient credential"
    # situation from this function's own point of view, so both fail closed
    # with the same documented error below.
    try:
        identity_token_str = detect_credential()
    except IdentityError:
        identity_token_str = None
    if not identity_token_str:
        raise RuntimeError(
            "no ambient OIDC credential found -- sign_index_bytes() only works inside a GitHub "
            "Actions job with `permissions: id-token: write` (or another Sigstore-supported CI OIDC issuer)"
        )
    identity_token = IdentityToken(identity_token_str)

    # sigstore==4.5.0 has no SigningContext.production() classmethod (a
    # real bug found live, 2026-09-28: the actual GitHub Actions run --
    # the only environment with an ambient credential to reach this line
    # at all -- crashed here with AttributeError; every local/CI test
    # environment fails closed at the check above first, so this line
    # was never actually exercised until the real run hit it). The
    # current, real API is SigningContext.from_trust_config(), given a
    # ClientTrustConfig -- ClientTrustConfig.production() is the direct
    # replacement for the removed shortcut.
    signing_ctx = SigningContext.from_trust_config(ClientTrustConfig.production())
    with signing_ctx.signer(identity_token) as signer:
        bundle = signer.sign_artifact(data)
    return bundle.to_json().encode("utf-8")


def verify_index_bytes(
    data: bytes,
    bundle_bytes: bytes,
    trusted_signer: TrustedSigner,
    *,
    allow_online_trust_root_refresh: bool = False,
    trust_root_path: str | Path | None = None,
) -> None:
    """Verifies `data` against `bundle_bytes` (a Sigstore bundle produced
    by sign_index_bytes()), asserting the signer matches `trusted_signer`
    -- OIDC issuer + source repository URI (+ optionally the exact build
    config), NOT the branch ref (see TrustedSigner's own docstring for
    why). Provider-agnostic: works identically for a GitHub Actions or a
    GitLab CI signer. Raises on any
    failure -- bad signature, missing/invalid Rekor inclusion proof, or
    an identity mismatch -- so a caller's own try/except decides what
    "untrusted index" means for it (the sync worker treats it as a hard
    sync failure, never a silent partial-trust fallback). Returns None
    on success.

    Offline by default: loads the trust root from a pinned, checked-in
    file (`trust_root_path`, defaulting to this package's own
    `vendor/sigstore_trusted_root.json`) via `TrustedRoot.from_file()`
    rather than fetching one over the network -- required for air-gapped/
    firewalled installs and for verifying an offline-uploaded index
    snapshot with zero network calls (this module's own header comment
    has the full egress-host breakdown by mode). Set
    `allow_online_trust_root_refresh=True` to instead fetch a fresh trust
    root from Sigstore's TUF repository (`tuf-repo-cdn.sigstore.dev`) --
    an explicit opt-in for staying current with an eventual Fulcio/Rekor
    key rotation, never the default.
    """
    from sigstore.models import Bundle, TrustedRoot
    from sigstore.verify import Verifier
    from sigstore.verify.policy import AllOf, OIDCBuildConfigURI, OIDCIssuer, OIDCSourceRepositoryURI

    bundle = Bundle.from_json(bundle_bytes)
    if allow_online_trust_root_refresh:
        verifier = Verifier.production(offline=False)
    else:
        trusted_root = TrustedRoot.from_file(str(trust_root_path or _VENDORED_TRUST_ROOT_PATH))
        verifier = Verifier(trusted_root=trusted_root)
    checks = [
        OIDCIssuer(trusted_signer.issuer),
        OIDCSourceRepositoryURI(trusted_signer.source_repository_uri),
    ]
    if trusted_signer.build_config_uri:
        checks.append(OIDCBuildConfigURI(trusted_signer.build_config_uri))
    policy = AllOf(checks)
    verifier.verify_artifact(input_=data, bundle=bundle, policy=policy)


def trusted_signer_from_env(value: str) -> TrustedSigner:
    """Parses `ECOSYSTEM_CATALOG_TRUSTED_SIGNER`'s JSON string form into
    a TrustedSigner. Raises ValueError on malformed/incomplete JSON --
    fail-closed, same as everywhere else in this module; a caller must
    never fall back to "trust nothing configured means trust everyone."
    """
    import json

    parsed = json.loads(value)
    missing = [k for k in ("issuer", "source_repository_uri") if not parsed.get(k)]
    if missing:
        raise ValueError(f"ECOSYSTEM_CATALOG_TRUSTED_SIGNER is missing required field(s): {missing}")
    return TrustedSigner(
        issuer=parsed["issuer"], source_repository_uri=parsed["source_repository_uri"],
        build_config_uri=parsed.get("build_config_uri"),
    )
