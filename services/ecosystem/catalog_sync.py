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
from db.models import EcosystemItem, EcosystemSource
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


def _is_bundle_url(location: str) -> bool:
    return location.startswith("http://") or location.startswith("https://")


def _read_bundle_bytes(location: str) -> bytes:
    """Reads bytes from a bundle location -- a local filesystem path or
    an http(s) URL (e.g. an internal GitLab raw-file URL), auto-detected.
    Deliberately does NOT call import_adapters/ssrf_guard.py's
    assert_safe_https_url() the way the online path's _fetch_with_etag()
    does -- that guard exists to stop a CRAWLED, attacker-influenceable
    pointer's own source_url from redirecting this server at its own
    internal network. `location` here is the opposite: static, operator-
    set trusted config (ECOSYSTEM_CATALOG_BUNDLE_PATH) whose entire point
    is reaching an internal-only host on an air-gapped instance. No ETag/
    caching either -- bundle mode is meant for a small, operator-
    controlled snapshot re-synced occasionally, not a high-frequency
    poll; a real, disclosed simplification, not hidden.
    """
    if _is_bundle_url(location):
        if not location.startswith("https://"):
            raise ImportFetchError(f"bundle fetch refused: {location!r} is not https://")
        resp = relay_request("GET", location, timeout=30.0)
        if resp.status_code != 200:
            raise ImportFetchError(f"bundle fetch failed: HTTP {resp.status_code} fetching {location!r}")
        return resp.content
    from pathlib import Path

    path = Path(location)
    if not path.is_file():
        raise ImportFetchError(f"bundle file not found: {location!r}")
    return path.read_bytes()


def _bundle_join(bundle_root: str, relative: str) -> str:
    if _is_bundle_url(bundle_root):
        return f"{bundle_root.rstrip('/')}/{relative}"
    from pathlib import Path

    return str(Path(bundle_root) / relative)


def _read_content_from_bundle(bundle_root: str, pointer: dict) -> dict[str, Any]:
    """Reads one skill's own content out of a bundle exported by
    scripts/ecosystem/export_offline_bundle.py, in the exact shape
    materialize_from_catalog()'s caller already expects from
    import_from_github()/import_from_well_known() (`manifest`, `files`,
    `license`, `display_name`, `description`, `resolved_sha`,
    `source_url`) -- so every downstream step (the drift check against
    the pointer's own recorded content_hash, license enforcement, gate
    dispatch) runs completely unchanged regardless of which source this
    came from. Layout: `<bundle_root>/skills/<hex-digest>/content.json`
    ({"manifest", "files"}, the exact encode_envelope() shape) +
    `meta.json` ({"license_spdx", "display_name", "description"}).
    Raises ImportFetchError if this pointer's own content_hash has no
    matching bundle entry (e.g. it wasn't in the approved-for-export set,
    or "no MCP" excluded it) -- never a silent/partial install.
    """
    content_hash = pointer.get("content_hash", "")
    if not content_hash:
        raise ImportFetchError("bundle install refused: this item's catalog_pointer has no recorded content_hash")
    hex_digest = content_hash.split(":", 1)[-1]
    skill_dir = f"skills/{hex_digest}"

    content = json.loads(_read_bundle_bytes(_bundle_join(bundle_root, f"{skill_dir}/content.json")))
    meta = json.loads(_read_bundle_bytes(_bundle_join(bundle_root, f"{skill_dir}/meta.json")))

    return {
        "manifest": content.get("manifest", {}),
        "files": content.get("files", {}),
        "license": meta.get("license_spdx", ""),
        "display_name": meta.get("display_name", ""),
        "description": meta.get("description", ""),
        "resolved_sha": pointer.get("source_ref", ""),
        "source_url": pointer.get("source_url", ""),
    }


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


