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
# ============================================================

from __future__ import annotations

from dataclasses import dataclass


class SigningIdentityMismatchError(Exception):
    """Raised by verify_index_bytes() when the bundle's signer identity
    doesn't match the caller's configured trusted identity -- fail-closed,
    never a partial-trust fallback."""


@dataclass(frozen=True)
class TrustedIdentity:
    """The (issuer, subject) pair a verifier expects the signer's OIDC
    token to carry -- e.g. issuer="https://token.actions.githubusercontent.com",
    subject="repo:OWNER/REPO:ref:refs/heads/main" for a workflow run on
    `main` of a specific repo. A fork MUST configure its own (§2) --
    there is no default that verifies against every possible signer."""
    issuer: str
    subject: str


def sign_index_bytes(data: bytes) -> bytes:
    """Signs `data` using the ambient GitHub Actions OIDC credential
    (sigstore.oidc.detect_credential()) -- only succeeds when actually
    running inside a GitHub Actions job with `id-token: write` permission.
    Returns the serialized Sigstore bundle (JSON bytes) meant to be
    committed alongside the signed file as `<file>.sigstore`.
    """
    from sigstore.oidc import IdentityToken, detect_credential
    from sigstore.sign import SigningContext

    identity_token_str = detect_credential()
    if not identity_token_str:
        raise RuntimeError(
            "no ambient OIDC credential found -- sign_index_bytes() only works inside a GitHub "
            "Actions job with `permissions: id-token: write` (or another Sigstore-supported CI OIDC issuer)"
        )
    identity_token = IdentityToken(identity_token_str)

    signing_ctx = SigningContext.production()
    with signing_ctx.signer(identity_token) as signer:
        bundle = signer.sign_artifact(data)
    return bundle.to_json().encode("utf-8")


def verify_index_bytes(data: bytes, bundle_bytes: bytes, trusted_identity: TrustedIdentity) -> None:
    """Verifies `data` against `bundle_bytes` (a Sigstore bundle produced
    by sign_index_bytes()), asserting the signer's identity matches
    `trusted_identity` exactly. Raises on any failure -- bad signature,
    missing/invalid Rekor inclusion proof, or an identity mismatch -- so
    a caller's own try/except decides what "untrusted index" means for
    it (the sync worker treats it as a hard sync failure, never a
    silent partial-trust fallback). Returns None on success.
    """
    from sigstore.models import Bundle
    from sigstore.verify import Verifier
    from sigstore.verify.policy import Identity

    bundle = Bundle.from_json(bundle_bytes)
    verifier = Verifier.production()
    policy = Identity(identity=trusted_identity.subject, issuer=trusted_identity.issuer)
    verifier.verify_artifact(input_=data, bundle=bundle, policy=policy)
