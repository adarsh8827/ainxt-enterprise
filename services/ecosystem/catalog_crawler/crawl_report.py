# SPDX-License-Identifier: MIT
"""Crawl report (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §4, stop point 2)
-- every excluded candidate is logged with its reason here; excluded
items are never listed in the catalog itself."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncludedEntry:
    namespace: str
    source_kind: str
    license_spdx: str
    license_evidence: str


@dataclass
class ExcludedEntry:
    source_kind: str
    identifier: str    # repo path / well-known slug / mcp server name
    reason: str


@dataclass
class CrawlReport:
    included: list[IncludedEntry] = field(default_factory=list)
    excluded: list[ExcludedEntry] = field(default_factory=list)

    @property
    def included_count(self) -> int:
        return len(self.included)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    def excluded_by_reason(self) -> Counter:
        # Bucketed by the reason's leading clause (before the first ':' or
        # '(') so near-duplicate messages (different repos, same root
        # cause) group into one count instead of 200 one-off rows.
        counter: Counter = Counter()
        for e in self.excluded:
            bucket = e.reason.split(":", 1)[0].split("(", 1)[0].strip()
            counter[bucket] += 1
        return counter

    def to_markdown(self) -> str:
        lines = [
            "# Catalog crawl report",
            "",
            f"- Included: **{self.included_count}**",
            f"- Excluded: **{self.excluded_count}**",
            "",
            "## Excluded, by reason",
            "",
        ]
        for reason, count in self.excluded_by_reason().most_common():
            lines.append(f"- {reason}: {count}")
        lines += ["", "## Sample included entries (license evidence)", ""]
        for e in self.included[:20]:
            lines.append(f"- `{e.namespace}` ({e.source_kind}) -- {e.license_spdx} via {e.license_evidence}")
        lines += ["", "## All excluded entries", ""]
        for e in self.excluded:
            lines.append(f"- `{e.identifier}` ({e.source_kind}): {e.reason}")
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "included_count": self.included_count,
            "excluded_count": self.excluded_count,
            "excluded_by_reason": dict(self.excluded_by_reason()),
            "included": [vars(e) for e in self.included],
            "excluded": [vars(e) for e in self.excluded],
        }