def _verify_and_upsert_shard(shard: str, data: bytes, bundle: bytes, trusted_signer: TrustedSigner) -> ShardSyncResult:
    """The half of a shard sync that's identical regardless of WHERE the
    bytes came from (online HTTP or a local/internal bundle): signature
    verification, index parsing, upsert, and stale-marking. Callers
    (_sync_one_shard()/_sync_one_shard_from_bundle()) only differ in how
    they fetch `data`/`bundle` in the first place."""
    result = ShardSyncResult(shard=shard, fetched=True)
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


def _sync_one_shard(base_url: str, shard: str, trusted_signer: TrustedSigner) -> ShardSyncResult:
    shard_url = f"{base_url.rstrip('/')}/{shard}.json"
    bundle_url = f"{shard_url}.sigstore"

    try:
        data, fetched = _fetch_with_etag(shard_url)
    except ImportFetchError as exc:
        return ShardSyncResult(shard=shard, error=f"fetch failed: {exc}")
    if not fetched:
        return ShardSyncResult(shard=shard, fetched=False)  # 304 -- unchanged, nothing to verify or upsert

    try:
        bundle, _ = _fetch_with_etag(bundle_url)
        if bundle is None:
            # A 304 on the bundle URL alone (no cached etag for THIS run)
            # can't happen in practice since we never send If-None-Match
            # for a URL we haven't fetched before -- but fail closed
            # rather than assume.
            raise ImportFetchError(f"no signature bundle body returned for {bundle_url!r}")
    except ImportFetchError as exc:
        return ShardSyncResult(shard=shard, fetched=True, error=f"signature bundle fetch failed -- rejecting unsigned index: {exc}")

    return _verify_and_upsert_shard(shard, data, bundle, trusted_signer)


def _sync_one_shard_from_bundle(bundle_root: str, shard: str, trusted_signer: TrustedSigner) -> ShardSyncResult:
    """Bundle-mode equivalent of _sync_one_shard() -- reads
    `<bundle_root>/index/<shard>.json`(.sigstore) via _read_bundle_bytes()
    (local file or internal https:// URL) instead of an online HTTP GET
    with ETag caching. A shard simply absent from the bundle (e.g. an
    operator only exported "skill", never "mcp_server") is reported as
    not-fetched, same as a 304 would be online -- not an error, since a
    bundle covering a subset of shards is entirely expected (this
    feature's own spec explicitly excludes MCP from the export)."""
    index_location = _bundle_join(bundle_root, f"index/{shard}.json")
    sigstore_location = f"{index_location}.sigstore"

    try:
        data = _read_bundle_bytes(index_location)
    except ImportFetchError:
        return ShardSyncResult(shard=shard, fetched=False)
    try:
        bundle = _read_bundle_bytes(sigstore_location)
    except ImportFetchError as exc:
        return ShardSyncResult(shard=shard, fetched=True, error=f"signature bundle read failed -- rejecting unsigned index: {exc}")

    return _verify_and_upsert_shard(shard, data, bundle, trusted_signer)


def sync_catalog(base_url: str, trusted_signer: TrustedSigner) -> SyncReport:
    """Syncs every known shard (skill, mcp_server) from base_url (the
    catalog's index/ directory -- NOT a specific shard file). Each
    shard is independent: a signature failure on one never blocks the
    other from syncing."""
    report = SyncReport()
    for shard in _SHARD_ITEM_TYPES:
        report.shards.append(_sync_one_shard(base_url, shard, trusted_signer))
    _persist_last_sync_status(report)
    return report


def sync_catalog_from_bundle(bundle_root: str, trusted_signer: TrustedSigner) -> SyncReport:
    """Offline catalog bundle mode (porting-pack round): the bundle-mode
    equivalent of sync_catalog(), reading every shard from
    `<bundle_root>/index/` (a local filesystem path or an internal
    https:// URL) instead of the public internet. Same signature
    verification, same upsert/stale-marking, same persisted "last sync"
    status the admin Sources screen already reads -- only the fetch
    mechanics differ, entirely inside _sync_one_shard_from_bundle()."""
    report = SyncReport()
    for shard in _SHARD_ITEM_TYPES:
        report.shards.append(_sync_one_shard_from_bundle(bundle_root, shard, trusted_signer))
    _persist_last_sync_status(report)
    return report


