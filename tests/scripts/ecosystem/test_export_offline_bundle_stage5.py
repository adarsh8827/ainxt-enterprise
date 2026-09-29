# SPDX-License-Identifier: MIT
# ============================================================
# Stage 5 (Connectors+Plugins phase) extension to
# scripts/ecosystem/export_offline_bundle.py: widened from item_type ==
# "skill" only to also cover connector/mcp_server/plugin, with a real
# test proving a real OAuth-token-shaped secret in ecosystem_secrets
# never leaks into the exported bundle bytes.
# ============================================================

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.ckms.key_service import KeyService
from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemItemVersion, EcosystemSource
from services.ecosystem.versions_service import encode_envelope
from store.ecosystem_object_storage import get_ecosystem_object_storage

ORG_A = f"org-export-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _test_key_service():
    """Same throwaway-DEK pattern as tests/store/test_ecosystem_secret_store.py
    -- KEY_CREDS has no active DEK outside the real CKMS boot sequence."""
    KeyService.reset_for_tests()
    KeyService.instance().install(cache={"KEY_CREDS": b"\x11" * 32}, mapping={})
    yield
    KeyService.reset_for_tests()


def _local_source() -> str:
    db = SessionLocal()
    try:
        source = db.query(EcosystemSource).filter(EcosystemSource.kind == "local").first()
        if not source:
            source = EcosystemSource(id=str(uuid.uuid4()), kind="local", org_id=None, created_by="test-fixture")
            db.add(source)
            db.commit()
        return source.id
    finally:
        db.close()


def _create_installed_item(item_type: str, manifest: dict) -> str:
    object_key = get_ecosystem_object_storage().put(encode_envelope(manifest, {}))
    db = SessionLocal()
    try:
        item = EcosystemItem(
            id=str(uuid.uuid4()), namespace=f"export-test/{item_type}-{uuid.uuid4().hex[:8]}",
            item_type=item_type, category="productivity", display_name="Export Test Item",
            description="d", source_id=_local_source(), org_id=ORG_A,
            license="MIT", status="active", scope="org_private",
        )
        db.add(item)
        db.flush()
        version = EcosystemItemVersion(
            id=str(uuid.uuid4()), item_id=item.id, version="1.0.0",
            content_hash=f"sha256:{uuid.uuid4().hex}", object_key=object_key,
            license="MIT", attribution="MIT License", manifest=manifest, gate_verdict="pass",
        )
        db.add(version)
        db.commit()
        return item.id
    finally:
        db.close()


def _cleanup_item(item_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).delete()
        db.query(EcosystemItem).filter(EcosystemItem.id == item_id).delete()
        db.commit()
    finally:
        db.close()


def test_connector_item_is_included_and_secret_never_leaks_into_the_bundle(tmp_path):
    from scripts.ecosystem.export_offline_bundle import export_bundle
    from store import ecosystem_secret_store as secret_store

    real_oauth_token_value = f"ghp_realsecrettoken{uuid.uuid4().hex}"
    secret_store.create_secret(
        org_id=ORG_A, kind="per_user", name="oauth_tokens:export-test/connector",
        value=real_oauth_token_value, user_id="user-export-test",
    )
    from db.database import SessionLocal as _SL
    from db.models import EcosystemSecret
    db = _SL()
    try:
        secret_row = db.query(EcosystemSecret).filter(EcosystemSecret.org_id == ORG_A).first()
        real_ciphertext = secret_row.ciphertext
    finally:
        db.close()
    assert real_oauth_token_value not in real_ciphertext  # sanity: it really is encrypted, not just stored plainly

    item_id = _create_installed_item("connector", {
        "name": "Export Test Connector", "description": "A connector for export testing.",
        "connector_url": "https://example.com/mcp", "oauth": {"provider": "example"},
        "tools": [{"name": "read_thing", "annotations": {"readOnlyHint": True}}],
    })
    try:
        counts = export_bundle(tmp_path, dry_run=False)
        assert counts["included_by_item_type"].get("connector", 0) >= 1

        all_bundle_bytes = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
        assert real_oauth_token_value.encode() not in all_bundle_bytes
        assert real_ciphertext.encode() not in all_bundle_bytes

        # The connector's own declared manifest (non-secret shape) SHOULD
        # be present somewhere in the export -- the whole point of this
        # phase's export widening, not just "nothing leaked".
        assert b"connector_url" in all_bundle_bytes or b"Export Test Connector" in all_bundle_bytes
    finally:
        _cleanup_item(item_id)


def test_mcp_server_and_plugin_items_are_also_included(tmp_path):
    from scripts.ecosystem.export_offline_bundle import export_bundle

    mcp_id = _create_installed_item("mcp_server", {"name": "Export Test MCP", "description": "d"})
    plugin_id = _create_installed_item("plugin", {"name": "Export Test Plugin", "description": "d", "parts": {"skills": []}})
    try:
        counts = export_bundle(tmp_path, dry_run=False)
        assert counts["included_by_item_type"].get("mcp_server", 0) >= 1
        assert counts["included_by_item_type"].get("plugin", 0) >= 1
    finally:
        _cleanup_item(mcp_id)
        _cleanup_item(plugin_id)


def test_meta_json_carries_the_real_item_type_not_always_skill(tmp_path):
    from scripts.ecosystem.export_offline_bundle import export_bundle

    item_id = _create_installed_item("connector", {"name": "Meta Check Connector", "description": "d"})
    try:
        export_bundle(tmp_path, dry_run=False)
        meta_files = list(tmp_path.rglob("meta.json"))
        matching = [
            json.loads(p.read_text(encoding="utf-8")) for p in meta_files
            if json.loads(p.read_text(encoding="utf-8")).get("display_name") == "Export Test Item" or True
        ]
        found = [m for m in matching if m.get("item_type") == "connector"]
        assert found, f"expected at least one meta.json with item_type=='connector', got: {matching[:3]}"
    finally:
        _cleanup_item(item_id)
