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

# Captured at collection time, before tests/services/ecosystem/conftest.py's
# autouse fixture ever runs and overwrites core.job_queue's module attribute
# with its inline-worker stub -- same technique as
# test_gate_queue_separation.py's own module-level capture. Needed by
# test_run_gate_synchronously_falls_back_to_async_on_timeout_without_double_executing
# to prove a REAL fallback enqueue happens, not the inline stub.
from core.job_queue import enqueue_ecosystem_gate_job as _REAL_ENQUEUE_ECOSYSTEM_GATE_JOB

_A_SIGNER = TrustedSigner(
    issuer="https://token.actions.githubusercontent.com",
    source_repository_uri="https://github.com/adarsh8827/ainxt-enterprise",
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

def _seed_central_index_item(*, source_path: str = "", content_hash: str = "", license_spdx: str = "") -> str:
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
                "license_spdx": license_spdx, "license_evidence": "repo SPDX", "compatibility": "chat",
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


def _seed_central_index_git_repo_item(*, content_hash: str = "", read_token_env: str = "") -> str:
    db = SessionLocal()
    try:
        from services.ecosystem.items_service import get_or_create_import_source

        source_id = get_or_create_import_source(
            kind="git_repo", url="https://gitlab.com/acme/hello-skill.git",
            created_by="catalog_sync", tos_notes="test",
        )
        item = EcosystemItem(
            namespace="acme/hello-skill-git", item_type="skill", category="general", tags=[],
            display_name="Hello Skill", description="Says hello.", source_id=source_id,
            scope="central_index", org_id=None, trust_tier="community", license="MIT",
            status="active",
            catalog_pointer={
                "source_kind": "git_repo", "source_url": "https://gitlab.com/acme/hello-skill.git",
                "source_ref": "a" * 40, "source_path": "", "content_hash": content_hash,
                "license_spdx": "MIT", "license_evidence": "repo LICENSE (fallback)", "compatibility": "chat",
                "read_token_env": read_token_env,
            },
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def test_materialize_from_catalog_installs_a_git_repo_pointer(monkeypatch):
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import git_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_git_repo_item(content_hash=correct_hash)
    monkeypatch.setattr(git_repo, "import_from_git", lambda url, ref=None, read_token_env=None: _IMPORTED_RESULT)

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


def test_materialize_from_catalog_passes_the_pointers_own_read_token_env_to_git_repo(monkeypatch):
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import git_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_git_repo_item(content_hash=correct_hash, read_token_env="SOME_GITLAB_TOKEN")

    seen_kwargs = {}

    def _fake_import(url, ref=None, read_token_env=None):
        seen_kwargs["read_token_env"] = read_token_env
        return _IMPORTED_RESULT

    monkeypatch.setattr(git_repo, "import_from_git", _fake_import)
    catalog_sync.materialize_from_catalog(item_id, requested_by="user-1", org_id="default")
    assert seen_kwargs["read_token_env"] == "SOME_GITLAB_TOKEN"


def test_materialize_from_catalog_uses_the_signed_license_not_a_fresh_re_derivation(monkeypatch):
    # Real gap found 2026-09-29: the drift check just above this proves
    # the fetched content byte-for-byte matches what the crawler already
    # verified and signed -- at that point, re-deriving the license from
    # scratch via the import adapter's own fresh SPDX/frontmatter check
    # is redundant work that could even disagree with the already-
    # verified, signed value. The pointer's own `license_spdx` (recorded
    # by the crawler, part of the signed index) must win -- proven here
    # by making it deliberately DIFFERENT from what the adapter's own
    # fresh re-derivation would return (_IMPORTED_RESULT["license"] ==
    # "MIT"), so a version.license == "MIT" result would prove the bug
    # is still there, not a coincidence.
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import github_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash, license_spdx="Apache-2.0")
    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="user-license-signed", org_id="default")

    db = SessionLocal()
    try:
        from db.models import EcosystemItemVersion
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
    finally:
        db.close()
    assert version.license == "Apache-2.0", (
        f"expected the signed pointer's license_spdx ('Apache-2.0'), got {version.license!r} -- "
        "materialize_from_catalog() re-derived the license from scratch instead of trusting the signed evidence"
    )


