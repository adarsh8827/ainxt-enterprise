# SPDX-License-Identifier: MIT
# ============================================================
# Catalog sync (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §5) -- fetches
# the signed ecosystem-index catalog (built by
# .github/workflows/ecosystem-catalog-crawl.yml) and upserts pointer-
# only EcosystemItem rows (scope="central_index") so Discover can
# actually surface them. No skill content is downloaded here -- that
# only happens on demand, at install time (materialize_from_catalog()
# below), reusing create_service.py's existing import adapters.
#
# Fail-closed on signing, matching run_catalog_crawl.py's own
# --verify-after-sign contract: a shard whose signature doesn't verify
# against ECOSYSTEM_CATALOG_TRUSTED_SIGNER is not upserted at all, and
# the failure is returned/logged with a specific reason -- never a
# partial-trust fallback.
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from connectors.net_relay import relay_request
from db.database import SessionLocal
from db.models import EcosystemItem
from services.ecosystem.catalog_crawler.pointer_schema import PointerEntry, compute_content_hash
from services.ecosystem.catalog_crawler.signing import TrustedSigner, verify_index_bytes
from services.ecosystem.errors import EcosystemError, ImportFetchError
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.items_service import get_latest_version, get_or_create_import_source

_SHARD_ITEM_TYPES = ("skill", "mcp_server")
_SYNCED_BY = "catalog_sync"


@dataclass
class ShardSyncResult:
    shard: str
    fetched: bool = False          # False on a 304 (unchanged)
    verified: bool = False
    error: str | None = None
    created: int = 0
    updated: int = 0
    yanked: int = 0


@dataclass
class SyncReport:
    shards: list[ShardSyncResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.error is None for s in self.shards)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "shards": [
                {
                    "shard": s.shard, "fetched": s.fetched, "verified": s.verified,
                    "error": s.error, "created": s.created, "updated": s.updated, "yanked": s.yanked,
                }
                for s in self.shards
            ],
        }


class CatalogSyncError(EcosystemError):
    """A shard failed to verify or fetch -- callers decide whether that
    aborts the whole sync or just skips that one shard (sync_catalog()
    itself always does the latter, recording the error on that shard's
    ShardSyncResult rather than raising, so one bad shard never blocks
    the other from syncing)."""


def _etag_cache_key(shard: str) -> str:
    return f"catalog_sync:etag:{shard}"


def _fetch_with_etag(url: str) -> tuple[bytes | None, bool]:
    """Returns (body_bytes, fetched) -- fetched=False means a 304 (the
    cached body, if any, is still valid; body_bytes is None in that
    case, callers must skip). Raises ImportFetchError on any non-200/304
    response. ETag state is stored via the same content-by-identity
    fetch_cache every other ecosystem import adapter already uses."""
    cache_key = _etag_cache_key(url)
    cached_raw = get_cached(cache_key)
    cached_etag: str | None = None
    if cached_raw is not None:
        try:
            cached_etag = json.loads(cached_raw.decode("utf-8")).get("etag")
        except (ValueError, UnicodeDecodeError, AttributeError):
            cached_etag = None

    safe_url = assert_safe_https_url(url)
    headers = {}
    if cached_etag:
        headers["If-None-Match"] = cached_etag
    resp = relay_request("GET", safe_url, headers=headers, timeout=30.0)

    if resp.status_code == 304:
        return None, False
    if resp.status_code != 200:
        raise ImportFetchError(f"catalog_sync: HTTP {resp.status_code} fetching {url!r}")

    etag = resp.headers.get("ETag") or resp.headers.get("etag")
    if etag:
        put_cached(cache_key, json.dumps({"etag": etag}).encode("utf-8"))
    return resp.content, True


def _status_for_item_type(item_type: str) -> str:
    # mcp_server install support doesn't exist yet (create_via_import's
    # mcp_registry branch raises NotImplementedError by design) --
    # stored so future work can see it, never shown by default
    # (items_service.list_items()'s own status exclusion).
    return "coming_soon" if item_type == "mcp_server" else "active"


