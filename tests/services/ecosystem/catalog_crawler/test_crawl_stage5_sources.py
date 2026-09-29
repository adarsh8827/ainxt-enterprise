# SPDX-License-Identifier: MIT
# ============================================================
# Stage 5 (Connectors+Plugins phase) catalog crawler extensions:
# McpServerRepoSource ("original-author" MCP repos, one repo == one
# item_type="mcp_server" pointer) and ActivepiecesSource (community
# pieces, one piece == one item_type="connector" pointer). Same
# monkeypatch-the-adapter-layer style as test_crawl.py.
# ============================================================

from __future__ import annotations

from pathlib import Path

from services.ecosystem.catalog_crawler import crawl
from services.ecosystem.import_adapters import github_repo


def _write_sources_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sources.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_mcp_server_repo_with_allowed_license_becomes_an_mcp_server_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(github_repo, "import_repo_metadata", lambda repo: {
        "resolved_sha": "sha1", "license": "MIT", "license_evidence": "GitHub API license detection",
        "display_name": "cool-mcp-server", "description": "A cool MCP server.",
        "source_url": "https://github.com/acme/cool-mcp-server",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
mcp_server_repos:
  - repo: acme/cool-mcp-server
    category: productivity
    tos_note: "self-hosted, no remote service"
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 1
    assert report.excluded_count == 0
    assert report.included[0].namespace == "acme/cool-mcp-server"

    index_path = tmp_path / "out" / "index" / "mcp_server.json"
    rows = __import__("json").loads(index_path.read_text(encoding="utf-8"))
    assert any(r["namespace"] == "acme/cool-mcp-server" for r in rows)
    assert not (tmp_path / "out" / "index" / "skill.json").exists() or not any(
        r["namespace"] == "acme/cool-mcp-server"
        for r in __import__("json").loads((tmp_path / "out" / "index" / "skill.json").read_text(encoding="utf-8"))
    )


def test_mcp_server_repo_with_disallowed_license_is_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(github_repo, "import_repo_metadata", lambda repo: {
        "resolved_sha": "sha1", "license": "GPL-3.0", "license_evidence": "GitHub API license detection",
        "display_name": "gpl-server", "description": "d", "source_url": "https://github.com/acme/gpl-server",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
mcp_server_repos:
  - repo: acme/gpl-server
    category: productivity
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 0
    assert report.excluded_count == 1
    assert "GPL-3.0" in report.excluded[0].reason


def test_mcp_server_repo_naming_an_ai_vendor_is_excluded_for_neutrality(tmp_path, monkeypatch):
    monkeypatch.setattr(github_repo, "import_repo_metadata", lambda repo: {
        "resolved_sha": "sha1", "license": "MIT", "license_evidence": "x",
        "display_name": "openai-helper", "description": "Wraps OpenAI's API.",
        "source_url": "https://github.com/acme/openai-helper",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
mcp_server_repos:
  - repo: acme/openai-helper
    category: productivity
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 0
    assert "OpenAI" in report.excluded[0].reason


def test_activepieces_piece_with_allowed_license_becomes_a_connector_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(github_repo, "import_activepieces_piece", lambda piece: {
        "resolved_sha": "sha1", "license": "MIT", "license_evidence": "LICENSE file at 'LICENSE' (text-guess)",
        "display_name": "Slack", "description": "Activepieces integration piece for slack (@activepieces/piece-slack).",
        "source_url": "https://github.com/activepieces/activepieces/tree/sha1/packages/pieces/community/slack",
        "package_name": "@activepieces/piece-slack",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
activepieces:
  - pieces: [slack]
    category: productivity
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 1
    assert report.included[0].namespace == "activepieces/slack"

    index_path = tmp_path / "out" / "index" / "connector.json"
    rows = __import__("json").loads(index_path.read_text(encoding="utf-8"))
    assert any(r["namespace"] == "activepieces/slack" for r in rows)


def test_activepieces_piece_under_ee_license_is_excluded_not_silently_included(tmp_path, monkeypatch):
    # Simulates the defensive case: a piece whose nearest LICENSE file
    # resolves to a non-MIT/Apache text (e.g. if Activepieces ever nested
    # a piece under a differently-licensed subtree) -- must exclude, not
    # fall back to assuming MIT.
    monkeypatch.setattr(github_repo, "import_activepieces_piece", lambda piece: {
        "resolved_sha": "sha1", "license": "", "license_evidence": "no LICENSE file found in this piece's own or any ancestor folder",
        "display_name": "Mystery", "description": "d", "source_url": "https://github.com/activepieces/activepieces",
        "package_name": "@activepieces/piece-mystery",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
activepieces:
  - pieces: [mystery]
    category: productivity
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 0
    assert report.excluded_count == 1
    assert "not MIT/Apache-2.0" in report.excluded[0].reason


def test_activepieces_piece_naming_an_ai_vendor_is_excluded_for_neutrality(tmp_path, monkeypatch):
    monkeypatch.setattr(github_repo, "import_activepieces_piece", lambda piece: {
        "resolved_sha": "sha1", "license": "MIT", "license_evidence": "x",
        "display_name": "Claude Piece", "description": "Talks to Claude's API.",
        "source_url": "https://github.com/activepieces/activepieces",
        "package_name": "@activepieces/piece-claude",
    })
    sources_yaml = _write_sources_yaml(tmp_path, """
activepieces:
  - pieces: [claude]
    category: productivity
""")
    report = crawl.run_crawl(sources_yaml, tmp_path / "yanked.yaml", tmp_path / "out")
    assert report.included_count == 0
    assert "Claude" in report.excluded[0].reason


def test_mcp_server_repo_bad_category_fails_load_loudly():
    import tempfile

    from services.ecosystem.catalog_crawler.sources_config import load_sources

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sources.yaml"
        p.write_text("""
mcp_server_repos:
  - repo: acme/x
    category: not-a-real-category
""", encoding="utf-8")
        try:
            load_sources(p)
            assert False, "expected a ValueError for an unknown taxonomy category"
        except ValueError as exc:
            assert "not-a-real-category" in str(exc)


def test_activepieces_bad_category_fails_load_loudly():
    import tempfile

    from services.ecosystem.catalog_crawler.sources_config import load_sources

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sources.yaml"
        p.write_text("""
activepieces:
  - pieces: [slack]
    category: not-a-real-category
""", encoding="utf-8")
        try:
            load_sources(p)
            assert False, "expected a ValueError for an unknown taxonomy category"
        except ValueError as exc:
            assert "not-a-real-category" in str(exc)
