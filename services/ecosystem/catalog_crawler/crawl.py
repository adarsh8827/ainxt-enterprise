# SPDX-License-Identifier: MIT
# ============================================================
# Crawl orchestrator (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §1, §3, §4).
# Reuses the SAME adapters and license-inheritance logic the manual
# admin-import path already uses (services/ecosystem/import_adapters/
# github_repo.py, well_known.py, mcp_registry.py) -- nothing here
# re-derives a license verdict independently; every "allowed" here is an
# allowed the existing adapters already computed. Fast safety checks
# (services/ecosystem/gate/static_safety_stage.py's run_fast_path) and
# the item-level neutrality check (neutrality_check.py) are crawl-time
# pre-filters only -- the full 7-stage gate still runs, unconditionally,
# at install time (§4).
# ============================================================

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from services.ecosystem.catalog_crawler.crawl_report import (
    CircuitBreakerTrip,
    CrawlReport,
    ExcludedEntry,
    IncludedEntry,
    OverCapEntry,
)
from services.ecosystem.catalog_crawler.neutrality_check import scan_for_ai_vendor_names
from services.ecosystem.catalog_crawler.pointer_schema import PointerEntry, build_index_shards
from services.ecosystem.catalog_crawler.sources_config import CrawlLimits, SourcesConfig, load_sources, load_yanked
from services.ecosystem.compatibility import classify_compatibility
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError
from services.ecosystem.gate.static_safety_stage import run_fast_path
from services.ecosystem.import_adapters import github_repo, mcp_registry, well_known

_SOURCE_KIND_PREFERENCE = {"github_repo": 0, "well_known": 1, "mcp_registry": 2}
_CIRCUIT_BREAKER_THRESHOLD = 0.2


