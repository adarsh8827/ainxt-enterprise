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
  - repo: wshobson/agents
    category: engineering
    include_paths: [plugins/incident-response/skills]
    exclude_paths: [plugins/incident-response/skills/postmortem-writing]
    needs_product: SomeProduct
    account_required: true
    tos_note: "public repo, MIT"
github_topic_searches:
  - topic: agent-skills
    tos_note: "GitHub topic search, anonymous, rate-limited"
well_known_sites:
  - domain: docs.x.com
    category: engineering
    test_source: true
    tos_note: "publishes /.well-known/agent-skills/index.json"
mcp_registry:
  enabled: true
  max_pages: 5
  tos_note: "official MCP Registry, API v0.1"
crawl_limits:
  max_skills_per_repo: 25
  max_total_items: 500
"""


def test_load_sources_parses_every_section(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text(_SOURCES_YAML, encoding="utf-8")
    config = load_sources(p)

    assert len(config.github_repos) == 3
    assert config.github_repos[0].repo == "addyosmani/agent-skills"
    assert config.github_repos[0].enabled is True
    assert config.github_repos[1].enabled is False
    assert config.github_repos[2].include_paths == ["plugins/incident-response/skills"]
    assert config.github_repos[2].exclude_paths == ["plugins/incident-response/skills/postmortem-writing"]
    assert config.github_repos[2].needs_product == "SomeProduct"
    assert config.github_repos[2].account_required is True

    assert config.github_topic_searches[0].topic == "agent-skills"

    assert config.well_known_sites[0].domain == "docs.x.com"
    assert config.well_known_sites[0].test_source is True

    assert config.mcp_registry is not None
    assert config.mcp_registry.max_pages == 5

    assert config.crawl_limits.max_skills_per_repo == 25
    assert config.crawl_limits.max_total_items == 500


def test_crawl_limits_default_when_absent(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text("github_repos: []\n", encoding="utf-8")
    config = load_sources(p)
    assert config.crawl_limits.max_skills_per_repo == 50
    assert config.crawl_limits.max_total_items == 10000


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


def test_load_sources_rejects_a_github_repo_category_not_in_the_real_taxonomy(tmp_path: Path):
    # Real incident, 2026-09-29: a category assigned here that isn't in
    # config_service.TAXONOMY_CATEGORIES made real crawled/imported items
    # silently invisible in Discover (twice, for two different reasons --
    # a sources.yaml repo-level category, and separately a hardcoded
    # admin-import spec). This must fail the load itself, loudly, before
    # any crawl runs.
    p = tmp_path / "sources.yaml"
    p.write_text(
        "github_repos:\n  - repo: someone/bad-category-repo\n    category: totally-not-a-real-category\n",
        encoding="utf-8",
    )
    try:
        load_sources(p)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "someone/bad-category-repo" in str(exc)
        assert "totally-not-a-real-category" in str(exc)


def test_load_sources_rejects_a_well_known_site_category_not_in_the_real_taxonomy(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text(
        "well_known_sites:\n  - domain: example.com\n    category: also-not-real\n",
        encoding="utf-8",
    )
    try:
        load_sources(p)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "example.com" in str(exc)
        assert "also-not-real" in str(exc)


def test_load_sources_accepts_every_real_taxonomy_category(tmp_path: Path):
    from services.ecosystem.config_service import TAXONOMY_CATEGORIES

    p = tmp_path / "sources.yaml"
    repos = "\n".join(
        f"  - repo: someone/repo-{i}\n    category: {cat}" for i, cat in enumerate(TAXONOMY_CATEGORIES)
    )
    p.write_text(f"github_repos:\n{repos}\n", encoding="utf-8")
    config = load_sources(p)
    assert len(config.github_repos) == len(TAXONOMY_CATEGORIES)


def test_the_real_sources_yaml_loads_cleanly_with_the_new_category_validation():
    # The whole point of this check is to catch a bad category BEFORE a
    # crawl runs -- so the real, checked-in file must itself pass it.
    config = load_sources("docs/ecosystem/catalog/sources.yaml")
    assert len(config.github_repos) > 0


_GIT_REPO_SOURCES_YAML = """
git_repos:
  - url: https://gitlab.com/some-group/some-project.git
    ref: main
    category: engineering
    tags: [gitlab]
    include_paths: [skills]
    exclude_paths: [skills/legacy]
    needs_product: SomeProduct
    account_required: true
    read_token_env: SOME_GITLAB_TOKEN
    tos_note: "public GitLab repo, MIT"
  - url: https://git.example.com/team/disabled-project.git
    category: engineering
    enabled: false
    tos_note: "kept for reference, not crawled"
"""


def test_load_sources_parses_git_repos(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text(_GIT_REPO_SOURCES_YAML, encoding="utf-8")
    config = load_sources(p)

    assert len(config.git_repos) == 2
    first = config.git_repos[0]
    assert first.url == "https://gitlab.com/some-group/some-project.git"
    assert first.ref == "main"
    assert first.include_paths == ["skills"]
    assert first.exclude_paths == ["skills/legacy"]
    assert first.needs_product == "SomeProduct"
    assert first.account_required is True
    assert first.read_token_env == "SOME_GITLAB_TOKEN"
    assert first.enabled is True
    assert config.git_repos[1].enabled is False


def test_git_repos_default_ref_is_head_when_omitted(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text("git_repos:\n  - url: https://gitlab.com/g/p.git\n    category: engineering\n", encoding="utf-8")
    config = load_sources(p)
    assert config.git_repos[0].ref == "HEAD"


def test_load_sources_rejects_a_non_https_git_repo_url(tmp_path: Path):
    # Same real-world boundary github_repo.py's own assert_safe_https_url
    # enforces -- checked here, at config-load time, since git_repo.py's
    # own adapter functions deliberately accept any well-formed URL (its
    # own tests clone a local file:// fixture repo with no network at all).
    p = tmp_path / "sources.yaml"
    p.write_text(
        "git_repos:\n  - url: http://insecure.example.com/team/project.git\n    category: engineering\n",
        encoding="utf-8",
    )
    try:
        load_sources(p)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "http://insecure.example.com/team/project.git" in str(exc)


def test_load_sources_rejects_a_git_repo_category_not_in_the_real_taxonomy(tmp_path: Path):
    p = tmp_path / "sources.yaml"
    p.write_text(
        "git_repos:\n  - url: https://gitlab.com/g/p.git\n    category: totally-not-a-real-category\n",
        encoding="utf-8",
    )
    try:
        load_sources(p)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "https://gitlab.com/g/p.git" in str(exc)
        assert "totally-not-a-real-category" in str(exc)
