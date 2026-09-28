# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from services.ecosystem.catalog_crawler.pointer_schema import PointerEntry, build_index_shards


def _entry(namespace="addyosmani/code-review", **overrides) -> PointerEntry:
    kwargs = dict(
        namespace=namespace, item_type="skill", display_name="Code Review",
        description="Reviews code.", category="engineering", tags=["review"],
        source_kind="github_repo", source_url="https://github.com/addyosmani/agent-skills",
        source_ref="2686b62", source_path="skills/code-review-and-quality",
        license_spdx="MIT", license_evidence="SKILL.md license field",
    )
    kwargs.update(overrides)
    return PointerEntry(**kwargs)


def test_rejects_a_malformed_namespace():
    with pytest.raises(ValueError, match="namespace"):
        _entry(namespace="not-a-namespace")


def test_rejects_an_invalid_item_type():
    with pytest.raises(ValueError, match="item_type"):
        _entry(item_type="plugin")


def test_pointer_file_path_matches_the_catalog_publisher_name_layout():
    entry = _entry()
    assert entry.pointer_file_path() == "catalog/skill/addyosmani/code-review.yaml"


def test_publisher_and_name_split_on_the_first_slash_only():
    entry = _entry(namespace="a/b-c")
    assert entry.publisher == "a"
    assert entry.name == "b-c"


def test_to_yaml_dict_omits_path_and_remote_only_when_absent():
    entry = _entry(source_path="", remote_only=False)
    d = entry.to_yaml_dict()
    assert "path" not in d["source"]
    assert "remote_only" not in d


def test_to_yaml_dict_includes_path_and_remote_only_when_set():
    entry = _entry(remote_only=True)
    d = entry.to_yaml_dict()
    assert d["source"]["path"] == "skills/code-review-and-quality"
    assert d["remote_only"] is True


def test_roundtrip_through_yaml_dict_preserves_every_field():
    entry = _entry()
    restored = PointerEntry.from_yaml_dict(entry.to_yaml_dict())
    assert restored.to_yaml_dict() == entry.to_yaml_dict()


def test_crawled_at_defaults_to_now_when_not_supplied():
    entry = _entry()
    assert entry.crawled_at  # non-empty, ISO-ish


def test_build_index_shards_groups_by_item_type_and_sorts_by_namespace():
    a = _entry(namespace="b-pub/skill")
    b = _entry(namespace="a-pub/skill")
    mcp = _entry(namespace="mcp/server-one", item_type="mcp_server", source_kind="mcp_registry")
    shards = build_index_shards([a, b, mcp])
    assert [row["namespace"] for row in shards["skill"]] == ["a-pub/skill", "b-pub/skill"]
    assert [row["namespace"] for row in shards["mcp_server"]] == ["mcp/server-one"]
