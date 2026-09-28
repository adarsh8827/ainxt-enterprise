# SPDX-License-Identifier: MIT
# ============================================================
# Crawl orchestrator (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §1, §3, §4).
# Reuses the SAME adapters and license-inheritance logic the manual
# admin-import path already uses (services/ecosystem/import_adapters/
# github_repo.py, well_known.py, mcp_registry.py) -- nothing here
# re-derives a license verdict independently; every "allowed" here is an
# allowed the existing adapters already computed. Fast safety checks
# (services/ecosystem/gate/static_safety_stage.py's run_fast_path) are a
# crawl-time pre-filter only -- the full 7-stage gate still runs,
# unconditionally, at install time (§4).
# ============================================================

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from services.ecosystem.catalog_crawler.crawl_report import CrawlReport, ExcludedEntry, IncludedEntry
from services.ecosystem.catalog_crawler.pointer_schema import PointerEntry, build_index_shards
from services.ecosystem.catalog_crawler.sources_config import SourcesConfig, load_sources, load_yanked
from services.ecosystem.compatibility import classify_compatibility
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError
from services.ecosystem.gate.static_safety_stage import run_fast_path
from services.ecosystem.import_adapters import github_repo, mcp_registry, well_known


def _content_hash(manifest_text: str, files: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(manifest_text.encode("utf-8"))
    for rel_path in sorted(files):
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(files[rel_path].encode("utf-8"))
    return f"sha256:{hasher.hexdigest()}"


def _crawl_github_repo(source, report: CrawlReport) -> list[PointerEntry]:
    entries: list[PointerEntry] = []
    try:
        candidates = github_repo.discover_skills_in_repo(source.repo, path=source.path)
    except (ImportFetchError, ImportRateLimitedError) as exc:
        report.excluded.append(ExcludedEntry(source_kind="github_repo", identifier=source.repo, reason=f"discovery failed: {exc}"))
        return entries

    owner_slug = source.repo.split("/", 1)[0].lower()
    for cand in candidates:
        identifier = f"{source.repo}#{cand['path'] or '(root)'}"
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

        skill_name = (cand["path"].rsplit("/", 1)[-1] if cand["path"] else source.repo.split("/", 1)[1]).lower().replace("_", "-")
        namespace = f"{owner_slug}/{skill_name}"
        entry = PointerEntry(
            namespace=namespace,
            item_type="skill",
            display_name=imported["display_name"],
            description=imported["description"],
            category=source.category,
            tags=list(source.tags),
            source_kind="github_repo",
            source_url=f"https://github.com/{source.repo}",
            source_ref=imported["resolved_sha"],
            source_path=cand["path"],
            license_spdx=imported["license"],
            license_evidence=cand["license_evidence"]["effective_license_source"],
            compatibility=classify_compatibility(manifest_text),
            content_hash=_content_hash(manifest_text, imported["files"]),
        )
        entries.append(entry)
        report.included.append(IncludedEntry(
            namespace=namespace, source_kind="github_repo",
            license_spdx=entry.license_spdx, license_evidence=entry.license_evidence,
        ))
    return entries


def _crawl_well_known(source, report: CrawlReport) -> list[PointerEntry]:
    entries: list[PointerEntry] = []
    try:
        candidates = well_known.discover_skills_at_well_known(source.domain)
    except ImportFetchError as exc:
        report.excluded.append(ExcludedEntry(source_kind="well_known", identifier=source.domain, reason=f"discovery failed: {exc}"))
        return entries

    domain_slug = source.domain.split(".")[0].lower()
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

        namespace = f"{domain_slug}/{cand['slug'].lower().replace('_', '-')}"
        entry = PointerEntry(
            namespace=namespace,
            item_type="skill",
            display_name=cand["display_name"],
            description=cand["description"],
            category=source.category,
            tags=list(source.tags),
            source_kind="well_known",
            source_url=cand["source_url"],
            source_ref=cand["resolved_sha"] or "",
            license_spdx=cand["license_evidence"]["skill_md_license_field"] or "",
            license_evidence="SKILL.md license field (well-known site)",
            compatibility=classify_compatibility(manifest_text),
            content_hash=_content_hash(manifest_text, files),
        )
        entries.append(entry)
        report.included.append(IncludedEntry(
            namespace=namespace, source_kind="well_known",
            license_spdx=entry.license_spdx, license_evidence=entry.license_evidence,
        ))
    return entries


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
        report.included.append(IncludedEntry(
            namespace=namespace, source_kind="mcp_registry",
            license_spdx=entry.license_spdx, license_evidence=entry.license_evidence,
        ))
    return entries


def run_crawl(sources_path: str | Path, yanked_path: str | Path, output_dir: str | Path) -> CrawlReport:
    """Runs every enabled source in sources.yaml, writes one pointer YAML
    per included entry under `output_dir/catalog/...`, and builds
    `output_dir/index/<item_type>.json`. Does NOT sign anything (§2's
    sign_index_bytes() is a separate step the caller invokes on the
    written index files) and does NOT commit/push (the calling workflow
    script owns that, against the `ecosystem-index` branch checkout).
    Returns the crawl report (stop point 2's artifact).
    """
    config: SourcesConfig = load_sources(sources_path)
    yanked = load_yanked(yanked_path)
    report = CrawlReport()
    all_entries: list[PointerEntry] = []

    for repo_source in config.github_repos:
        if not repo_source.enabled:
            continue
        all_entries.extend(_crawl_github_repo(repo_source, report))

    for site_source in config.well_known_sites:
        if not site_source.enabled:
            continue
        all_entries.extend(_crawl_well_known(site_source, report))

    if config.mcp_registry and config.mcp_registry.enabled:
        all_entries.extend(_crawl_mcp_registry(config.mcp_registry, report))

    # yanked.yaml removes single items even if their source would still
    # produce them -- filtered out of both the pointer files and the
    # index, and out of the report's included list (never silently
    # counted as "included" once yanked).
    kept_entries = [e for e in all_entries if e.namespace not in yanked]
    report.included = [i for i in report.included if i.namespace not in yanked]

    out = Path(output_dir)
    for entry in kept_entries:
        pointer_path = out / entry.pointer_file_path()
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(yaml.safe_dump(entry.to_yaml_dict(), sort_keys=False), encoding="utf-8")

    shards = build_index_shards(kept_entries)
    index_dir = out / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    for item_type, rows in shards.items():
        (index_dir / f"{item_type}.json").write_text(json.dumps(rows, indent=2, sort_keys=False), encoding="utf-8")

    return report