# ── Admin Sources screen support (Task 3a) ───────────────────────────────
# Real observability gap found while building the admin Sources screen:
# sync_catalog() never persisted its own last-run report anywhere durable
# -- an admin's "Sync now" click got a one-shot response, but nothing
# survived to be shown on a page load or by the SCHEDULED sync (run_
# scheduled_sync(), which nobody is watching the logs of in real time).
# Deliberately NOT a new table -- this is observability, not a new
# subsystem (per the task's own instruction) -- a single Redis key holding
# the most recent report (from EITHER caller, whichever ran last) is
# enough for "what happened last time" and costs nothing to add. Same
# fire-and-forget convention as events_service.publish_ecosystem_changed():
# a Redis hiccup here must never fail or roll back the sync itself, which
# has already committed to Postgres by the time this runs.
_LAST_SYNC_STATUS_KV = "ecosystem:catalog_sync:last_status"


def _persist_last_sync_status(report: SyncReport) -> None:
    from datetime import datetime, timezone

    from core.config import RDB_CACHE
    from core.kv import get_kv

    try:
        payload = {**report.to_dict(), "synced_at": datetime.now(timezone.utc).isoformat()}
        get_kv(RDB_CACHE, decode_responses=True).set(_LAST_SYNC_STATUS_KV, json.dumps(payload))
    except Exception:
        pass


def get_last_sync_status() -> dict[str, Any] | None:
    """Admin Sources screen's read of the most recent sync_catalog() run --
    whichever of the scheduled cron job (run_scheduled_sync()) or an
    admin's own "Sync now" (POST /ecosystem/admin/catalog-sync) ran last.
    None when no sync has ever run on this instance, or Redis is
    unreachable -- never confused with a real, empty-but-successful run
    (which has "shards": [...] with real, zeroed counts, not None)."""
    from core.config import RDB_CACHE
    from core.kv import get_kv

    try:
        raw = get_kv(RDB_CACHE, decode_responses=True).get(_LAST_SYNC_STATUS_KV)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def list_org_sources(org_id: str) -> list[dict[str, Any]]:
    """Admin Sources screen's "Org sources" list (external-sources-catalog
    plan §8): EcosystemSource rows this org actually has a stake in --
    its own kind="local" row (get_or_create_local_source()'s per-org
    created-items source, db/migrate.py's ux_ecosystem_sources_one_local_
    per_org constraint guarantees at most one) plus any instance-level
    import source (github_repo/well_known, org_id=None per get_or_create_
    import_source()'s own docstring) that at least one of this org's own
    EcosystemItem rows was actually imported through. Read-only display --
    never exposes credential_ciphertext, only whether one is configured."""
    db = SessionLocal()
    try:
        used_source_ids = db.query(EcosystemItem.source_id).filter(EcosystemItem.org_id == org_id)
        rows = (
            db.query(EcosystemSource)
            .filter((EcosystemSource.org_id == org_id) | (EcosystemSource.id.in_(used_source_ids)))
            .order_by(EcosystemSource.created_at.desc())
            .all()
        )
        return [
            {
                "id": r.id, "kind": r.kind, "url": r.url, "enabled": r.enabled,
                "tos_checked_at": r.tos_checked_at.isoformat() if r.tos_checked_at else None,
                "tos_notes": r.tos_notes, "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "credential_configured": bool(r.secret_backend or r.credential_ciphertext or r.credential_external_ref),
            }
            for r in rows
        ]
    finally:
        db.close()


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


