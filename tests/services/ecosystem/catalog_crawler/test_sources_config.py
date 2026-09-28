# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from services.ecosystem.catalog_crawler.sources_config import load_sources, load_yanked

_SOURCES_YAML = """
github_repos:
  - repo: addyosmani/agent-skills
    category: engineering
    tags: [review]
    tos_note: "public repo, no auth required, MIT"
  - repo: disabled/repo
    category: engineering
    enabled: false
    tos_note: "kept for reference, not crawled"
github_topic_searches:
  - topic: agent-skills
    tos_note: "GitHub topic search, anonymous, rate-limited"
well_known_sites:
  - domain: docs.x.com
    category: engineering
    tos_note: "publishes /.well-known/agent-skills/index.json"
mcp_registry:
  enabled: true
  max_pages: 5
  tos_note: "official MCP Registry, API v0.1"
"""


def test_load_sources_parses_every_section(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text(_SOURCES_YAML, encoding="utf-8")
    config = load_sources(p)

    assert len(config.github_repos) == 2
    assert config.github_repos[0].repo == "addyosmani/agent-skills"
    assert config.github_repos[0].enabled is True
    assert config.github_repos[1].enabled is False

    assert config.github_topic_searches[0].topic == "agent-skills"

    assert config.well_known_sites[0].domain == "docs.x.com"

    assert config.mcp_registry is not None
    assert config.mcp_registry.max_pages == 5


def test_load_sources_rejects_a_non_mapping_top_level(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    try:
        load_sources(p)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_load_yanked_returns_empty_set_when_file_is_missing(tmp_path: Path):
    assert load_yanked(tmp_path / "does-not-exist.yaml") == set()


def test_load_yanked_reads_the_namespace_list(tmp_path: Path):
    p = tmp_path / "yanked.yaml"
    p.write_text("yanked:\n  - some/skill\n  - other/skill\n", encoding="utf-8")
    assert load_yanked(p) == {"some/skill", "other/skill"}
