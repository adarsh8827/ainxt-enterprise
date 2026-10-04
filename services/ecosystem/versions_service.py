# SPDX-License-Identifier: MIT
# ============================================================
# Versions service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3 skeleton).
#
# create_or_refresh_legacy_version() is real, not a stub — task B-4's
# backfill job (M1) needs it now. See docs/ecosystem/design/LLD/
# legacy-bridge.md for why a version row exists at all for a legacy item
# whose live content is never migrated out of its source table.
# ============================================================

from __future__ import annotations

import json
from typing import Any

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion
from services.ecosystem.errors import NotFoundError
from services.ecosystem.items_service import _visible_to_caller
from store.ecosystem_object_storage import content_hash, get_ecosystem_object_storage


def encode_envelope(manifest: dict[str, Any], files: dict[str, str]) -> bytes:
    """The one content encoding every version's object-storage payload
    uses, regardless of which creation path produced it (task B-6's
    write/upload/import, or task B-4's legacy bridge) — the gate
    orchestrator (task B-9's gate_service.run_gate) decodes every version
    it scans with decode_envelope() below, so every producer must agree on
    this shape. Sorted keys so identical (manifest, files) always hashes
    identically regardless of dict insertion order.
    """
    return json.dumps({"manifest": manifest, "files": files}, sort_keys=True).encode("utf-8")


def decode_envelope(raw: bytes) -> tuple[dict[str, Any], dict[str, str]]:
    parsed = json.loads(raw.decode("utf-8"))
    return parsed.get("manifest", {}), parsed.get("files", {})


def get_manifest(version_id: str) -> dict[str, Any]:
    """Per-surface toggles round (2026-09-29): the install path needs a
    version's own `manifest` (specifically manifest["compatibility"],
    stamped by create_service.py's own classify_compatibility() at
    creation time) to re-run enforce_compatibility_on_surfaces() at
    INSTALL time too -- not just at create time. `EcosystemItemVersion.
    manifest` is stored directly as a JSONB column (see decode_envelope's
    own module docstring for why the object-storage payload duplicates
    it) so this is a cheap direct read, not an object-storage fetch.
    Returns {} for a version_id that doesn't resolve to a real row rather
    than raising -- callers treat a missing/unclassified manifest as
    "assume CHAT", the same safe default classify_compatibility() itself
    falls back to for empty instructions.
    """
    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
        return dict(version.manifest or {}) if version is not None else {}
    finally:
        db.close()


