#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline catalog bundle export (porting-pack round, 2026-09-29).

Exports the current signed skill index plus every APPROVED skill's own
real content into a self-contained bundle directory that
ECOSYSTEM_CATALOG_SOURCE_MODE=bundle (core/config.py,
services/ecosystem/catalog_sync.py's sync_catalog_from_bundle()/
_read_content_from_bundle()) can later sync + install from with ZERO
network calls -- built for an internal GitLab-hosted, air-gapped
instance with no internet/GitHub access, but the bundle itself is just a
directory tree; nothing about reading it is GitLab-specific.

Run this on a machine WITH real internet access (a maintainer's own
machine, or a CI job on the source repo's own GitHub Actions) --
ECOSYSTEM_CATALOG_URL/ECOSYSTEM_CATALOG_TRUSTED_SIGNER must be the
ONLINE values here regardless of what the target air-gapped instance's
own .env will later be set to, since this script needs to actually
reach the public index to re-verify+copy it.

"Approved" (this script's own gate, independent of whatever gate verdict
a version happens to carry, since a catalog-pointer item that was never
installed on THIS instance has no gate run at all yet):
  - item_type in ("skill", "connector", "mcp_server", "plugin") -- widened
    from the original "skill only" scope (Connectors+Plugins phase, Stage
    5). A connector/mcp_server pointer with no fetchable content
    (remote_only, content_hash="") is skipped the same way it already
    would be -- _content_for_never_installed_pointer only knows how to
    live-fetch source_kind in ("github_repo", "well_known"); nothing new
    was added there, so a never-installed mcp_registry/activepieces/
    mcp_server_repos pointer still correctly logs a skip rather than
    fabricating content. A locally-installed connector/mcp_server/plugin
    (has its own version + object-storage entry) exports exactly like a
    skill does today -- decode_envelope() doesn't care about item_type.
  - NEVER exports a real credential: a connector's exported manifest is
    its OWN declared shape (OAuth config, tool list, URLs) read from
    ecosystem_object_storage -- the actual per-user OAuth token lives in
    a completely separate table (ecosystem_secrets, store/
    ecosystem_secret_store.py) that this script never queries at all.
    Verified by a real test that seeds an actual ecosystem_secrets row
    and asserts its plaintext/ciphertext never appears anywhere in the
    exported bundle bytes.
  - license is MIT/Apache-2.0-compatible (services/ecosystem/
    license_policy.is_allowed_license()) -- the SAME check every real
    install already enforces.
  - content passes the real neutrality scanner (scan_for_ai_vendor_names)
    and the real fast static-safety check (run_fast_path) -- the SAME
    two checks the crawler itself already runs before a pointer ever
    reaches the signed index, re-run here directly against the actual
    bytes being bundled (not assumed from the pointer's own metadata).

Must run INSIDE a container/host sharing the SAME object-storage mount
gate-worker uses (assert_local_storage_root_is_mounted(), same
convention as scripts/ecosystem/admin_import.py -- see that module's own
header for the real 2026-09-28 incident this guards against).

Usage:
    python -m scripts.ecosystem.export_offline_bundle --output porting-pack/bundle [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from db.database import SessionLocal  # noqa: E402
from db.models import EcosystemItem, EcosystemItemVersion  # noqa: E402


def _log(msg: str) -> None:
    print(f"[export_offline_bundle] {msg}")


def _content_for_installed_item(item: EcosystemItem, version: EcosystemItemVersion) -> tuple[dict, dict] | None:
    """Reads manifest+files from THIS instance's own object storage --
    no network. Returns None (logged) on a real read failure rather than
    raising, so one bad object never aborts the whole export."""
    from services.ecosystem.versions_service import decode_envelope
    from store.ecosystem_object_storage import ObjectCorruptedError, ObjectNotFoundError, get_ecosystem_object_storage

    try:
        raw = get_ecosystem_object_storage().get(version.object_key)
    except (ObjectNotFoundError, ObjectCorruptedError) as exc:
        _log(f"SKIP {item.namespace!r}: object storage read failed for {version.object_key!r}: {exc}")
        return None
    manifest, files = decode_envelope(raw)
    return manifest, files


def _content_for_never_installed_pointer(item: EcosystemItem) -> tuple[dict, dict] | None:
    """A scope=central_index item with no version yet -- fetches the
    real content live (the same import adapters materialize_from_
    catalog() itself would use), requiring real internet access on THIS
    machine. Returns None (logged) on any fetch/drift failure."""
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.errors import EcosystemError

    pointer = dict(item.catalog_pointer or {})
    source_kind = pointer.get("source_kind", "")
    source_url = pointer.get("source_url", "")
    source_ref = pointer.get("source_ref", "")
    source_path = pointer.get("source_path", "")
    recorded_hash = pointer.get("content_hash", "")

    try:
        if source_kind == "github_repo":
            from services.ecosystem.import_adapters.github_repo import import_from_github, import_from_github_path

            repo = source_url.rstrip("/").split("github.com/", 1)[-1]
            imported = (
                import_from_github_path(repo, source_path, ref=source_ref) if source_path
                else import_from_github(repo, ref=source_ref)
            )
        elif source_kind == "well_known":
            from services.ecosystem.import_adapters.well_known import import_from_well_known

            domain, _, skill_slug = item.namespace.partition("/")
            imported = import_from_well_known(domain, skill_slug)
        else:
            _log(f"SKIP {item.namespace!r}: source_kind {source_kind!r} has no live-fetch adapter (not installable offline either)")
            return None
    except EcosystemError as exc:
        _log(f"SKIP {item.namespace!r}: live fetch failed: {exc}")
        return None

    manifest_text = imported["manifest"].get("instructions", "") if isinstance(imported.get("manifest"), dict) else ""
    fresh_hash = compute_content_hash(manifest_text, imported["files"])
    if recorded_hash and fresh_hash != recorded_hash:
        _log(f"SKIP {item.namespace!r}: fetched content no longer matches the catalog's recorded content_hash -- source changed since last sync")
        return None
    return imported["manifest"], imported["files"]


def export_bundle(output_dir: Path, *, dry_run: bool = False) -> dict:
    from services.ecosystem.catalog_crawler.neutrality_check import scan_for_ai_vendor_names
    from services.ecosystem.gate.static_safety_stage import run_fast_path
    from services.ecosystem.license_policy import is_allowed_license

    db = SessionLocal()
    try:
        items = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.item_type.in_(("skill", "connector", "mcp_server", "plugin")), EcosystemItem.status == "active")
            .all()
        )
        rows = [
            (item.id, item.namespace, item.item_type, item.display_name, item.description, item.license, item.catalog_pointer)
            for item in items
        ]
    finally:
        db.close()

    included = 0
    included_by_item_type: dict[str, int] = {}
    skipped_license = 0
    skipped_neutrality_or_safety = 0
    skipped_other = 0
    skills_dir = output_dir / "skills"  # content-hash-addressed, shared across every item_type -- see catalog_sync.py's _read_content_from_bundle(), which reads "skills/<hex>" regardless of the item's real type

    for item_id, namespace, item_type, display_name, description, license_str, catalog_pointer in rows:
        if not is_allowed_license(license_str):
            _log(f"SKIP {namespace!r}: license {license_str!r} is not MIT/Apache-2.0")
            skipped_license += 1
            continue

        db2 = SessionLocal()
        try:
            item = db2.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
            version = (
                db2.query(EcosystemItemVersion)
                .filter(EcosystemItemVersion.item_id == item_id)
                .order_by(EcosystemItemVersion.created_at.desc())
                .first()
            )
            if version is not None:
                db2.expunge(version)
            attribution = version.attribution if version else ""
        finally:
            db2.close()

        content = (
            _content_for_installed_item(item, version) if version is not None
            else _content_for_never_installed_pointer(item)
        )
        if content is None:
            skipped_other += 1
            continue
        manifest, files = content

        manifest_text = manifest.get("instructions", "") if isinstance(manifest, dict) else ""
        vendor_hits = scan_for_ai_vendor_names(manifest_text)
        for text in files.values():
            vendor_hits += [h for h in scan_for_ai_vendor_names(text) if h not in vendor_hits]
        if vendor_hits:
            _log(f"SKIP {namespace!r}: names AI vendor/product(s) {vendor_hits} -- violates neutrality requirement")
            skipped_neutrality_or_safety += 1
            continue
        fast_result = run_fast_path(files, manifest_text=manifest_text)
        if fast_result.verdict == "fail":
            reasons = "; ".join(f.code for f in fast_result.findings)
            _log(f"SKIP {namespace!r}: fast safety check failed: {reasons}")
            skipped_neutrality_or_safety += 1
            continue

        from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash

        content_hash_value = compute_content_hash(manifest_text, files)
        hex_digest = content_hash_value.split(":", 1)[-1]
        skill_dir = skills_dir / hex_digest

        if not dry_run:
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "content.json").write_text(
                json.dumps({"manifest": manifest, "files": files}, sort_keys=True), encoding="utf-8",
            )
            license_spdx = (catalog_pointer or {}).get("license_spdx") or license_str
            (skill_dir / "meta.json").write_text(
                json.dumps({
                    "namespace": namespace, "item_type": item_type, "display_name": display_name,
                    "description": description, "license_spdx": license_spdx, "attribution": attribution,
                }, sort_keys=True), encoding="utf-8",
            )
            # Human-readable, not just machine-readable -- "each with
            # LICENSE/NOTICE + attribution" per this round's own spec.
            (skill_dir / "ATTRIBUTION.txt").write_text(
                f"{namespace}\nLicense: {license_spdx}\nAttribution: {attribution}\n", encoding="utf-8",
            )
        included += 1
        included_by_item_type[item_type] = included_by_item_type.get(item_type, 0) + 1
        _log(f"OK {namespace!r} ({item_type}) -> skills/{hex_digest}")

    counts = {
        "included": included, "included_by_item_type": included_by_item_type,
        "skipped_license": skipped_license,
        "skipped_neutrality_or_safety": skipped_neutrality_or_safety, "skipped_other": skipped_other,
        "total_candidates": len(rows),
    }
    return counts


