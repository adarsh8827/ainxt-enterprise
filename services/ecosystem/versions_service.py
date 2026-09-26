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
from db.models import EcosystemItemVersion
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
