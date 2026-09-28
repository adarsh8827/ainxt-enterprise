# SPDX-License-Identifier: MIT
# ============================================================
# catalog_sync.py tests. No live network -- connectors.net_relay.
# relay_request is monkeypatched (same convention as
# tests/services/ecosystem/import_adapters/test_github_repo.py). One
# test uses the REAL, checked-in signed fixture
# (tests/services/ecosystem/catalog_crawler/fixtures/real_signed_
# mcp_server.json[.sigstore], pulled from the actual live
# ecosystem-index branch this session) to prove the real, unmocked
# sigstore verification path end to end; the rest monkeypatch
# verify_index_bytes() directly to exercise sync_catalog()'s own
# upsert/304/yank logic in isolation, deterministically.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemSource
from services.ecosystem import catalog_sync
from services.ecosystem.catalog_crawler.signing import TrustedSigner

_A_SIGNER = TrustedSigner(
    issuer="https://token.actions.githubusercontent.com",
    repository="adarsh8827/ainxt-enterprise",
    workflow_name="Ecosystem catalog crawl",
)
_BASE_URL = "https://raw.githubusercontent.com/adarsh8827/ainxt-enterprise/ecosystem-index/index"

_FIXTURES_DIR = Path(__file__).parent / "catalog_crawler" / "fixtures"
_REAL_MCP_DATA = (_FIXTURES_DIR / "real_signed_mcp_server.json").read_bytes()
_REAL_MCP_BUNDLE = (_FIXTURES_DIR / "real_signed_mcp_server.json.sigstore").read_bytes()

_SKILL_ROWS = [
    {
        "namespace": "acme/hello-skill", "item_type": "skill", "display_name": "Hello Skill",
        "description": "Says hello.", "category": "general", "tags": ["greeting"],
        "source": {"kind": "github_repo", "url": "https://github.com/acme/hello-skill", "ref": "a" * 40},
        "license": {"spdx": "MIT", "evidence": "repo SPDX"}, "compatibility": "chat",
        "content_hash": "sha256:" + "b" * 64, "attribution": "github_repo:acme/hello-skill@" + "a" * 40,
        "crawled_at": "2026-09-28T00:00:00+00:00",
    },
]


def _response(status_code: int, content: bytes = b"", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, content=content, headers=headers or {},
        request=httpx.Request("GET", "https://raw.githubusercontent.com/fixture"),
    )


class _FakeCache:
    """In-memory stand-in for fetch_cache.get_cached/put_cached -- avoids
    any dependency on real Redis state between tests."""
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, content):
        self.store[key] = content


@pytest.fixture(autouse=True)
def _fake_cache(monkeypatch):
    cache = _FakeCache()
    monkeypatch.setattr(catalog_sync, "get_cached", cache.get)
    monkeypatch.setattr(catalog_sync, "put_cached", cache.put)
    monkeypatch.setattr(catalog_sync, "assert_safe_https_url", lambda url: url)
    return cache


def _install_relay(monkeypatch, responses: dict[str, httpx.Response]):
    def _fake_relay(method, url, **kwargs):
        for key, resp in responses.items():
            if key in url:
                return resp
        raise AssertionError(f"no fixture response registered for {url!r}")
    monkeypatch.setattr(catalog_sync, "relay_request", _fake_relay)


def _skill_and_bundle_bytes(rows: list[dict]) -> bytes:
    return json.dumps(rows).encode("utf-8")