def _upsert_pointer_entry(db, entry: PointerEntry, *, seen_ids: set[str]) -> str:
    """Create or update the EcosystemItem for one pointer entry. Returns
    "created" or "updated". Adds the row's id to seen_ids so the caller
    can yank anything from a prior sync that's no longer present."""
    existing = (
        db.query(EcosystemItem)
        .filter(EcosystemItem.namespace == entry.namespace, EcosystemItem.item_type == entry.item_type)
        .first()
    )
    source_id = get_or_create_import_source(
        kind=entry.source_kind, url=entry.source_url, created_by=_SYNCED_BY,
        tos_notes=f"External sources catalog ({entry.source_kind}): {entry.source_url!r}.",
    )
    catalog_pointer = {
        "source_kind": entry.source_kind, "source_url": entry.source_url,
        "source_ref": entry.source_ref, "source_path": entry.source_path,
        "content_hash": entry.content_hash, "license_evidence": entry.license_evidence,
        "compatibility": entry.compatibility,
    }
    if existing is not None:
        existing.display_name = entry.display_name
        existing.description = entry.description
        existing.category = entry.category
        existing.tags = list(entry.tags)
        existing.license = entry.license_spdx
        existing.source_id = source_id
        existing.catalog_pointer = catalog_pointer
        existing.status = _status_for_item_type(entry.item_type)
        db.flush()
        seen_ids.add(existing.id)
        return "updated"

    row = EcosystemItem(
        namespace=entry.namespace, item_type=entry.item_type, category=entry.category,
        tags=list(entry.tags), display_name=entry.display_name, description=entry.description,
        source_id=source_id, scope="central_index", org_id=None, trust_tier="community",
        license=entry.license_spdx, status=_status_for_item_type(entry.item_type),
        catalog_pointer=catalog_pointer,
    )
    db.add(row)
    db.flush()
    seen_ids.add(row.id)
    return "created"


def _sync_one_shard(base_url: str, shard: str, trusted_signer: TrustedSigner) -> ShardSyncResult:
    result = ShardSyncResult(shard=shard)
    shard_url = f"{base_url.rstrip('/')}/{shard}.json"
    bundle_url = f"{shard_url}.sigstore"

    try:
        data, fetched = _fetch_with_etag(shard_url)
    except ImportFetchError as exc:
        result.error = f"fetch failed: {exc}"
        return result
    result.fetched = fetched
    if not fetched:
        return result  # 304 -- unchanged, nothing to verify or upsert

    try:
        bundle, _ = _fetch_with_etag(bundle_url)
        if bundle is None:
            # A 304 on the bundle URL alone (no cached etag for THIS run)
            # can't happen in practice since we never send If-None-Match
            # for a URL we haven't fetched before -- but fail closed
            # rather than assume.
            raise ImportFetchError(f"no signature bundle body returned for {bundle_url!r}")
    except ImportFetchError as exc:
        result.error = f"signature bundle fetch failed -- rejecting unsigned index: {exc}"
        return result

    try:
        verify_index_bytes(data, bundle, trusted_signer)
    except Exception as exc:
        result.error = f"signature verification failed -- rejecting: {exc}"
        return result
    result.verified = True

    try:
        rows = json.loads(data.decode("utf-8"))
    except Exception as exc:
        result.error = f"index JSON parse failed: {exc}"
        return result

    entries = [PointerEntry.from_yaml_dict(row) for row in rows]

    db = SessionLocal()
    try:
        seen_ids: set[str] = set()
        for entry in entries:
            outcome = _upsert_pointer_entry(db, entry, seen_ids=seen_ids)
            if outcome == "created":
                result.created += 1
            else:
                result.updated += 1

        # Anything previously synced under this shard's item_type that's
        # absent from the current fetch (removed upstream, including
        # anything the crawler dropped via yanked.yaml) is hidden -- not
        # deleted, so audit/install history for it is preserved.
        stale = (
            db.query(EcosystemItem)
            .filter(
                EcosystemItem.item_type == shard, EcosystemItem.scope == "central_index",
                EcosystemItem.status != "yanked", ~EcosystemItem.id.in_(seen_ids) if seen_ids else True,
            )
            .all()
        )
        for row in stale:
            row.status = "yanked"
            result.yanked += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        result.error = f"upsert failed: {exc}"
    finally:
        db.close()

    return result


def sync_catalog(base_url: str, trusted_signer: TrustedSigner) -> SyncReport:
    """Syncs every known shard (skill, mcp_server) from base_url (the
    catalog's index/ directory -- NOT a specific shard file). Each
    shard is independent: a signature failure on one never blocks the
    other from syncing."""
    report = SyncReport()
    for shard in _SHARD_ITEM_TYPES:
        report.shards.append(_sync_one_shard(base_url, shard, trusted_signer))
    return report


