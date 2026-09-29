# SPDX-License-Identifier: MIT
# ============================================================
# Task 3a: admin Sources screen backend -- GET /ecosystem/admin/sources
# (catalog URL/last-sync status/well-known sites/org sources/GitHub
# credential status) plus the last-sync-status persistence sync_catalog()
# gained (services/ecosystem/catalog_sync.py's _persist_last_sync_status()/
# get_last_sync_status()) and the org sources list (list_org_sources()).
# A separate file (not added to test_ecosystem_router_http.py) so its own
# `client` fixture stays self-contained.
# ============================================================

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from routers.ecosystem_router import router as ecosystem_router
from services.ecosystem import catalog_sync
from services.ecosystem.catalog_crawler.signing import TrustedSigner
from services.ecosystem.catalog_sync import SyncReport, ShardSyncResult, _persist_last_sync_status
from services.ecosystem.items_service import get_or_create_local_source


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "admin-sources-test-user", "user_id": "admin-sources-test-user",
        "org_id": "admin-sources-test-org", "role": "admin",
    }
    return TestClient(app)


@pytest.fixture
def normal_user_client():
    app = FastAPI()
    app.include_router(ecosystem_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "admin-sources-test-normal", "user_id": "admin-sources-test-normal",
        "org_id": "admin-sources-test-org", "role": "developer",
    }
    return TestClient(app)


def test_admin_sources_endpoint_requires_admin_sources_permission(normal_user_client):
    resp = normal_user_client.get("/ainxt/v1/api/ecosystem/admin/sources")
    assert resp.status_code == 403


def test_admin_sources_endpoint_shape(client):
    resp = client.get("/ainxt/v1/api/ecosystem/admin/sources")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "catalog_url", "catalog_signer_configured", "last_sync", "well_known_sites",
        "sources_yaml_error", "org_sources", "github_credential_configured",
        "github_credential_hint", "live_sources_flag_enabled", "service_health",
    ):
        assert key in body, f"missing {key!r} in GET /ecosystem/admin/sources response: {body}"
    # docs/ecosystem/catalog/sources.yaml is real and checked in -- this
    # must parse cleanly, not fall back to the error path, on a real repo.
    assert body["sources_yaml_error"] is None
    assert isinstance(body["well_known_sites"], list)
    assert len(body["well_known_sites"]) > 0


def test_admin_sources_endpoint_reports_real_service_health_via_the_http_path(client):
    # Real incident, 2026-09-29: stale gateway/gate-worker/gate-sweeper
    # containers producing symptoms with nothing reporting "you're running
    # old code" anywhere. This proves the full path -- report_service_
    # startup() -> Redis -> GET /ecosystem/admin/sources -- not just the
    # service_health module in isolation (test_service_health.py already
    # covers that unit-level).
    from services.ecosystem.service_health import _KNOWN_SERVICES, _SERVICE_HEALTH_KV_PREFIX, report_service_startup
    from core.config import RDB_CACHE
    from core.kv import get_kv

    kv = get_kv(RDB_CACHE, decode_responses=True)
    for name in _KNOWN_SERVICES:
        kv.delete(f"{_SERVICE_HEALTH_KV_PREFIX}{name}")
    try:
        report_service_startup("gateway")

        resp = client.get("/ainxt/v1/api/ecosystem/admin/sources")
        assert resp.status_code == 200, resp.text
        health = resp.json()["service_health"]
        assert health["services"]["gateway"] is not None
        assert health["services"]["gateway"]["commit_mismatch"] is False
        assert health["services"]["gate_worker"] is None
        assert any("gate_worker" in w and "never reported" in w for w in health["warnings"])
    finally:
        for name in _KNOWN_SERVICES:
            kv.delete(f"{_SERVICE_HEALTH_KV_PREFIX}{name}")


def test_admin_sources_lists_the_callers_own_local_source():
    org_id = "admin-sources-test-org-local"
    source_id = get_or_create_local_source(org_id, created_by="test")
    rows = catalog_sync.list_org_sources(org_id)
    assert any(r["id"] == source_id and r["kind"] == "local" for r in rows)
    # Never leaks whether a credential is configured beyond a boolean.
    assert all("credential_ciphertext" not in r for r in rows)


def test_admin_sources_never_lists_another_orgs_local_source():
    org_a = "admin-sources-test-org-a"
    org_b = "admin-sources-test-org-b"
    get_or_create_local_source(org_a, created_by="test")
    rows_for_b = catalog_sync.list_org_sources(org_b)
    assert all(r["kind"] != "local" or r.get("id") is None for r in rows_for_b) or all(
        r["kind"] != "local" for r in rows_for_b
    )


def test_last_sync_status_is_none_before_any_sync_and_set_after():
    # Uses the real Redis-backed persistence -- skips cleanly if Redis is
    # unreachable in this environment (same convention as the rest of this
    # suite's Redis-backed tests, per root conftest.py).
    try:
        from core.config import RDB_CACHE
        from core.kv import get_kv
        get_kv(RDB_CACHE, decode_responses=True).ping()
    except Exception:
        pytest.skip("Redis unreachable in this environment")

    report = SyncReport(shards=[
        ShardSyncResult(shard="skill", fetched=True, verified=True, created=3, updated=1, yanked=0),
        ShardSyncResult(shard="mcp_server", fetched=False),
    ])
    _persist_last_sync_status(report)
    status = catalog_sync.get_last_sync_status()
    assert status is not None
    assert status["ok"] is True
    assert "synced_at" in status
    assert status["shards"][0]["created"] == 3


def test_sync_catalog_persists_status_even_on_a_verification_failure(monkeypatch):
    """A rejected/unsigned index must still be reported to the admin
    screen, not silently vanish -- sync_catalog() persists whatever
    report.to_dict() produces, error included."""
    try:
        from core.config import RDB_CACHE
        from core.kv import get_kv
        get_kv(RDB_CACHE, decode_responses=True).ping()
    except Exception:
        pytest.skip("Redis unreachable in this environment")

    def _fake_sync_one_shard(base_url, shard, trusted_signer):
        return ShardSyncResult(shard=shard, fetched=True, verified=False, error="signature verification failed -- rejecting: boom")

    monkeypatch.setattr(catalog_sync, "_sync_one_shard", _fake_sync_one_shard)
    signer = TrustedSigner(issuer="https://example.test", source_repository_uri="https://example.test/acme/repo")
    report = catalog_sync.sync_catalog("https://example.test/index", signer)
    assert report.ok is False

    status = catalog_sync.get_last_sync_status()
    assert status is not None
    assert status["ok"] is False
    assert "signature verification failed" in status["shards"][0]["error"]