def test_sync_catalog_accepts_the_real_signed_fixture_end_to_end(monkeypatch):
    # No mocking of verify_index_bytes here -- this is the real,
    # unmocked sigstore verification path against real signed bytes.
    pytest.importorskip("sigstore")
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(404),
        "/skill.json": _response(404),
        "/mcp_server.json.sigstore": _response(200, _REAL_MCP_BUNDLE),
        "/mcp_server.json": _response(200, _REAL_MCP_DATA, {"ETag": '"mcp-etag-1"'}),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)

    skill_result = next(s for s in report.shards if s.shard == "skill")
    mcp_result = next(s for s in report.shards if s.shard == "mcp_server")
    assert skill_result.error is not None  # 404 on skill.json -- fetch failed, not a signing issue
    assert mcp_result.error is None
    assert mcp_result.verified is True
    assert mcp_result.created == 73  # real fixture row count

    db = SessionLocal()
    try:
        count = db.query(EcosystemItem).filter(EcosystemItem.item_type == "mcp_server").count()
        sample = db.query(EcosystemItem).filter(EcosystemItem.namespace == "ai.adeu/adeu").first()
    finally:
        db.close()
    assert count == 73
    assert sample is not None
    assert sample.scope == "central_index"
    assert sample.status == "coming_soon"  # mcp_server -- stored, not shown, per spec
    assert sample.catalog_pointer["source_kind"] == "mcp_registry"


def test_sync_catalog_rejects_an_unsigned_shard_and_upserts_nothing(monkeypatch):
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"not a real sigstore bundle"),
        "/skill.json": _response(200, _skill_and_bundle_bytes(_SKILL_ROWS), {"ETag": '"e1"'}),
        "/mcp_server.json.sigstore": _response(404),
        "/mcp_server.json": _response(404),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    skill_result = next(s for s in report.shards if s.shard == "skill")
    assert skill_result.error is not None
    assert "signature" in skill_result.error.lower()

    db = SessionLocal()
    try:
        count = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/hello-skill").count()
    finally:
        db.close()
    assert count == 0


def test_sync_catalog_skips_upsert_on_304(monkeypatch):
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)
    _install_relay(monkeypatch, {
        "/skill.json": _response(304),
        "/mcp_server.json": _response(304),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    assert all(not s.fetched and s.error is None for s in report.shards)

    db = SessionLocal()
    try:
        count = db.query(EcosystemItem).count()
    finally:
        db.close()
    assert count == 0


def test_sync_catalog_creates_a_central_index_skill_item(monkeypatch):
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes(_SKILL_ROWS), {"ETag": '"e1"'}),
        "/mcp_server.json.sigstore": _response(404),
        "/mcp_server.json": _response(404),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    skill_result = next(s for s in report.shards if s.shard == "skill")
    assert skill_result.error is None
    assert skill_result.created == 1

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/hello-skill").first()
        source = db.query(EcosystemSource).filter(EcosystemSource.id == item.source_id).first() if item else None
    finally:
        db.close()
    assert item is not None
    assert item.scope == "central_index"
    assert item.status == "active"  # skill -- shown by default, unlike mcp_server
    assert item.item_type == "skill"
    assert item.license == "MIT"
    assert item.catalog_pointer["source_ref"] == "a" * 40
    assert source is not None
    assert source.kind == "github_repo"


def test_sync_catalog_re_sync_updates_not_duplicates(monkeypatch):
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)

    def _responses(etag: str):
        return {
            "/skill.json.sigstore": _response(200, b"{}"),
            "/skill.json": _response(200, _skill_and_bundle_bytes(_SKILL_ROWS), {"ETag": f'"{etag}"'}),
            "/mcp_server.json.sigstore": _response(404),
            "/mcp_server.json": _response(404),
        }

    _install_relay(monkeypatch, _responses("e1"))
    catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)

    changed_rows = [dict(_SKILL_ROWS[0], description="Updated description.")]
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes(changed_rows), {"ETag": '"e2"'}),
        "/mcp_server.json.sigstore": _response(404),
        "/mcp_server.json": _response(404),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    skill_result = next(s for s in report.shards if s.shard == "skill")
    assert skill_result.created == 0
    assert skill_result.updated == 1

    db = SessionLocal()
    try:
        rows = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/hello-skill").all()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0].description == "Updated description."