def sync_from_local_files(paths: dict[str, tuple[str, str]], trusted_signer: TrustedSigner) -> SyncReport:
    """Offline snapshot import -- same verify+upsert as sync_catalog(),
    from local files instead of HTTP. `paths` maps shard name ("skill",
    "mcp_server") to (index_json_path, sigstore_bundle_path); a shard
    absent from `paths` is simply skipped (not an error -- an operator
    may only have one shard's snapshot on hand)."""
    report = SyncReport()
    for shard in _SHARD_ITEM_TYPES:
        if shard not in paths:
            continue
        index_path, bundle_path = paths[shard]
        result = ShardSyncResult(shard=shard, fetched=True)
        try:
            data = open(index_path, "rb").read()
            bundle = open(bundle_path, "rb").read()
        except OSError as exc:
            result.error = f"could not read snapshot files: {exc}"
            report.shards.append(result)
            continue

        try:
            verify_index_bytes(data, bundle, trusted_signer)
        except Exception as exc:
            result.error = f"signature verification failed -- rejecting: {exc}"
            report.shards.append(result)
            continue
        result.verified = True

        try:
            rows = json.loads(data.decode("utf-8"))
            entries = [PointerEntry.from_yaml_dict(row) for row in rows]
        except Exception as exc:
            result.error = f"index JSON parse failed: {exc}"
            report.shards.append(result)
            continue

        db = SessionLocal()
        try:
            seen_ids: set[str] = set()
            for entry in entries:
                outcome = _upsert_pointer_entry(db, entry, seen_ids=seen_ids)
                if outcome == "created":
                    result.created += 1
                else:
                    result.updated += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            result.error = f"upsert failed: {exc}"
        finally:
            db.close()
        report.shards.append(result)
    return report


def run_scheduled_sync() -> None:
    """Zero-arg entry point for workers/start_workers.py's cron
    scheduler thread (interval_jobs). Re-checks ECOSYSTEM_CATALOG_SYNC
    itself (defense in depth -- the scheduler only registers this job
    when the flag is on at startup, but a config re-read shouldn't rely
    on that alone), reads the URL/signer from core.config, and logs a
    summary. Never raises -- the scheduler's own dispatch loop already
    catches exceptions per-tick, but a partial/aborted sync should look
    like a clean, well-logged no-op, not an unhandled crash."""
    from core.config import ECOSYSTEM_CATALOG_SYNC, ECOSYSTEM_CATALOG_TRUSTED_SIGNER, ECOSYSTEM_CATALOG_URL
    from core.logger import logger

    if not ECOSYSTEM_CATALOG_SYNC:
        return
    if not ECOSYSTEM_CATALOG_URL or not ECOSYSTEM_CATALOG_TRUSTED_SIGNER:
        logger.warning(
            "ecosystem catalog_sync: ECOSYSTEM_CATALOG_SYNC is true but "
            "ECOSYSTEM_CATALOG_URL/ECOSYSTEM_CATALOG_TRUSTED_SIGNER is not set -- skipping"
        )
        return

    # trusted_signer_from_env() is the real, validating parser -- imported
    # lazily (matches signing.py's own module docstring: sigstore is only
    # ever imported inside functions that actually need it).
    from services.ecosystem.catalog_crawler.signing import trusted_signer_from_env

    try:
        trusted_signer = trusted_signer_from_env(ECOSYSTEM_CATALOG_TRUSTED_SIGNER)
    except ValueError as exc:
        logger.error(f"ecosystem catalog_sync: invalid ECOSYSTEM_CATALOG_TRUSTED_SIGNER -- {exc}")
        return

    report = sync_catalog(ECOSYSTEM_CATALOG_URL, trusted_signer)
    for shard in report.shards:
        if shard.error:
            logger.error(f"ecosystem catalog_sync: shard {shard.shard!r} failed -- {shard.error}")
        else:
            logger.info(
                f"ecosystem catalog_sync: shard {shard.shard!r} fetched={shard.fetched} "
                f"created={shard.created} updated={shard.updated} yanked={shard.yanked}"
            )


# ── Install-from-catalog ─────────────────────────────────────────────────
# Materializes a scope="central_index" item's first real version on
# demand, reusing the existing create_service.py import adapters --
# never re-implemented here. Called by the install endpoint when the
# target item has no version yet.

class CatalogInstallNotSupportedError(EcosystemError):
    """Raised for a source_kind with no installer built yet (mcp_registry,
    this phase) -- a clear, typed error rather than a confusing
    NotImplementedError leaking out of create_via_import()."""


class CatalogContentDriftError(EcosystemError):
    """Raised when freshly-fetched content's hash doesn't match the
    pointer's recorded content_hash -- the source moved since the last
    sync (e.g. someone force-pushed the pinned ref) or something
    tampered with it. Never installs mismatched content silently."""


class _AlreadyInFlightError(EcosystemError):
    """Internal -- caught by materialize_from_catalog()'s own retry loop,
    never expected to escape to a caller."""


