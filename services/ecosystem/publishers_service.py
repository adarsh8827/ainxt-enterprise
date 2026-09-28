# SPDX-License-Identifier: MIT
# ============================================================
# Publisher/namespace service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-5).
#
# An ecosystem item's namespace is "publisher/name". The publisher segment
# must resolve to a verified row in ecosystem_publishers before an item can
# be created under it (docs/ecosystem/CONTRACTS.md §15) — auto-provisioned
# on first use by its owner, never requiring a separate manual registration
# step, but never resolvable by anyone other than the owner who first
# claimed it.
# ============================================================

from __future__ import annotations

import hashlib
import re

from db.database import SessionLocal
from db.models import EcosystemPublisher
from services.ecosystem.errors import NamespaceInvalidError

# Lowercase alnum + hyphen/underscore, 2-64 chars — mirrors common package-
# registry slug conventions (npm/PyPI); no length/charset rule is specified
# in CONTRACTS.md §15, so this is a deliberate, documented choice rather
# than an unstated assumption.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

# Anything not in the slug charset collapses to a single hyphen, so
# "John.Doe@x.com" and "john_doe@x.com" don't silently produce the exact
# same sanitized text (they'd still differ once the hash suffix below is
# appended, but collapsing runs keeps the human-readable part legible).
_SLUG_DISALLOWED_RE = re.compile(r"[^a-z0-9_-]+")


def split_namespace(namespace: str) -> tuple[str, str]:
    """Split "publisher/name" into (publisher_slug, item_name).

    Raises NamespaceInvalidError if the namespace isn't exactly two
    non-empty segments, or either segment fails the slug charset check.
    """
    parts = (namespace or "").split("/")
    if len(parts) != 2:
        raise NamespaceInvalidError(
            f"namespace {namespace!r} must be exactly 'publisher/name' (one slash)"
        )
    publisher_slug, item_name = parts
    if not _SLUG_RE.match(publisher_slug):
        raise NamespaceInvalidError(f"publisher segment {publisher_slug!r} is not a valid slug")
    if not _SLUG_RE.match(item_name):
        raise NamespaceInvalidError(f"name segment {item_name!r} is not a valid slug")
    return publisher_slug, item_name


def _ensure_publisher_row(publisher_slug: str, owner_type: str, owner_ref: str) -> str:
    """Auto-provision a fresh ecosystem_publishers row for publisher_slug on
    first use, or verify the caller owns an already-existing one. Shared by
    resolve_publisher() (an explicit namespace's publisher segment) and
    resolve_caller_publisher_slug() (a derived, caller-own-identity slug) —
    one provisioning path, not two."""
    if owner_type not in ("org", "user"):
        raise NamespaceInvalidError(f"owner_type must be 'org' or 'user', got {owner_type!r}")

    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemPublisher)
            .filter(EcosystemPublisher.slug == publisher_slug)
            .first()
        )
        if existing is None:
            row = EcosystemPublisher(
                slug=publisher_slug,
                owner_type=owner_type,
                owner_ref=owner_ref,
            )
            db.add(row)
            db.commit()
            return publisher_slug

        if existing.owner_type != owner_type or existing.owner_ref != owner_ref:
            raise NamespaceInvalidError(
                f"publisher slug {publisher_slug!r} is already owned by a different {existing.owner_type}"
            )
        return publisher_slug
    finally:
        db.close()


def resolve_publisher(
    namespace: str,
    owner_type: str,
    owner_ref: str,
) -> str:
    """Resolve the namespace's publisher segment, auto-provisioning a fresh
    ecosystem_publishers row on first use, or verifying the caller owns an
    already-existing one.

    owner_type: 'org' | 'user' — matches ecosystem_publishers.owner_type.
    owner_ref:  the org_id or user_id that would own a newly-provisioned slug.

    Returns the validated publisher slug. Raises NamespaceInvalidError if
    the namespace is malformed, or the slug exists under a different owner.
    """
    publisher_slug, _item_name = split_namespace(namespace)
    return _ensure_publisher_row(publisher_slug, owner_type, owner_ref)


def derive_caller_publisher_slug(user_id: str, org_id: str) -> str:
    """Deterministic, _SLUG_RE-safe publisher segment derived from a
    caller's own identity (task: one-click "Copy to my skills" — no create
    flow in this codebase previously had any notion of "this caller's own
    default publisher prefix", per CreateForm.tsx's own disclosed gap).

    Keyed by BOTH user_id and org_id, not user_id alone: ecosystem_publishers.slug
    is globally unique (resolve_publisher()'s own lookup has no org_id filter
    at all), and every namespace create_via_write()/create_via_upload() actually
    provisions is registered owner_type='org', owner_ref=org_id (an org_private
    item's real owner is its org, not the individual member who happened to
    create it, _create_item_and_version()). A user_id-only slug would let the
    SAME person active in two different orgs derive the identical slug while
    needing two different, mutually-exclusive org owners for it — org_id in
    the hash keeps each (org, user) pair's derived slug distinct.

    user_id is whatever the auth layer's sub/user_id/id claim contains — not
    guaranteed to already be slug-safe (an email, a mixed-case UUID, etc.) —
    so this lowercases and collapses disallowed characters for legibility,
    then ALWAYS appends a short deterministic hash of the raw (org_id, user_id)
    pair, which is what actually guarantees uniqueness (two different user_ids
    can sanitize to identical text, e.g. "John.Doe@x.com" and "john_doe@x.com"
    both collapse toward "john-doe"). Same (user_id, org_id) always produces
    the same slug (deterministic hash, no randomness)."""
    if not user_id:
        raise ValueError("user_id is required to derive a publisher slug")
    sanitized = _SLUG_DISALLOWED_RE.sub("-", user_id.strip().lower()).strip("-_")
    base = sanitized[:40] if sanitized else "u"
    digest = hashlib.sha256(f"{org_id}:{user_id}".encode("utf-8")).hexdigest()[:10]
    return f"{base}-{digest}"[:64]


def resolve_caller_publisher_slug(user_id: str, org_id: str) -> str:
    """derive_caller_publisher_slug(user_id, org_id), auto-provisioned via
    the same ecosystem_publishers path resolve_publisher() uses —
    owner_type='org', owner_ref=org_id, matching exactly what
    create_via_write()'s own resolve_publisher(namespace, owner_type="org",
    owner_ref=org_id) call will expect when the resulting namespace is
    actually used to create an item. Idempotent: a returning caller in the
    same org gets back the same, already-provisioned slug every time."""
    slug = derive_caller_publisher_slug(user_id, org_id)
    return _ensure_publisher_row(slug, owner_type="org", owner_ref=org_id)


def get_publisher(publisher_slug: str) -> dict | None:
    """Return {"slug", "owner_type", "owner_ref", "verified_at"} or None."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == publisher_slug).first()
        if row is None:
            return None
        return {
            "slug": row.slug,
            "owner_type": row.owner_type,
            "owner_ref": row.owner_ref,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        }
    finally:
        db.close()
