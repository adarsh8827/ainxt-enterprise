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
    path: str | None = None        # optional subdirectory scope
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
    tos_note: str = ""
    enabled: bool = True


@dataclass
class McpRegistrySource:
    tos_note: str = ""
    enabled: bool = True
    max_pages: int = 20


@dataclass
class SourcesConfig:
    github_repos: list[GithubRepoSource] = field(default_factory=list)
    github_topic_searches: list[GithubTopicSearchSource] = field(default_factory=list)
    well_known_sites: list[WellKnownSource] = field(default_factory=list)
    mcp_registry: McpRegistrySource | None = None


def load_sources(path: str | Path) -> SourcesConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    github_repos = [
        GithubRepoSource(
            repo=r["repo"], category=r.get("category", "uncategorized"), tags=list(r.get("tags") or []),
            path=r.get("path"), tos_note=r.get("tos_note", ""), enabled=bool(r.get("enabled", True)),
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

    return SourcesConfig(
        github_repos=github_repos,
        github_topic_searches=github_topic_searches,
        well_known_sites=well_known_sites,
        mcp_registry=mcp_registry,
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