def materialize_from_catalog(item_id: str, *, requested_by: str, org_id: str) -> str:
    """Fetches real content for a scope="central_index" item that has no
    EcosystemItemVersion yet, verifies it against the pointer's own
    recorded content_hash, and creates the version (full gate, exactly
    like a normal import). Returns the new version_id. Raises
    CatalogInstallNotSupportedError / CatalogContentDriftError /
    ImportFetchError / LicenseNotAllowedError on failure -- callers
    decide what that means for the install attempt (the router surfaces
    it as a clear error, never a silent partial install).

    Catalog-checking round (2026-09-28): single-flight. Two callers
    hitting Add on the same item at nearly the same moment must not
    fetch/gate the same content twice -- a short-TTL Redis lock (SETNX,
    core/kv) keyed by item_id makes the second caller wait briefly for
    the first to finish, then simply read back whatever version the
    first created, rather than racing it. No DB-level unique constraint
    exists for "at most one version per item" (an item CAN legitimately
    gain a second version later, via update-to-a-new-version), so this
    has to be a transient coordination lock, not a schema constraint.
    """
    import time

    from core.config import RDB_CACHE
    from core.kv import get_kv

    lock_key = f"ecosystem:gate:inflight:{item_id}"
    kv = get_kv(RDB_CACHE, decode_responses=True)
    got_lock = kv.set(lock_key, requested_by, ex=30, nx=True)
    if not got_lock:
        # Someone else is already materializing this item -- wait briefly
        # for them to finish rather than doing the same fetch/gate twice.
        for _ in range(60):  # up to ~6s
            time.sleep(0.1)
            existing = get_latest_version(item_id)
            if existing is not None:
                return existing.id
        raise EcosystemError(f"item {item_id!r} is already being installed by another request -- try again shortly")
    try:
        return _materialize_from_catalog_locked(item_id, requested_by=requested_by, org_id=org_id)
    finally:
        kv.delete(lock_key)


def _materialize_from_catalog_locked(item_id: str, *, requested_by: str, org_id: str) -> str:
    from services.ecosystem.gate_service import enqueue_gate_run
    from services.ecosystem.versions_service import create_version_for_content, encode_envelope

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise EcosystemError(f"no ecosystem item {item_id!r}")
        pointer = dict(item.catalog_pointer or {})
        namespace = item.namespace
        item_type = item.item_type
    finally:
        db.close()

    if get_latest_version(item_id) is not None:
        raise EcosystemError(f"item {item_id!r} already has a version -- materialize_from_catalog() is for first-install only")

    if not pointer:
        raise EcosystemError(f"item {item_id!r} has no catalog_pointer -- not a catalog item, or already installed")

    source_kind = pointer.get("source_kind", "")
    source_url = pointer.get("source_url", "")
    source_ref = pointer.get("source_ref", "")
    source_path = pointer.get("source_path", "")
    recorded_hash = pointer.get("content_hash", "")

    if source_kind == "github_repo":
        from services.ecosystem.import_adapters.github_repo import import_from_github, import_from_github_path

        repo = source_url.rstrip("/").split("github.com/", 1)[-1]
        imported = (
            import_from_github_path(repo, source_path, ref=source_ref) if source_path
            else import_from_github(repo, ref=source_ref)
        )
    elif source_kind == "well_known":
        from services.ecosystem.import_adapters.well_known import import_from_well_known

        domain, _, skill_slug = namespace.partition("/")
        imported = import_from_well_known(domain, skill_slug)
    else:
        raise CatalogInstallNotSupportedError(
            f"catalog items from source {source_kind!r} are not yet installable (item_type={item_type!r})"
        )

    manifest_text = imported["manifest"].get("instructions", "") if isinstance(imported.get("manifest"), dict) else ""
    fresh_hash = compute_content_hash(manifest_text, imported["files"])
    if recorded_hash and fresh_hash != recorded_hash:
        raise CatalogContentDriftError(
            f"fetched content for {namespace!r} no longer matches the catalog's recorded content_hash "
            f"({recorded_hash!r} != {fresh_hash!r}) -- source changed since the last sync"
        )

    payload = encode_envelope(imported["manifest"], imported["files"])
    version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=imported["manifest"], license=imported["license"],
        attribution=f"{source_kind}:{source_url}@{source_ref}" + (f"#{source_path}" if source_path else ""),
    )
    enqueue_gate_run(
        version_id, trigger="ui_add", installed_by=requested_by, installed_for=requested_by,
        org_id=org_id, surfaces=[], priority="high",  # a real user's own "Add" click -- highest lane
    )
    return version_id