def test_materialize_from_catalog_falls_back_to_a_fresh_derivation_when_the_pointer_has_no_signed_license(monkeypatch):
    # The other half: a pointer with no license_spdx recorded at all
    # (should not happen for a real crawled entry, but never silently
    # install with an empty license string) still gets a real value from
    # the adapter's own fresh check.
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import github_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash, license_spdx="")
    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="user-license-fallback", org_id="default")

    db = SessionLocal()
    try:
        from db.models import EcosystemItemVersion
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
    finally:
        db.close()
    assert version.license == "MIT"


def test_materialize_from_catalog_instructions_only_resolves_synchronously_and_installs(monkeypatch):
    # Section 3's headline deliverable: "instructions-only catalog skills
    # should go Add -> Active in about a second." No scripts/dependencies
    # in _IMPORTED_RESULT["files"] (empty {}) -- this must take the
    # synchronous fast path (gate_service.run_gate_synchronously()), not
    # the async enqueue, and by the time materialize_from_catalog()
    # returns the gate run must already be resolved AND the caller
    # auto-installed -- no polling required.
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import github_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash)
    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="sync-fast-user", org_id="default")

    from db.models import EcosystemGateRun, EcosystemInstall

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.version_id == version_id).one()
        install = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.installed_by == "sync-fast-user",
        ).first()
    finally:
        db.close()

    assert run.verdict in ("pass", "warn")
    assert run.finished_at is not None
    assert install is not None, "auto-install must have already happened by the time materialize_from_catalog() returns"


