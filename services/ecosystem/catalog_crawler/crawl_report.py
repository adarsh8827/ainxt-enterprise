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
    test_source: bool = False


@dataclass
class ExcludedEntry:
    source_kind: str
    identifier: str    # repo path / well-known slug / mcp server name
    reason: str


@dataclass
class OverCapEntry:
    """A repo or the whole run produced more allowed candidates than a
    configured cap -- reported explicitly (never a silent truncation)."""
    scope: str          # "repo:<owner/name>" or "total"
    cap: int
    available: int
    included: int


@dataclass
class CircuitBreakerTrip:
    """A source's crawled content changed too fast vs. the previous
    index to trust blindly -- that source's new results are discarded
    for this run entirely, not partially trusted."""
    source_kind: str
    source_identifier: str
    changed: int
    total_compared: int
    threshold: float


@dataclass
class CrawlReport:
    included: list[IncludedEntry] = field(default_factory=list)
    excluded: list[ExcludedEntry] = field(default_factory=list)
    over_cap: list[OverCapEntry] = field(default_factory=list)
    circuit_breaker_trips: list[CircuitBreakerTrip] = field(default_factory=list)
    skipped_unchanged_repos: list[str] = field(default_factory=list)
    api_call_stats: dict[str, int] = field(default_factory=dict)

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
            f"- Included: **{self.included_count}** ({sum(1 for e in self.included if e.test_source)} from test-only sources)",
            f"- Excluded: **{self.excluded_count}**",
        ]
        if self.api_call_stats:
            total = self.api_call_stats.get("total_requests", 0)
            consuming = self.api_call_stats.get("rate_limit_consuming_requests", 0)
            lines.append(
                f"- GitHub API calls: **{consuming}** rate-limit-consuming ({total} total requests, "
                f"{total - consuming} served as free 304s via ETag)"
            )
        if self.skipped_unchanged_repos:
            lines.append(f"- Repos skipped (HEAD unchanged since the last index): **{len(self.skipped_unchanged_repos)}**")
        lines.append("")
        if self.skipped_unchanged_repos:
            lines += ["## Skipped, unchanged since the last crawl", ""]
            for repo in self.skipped_unchanged_repos:
                lines.append(f"- `{repo}` -- HEAD matches the previous index, reused those entries verbatim")
            lines.append("")
        if self.circuit_breaker_trips:
            lines += ["## Circuit breaker trips (source discarded this run)", ""]
            for t in self.circuit_breaker_trips:
                lines.append(
                    f"- `{t.source_identifier}` ({t.source_kind}): {t.changed}/{t.total_compared} previously-seen "
                    f"items changed (threshold {t.threshold:.0%}) -- this source's results were discarded for this run"
                )
            lines.append("")
        if self.over_cap:
            lines += ["## Over cap (reported, not silently truncated)", ""]
            for c in self.over_cap:
                lines.append(f"- {c.scope}: {c.available} available, cap {c.cap}, {c.included} included")
            lines.append("")
        lines += ["## Excluded, by reason", ""]
        for reason, count in self.excluded_by_reason().most_common():
            lines.append(f"- {reason}: {count}")
        lines += ["", "## Sample included entries (license evidence)", ""]
        for e in self.included[:20]:
            test_tag = " [test source]" if e.test_source else ""
            lines.append(f"- `{e.namespace}` ({e.source_kind}){test_tag} -- {e.license_spdx} via {e.license_evidence}")
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
            "over_cap": [vars(e) for e in self.over_cap],
            "circuit_breaker_trips": [vars(e) for e in self.circuit_breaker_trips],
            "skipped_unchanged_repos": list(self.skipped_unchanged_repos),
            "api_call_stats": dict(self.api_call_stats),
        }