def export_signed_index(output_dir: Path, *, dry_run: bool = False) -> None:
    """Re-fetches the CURRENT signed skill index from ECOSYSTEM_CATALOG_URL
    (this machine's own real internet access), verifies it against
    ECOSYSTEM_CATALOG_TRUSTED_SIGNER, then copies both files byte-for-byte
    into `<output>/index/` -- never re-serializes/re-signs (that would
    invalidate the signature); the bundle carries the EXACT bytes the
    crawl workflow produced and signed."""
    from core.config import ECOSYSTEM_CATALOG_TRUSTED_SIGNER, ECOSYSTEM_CATALOG_URL
    from services.ecosystem.catalog_crawler.signing import trusted_signer_from_env, verify_index_bytes
    from services.ecosystem.catalog_sync import _fetch_with_etag

    if not ECOSYSTEM_CATALOG_URL or not ECOSYSTEM_CATALOG_TRUSTED_SIGNER:
        raise SystemExit(
            "export_offline_bundle: ECOSYSTEM_CATALOG_URL/ECOSYSTEM_CATALOG_TRUSTED_SIGNER must be set on THIS "
            "(exporting) machine -- it needs real internet access to fetch+verify the current signed index, "
            "regardless of what the target air-gapped instance's own .env will later say."
        )
    trusted_signer = trusted_signer_from_env(ECOSYSTEM_CATALOG_TRUSTED_SIGNER)

    index_dir = output_dir / "index"
    if not dry_run:
        index_dir.mkdir(parents=True, exist_ok=True)

    shard_url = f"{ECOSYSTEM_CATALOG_URL.rstrip('/')}/skill.json"
    data, _ = _fetch_with_etag(shard_url)
    bundle, _ = _fetch_with_etag(f"{shard_url}.sigstore")
    if data is None or bundle is None:
        raise SystemExit("export_offline_bundle: could not fetch the current skill.json/.sigstore -- aborting")
    verify_index_bytes(data, bundle, trusted_signer)
    _log(f"index signature verified OK ({len(data)} bytes)")

    if not dry_run:
        (index_dir / "skill.json").write_bytes(data)
        (index_dir / "skill.json.sigstore").write_bytes(bundle)


def main() -> int:
    from store.ecosystem_object_storage import assert_local_storage_root_is_mounted

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="porting-pack/bundle", help="bundle output directory (default: porting-pack/bundle)")
    parser.add_argument("--dry-run", action="store_true", help="report what would be exported without writing anything")
    parser.add_argument("--skip-index", action="store_true", help="skip re-fetching the signed index (skills-only export)")
    args = parser.parse_args()

    assert_local_storage_root_is_mounted()
    output_dir = Path(args.output)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    counts = export_bundle(output_dir, dry_run=args.dry_run)
    if not args.skip_index:
        export_signed_index(output_dir, dry_run=args.dry_run)

    if not args.dry_run:
        skills_dir = output_dir / "skills"
        total_bytes = sum(f.stat().st_size for f in skills_dir.rglob("*") if f.is_file()) if skills_dir.exists() else 0
        checksums = {
            str(f.relative_to(output_dir)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(output_dir.rglob("*")) if f.is_file()
        }
        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "total_skill_bytes": total_bytes,
            "checksums": checksums,
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    _log(f"done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
