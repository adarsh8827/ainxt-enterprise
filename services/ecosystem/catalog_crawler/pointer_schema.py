# SPDX-License-Identifier: MIT
# ============================================================
# Pointer-entry schema for the `ecosystem-index` orphan branch
# (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §1). One PointerEntry per
# catalog item; never carries skill file bytes, only enough metadata for
# an installation to fetch the real content from its original source at
# install time. Kept flat and small on purpose -- 10k+ entries must stay
# a few MB total.
# ============================================================

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Skill namespaces (GitHub/well-known publishers) are plain lowercase-
# hyphen names; MCP server names legitimately use reverse-DNS-style
# publisher segments (e.g. "ai.adeu/adeu", "io.github.owner/repo") --
# a real, live crawl found this immediately (2026-09-28) on the very
# first MCP Registry entry, so "." is allowed in both segments, not
# just "-"/"_".
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*$")


@dataclass
class PointerEntry:
    namespace: str                  # "publisher/name"
    item_type: str                  # "skill" | "mcp_server"
    display_name: str
    description: str
    category: str
    tags: list[str]
    source_kind: str                # "github_repo" | "well_known" | "mcp_registry"
    source_url: str
    source_ref: str                 # pinned commit SHA, or a content digest for well_known/mcp_registry
    source_path: str = ""           # subdirectory within source_url, if any
    license_spdx: str = ""
    license_evidence: str = ""
    compatibility: str = "chat"
    content_hash: str = ""          # "sha256:<hex>"
    attribution: str = ""
    crawled_at: str = ""
    remote_only: bool = False       # mcp_server entries with no installable package
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _NAMESPACE_RE.match(self.namespace):
            raise ValueError(f"pointer entry namespace {self.namespace!r} must be 'publisher/name' (lowercase, - or _)")
        if self.item_type not in ("skill", "mcp_server"):
            raise ValueError(f"pointer entry item_type {self.item_type!r} must be 'skill' or 'mcp_server'")
        if not self.crawled_at:
            self.crawled_at = datetime.now(timezone.utc).isoformat()

    @property
    def publisher(self) -> str:
        return self.namespace.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.namespace.split("/", 1)[1]

    def pointer_file_path(self) -> str:
        """Relative path within the `ecosystem-index` branch this entry's
        own YAML file lives at: catalog/<item_type>/<publisher>/<name>.yaml."""
        return f"catalog/{self.item_type}/{self.publisher}/{self.name}.yaml"

    def to_yaml_dict(self) -> dict[str, Any]:
        source: dict[str, Any] = {"kind": self.source_kind, "url": self.source_url, "ref": self.source_ref}
        if self.source_path:
            source["path"] = self.source_path
        d: dict[str, Any] = {
            "namespace": self.namespace,
            "item_type": self.item_type,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
            "source": source,
            "license": {"spdx": self.license_spdx, "evidence": self.license_evidence},
            "compatibility": self.compatibility,
            "content_hash": self.content_hash,
            "attribution": self.attribution,
            "crawled_at": self.crawled_at,
        }
        if self.remote_only:
            d["remote_only"] = True
        return d

    def to_index_row(self) -> dict[str, Any]:
        """Flattened row for the built `index.json` (or its per-type
        shard) -- the same data as to_yaml_dict(), just as one array
        entry rather than a standalone document, since installations
        fetch this directly over HTTP and don't need per-file framing."""
        return self.to_yaml_dict()

    @classmethod
    def from_yaml_dict(cls, d: dict[str, Any]) -> "PointerEntry":
        source = d.get("source") or {}
        license_block = d.get("license") or {}
        return cls(
            namespace=d["namespace"],
            item_type=d["item_type"],
            display_name=d.get("display_name", ""),
            description=d.get("description", ""),
            category=d.get("category", ""),
            tags=list(d.get("tags") or []),
            source_kind=source.get("kind", ""),
            source_url=source.get("url", ""),
            source_ref=source.get("ref", ""),
            source_path=source.get("path", ""),
            license_spdx=license_block.get("spdx", ""),
            license_evidence=license_block.get("evidence", ""),
            compatibility=d.get("compatibility", "chat"),
            content_hash=d.get("content_hash", ""),
            attribution=d.get("attribution", ""),
            crawled_at=d.get("crawled_at", ""),
            remote_only=bool(d.get("remote_only", False)),
        )


def build_index_shards(entries: list[PointerEntry]) -> dict[str, list[dict[str, Any]]]:
    """Groups entries by item_type into the sharded index.json shape --
    {"skill": [...], "mcp_server": [...]} -- sorted by namespace within
    each shard for a stable, low-diff-noise output across crawl runs."""
    shards: dict[str, list[dict[str, Any]]] = {}
    for entry in sorted(entries, key=lambda e: e.namespace):
        shards.setdefault(entry.item_type, []).append(entry.to_index_row())
    return shards