class CatalogSyncNotConfiguredError(EcosystemError):
    """Raised by run_configured_sync() when the active source mode's own
    required config isn't set -- callers (the router's "Sync now"
    endpoint, run_scheduled_sync()) decide what that means for them."""


def run_configured_sync() -> SyncReport:
    """The one place that reads ECOSYSTEM_CATALOG_SOURCE_MODE and decides
    which sync function to call -- both the scheduler (run_scheduled_sync
    below) and the router's admin "Sync now" endpoint call THIS, so
    neither has its own copy of the mode-branching logic to drift out of
    sync with the other. Switching between "online" and "bundle" is
    entirely a config change (ECOSYSTEM_CATALOG_SOURCE_MODE +
    ECOSYSTEM_CATALOG_URL/ECOSYSTEM_CATALOG_BUNDLE_PATH) -- no caller of
    this function needs to know or care which mode is active. Raises
    CatalogSyncNotConfiguredError/ValueError on bad config -- never
    silently no-ops; run_scheduled_sync() below is what turns that into a
    logged, swallowed no-op for the unattended scheduler path.
    """
    from core.config import (
        ECOSYSTEM_CATALOG_BUNDLE_PATH, ECOSYSTEM_CATALOG_SOURCE_MODE,
        ECOSYSTEM_CATALOG_TRUSTED_SIGNER, ECOSYSTEM_CATALOG_URL,
    )
    from services.ecosystem.catalog_crawler.signing import trusted_signer_from_env

    if not ECOSYSTEM_CATALOG_TRUSTED_SIGNER:
        raise CatalogSyncNotConfiguredError("ECOSYSTEM_CATALOG_TRUSTED_SIGNER is not set")
    trusted_signer = trusted_signer_from_env(ECOSYSTEM_CATALOG_TRUSTED_SIGNER)  # raises ValueError on malformed JSON

    if ECOSYSTEM_CATALOG_SOURCE_MODE == "bundle":
        if not ECOSYSTEM_CATALOG_BUNDLE_PATH:
            raise CatalogSyncNotConfiguredError("ECOSYSTEM_CATALOG_SOURCE_MODE=bundle but ECOSYSTEM_CATALOG_BUNDLE_PATH is not set")
        return sync_catalog_from_bundle(ECOSYSTEM_CATALOG_BUNDLE_PATH, trusted_signer)
    if ECOSYSTEM_CATALOG_SOURCE_MODE != "online":
        raise CatalogSyncNotConfiguredError(f"unknown ECOSYSTEM_CATALOG_SOURCE_MODE {ECOSYSTEM_CATALOG_SOURCE_MODE!r} -- expected 'online' or 'bundle'")
    if not ECOSYSTEM_CATALOG_URL:
        raise CatalogSyncNotConfiguredError("ECOSYSTEM_CATALOG_SOURCE_MODE=online (the default) but ECOSYSTEM_CATALOG_URL is not set")
    return sync_catalog(ECOSYSTEM_CATALOG_URL, trusted_signer)


def run_scheduled_sync() -> None:
    """Zero-arg entry point for workers/start_workers.py's cron
    scheduler thread (interval_jobs). Re-checks ECOSYSTEM_CATALOG_SYNC
    itself (defense in depth -- the scheduler only registers this job
    when the flag is on at startup, but a config re-read shouldn't rely
    on that alone), then delegates the actual online-vs-bundle decision
    to run_configured_sync() and logs a summary. Never raises -- the
    scheduler's own dispatch loop already catches exceptions per-tick,
    but a partial/aborted/not-configured sync should look like a clean,
    well-logged no-op, not an unhandled crash."""
    from core.config import ECOSYSTEM_CATALOG_SYNC
    from core.logger import logger

    if not ECOSYSTEM_CATALOG_SYNC:
        return

    try:
        report = run_configured_sync()
    except (CatalogSyncNotConfiguredError, ValueError) as exc:
        logger.warning(f"ecosystem catalog_sync: not configured -- {exc}")
        return

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


