# SPDX-License-Identifier: MIT
# ============================================================
# Offline catalog bundle mode (porting-pack round, 2026-09-29):
# sync_catalog_from_bundle()/_read_content_from_bundle() -- the "read the
# index + skill files from a local path or an internal Git(Lab) raw URL"
# feature. Same convention as test_catalog_sync.py: the real, checked-in
# signed fixture (real_signed_mcp_server.json[.sigstore]) proves the real,
# unmocked sigstore verification path works from LOCAL FILES too, not
# just over HTTP.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path

import pytest

from db.database import SessionLocal
from db.models import EcosystemItem
from services.ecosystem import catalog_sync
from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
from services.ecosystem.catalog_crawler.signing import TrustedSigner
from services.ecosystem.errors import ImportFetchError

_A_SIGNER = TrustedSigner(
    issuer="https://token.actions.githubusercontent.com",
    source_repository_uri="https://github.com/adarsh8827/ainxt-enterprise",
)

_FIXTURES_DIR = Path(__file__).parent / "catalog_crawler" / "fixtures"
_REAL_MCP_DATA = (_FIXTURES_DIR / "real_signed_mcp_server.json").read_bytes()
_REAL_MCP_BUNDLE = (_FIXTURES_DIR / "real_signed_mcp_server.json.sigstore").read_bytes()


def _write_index_shard(bundle_root: Path, shard: str, data: bytes, bundle: bytes) -> None:
    index_dir = bundle_root / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{shard}.json").write_bytes(data)
    (index_dir / f"{shard}.json.sigstore").write_bytes(bundle)


def test_sync_catalog_from_bundle_accepts_the_real_signed_fixture_from_local_files(tmp_path):
    # No mocking of verify_index_bytes here -- the real, unmocked
    # sigstore verification path, reading from a plain local directory
    # instead of HTTP, exactly what an air-gapped instance's own bundle
    # sync does.
    pytest.importorskip("sigstore")
    _write_index_shard(tmp_path, "mcp_server", _REAL_MCP_DATA, _REAL_MCP_BUNDLE)

    report = catalog_sync.sync_catalog_from_bundle(str(tmp_path), _A_SIGNER)

    skill_result = next(s for s in report.shards if s.shard == "skill")
    mcp_result = next(s for s in report.shards if s.shard == "mcp_server")
    # "skill" shard simply absent from this bundle -- not an error, same
    # as a 304 online (an operator's bundle can legitimately cover a
    # subset of shards).
    assert skill_result.fetched is False
    assert skill_result.error is None
    assert mcp_result.error is None
    assert mcp_result.verified is True
    assert mcp_result.created == 73  # real fixture row count, same as the online-mode test

    db = SessionLocal()
    try:
        sample = db.query(EcosystemItem).filter(EcosystemItem.namespace == "ai.adeu/adeu").first()
    finally:
        db.close()
    assert sample is not None
    assert sample.scope == "central_index"


def test_sync_catalog_from_bundle_rejects_a_tampered_local_index_file(tmp_path):
    pytest.importorskip("sigstore")
    tampered = bytearray(_REAL_MCP_DATA)
    tampered[100] ^= 0xFF
    _write_index_shard(tmp_path, "mcp_server", bytes(tampered), _REAL_MCP_BUNDLE)

    report = catalog_sync.sync_catalog_from_bundle(str(tmp_path), _A_SIGNER)
    mcp_result = next(s for s in report.shards if s.shard == "mcp_server")
    assert mcp_result.verified is False
    assert mcp_result.error is not None
    assert "signature verification failed" in mcp_result.error


def test_sync_catalog_from_bundle_missing_sigstore_file_is_a_reported_error_not_a_crash(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "skill.json").write_bytes(b"[]")
    # No skill.json.sigstore written at all.

    report = catalog_sync.sync_catalog_from_bundle(str(tmp_path), _A_SIGNER)
    skill_result = next(s for s in report.shards if s.shard == "skill")
    assert skill_result.error is not None
    assert "signature bundle read failed" in skill_result.error


def test_read_content_from_bundle_returns_the_shape_materialize_from_catalog_expects(tmp_path):
    manifest = {"instructions": "Say hello.", "compatibility": "chat"}
    files: dict[str, str] = {}
    content_hash = compute_content_hash(manifest["instructions"], files)
    hex_digest = content_hash.split(":", 1)[-1]

    skill_dir = tmp_path / "skills" / hex_digest
    skill_dir.mkdir(parents=True)
    (skill_dir / "content.json").write_text(json.dumps({"manifest": manifest, "files": files}), encoding="utf-8")
    (skill_dir / "meta.json").write_text(
        json.dumps({
            "namespace": "acme/hello", "display_name": "Hello", "description": "d",
            "license_spdx": "MIT", "attribution": "github_repo:acme/hello@" + "a" * 40,
        }),
        encoding="utf-8",
    )

    pointer = {
        "content_hash": content_hash, "source_ref": "a" * 40,
        "source_url": "https://github.com/acme/hello",
    }
    imported = catalog_sync._read_content_from_bundle(str(tmp_path), pointer)
    assert imported["manifest"] == manifest
    assert imported["files"] == files
    assert imported["license"] == "MIT"
    assert imported["display_name"] == "Hello"
    assert imported["description"] == "d"
    assert imported["resolved_sha"] == "a" * 40
    assert imported["source_url"] == "https://github.com/acme/hello"