def test_run_gate_synchronously_real_timing_for_an_instructions_only_item():
    # Real timing, not estimated -- the actual claim being verified is
    # "about a second" (the spec's own words), measured over several
    # runs for a real p50/p95, against the real DB/object storage (no
    # network -- github_repo is not involved here, this measures the
    # gate pipeline itself, which is the part the 3s budget covers).
    import statistics
    import time

    from services.ecosystem.gate_service import run_gate_synchronously
    from services.ecosystem.versions_service import create_version_for_content, encode_envelope

    durations_ms = []
    for i in range(10):
        # A genuine central_index (signed catalog) item with a
        # catalog_pointer -- NOT a legacy/non-catalog item -- since only
        # this shape actually gets the redundant static_safety re-scan
        # AND (under the default ethics_review_policy) the ethics stage
        # skipped; a legacy item legitimately still runs ethics under
        # that same default ("non-catalog source"), which would make this
        # timing measurement not representative of what the spec actually
        # asks for ("instructions-only CATALOG skills").
        manifest = {"name": "Sync Timing Test", "description": "d", "instructions": f"Say hello {i}."}
        from services.ecosystem.items_service import get_or_create_import_source

        source_id = get_or_create_import_source(
            kind="github_repo", url=f"https://github.com/acme/sync-timing-{i}",
            created_by="catalog_sync", tos_notes="test",
        )
        db = SessionLocal()
        try:
            item = EcosystemItem(
                namespace=f"acme/sync-timing-{i}", item_type="skill", category="general", tags=[],
                display_name="Sync Timing Test", description="d", source_id=source_id,
                scope="central_index", org_id=None, trust_tier="community", license="MIT", status="active",
                catalog_pointer={
                    "source_kind": "github_repo", "source_url": f"https://github.com/acme/sync-timing-{i}",
                    "source_ref": "a" * 40, "source_path": "", "content_hash": "irrelevant-not-compared-anymore",
                    "license_evidence": "repo SPDX", "compatibility": "chat",
                },
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            item_id = item.id
        finally:
            db.close()

        payload = encode_envelope(manifest, {})
        version_id = create_version_for_content(item_id=item_id, content=payload, manifest=manifest, license="MIT")

        t0 = time.monotonic()
        result = run_gate_synchronously(
            version_id, trigger="ui_add", timeout_seconds=3.0,
            installed_by=f"timing-user-{i}", installed_for=f"timing-user-{i}", org_id="default",
        )
        durations_ms.append((time.monotonic() - t0) * 1000)
        assert result["timed_out"] is False
        assert result["verdict"] in ("pass", "warn"), f"run {i}: {result}"

    durations_ms.sort()
    p50 = statistics.median(durations_ms)
    p95 = durations_ms[int(len(durations_ms) * 0.95) if int(len(durations_ms) * 0.95) < len(durations_ms) else -1]
    print(f"\nrun_gate_synchronously real timing over {len(durations_ms)} runs: p50={p50:.1f}ms p95={p95:.1f}ms all={[round(d) for d in durations_ms]}")
    assert p95 < 3000, f"p95={p95:.1f}ms exceeded the 3s budget this path exists to stay under"


def test_run_gate_synchronously_falls_back_to_async_on_timeout_without_double_executing(monkeypatch):
    # Forces the stage pipeline to exceed the (tiny, test-only) timeout,
    # confirms the fallback enqueue happens, and -- the real point of the
    # mutual-exclusion lock in run_gate() -- confirms the stages are only
    # ever actually EXECUTED once even though both the original thread and
    # the fallback path attempt to run them.
    import time
    from unittest.mock import patch as _patch

    from services.ecosystem import gate_service
    from services.ecosystem.items_service import upsert_legacy_pointer_item
    from services.ecosystem.versions_service import create_or_refresh_legacy_version

    # This is a non-catalog (legacy) item, so under the default
    # ethics_review_policy the ethics stage genuinely runs -- mock it for
    # determinism and to avoid a real, billed LLM call, same convention
    # test_gate_service_orchestrator.py's own _mock_ethics_pass() uses.
    monkeypatch.setattr(
        "models.model_router.model_router.generate",
        lambda *a, **k: '{"verdict": "pass", "reason": "fine"}',
    )

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/sync-timeout-fallback", item_type="skill", category="general",
        display_name="Sync Timeout Fallback", description="d",
        org_id="org-sync-timeout", legacy_source="skills_pg", legacy_ref="sync-timeout-fallback",
    )
    version_id, _ = create_or_refresh_legacy_version(
        item_id=item_id, content_text="c", manifest={"name": "Sync Timeout Fallback", "description": "d"},
    )

    call_count = {"n": 0}
    real_manifest_run = gate_service.manifest_stage.run

    def _slow_manifest_run(*a, **k):
        call_count["n"] += 1
        time.sleep(0.3)  # exceeds the 0.05s test timeout below
        return real_manifest_run(*a, **k)

    monkeypatch.setattr(gate_service.manifest_stage, "run", _slow_manifest_run)

    # Undo the package's inline-worker stub for this one call so the
    # fallback enqueue is real (goes to the real Redis queue), matching
    # test_gate_queue_separation.py's own technique.
    import core.job_queue as _job_queue

    monkeypatch.setattr(_job_queue, "enqueue_ecosystem_gate_job", _REAL_ENQUEUE_ECOSYSTEM_GATE_JOB)

    result = gate_service.run_gate_synchronously(
        version_id, trigger="ui_add", timeout_seconds=0.05,
        installed_by="timeout-user", installed_for="timeout-user", org_id="org-sync-timeout",
    )
    assert result["timed_out"] is True

    gate_run_id = result["gate_run_id"]
    job_id = _job_queue.ecosystem_gate_job_id(gate_run_id)
    job = _job_queue.get_queue(_job_queue.Q_ECOSYSTEM_GATE_HIGH).fetch_job(job_id)
    assert job is not None, "timeout must enqueue a real fallback job on the high-priority lane"

    # The real point of the mutex: the original background thread is
    # almost certainly STILL inside its 0.3s sleep right now (the sync
    # attempt only waited 0.05s before giving up) -- simulate the
    # fallback job's real worker calling run_gate() for the SAME
    # gate_run_id in this exact window. It must see the lock already
    # held and no-op immediately, not race the still-running thread.
    # Either outcome proves "no double execution," just via a different
    # branch depending on exact timing: "pending" means this call hit the
    # still-held lock and no-op'd; a real resolved verdict means the
    # original thread's 0.3s sleep already finished by the time this
    # call reached the idempotency short-circuit at the top of
    # run_gate(). Either way, call_count["n"] below is the real invariant.
    fallback_result = gate_service.run_gate(gate_run_id, installed_by="timeout-user", installed_for="timeout-user", org_id="org-sync-timeout")
    assert fallback_result["verdict"] in ("pending", "pass", "warn", "fail")

    # Let the original (still-running) background thread actually finish.
    time.sleep(1.0)

    from db.database import SessionLocal as _SL
    from db.models import EcosystemGateRun as _GR

    db = _SL()
    try:
        run = db.query(_GR := _GR).filter(_GR.id == gate_run_id).one()
    finally:
        db.close()
    assert run.finished_at is not None
    assert call_count["n"] == 1, "manifest stage must only ever actually execute once, not once per (thread, fallback job)"


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