class _PrecheckSkippedError(EcosystemError):
    """Raised only for caller_priority="low" (the pre-check dispatcher)
    when the item's single-flight lock is already held by anyone else --
    the pre-check backs off immediately rather than contending, so it can
    never be the reason a real user's own Add waits on anything (see
    materialize_from_catalog()'s own docstring, "priority-aware single-
    flight"). Caught by run_precheck_batch(), never expected to reach an
    HTTP caller."""


def materialize_from_catalog(item_id: str, *, requested_by: str, org_id: str, caller_priority: str = "high") -> str:
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

    caller_priority ("high" default | "low"): priority QUEUE lanes
    (core/job_queue.py's Q_ECOSYSTEM_GATE_HIGH/_LOW) only govern which
    QUEUED job an idle worker picks up next -- RQ does not preempt a
    job that's already running, so lane ordering alone cannot guarantee
    "a real user's Add never waits behind a pre-check job" for the
    narrower case of THIS function's own single-flight lock (a
    pre-check's fetch could already be inside this critical section when
    a real user clicks Add on the exact same item). Two separate,
    provable guarantees close that gap instead of assuming lane order is
    enough:
      - caller_priority="low" (only run_precheck_batch() below passes
        this): if the lock is already held by ANYONE, back off
        immediately (raises _PrecheckSkippedError, zero wait) -- a
        pre-check can never be the one making someone else wait.
      - caller_priority="high" (every real HTTP Add): if the lock is
        already held, waits for at most ~0.5s (bounded, not the
        previous ~6s) before giving up and raising -- a real user is
        never blocked long regardless of who's holding the lock or why.
    """
    import time

    from core.config import RDB_CACHE
    from core.kv import get_kv

    lock_key = f"ecosystem:gate:inflight:{item_id}"
    kv = get_kv(RDB_CACHE, decode_responses=True)
    got_lock = kv.set(lock_key, requested_by, ex=30, nx=True)
    if not got_lock:
        if caller_priority == "low":
            raise _PrecheckSkippedError(f"item {item_id!r} already in flight -- pre-check backing off, never contending")
        # A real user's Add: wait briefly for whoever holds the lock (another
        # real Add, or a pre-check that got there first) to finish, but with a
        # hard, short bound -- never the ~6s this used to allow.
        for _ in range(5):  # up to ~0.5s
            time.sleep(0.1)
            existing = get_latest_version(item_id)
            if existing is not None:
                return existing.id
        raise EcosystemError(f"item {item_id!r} is already being installed by another request -- try again shortly")
    try:
        return _materialize_from_catalog_locked(item_id, requested_by=requested_by, org_id=org_id, caller_priority=caller_priority)
    finally:
        kv.delete(lock_key)


def _materialize_from_catalog_locked(item_id: str, *, requested_by: str, org_id: str, caller_priority: str = "high") -> str:
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

    # Offline catalog bundle mode (porting-pack round): when active, Add
    # reads the skill's own content from the local bundle (hash-verified
    # by the SAME drift check just below every other source already goes
    # through) instead of ever reaching out to GitHub/a well-known site --
    # required for an air-gapped/firewalled instance with no internet
    # access at all. source_kind/source_url/source_path are still the
    # ORIGINAL provenance recorded by the crawler (preserved for
    # attribution) -- only WHERE the bytes are actually read from changes.
    from core.config import ECOSYSTEM_CATALOG_BUNDLE_PATH, ECOSYSTEM_CATALOG_SOURCE_MODE

    if ECOSYSTEM_CATALOG_SOURCE_MODE == "bundle":
        if not ECOSYSTEM_CATALOG_BUNDLE_PATH:
            raise CatalogInstallNotSupportedError(
                "ECOSYSTEM_CATALOG_SOURCE_MODE=bundle but ECOSYSTEM_CATALOG_BUNDLE_PATH is not set"
            )
        imported = _read_content_from_bundle(ECOSYSTEM_CATALOG_BUNDLE_PATH, pointer)
    elif source_kind == "github_repo":
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

    # Real gap found 2026-09-29: up to this point, `imported["license"]`
    # was used unconditionally -- the import adapter's own FRESH,
    # from-scratch license re-derivation (a real GitHub SPDX API call +
    # SKILL.md frontmatter re-parse), even though the drift check just
    # above already proved this exact content byte-for-byte matches what
    # the crawler already verified and recorded as `license_spdx` in the
    # signed index. For a signed catalog item, trust that signed evidence
    # instead of re-deriving it -- `is_allowed_license()` (license_stage,
    # always) and check_tier2_license() (an org's own stricter allowlist,
    # already called for scope-widening installs) still run against it;
    # only the redundant RE-EVALUATION is skipped. Falls back to the
    # freshly-derived value only if the pointer somehow has none recorded
    # (should not happen for a real crawled entry, but never silently use
    # an empty license string).
    version_license = pointer.get("license_spdx") or imported["license"]

    payload = encode_envelope(imported["manifest"], imported["files"])
    version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=imported["manifest"], license=version_license,
        attribution=f"{source_kind}:{source_url}@{source_ref}" + (f"#{source_path}" if source_path else ""),
    )

    from services.ecosystem.gate_service import _has_scripts_or_dependencies, run_gate_synchronously

    # Section 3's headline deliverable: "instructions-only catalog skills
    # should go Add -> Active in about a second." An item with no
    # scripts/dependencies has nothing for supply_chain/sandbox to check
    # (already skipped, see gate_service.run_gate()'s proportionate-
    # gating logic) and, being a signed catalog item, also skips the
    # redundant static_safety re-scan -- for the default ethics policy
    # ("scripts_or_noncatalog"), that leaves only manifest+license+
    # mcp_connector, all fast local checks. Attempt the whole thing
    # synchronously with a real 3s budget; only fall back to the async
    # queue if that budget is actually exceeded (run_gate_synchronously()'s
    # own docstring covers exactly how that fallback avoids a double-run).
    # caller_priority="low" (run_precheck_batch() only): never take the
    # synchronous fast path even for an instructions-only item -- a
    # pre-check has no live HTTP request waiting on it, so there's no
    # "about a second" deadline to hit, and running synchronously would
    # just tie up the background dispatcher's own thread for no benefit.
    # Always async, always the low-priority lane.
    if caller_priority == "low":
        enqueue_gate_run(
            version_id, trigger="ui_add", installed_by=requested_by, installed_for=requested_by,
            org_id=org_id, surfaces=[], priority="low",
        )
    elif not _has_scripts_or_dependencies(imported["manifest"], imported["files"]):
        run_gate_synchronously(
            version_id, trigger="ui_add", timeout_seconds=3.0,
            installed_by=requested_by, installed_for=requested_by, org_id=org_id, surfaces=[],
            fallback_priority="high",
        )
    else:
        enqueue_gate_run(
            version_id, trigger="ui_add", installed_by=requested_by, installed_for=requested_by,
            org_id=org_id, surfaces=[], priority="high",  # a real user's own "Add" click -- highest lane
        )
    return version_id


def run_precheck_batch() -> dict[str, Any]:
    """Catalog-checking round (2026-09-28), section 4: optional background
    pre-check of featured/popular catalog items, admin-enabled per org
    (EcosystemOrgPolicy.gate_precheck_enabled, off by default) and capped
    at gate_precheck_cap_per_hour per org -- so the FIRST real user to
    click Add on a popular item gets an already-resolved gate instead of
    waiting on it. Called from workers/start_workers.py's cron-thread
    interval_jobs, same pattern as ecosystem_catalog_sync's own
    run_scheduled_sync().

    Never blocks a real user's Add: every materialize_from_catalog() call
    here passes caller_priority="low", which (1) backs off immediately
    rather than waiting if the item's single-flight lock is already held
    by anyone (a real Add always wins any contention, never the reverse)
    and (2) always enqueues to the LOW-priority gate queue lane, never
    the synchronous fast path -- see materialize_from_catalog()'s and
    _materialize_from_catalog_locked()'s own docstrings for exactly how
    each guarantee holds.

    Returns {"orgs_checked": int, "items_attempted": int, "items_skipped_in_flight": int,
    "items_failed": int, "org_results": {org_id: {"attempted": int, "capped_at": int}}}."""
    from datetime import datetime, timezone

    from core.config import RDB_CACHE
    from core.kv import get_kv
    from db.models import EcosystemOrgPolicy

    result: dict[str, Any] = {
        "orgs_checked": 0, "items_attempted": 0, "items_skipped_in_flight": 0, "items_failed": 0,
        "org_results": {},
    }

    db = SessionLocal()
    try:
        enabled_org_ids = [
            row.org_id for row in db.query(EcosystemOrgPolicy).filter(EcosystemOrgPolicy.gate_precheck_enabled.is_(True)).all()
        ]
        caps_by_org = {
            row.org_id: row.gate_precheck_cap_per_hour
            for row in db.query(EcosystemOrgPolicy).filter(EcosystemOrgPolicy.org_id.in_(enabled_org_ids)).all()
        }
    finally:
        db.close()

    result["orgs_checked"] = len(enabled_org_ids)
    if not enabled_org_ids:
        return result

    kv = get_kv(RDB_CACHE, decode_responses=True)
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")

    for org_id in enabled_org_ids:
        cap = caps_by_org.get(org_id, 20)
        counter_key = f"ecosystem:gate:precheck:count:{org_id}:{hour_bucket}"
        already_this_hour = int(kv.get(counter_key) or 0)
        remaining = max(0, cap - already_this_hour)
        result["org_results"][org_id] = {"attempted": 0, "capped_at": cap}
        if remaining <= 0:
            continue

        db = SessionLocal()
        try:
            candidates = (
                db.query(EcosystemItem)
                .filter(
                    EcosystemItem.scope == "central_index", EcosystemItem.status == "active",
                    EcosystemItem.is_featured.is_(True),
                )
                .order_by(EcosystemItem.created_at.desc())
                .limit(remaining * 3)  # over-fetch -- some will already have a version, filtered below
                .all()
            )
            candidate_ids = [c.id for c in candidates]
        finally:
            db.close()

        for item_id in candidate_ids:
            if remaining <= 0:
                break
            if get_latest_version(item_id) is not None:
                continue  # already materialized -- nothing to pre-check
            try:
                materialize_from_catalog(item_id, requested_by="system:precheck", org_id=org_id, caller_priority="low")
                kv.set(counter_key, str(already_this_hour + result["org_results"][org_id]["attempted"] + 1), ex=3600)
                result["org_results"][org_id]["attempted"] += 1
                result["items_attempted"] += 1
                remaining -= 1
            except _PrecheckSkippedError:
                result["items_skipped_in_flight"] += 1
            except Exception:
                result["items_failed"] += 1

    return result


def run_scheduled_precheck() -> None:
    """Zero-arg entry point for workers/start_workers.py's cron-thread
    interval_jobs (gated ECOSYSTEM_CATALOG_PRECHECK -- the module-level
    "is this feature on at all" switch; per-org gate_precheck_enabled
    above is the finer-grained "which orgs" switch). Re-checks its own
    flag at fire time too, defense in depth, same pattern as
    catalog_sync.run_scheduled_sync()."""
    from core.config import ECOSYSTEM_CATALOG_PRECHECK
    from core.logger import logger

    if not ECOSYSTEM_CATALOG_PRECHECK:
        return
    result = run_precheck_batch()
    if result["items_attempted"] or result["items_failed"]:
        logger.info(f"catalog_sync: precheck batch -- {result}")