def test_read_content_from_bundle_raises_clearly_when_hash_has_no_bundle_entry(tmp_path):
    pointer = {"content_hash": "sha256:" + "b" * 64}
    with pytest.raises(ImportFetchError, match="bundle file not found"):
        catalog_sync._read_content_from_bundle(str(tmp_path), pointer)


def test_read_content_from_bundle_raises_clearly_when_pointer_has_no_content_hash(tmp_path):
    with pytest.raises(ImportFetchError, match="no recorded content_hash"):
        catalog_sync._read_content_from_bundle(str(tmp_path), {})


def test_materialize_from_catalog_reads_from_bundle_with_zero_network_calls(tmp_path, monkeypatch):
    """The one guarantee this whole feature exists for: with
    ECOSYSTEM_CATALOG_SOURCE_MODE=bundle, materialize_from_catalog() never
    reaches out to GitHub/well_known at all -- relay_request (every
    online import adapter's own shared HTTP call point) is monkeypatched
    to raise if it's ever invoked, so a regression back to the online
    path would fail this test loudly instead of just working by
    coincidence in CI (which has real internet)."""
    from services.ecosystem import items_service
    from services.ecosystem.catalog_sync import materialize_from_catalog

    def _relay_must_not_be_called(*args, **kwargs):
        raise AssertionError("bundle mode must never make a real network call")

    monkeypatch.setattr("connectors.net_relay.relay_request", _relay_must_not_be_called)

    manifest = {"instructions": "Say hello from the bundle.", "compatibility": "chat"}
    files: dict[str, str] = {}
    content_hash = compute_content_hash(manifest["instructions"], files)
    hex_digest = content_hash.split(":", 1)[-1]
    skill_dir = tmp_path / "skills" / hex_digest
    skill_dir.mkdir(parents=True)
    (skill_dir / "content.json").write_text(json.dumps({"manifest": manifest, "files": files}), encoding="utf-8")
    (skill_dir / "meta.json").write_text(
        json.dumps({"namespace": "acme/bundle-item", "display_name": "Bundle Item", "description": "d", "license_spdx": "MIT", "attribution": "bundle"}),
        encoding="utf-8",
    )

    item_id, _ = items_service.upsert_legacy_pointer_item(
        namespace="acme/bundle-item", item_type="skill", category="general",
        display_name="Bundle Item", description="d",
        org_id="org-bundle-test", legacy_source="skills_pg", legacy_ref="bundle-test-1",
    )
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        item.scope = "central_index"
        item.catalog_pointer = {
            "source_kind": "github_repo", "source_url": "https://github.com/acme/bundle-item",
            "source_ref": "a" * 40, "source_path": "", "content_hash": content_hash,
            "license_spdx": "MIT", "license_evidence": "repo SPDX",
        }
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr("core.config.ECOSYSTEM_CATALOG_SOURCE_MODE", "bundle")
    monkeypatch.setattr("core.config.ECOSYSTEM_CATALOG_BUNDLE_PATH", str(tmp_path))

    version_id = materialize_from_catalog(item_id, requested_by="tester", org_id="org-bundle-test")
    assert version_id


def test_materialize_from_catalog_bundle_mode_fails_clearly_without_a_configured_path(monkeypatch):
    from services.ecosystem import items_service
    from services.ecosystem.catalog_sync import CatalogInstallNotSupportedError, materialize_from_catalog

    item_id, _ = items_service.upsert_legacy_pointer_item(
        namespace="acme/bundle-item-2", item_type="skill", category="general",
        display_name="Bundle Item 2", description="d",
        org_id="org-bundle-test-2", legacy_source="skills_pg", legacy_ref="bundle-test-2",
    )
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        item.scope = "central_index"
        item.catalog_pointer = {"source_kind": "github_repo", "source_url": "https://github.com/acme/x", "source_ref": "a" * 40, "content_hash": "sha256:" + "c" * 64}
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr("core.config.ECOSYSTEM_CATALOG_SOURCE_MODE", "bundle")
    monkeypatch.setattr("core.config.ECOSYSTEM_CATALOG_BUNDLE_PATH", "")

    with pytest.raises(CatalogInstallNotSupportedError, match="ECOSYSTEM_CATALOG_BUNDLE_PATH"):
        materialize_from_catalog(item_id, requested_by="tester", org_id="org-bundle-test-2")
