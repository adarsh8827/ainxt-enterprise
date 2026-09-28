# SPDX-License-Identifier: MIT
# ============================================================
# Parses docs/ecosystem/catalog/sources.yaml -- the reviewed crawl
# allowlist (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §1, §7). Changes to
# the underlying file go through a normal reviewed PR; this module only
# reads it, never writes it -- the crawl workflow never edits sources.yaml.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GithubRepoSource:
    repo: str                      # "owner/name"
    category: str
    tags: list[str] = field(default_factory=list)
    include_paths: list[str] = field(default_factory=list)   # empty = whole repo
    exclude_paths: list[str] = field(default_factory=list)   # subtrees never crawled, even if include_paths would otherwise reach them
    needs_product: str = ""        # e.g. "ClickHouse" -- becomes a "needs-<product>" tag
    account_required: bool = False  # becomes an "account-required" tag
    tos_note: str = ""
    enabled: bool = True


@dataclass
class GithubTopicSearchSource:
    topic: str
    tos_note: str = ""
    enabled: bool = True


@dataclass
class WellKnownSource:
    domain: str
    category: str
    tags: list[str] = field(default_factory=list)
    needs_product: str = ""
    account_required: bool = False
    test_source: bool = False      # verifies the adapter against a real site; not counted as a real catalog contribution
    tos_note: str = ""
    enabled: bool = True


@dataclass
class McpRegistrySource:
    tos_note: str = ""
    enabled: bool = True
    max_pages: int = 20


@dataclass
class CrawlLimits:
    """Caps that stop a single crawl from growing the catalog unbounded.
    Exceeding either cap is REPORTED (CrawlReport.over_cap), never a
    silent truncation -- a maintainer needs to see that a repo/run hit
    its limit, not just get a shorter list with no explanation."""
    max_skills_per_repo: int = 50
    max_total_items: int = 10000


@dataclass
class SourcesConfig:
    github_repos: list[GithubRepoSource] = field(default_factory=list)
    github_topic_searches: list[GithubTopicSearchSource] = field(default_factory=list)
    well_known_sites: list[WellKnownSource] = field(default_factory=list)
    mcp_registry: McpRegistrySource | None = None
    crawl_limits: CrawlLimits = field(default_factory=CrawlLimits)


def load_sources(path: str | Path) -> SourcesConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    github_repos = [
        GithubRepoSource(
            repo=r["repo"], category=r.get("category", "uncategorized"), tags=list(r.get("tags") or []),
            include_paths=list(r.get("include_paths") or []), exclude_paths=list(r.get("exclude_paths") or []),
            needs_product=r.get("needs_product", ""), account_required=bool(r.get("account_required", False)),
            tos_note=r.get("tos_note", ""), enabled=bool(r.get("enabled", True)),
        )
        for r in (raw.get("github_repos") or [])
    ]
    github_topic_searches = [
        GithubTopicSearchSource(topic=t["topic"], tos_note=t.get("tos_note", ""), enabled=bool(t.get("enabled", True)))
        for t in (raw.get("github_topic_searches") or [])
    ]
    well_known_sites = [
        WellKnownSource(
            domain=w["domain"], category=w.get("category", "uncategorized"), tags=list(w.get("tags") or []),
            needs_product=w.get("needs_product", ""), account_required=bool(w.get("account_required", False)),
            test_source=bool(w.get("test_source", False)),
            tos_note=w.get("tos_note", ""), enabled=bool(w.get("enabled", True)),
        )
        for w in (raw.get("well_known_sites") or [])
    ]
    mcp_raw = raw.get("mcp_registry")
    mcp_registry = None
    if isinstance(mcp_raw, dict):
        mcp_registry = McpRegistrySource(
            tos_note=mcp_raw.get("tos_note", ""), enabled=bool(mcp_raw.get("enabled", True)),
            max_pages=int(mcp_raw.get("max_pages", 20)),
        )

    limits_raw = raw.get("crawl_limits") or {}
    crawl_limits = CrawlLimits(
        max_skills_per_repo=int(limits_raw.get("max_skills_per_repo", 50)),
        max_total_items=int(limits_raw.get("max_total_items", 10000)),
    )

    return SourcesConfig(
        github_repos=github_repos,
        github_topic_searches=github_topic_searches,
        well_known_sites=well_known_sites,
        mcp_registry=mcp_registry,
        crawl_limits=crawl_limits,
    )


def load_yanked(path: str | Path) -> set[str]:
    """`yanked.yaml`: a flat list of namespaces removed from the catalog
    (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §7). Missing file == nothing
    yanked yet, not an error."""
    p = Path(path)
    if not p.exists():
        return set()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    namespaces = raw.get("yanked") if isinstance(raw, dict) else raw
    return set(namespaces or [])