def _content_hash(manifest_text: str, files: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(manifest_text.encode("utf-8"))
    for rel_path in sorted(files):
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(files[rel_path].encode("utf-8"))
    return f"sha256:{hasher.hexdigest()}"


def _scan_all_content_for_vendor_names(manifest_text: str, files: dict[str, str]) -> list[str]:
    hits = list(scan_for_ai_vendor_names(manifest_text))
    for text in files.values():
        for name in scan_for_ai_vendor_names(text):
            if name not in hits:
                hits.append(name)
    return hits


def _apply_per_source_cap(scope: str, entries: list[PointerEntry], cap: int, report: CrawlReport) -> list[PointerEntry]:
    """Enforces sources.yaml's crawl_limits.max_skills_per_repo. Exceeding
    it is REPORTED (CrawlReport.over_cap), never a silent truncation."""
    if len(entries) <= cap:
        return entries
    kept = sorted(entries, key=lambda e: e.namespace)[:cap]
    report.over_cap.append(OverCapEntry(scope=scope, cap=cap, available=len(entries), included=len(kept)))
    return kept


def _path_is_excluded(path: str, exclude_paths: list[str]) -> bool:
    for ex in exclude_paths:
        ex = ex.rstrip("/")
        if path == ex or path.startswith(ex + "/"):
            return True
    return False


def _crawl_github_repo(source, report: CrawlReport, crawl_limits: CrawlLimits) -> list[PointerEntry]:
    all_candidates: list[dict[str, Any]] = []
    for scan_path in (source.include_paths or [None]):
        try:
            all_candidates.extend(github_repo.discover_skills_in_repo(source.repo, path=scan_path))
        except (ImportFetchError, ImportRateLimitedError) as exc:
            identifier = f"{source.repo}#{scan_path or '(root)'}"
            report.excluded.append(ExcludedEntry(source_kind="github_repo", identifier=identifier, reason=f"discovery failed: {exc}"))

    owner_slug = source.repo.split("/", 1)[0].lower()
    passing_entries: list[PointerEntry] = []
    for cand in all_candidates:
        identifier = f"{source.repo}#{cand['path'] or '(root)'}"

        if cand["path"] and _path_is_excluded(cand["path"], source.exclude_paths):
            report.excluded.append(ExcludedEntry(
                source_kind="github_repo", identifier=identifier,
                reason="excluded via sources.yaml exclude_paths (copyright/originality risk -- the gate doesn't check copyright)",
            ))
            continue
        if not cand["allowed"]:
            report.excluded.append(ExcludedEntry(source_kind="github_repo", identifier=identifier, reason=cand["reason"]))
            continue

        try:
            imported = github_repo.import_from_github_path(source.repo, cand["path"], ref=cand["resolved_sha"]) \
                if cand["path"] else github_repo.import_from_github(source.repo, ref=cand["resolved_sha"])
        except (ImportFetchError, ImportRateLimitedError) as exc:
            report.excluded.append(ExcludedEntry(source_kind="github_repo", identifier=identifier, reason=f"import failed: {exc}"))
            continue

        manifest_text = imported["manifest"].get("instructions", "")
        fast_result = run_fast_path(imported["files"], manifest_text=manifest_text)
        if fast_result.verdict == "fail":
            reasons = "; ".join(f.code for f in fast_result.findings)
            report.excluded.append(ExcludedEntry(source_kind="github_repo", identifier=identifier, reason=f"fast safety check failed: {reasons}"))
            continue

        vendor_hits = _scan_all_content_for_vendor_names(manifest_text, imported["files"])
        if vendor_hits:
            report.excluded.append(ExcludedEntry(
                source_kind="github_repo", identifier=identifier,
                reason=f"names AI vendor/product(s) {', '.join(vendor_hits)} -- violates this catalog's neutrality requirement",
            ))
            continue

        skill_name = (cand["path"].rsplit("/", 1)[-1] if cand["path"] else source.repo.split("/", 1)[1]).lower().replace("_", "-")
        namespace = f"{owner_slug}/{skill_name}"
        tags = list(source.tags)
        if source.needs_product:
            tags.append(f"needs-{source.needs_product.lower().replace(' ', '-')}")
        if source.account_required:
            tags.append("account-required")

        entry = PointerEntry(
            namespace=namespace,
            item_type="skill",
            display_name=imported["display_name"],
            description=imported["description"],
            category=source.category,
            tags=tags,
            source_kind="github_repo",
            source_url=f"https://github.com/{source.repo}",
            source_ref=imported["resolved_sha"],
            source_path=cand["path"],
            license_spdx=imported["license"],
            license_evidence=cand["license_evidence"]["effective_license_source"],
            compatibility=classify_compatibility(manifest_text),
            content_hash=_content_hash(manifest_text, imported["files"]),
        )
        passing_entries.append(entry)

    return _apply_per_source_cap(f"repo:{source.repo}", passing_entries, crawl_limits.max_skills_per_repo, report)


def _crawl_well_known(source, report: CrawlReport, crawl_limits: CrawlLimits) -> list[PointerEntry]:
    try:
        candidates = well_known.discover_skills_at_well_known(source.domain)
    except ImportFetchError as exc:
        report.excluded.append(ExcludedEntry(source_kind="well_known", identifier=source.domain, reason=f"discovery failed: {exc}"))
        return []

    domain_slug = source.domain.split(".")[0].lower()
    passing_entries: list[PointerEntry] = []
    for cand in candidates:
        identifier = f"{source.domain}/{cand['slug']}"
        if not cand["allowed"]:
            report.excluded.append(ExcludedEntry(source_kind="well_known", identifier=identifier, reason=cand["reason"]))
            continue

        manifest_text = cand["skill_md_text"] or ""
        files = cand["files"] or {}
        fast_result = run_fast_path(files, manifest_text=manifest_text)
        if fast_result.verdict == "fail":
            reasons = "; ".join(f.code for f in fast_result.findings)
            report.excluded.append(ExcludedEntry(source_kind="well_known", identifier=identifier, reason=f"fast safety check failed: {reasons}"))
            continue

        vendor_hits = _scan_all_content_for_vendor_names(manifest_text, files)
        if vendor_hits:
            report.excluded.append(ExcludedEntry(
                source_kind="well_known", identifier=identifier,
                reason=f"names AI vendor/product(s) {', '.join(vendor_hits)} -- violates this catalog's neutrality requirement",
            ))
            continue

        namespace = f"{domain_slug}/{cand['slug'].lower().replace('_', '-')}"
        tags = list(source.tags)
        if source.needs_product:
            tags.append(f"needs-{source.needs_product.lower().replace(' ', '-')}")
        if source.account_required:
            tags.append("account-required")

        entry = PointerEntry(
            namespace=namespace,
            item_type="skill",
            display_name=cand["display_name"],
            description=cand["description"],
            category=source.category,
            tags=tags,
            source_kind="well_known",
            source_url=cand["source_url"],
            source_ref=cand["resolved_sha"] or "",
            license_spdx=cand["license_evidence"]["skill_md_license_field"] or "",
            license_evidence="SKILL.md license field (well-known site)",
            compatibility=classify_compatibility(manifest_text),
            content_hash=_content_hash(manifest_text, files),
            extra={"test_source": source.test_source},
        )
        passing_entries.append(entry)

    return _apply_per_source_cap(f"site:{source.domain}", passing_entries, crawl_limits.max_skills_per_repo, report)


def _crawl_mcp_registry(source, report: CrawlReport) -> list[PointerEntry]:
    entries: list[PointerEntry] = []
    try:
        candidates = mcp_registry.discover_mcp_servers(max_pages=source.max_pages)
    except ImportFetchError as exc:
        report.excluded.append(ExcludedEntry(source_kind="mcp_registry", identifier="(registry)", reason=f"discovery failed: {exc}"))
        return entries

    for cand in candidates:
        if not cand["allowed"]:
            report.excluded.append(ExcludedEntry(source_kind="mcp_registry", identifier=cand["name"], reason=cand["reason"]))
            continue

        publisher, _, name = cand["name"].rpartition("/")
        if not publisher:
            publisher, name = "mcp", cand["name"]
        namespace = f"{publisher.lower().replace('_', '-')}/{name.lower().replace('_', '-')}"
        evidence = cand["license_evidence"]
        entry = PointerEntry(
            namespace=namespace,
            item_type="mcp_server",
            display_name=cand["display_name"],
            description=cand["description"],
            category="mcp",
            tags=["mcp"],
            source_kind="mcp_registry",
            source_url=cand.get("repository_url") or "",
            source_ref=cand["name"],
            license_spdx=evidence.get("effective_license", "") or "",
            license_evidence=evidence.get("source", ""),
            compatibility="tool_dependent",
            content_hash="",  # no fetchable content -- a pointer to a package, not bytes to hash
            remote_only=cand.get("remote_only", False),
            extra={"safety_check": "not_applicable_no_fetchable_content"},
        )
        entries.append(entry)
    return entries


def _dedupe_by_content_hash(entries: list[PointerEntry], report: CrawlReport) -> list[PointerEntry]:
    """Cross-source dedup: the same skill can legitimately be crawled
    from more than one source.yaml entry (e.g. a repo AND a well-known
    site mirroring it) -- keep exactly one copy, preferring github_repo
    (pinned commit SHA) over well_known over mcp_registry. Entries with
    no content_hash (mcp_server pointers -- no fetchable content) are
    never deduped against each other."""
    by_hash: dict[str, list[PointerEntry]] = {}
    kept: list[PointerEntry] = []
    for e in entries:
        if not e.content_hash:
            kept.append(e)
            continue
        by_hash.setdefault(e.content_hash, []).append(e)

    for group in by_hash.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        ordered = sorted(group, key=lambda e: _SOURCE_KIND_PREFERENCE.get(e.source_kind, 99))
        winner = ordered[0]
        kept.append(winner)
        for loser in ordered[1:]:
            report.excluded.append(ExcludedEntry(
                source_kind=loser.source_kind, identifier=loser.namespace,
                reason=f"duplicate content of {winner.namespace!r} ({winner.source_kind}) -- preferring that source",
            ))
    return kept


def _load_previous_hashes_by_source(previous_index_dir: str | Path | None) -> dict[str, dict[str, str]]:
    """{source_url: {namespace: content_hash}} read from a previously-
    built index (the ecosystem-index branch's own last committed
    index/*.json, if one exists) -- empty if none (e.g. the first crawl
    ever has nothing to compare against, and the circuit breaker below
    is then a documented no-op)."""
    result: dict[str, dict[str, str]] = {}
    if not previous_index_dir:
        return result
    index_dir = Path(previous_index_dir)
    if not index_dir.exists():
        return result
    for shard_file in sorted(index_dir.glob("*.json")):
        try:
            rows = json.loads(shard_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows:
            source_url = (row.get("source") or {}).get("url", "")
            if not source_url:
                continue
            result.setdefault(source_url, {})[row["namespace"]] = row.get("content_hash", "")
    return result


def _check_circuit_breaker(
    source_kind: str, source_url: str, entries: list[PointerEntry],
    previous_hashes: dict[str, str], report: CrawlReport,
) -> bool:
    """Anomaly circuit breaker (ported from the reviewed teammate
    marketplace's own ingestion safeguard): if more than
    _CIRCUIT_BREAKER_THRESHOLD of a source's previously-seen items
    changed content since the last crawl, this run's results for that
    source are discarded entirely -- a source suddenly replacing most of
    its content is treated as a possible compromise/hijack, not trusted
    blindly. Returns True (discard) or False (nothing to compare against
    yet, or the change rate is within the normal range)."""
    if not previous_hashes:
        return False
    current_hashes = {e.namespace: e.content_hash for e in entries}
    total = 0
    changed = 0
    for namespace, old_hash in previous_hashes.items():
        if namespace in current_hashes:
            total += 1
            if current_hashes[namespace] != old_hash:
                changed += 1
    if total == 0:
        return False
    if (changed / total) > _CIRCUIT_BREAKER_THRESHOLD:
        report.circuit_breaker_trips.append(CircuitBreakerTrip(
            source_kind=source_kind, source_identifier=source_url,
            changed=changed, total_compared=total, threshold=_CIRCUIT_BREAKER_THRESHOLD,
        ))
        return True
    return False


def run_crawl(
    sources_path: str | Path, yanked_path: str | Path, output_dir: str | Path,
    *, previous_index_dir: str | Path | None = None,
) -> CrawlReport:
    """Runs every enabled source in sources.yaml, writes one pointer YAML
    per included entry under `output_dir/catalog/...`, and builds
    `output_dir/index/<item_type>.json`. Does NOT sign anything (§2's
    sign_index_bytes() is a separate step the caller invokes on the
    written index files) and does NOT commit/push (the calling workflow
    script owns that, against the `ecosystem-index` branch checkout).

    `previous_index_dir`, if given, points at the previously-built
    index/ directory (e.g. a checkout of ecosystem-index's own last
    commit) -- enables the anomaly circuit breaker per source. Omit it
    (the default) for a first crawl, where there is nothing to compare
    against yet.

    Returns the crawl report (stop point 2's artifact).
    """
    config: SourcesConfig = load_sources(sources_path)
    yanked = load_yanked(yanked_path)
    report = CrawlReport()
    previous_hashes_by_source = _load_previous_hashes_by_source(previous_index_dir)
    all_entries: list[PointerEntry] = []

    for repo_source in config.github_repos:
        if not repo_source.enabled:
            continue
        entries = _crawl_github_repo(repo_source, report, config.crawl_limits)
        source_url = f"https://github.com/{repo_source.repo}"
        if _check_circuit_breaker("github_repo", source_url, entries, previous_hashes_by_source.get(source_url, {}), report):
            continue
        all_entries.extend(entries)

    for site_source in config.well_known_sites:
        if not site_source.enabled:
            continue
        entries = _crawl_well_known(site_source, report, config.crawl_limits)
        source_url = f"https://{site_source.domain}"
        if _check_circuit_breaker("well_known", source_url, entries, previous_hashes_by_source.get(source_url, {}), report):
            continue
        all_entries.extend(entries)

    if config.mcp_registry and config.mcp_registry.enabled:
        all_entries.extend(_crawl_mcp_registry(config.mcp_registry, report))

    # yanked.yaml removes single items even if their source would still
    # produce them -- filtered out before dedup/caps, so a yanked item
    # never occupies a dedup "winner" slot or counts against a cap.
    all_entries = [e for e in all_entries if e.namespace not in yanked]

    all_entries = _dedupe_by_content_hash(all_entries, report)

    if len(all_entries) > config.crawl_limits.max_total_items:
        available = len(all_entries)
        all_entries = sorted(all_entries, key=lambda e: e.namespace)[: config.crawl_limits.max_total_items]
        report.over_cap.append(OverCapEntry(
            scope="total", cap=config.crawl_limits.max_total_items, available=available, included=len(all_entries),
        ))

    # report.included is built from whatever actually survives yanking/
    # dedup/caps -- never appended to speculatively during each source's
    # own crawl, since a later step can still remove an entry a source
    # itself thought was "included".
    report.included = [
        IncludedEntry(
            namespace=e.namespace, source_kind=e.source_kind, license_spdx=e.license_spdx,
            license_evidence=e.license_evidence, test_source=bool(e.extra.get("test_source", False)),
        )
        for e in all_entries
    ]

    out = Path(output_dir)
    for entry in all_entries:
        pointer_path = out / entry.pointer_file_path()
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(yaml.safe_dump(entry.to_yaml_dict(), sort_keys=False), encoding="utf-8")

    shards = build_index_shards(all_entries)
    index_dir = out / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    for item_type, rows in shards.items():
        (index_dir / f"{item_type}.json").write_text(json.dumps(rows, indent=2, sort_keys=False), encoding="utf-8")

    return report