# ── Pre-check dispatcher (section 4) -- never blocks a real user's Add ──────

def test_precheck_backs_off_immediately_when_item_already_in_flight():
    # The literal guarantee section 4 asks for: a pre-check must never be
    # the one making anyone wait. caller_priority="low" backs off with
    # ZERO wait (not even one poll iteration) the moment the lock is held.
    from core.config import RDB_CACHE
    from core.kv import get_kv
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash)

    kv = get_kv(RDB_CACHE, decode_responses=True)
    lock_key = f"ecosystem:gate:inflight:{item_id}"
    assert kv.set(lock_key, "real-user", ex=30, nx=True) is True

    import time

    t0 = time.monotonic()
    with pytest.raises(catalog_sync._PrecheckSkippedError):
        catalog_sync.materialize_from_catalog(item_id, requested_by="system:precheck", org_id="default", caller_priority="low")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05, f"pre-check must back off with zero wait, took {elapsed*1000:.1f}ms"

    kv.delete(lock_key)


def test_a_real_users_add_proceeds_promptly_even_while_a_precheck_is_mid_flight():
    # The concurrency proof the coordinator explicitly asked for: a
    # pre-check genuinely holding the lock (simulating it being mid-fetch)
    # must not make a real user's own Add for the SAME item wait the old
    # ~6s -- it's bounded to ~0.5s, and by the time that bound is hit the
    # pre-check's own version is very likely already there to reuse (the
    # common case), or the caller gets a clear, fast error to retry
    # rather than hanging.
    import threading
    import time

    from core.config import RDB_CACHE
    from core.kv import get_kv
    from services.ecosystem.catalog_crawler.pointer_schema import compute_content_hash
    from services.ecosystem.import_adapters import github_repo

    correct_hash = compute_content_hash(_IMPORTED_RESULT["manifest"]["instructions"], _IMPORTED_RESULT["files"])
    item_id = _seed_central_index_item(content_hash=correct_hash)

    kv = get_kv(RDB_CACHE, decode_responses=True)
    lock_key = f"ecosystem:gate:inflight:{item_id}"
    assert kv.set(lock_key, "precheck", ex=30, nx=True) is True  # simulates the pre-check holding it

    real_import = github_repo.import_from_github
    release_after = 0.2

    def _release_lock_after_delay():
        time.sleep(release_after)  # simulates the pre-check's own fetch finishing
        from services.ecosystem.versions_service import create_version_for_content, encode_envelope

        payload = encode_envelope(_IMPORTED_RESULT["manifest"], _IMPORTED_RESULT["files"])
        create_version_for_content(
            item_id=item_id, content=payload, manifest=_IMPORTED_RESULT["manifest"], license="MIT", attribution="precheck",
        )
        kv.delete(lock_key)

    releaser = threading.Thread(target=_release_lock_after_delay)
    releaser.start()

    t0 = time.monotonic()
    version_id = catalog_sync.materialize_from_catalog(item_id, requested_by="real-user", org_id="default", caller_priority="high")
    elapsed = time.monotonic() - t0

    releaser.join()
    assert version_id, "the real user's Add must succeed (reusing the pre-check's own version once it appears)"
    assert elapsed < 1.0, f"a real user's Add must never wait anywhere close to the old ~6s bound, took {elapsed:.2f}s"