def test_sync_catalog_yanks_rows_removed_from_a_re_fetched_shard(monkeypatch):
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)
    second_row = dict(_SKILL_ROWS[0], namespace="acme/second-skill", display_name="Second Skill")

    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes([_SKILL_ROWS[0], second_row]), {"ETag": '"e1"'}),
        "/mcp_server.json.sigstore": _response(404),
        "/mcp_server.json": _response(404),
    })
    catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)

    # Re-fetch with only the first row present -- the second must be yanked.
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes([_SKILL_ROWS[0]]), {"ETag": '"e2"'}),
        "/mcp_server.json.sigstore": _response(404),
        "/mcp_server.json": _response(404),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    skill_result = next(s for s in report.shards if s.shard == "skill")
    assert skill_result.yanked == 1

    db = SessionLocal()
    try:
        kept = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/hello-skill").first()
        removed = db.query(EcosystemItem).filter(EcosystemItem.namespace == "acme/second-skill").first()
    finally:
        db.close()
    assert kept.status == "active"
    assert removed.status == "yanked"


def test_list_items_excludes_coming_soon_by_default_but_includes_skill(monkeypatch):
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes(_SKILL_ROWS), {"ETag": '"e1"'}),
        "/mcp_server.json.sigstore": _response(200, b"{}"),
        "/mcp_server.json": _response(
            200,
            json.dumps([{
                "namespace": "ai.example/tool", "item_type": "mcp_server", "display_name": "Example Tool",
                "description": "An MCP server.", "category": "mcp", "tags": [],
                "source": {"kind": "mcp_registry", "url": "https://example.com", "ref": "ai.example/tool"},
                "license": {"spdx": "MIT", "evidence": "registry"}, "compatibility": "tool_dependent",
                "content_hash": "", "attribution": "", "crawled_at": "2026-09-28T00:00:00+00:00",
            }]).encode("utf-8"),
            {"ETag": '"e1"'},
        ),
    })
    catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)

    from services.ecosystem.items_service import list_items

    default_result = list_items(caller_org_id="default")
    namespaces = {row["namespace"] for row in default_result["items"]}
    assert "acme/hello-skill" in namespaces
    assert "ai.example/tool" not in namespaces

    explicit_result = list_items(caller_org_id="default", status=["coming_soon"])
    explicit_namespaces = {row["namespace"] for row in explicit_result["items"]}
    assert "ai.example/tool" in explicit_namespaces


# ── Install-from-catalog (materialize_from_catalog) ──────────────────────

def _seed_central_index_item(*, source_path: str = "", content_hash: str = "") -> str:
    db = SessionLocal()
    try:
        from services.ecosystem.items_service import get_or_create_import_source

        source_id = get_or_create_import_source(
            kind="github_repo", url="https://github.com/acme/hello-skill",
            created_by="catalog_sync", tos_notes="test",
        )
        item = EcosystemItem(
            namespace="acme/hello-skill", item_type="skill", category="general", tags=[],
            display_name="Hello Skill", description="Says hello.", source_id=source_id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT",
            status="active",
            catalog_pointer={
                "source_kind": "github_repo", "source_url": "https://github.com/acme/hello-skill",
                "source_ref": "a" * 40, "source_path": source_path, "content_hash": content_hash,
                "license_evidence": "repo SPDX", "compatibility": "chat",
            },
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


_IMPORTED_RESULT = {
    "manifest": {"name": "Hello Skill", "description": "Says hello.", "instructions": "Always greet the user warmly."},
    "files": {}, "license": "MIT", "display_name": "Hello Skill", "description": "Says hello.",
    "resolved_sha": "a" * 40, "source_url": "https://github.com/acme/hello-skill",
}


def test_materialize_from_catalog_installs_a_github_repo_pointer(monkeypatch):
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import github_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash)
    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="user-1", org_id="default")
    assert version_id

    db = SessionLocal()
    try:
        from db.models import EcosystemItemVersion
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
    finally:
        db.close()
    assert version is not None
    assert version.license == "MIT"


def test_materialize_from_catalog_rejects_content_drift(monkeypatch):
    from services.ecosystem.import_adapters import github_repo

    item_id = _seed_central_index_item(content_hash="sha256:" + "0" * 64)  # deliberately wrong
    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    with pytest.raises(catalog_sync.CatalogContentDriftError):
        catalog_sync.materialize_from_catalog(item_id, requested_by="user-1", org_id="default")