def create_or_refresh_legacy_version(
    *,
    item_id: str,
    content_text: str,
    manifest: dict[str, Any],
    license: str = "MIT",
    attribution: str = "",
    version: str = "legacy-1",
) -> tuple[str, bool]:
    """Create (or, if the legacy content changed, add a new) version row for
    a legacy-bridged item.

    Legacy items are read-through, not migrated (task B-4) — a live tool
    call still reads the current content from the legacy table, never from
    this version row. This version row exists only so the gate (task B-8/
    B-9) has something stable, hash-identified to scan and cache a verdict
    against; its object-storage copy is a scan target, not the item's
    source of truth. The content_hash is recomputed from the legacy
    content's current text on every backfill run — if the legacy owner has
    since edited the skill, the hash changes and a new version is written
    (re-triggering the gate), so a stale content_hash never masks new
    content that was never actually re-scanned.

    content_text is folded into manifest["instructions"] and encoded via
    the same encode_envelope() every other creation path uses (no bundled
    files for a legacy item) — so the gate orchestrator can scan a legacy
    version exactly the same way it scans any other, no special-casing.

    Returns (version_id, created) — created=True only when this exact
    content_hash hasn't been seen yet for this item.
    """
    full_manifest = {**manifest, "instructions": content_text}
    payload = encode_envelope(full_manifest, {})
    digest = content_hash(payload)

    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id, EcosystemItemVersion.content_hash == digest)
            .first()
        )
        if existing is not None:
            return existing.id, False

        store = get_ecosystem_object_storage()
        object_key = store.put(payload)

        # A prior version's number, if any, so the new one is distinguishable
        # (legacy-1, legacy-2, ...) without needing real semver from a source
        # that has no version concept of its own.
        prior_count = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id)
            .count()
        )
        version_label = version if prior_count == 0 else f"legacy-{prior_count + 1}"

        row = EcosystemItemVersion(
            item_id=item_id,
            version=version_label,
            content_hash=digest,
            object_key=object_key,
            license=license,
            attribution=attribution,
            manifest=full_manifest,
            gate_verdict="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, True
    finally:
        db.close()


def list_versions(item_id: str, *, caller_org_id: str, install_id: str | None = None) -> list[dict[str, Any]]:
    """GET /ecosystem/items/{id}/versions (CONTRACTS.md §9 `Version`),
    newest first; `is_current` marks the single most recent row — matches
    installs_service.update_to_version()'s own notion of "latest" (highest
    created_at), not a separately tracked pointer.

    caller_org_id: added after this function shipped with no visibility
    check at all -- any authenticated caller, any org, could read any
    item's version history (content_hash/pinned_sha included) by id. Reuses
    items_service's own `_visible_to_caller()` (global/builtin items are
    visible to everyone; an `org_private` item only to its own org) --
    the same boundary GET /ecosystem/items/{id} itself already enforces.

    install_id (BUG-U05 fix): `is_current` alone answers "what's the
    newest version of this item", a DIFFERENT question from "what version
    is THIS caller's own install actually pinned to" -- rollback/update
    change the latter (EcosystemInstall.version_id), never the former, so
    a caller who just rolled back saw literally no visible change anywhere
    (the "current" badge always meant "latest", not "yours"). When the
    caller's own install_id is supplied, each row also gets
    `is_installed_version` marking the ONE row (if any) that install is
    really pinned to right now -- independent of, and often different
    from, which row is newest. Silently omitted (every row False) if
    install_id is absent or doesn't resolve, same fail-open-to-"unknown"
    shape as get_manifest()'s own missing-id handling above.
    """
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, caller_org_id):
            raise NotFoundError(f"no such item {item_id!r}")
        rows = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id)
            .order_by(EcosystemItemVersion.created_at.desc())
            .all()
        )
        installed_version_id = None
        if install_id is not None:
            install = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
            if install is not None:
                installed_version_id = install.version_id
        return [
            {
                "id": row.id, "version": row.version, "pinned_sha": row.pinned_sha,
                "content_hash": row.content_hash, "license": row.license,
                "gate_verdict": row.gate_verdict,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "is_current": idx == 0,
                "is_installed_version": row.id == installed_version_id,
            }
            for idx, row in enumerate(rows)
        ]
    finally:
        db.close()


def create_version_for_content(
    *,
    item_id: str,
    content: bytes,
    manifest: dict[str, Any],
    license: str,
    attribution: str = "",
    version: str | None = None,
) -> str:
    """Create an immutable version row for freshly created/uploaded content
    (task B-6 — write/upload/import). Idempotent by content_hash within the
    item, same as the legacy path above: re-submitting byte-identical
    content returns the existing version rather than creating a duplicate.

    Returns the version_id.
    """
    digest = content_hash(content)

    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id, EcosystemItemVersion.content_hash == digest)
            .first()
        )
        if existing is not None:
            return existing.id

        store = get_ecosystem_object_storage()
        object_key = store.put(content)

        prior_count = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).count()
        version_label = version or ("1.0.0" if prior_count == 0 else f"1.0.{prior_count}")

        row = EcosystemItemVersion(
            item_id=item_id,
            version=version_label,
            content_hash=digest,
            object_key=object_key,
            license=license,
            attribution=attribution,
            manifest=manifest,
            gate_verdict="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()