def test_precheck_batch_respects_the_per_org_hourly_cap(monkeypatch):
    import uuid

    from core.config import RDB_CACHE
    from core.kv import get_kv
    from services.ecosystem.policy_service import set_policy

    # A fresh, unique org_id per test run -- the per-hour cap counter
    # lives in Redis (not Postgres), which _clean_ecosystem_tables'
    # autouse truncate does NOT reach; a fixed org_id here would leak
    # its counter across repeated runs within the same real hour (a
    # real test-isolation bug found live: this test passed alone, then
    # failed on a full-suite re-run because the earlier run's counter
    # was still sitting in Redis).
    org_id = f"org-precheck-cap-{uuid.uuid4().hex[:8]}"
    set_policy(org_id, gate_precheck_enabled=True, updated_by="test")

    db = SessionLocal()
    try:
        from db.models import EcosystemOrgPolicy

        row = db.query(EcosystemOrgPolicy).filter(EcosystemOrgPolicy.org_id == org_id).one()
        row.gate_precheck_cap_per_hour = 2
        db.commit()
    finally:
        db.close()

    # 5 eligible, featured, versionless central_index items -- only 2 (the cap) may be attempted.
    suffix = uuid.uuid4().hex[:8]
    for i in range(5):
        db = SessionLocal()
        try:
            from services.ecosystem.items_service import get_or_create_import_source

            source_id = get_or_create_import_source(
                kind="github_repo", url=f"https://github.com/acme/precheck-{suffix}-{i}", created_by="test", tos_notes="test",
            )
            db.add(EcosystemItem(
                namespace=f"acme/precheck-{suffix}-{i}", item_type="skill", category="general", tags=[],
                display_name="Precheck Candidate", description="d", source_id=source_id,
                scope="central_index", org_id=None, trust_tier="community", license="MIT",
                status="active", is_featured=True,
                catalog_pointer={
                    "source_kind": "github_repo", "source_url": f"https://github.com/acme/precheck-{suffix}-{i}",
                    "source_ref": "a" * 40, "source_path": "", "content_hash": "",  # empty -- drift check is a no-op
                    "license_evidence": "repo SPDX", "compatibility": "chat",
                },
            ))
            db.commit()
        finally:
            db.close()

    from services.ecosystem.import_adapters import github_repo

    monkeypatch.setattr(github_repo, "import_from_github", lambda repo, ref=None: _IMPORTED_RESULT)

    try:
        result = catalog_sync.run_precheck_batch()
        assert result["org_results"][org_id]["attempted"] == 2
        assert result["items_attempted"] == 2

        # Cap is exhausted for this hour -- a second batch this same hour attempts nothing more.
        result2 = catalog_sync.run_precheck_batch()
        assert result2["org_results"][org_id]["attempted"] == 0
    finally:
        # Clean up this test's own Redis counter so it can never leak
        # into a LATER test run within the same real hour either.
        from datetime import datetime, timezone

        kv = get_kv(RDB_CACHE, decode_responses=True)
        hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        kv.delete(f"ecosystem:gate:precheck:count:{org_id}:{hour_bucket}")
