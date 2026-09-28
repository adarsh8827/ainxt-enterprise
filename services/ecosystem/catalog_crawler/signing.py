# SPDX-License-Identifier: MIT
# ============================================================
# Keyless signing/verification for the built index.json (or per-shard
# index files) on the `ecosystem-index` branch
# (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §2).
#
# Decision: Sigstore keyless signing via the crawl workflow's own GitHub
# Actions OIDC identity (the `sigstore` package, Apache-2.0) rather than
# minisign -- no long-lived private key to generate, store, or rotate
# ourselves; the signer's identity is the exact workflow file + repo that
# ran it, verifiable independently through Rekor's public transparency
# log. `sigstore` is imported lazily (inside these two functions, not at
# module load) so importing this module never requires the package to be
# installed in every environment that merely reads pointer/catalog code
# -- only the machine actually signing (the crawl workflow's runner) or
# verifying (an instance's sync worker) needs it installed.
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
    OIDC issuer + the GitHub Actions workflow's own repo + declared
    `name:`, deliberately NOT the branch ref (review decision, 2026-09-28,
    superseding the original issuer+subject design): a ref-based match
    would break every time the workflow moves branches (e.g. a fork's
    temporary default-branch switch for validation, or the eventual
    move from a feature branch to `main`), even though it's still
    provably the same workflow file in the same repo. Verified via three
    separate X.509v3 certificate extensions Fulcio embeds
    (`sigstore.verify.policy`'s `OIDCIssuer`/`GitHubWorkflowRepository`/
    `GitHubWorkflowName`), combined with `AllOf` -- not the single-SAN
    `Identity` policy, which only supports an exact-string match and
    would need the ref baked in.

    `ECOSYSTEM_CATALOG_TRUSTED_SIGNER` (env var, JSON string) is this
    struct's serialized form: `{"issuer": "...", "repository": "owner/
    repo", "workflow_name": "..."}`. A fork MUST set its own -- there is
    no default that trusts every possible signer.
    """
    issuer: str
    repository: str        # "owner/repo" -- the repo the workflow ran in, not necessarily this installation's own repo
    workflow_name: str     # the workflow YAML's own top-level `name:` field, e.g. "Ecosystem catalog crawl"


def sign_index_bytes(data: bytes) -> bytes:
    """Signs `data` using the ambient GitHub Actions OIDC credential
    (sigstore.oidc.detect_credential()) -- only succeeds when actually
    running inside a GitHub Actions job with `id-token: write` permission.
    Returns the serialized Sigstore bundle (JSON bytes) meant to be
    committed alongside the signed file as `<file>.sigstore`.
    """
    from sigstore.models import ClientTrustConfig
    from sigstore.oidc import IdentityToken, detect_credential
    from sigstore.sign import SigningContext

    identity_token_str = detect_credential()
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
    -- OIDC issuer + GitHub Actions repo + workflow name, NOT the branch
    ref (see TrustedSigner's own docstring for why). Raises on any
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
    from sigstore.verify.policy import AllOf, GitHubWorkflowName, GitHubWorkflowRepository, OIDCIssuer

    bundle = Bundle.from_json(bundle_bytes)
    if allow_online_trust_root_refresh:
        verifier = Verifier.production(offline=False)
    else:
        trusted_root = TrustedRoot.from_file(str(trust_root_path or _VENDORED_TRUST_ROOT_PATH))
        verifier = Verifier(trusted_root=trusted_root)
    policy = AllOf([
        OIDCIssuer(trusted_signer.issuer),
        GitHubWorkflowRepository(trusted_signer.repository),
        GitHubWorkflowName(trusted_signer.workflow_name),
    ])
    verifier.verify_artifact(input_=data, bundle=bundle, policy=policy)


def trusted_signer_from_env(value: str) -> TrustedSigner:
    """Parses `ECOSYSTEM_CATALOG_TRUSTED_SIGNER`'s JSON string form into
    a TrustedSigner. Raises ValueError on malformed/incomplete JSON --
    fail-closed, same as everywhere else in this module; a caller must
    never fall back to "trust nothing configured means trust everyone."
    """
    import json

    parsed = json.loads(value)
    missing = [k for k in ("issuer", "repository", "workflow_name") if not parsed.get(k)]
    if missing:
        raise ValueError(f"ECOSYSTEM_CATALOG_TRUSTED_SIGNER is missing required field(s): {missing}")
    return TrustedSigner(issuer=parsed["issuer"], repository=parsed["repository"], workflow_name=parsed["workflow_name"])
