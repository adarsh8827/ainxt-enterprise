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

import re

from db.database import SessionLocal
from db.models import EcosystemPublisher
from services.ecosystem.errors import NamespaceInvalidError

# Lowercase alnum + hyphen/underscore, 2-64 chars — mirrors common package-
# registry slug conventions (npm/PyPI); no length/charset rule is specified
# in CONTRACTS.md §15, so this is a deliberate, documented choice rather
# than an unstated assumption.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


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
    if owner_type not in ("org", "user"):
        raise NamespaceInvalidError(f"owner_type must be 'org' or 'user', got {owner_type!r}")

    publisher_slug, _item_name = split_namespace(namespace)

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