def test_materialize_from_catalog_rejects_mcp_registry_as_not_yet_supported():
    db = SessionLocal()
    try:
        from services.ecosystem.items_service import get_or_create_import_source

        source_id = get_or_create_import_source(
            kind="mcp_registry", url="https://example.com", created_by="catalog_sync", tos_notes="test",
        )
        item = EcosystemItem(
            namespace="ai.example/tool", item_type="mcp_server", category="mcp", tags=[],
            display_name="Example Tool", description="An MCP server.", source_id=source_id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT",
            status="coming_soon",
            catalog_pointer={"source_kind": "mcp_registry", "source_url": "https://example.com", "source_ref": "", "source_path": "", "content_hash": "", "license_evidence": "", "compatibility": "tool_dependent"},
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
    finally:
        db.close()

    with pytest.raises(catalog_sync.CatalogInstallNotSupportedError):
        catalog_sync.materialize_from_catalog(item_id, requested_by="user-1", org_id="default")


def test_sync_catalog_never_enqueues_a_gate_run(monkeypatch):
    # Catalog-checking round, 2026-09-28: real user report that the sync
    # worker was flooding the gate queue. Investigated for real: it's
    # structurally impossible today (EcosystemGateRun.version_id is NOT
    # NULL, and a sync-created item has no version until
    # materialize_from_catalog() runs at install time) -- the 170 failed
    # jobs actually found in the real gate queue were unrelated,
    # pre-existing noise from a separate .venv_m4_verify run days earlier.
    # This test hardens that guarantee explicitly rather than leaving it
    # merely "true by accident of the current code shape."
    enqueue_calls = []
    monkeypatch.setattr(
        "services.ecosystem.gate_service.enqueue_gate_run",
        lambda *a, **k: enqueue_calls.append((a, k)),
    )
    monkeypatch.setattr(
        "core.job_queue.enqueue_ecosystem_gate_job",
        lambda *a, **k: enqueue_calls.append((a, k)),
    )
    monkeypatch.setattr(catalog_sync, "verify_index_bytes", lambda *a, **k: None)
    _install_relay(monkeypatch, {
        "/skill.json.sigstore": _response(200, b"{}"),
        "/skill.json": _response(200, _skill_and_bundle_bytes(_SKILL_ROWS), {"ETag": '"e1"'}),
        "/mcp_server.json.sigstore": _response(200, b"{}"),
        "/mcp_server.json": _response(200, _skill_and_bundle_bytes([]), {"ETag": '"e2"'}),
    })
    report = catalog_sync.sync_catalog(_BASE_URL, _A_SIGNER)
    assert all(s.error is None for s in report.shards)
    assert enqueue_calls == []


def test_materialize_from_catalog_single_flight_second_caller_reuses_the_first_version(monkeypatch):
    # Catalog-checking round (2026-09-28): two concurrent Adds of the
    # same item must not fetch/gate the content twice. Simulates the
    # "someone else already holds the lock" branch directly (real thread
    # concurrency isn't necessary to prove the wait-then-reuse logic) by
    # pre-seeding the lock key, then creating the version the "other
    # caller" would have created, and confirming this call returns that
    # SAME version_id instead of raising or re-fetching.
    from unittest.mock import patch as _patch

    from core.config import RDB_CACHE
    from core.kv import get_kv
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash)

    kv = get_kv(RDB_CACHE, decode_responses=True)
    lock_key = f"ecosystem:gate:inflight:{item_id}"
    assert kv.set(lock_key, "other-caller", ex=30, nx=True) is True

    from services.ecosystem.import_adapters import github_repo
    from services.ecosystem.versions_service import create_version_for_content, encode_envelope

    payload = encode_envelope(_IMPORTED_RESULT["manifest"], _IMPORTED_RESULT["files"])
    already_created_version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=_IMPORTED_RESULT["manifest"], license="MIT", attribution="test",
    )

    with _patch.object(github_repo, "import_from_github") as mock_import:
        result_version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="user-2", org_id="default")
        mock_import.assert_not_called()

    assert result_version_id == already_created_version_id
    kv.delete(lock_key)
