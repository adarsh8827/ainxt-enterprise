# SPDX-License-Identifier: MIT
# ============================================================
# Stage 3 (Advanced: MCP servers) backend tests --
# docs/ecosystem/CONNECTORS_PHASE_PLAN.md item 7.
#
# Covers: flag-off is a real no-op, health-check -> restart-backoff
# sequencing, idle shutdown, admin-only auth + cross-org isolation on the
# 3 new router endpoints, and the fork-safety constraint on the new
# --mcp-runtime worker flag. All Docker calls are mocked -- no real
# Docker daemon is required or assumed.
# ============================================================

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemMcpRuntimeInstance
from routers.ecosystem_connectors_router import router as connectors_router
from services.ecosystem import mcp_runtime_service as svc

ORG_A, ORG_B = "mcp-runtime-org-a", "mcp-runtime-org-b"


def _make_instance(org_id: str, package_kind: str = "npm", package_ref: str = "@acme/mcp-server", status: str = "stopped") -> str:
    from db.models import EcosystemSource

    db = SessionLocal()
    try:
        source = db.query(EcosystemSource).filter(EcosystemSource.kind == "local").first()
        if not source:
            source = EcosystemSource(id=str(uuid.uuid4()), kind="local", org_id=None, created_by="test-fixture")
            db.add(source)
            db.commit()

        item = EcosystemItem(
            id=str(uuid.uuid4()), namespace=f"acme/mcp-runtime-{uuid.uuid4().hex[:8]}", item_type="mcp_server",
            category="productivity", display_name="Runtime Test", description="d", license="MIT",
            org_id=org_id, created_by="user-a", source_id=source.id,
        )
        db.add(item)
        db.flush()
        instance = EcosystemMcpRuntimeInstance(
            id=str(uuid.uuid4()), org_id=org_id, item_id=item.id, package_kind=package_kind,
            package_ref=package_ref, pinned_version="1.0.0", status=status,
        )
        db.add(instance)
        db.commit()
        return instance.id
    finally:
        db.close()


# ── Flag-off is a real no-op ──────────────────────────────────────────────

def test_start_raises_when_flag_is_off():
    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", False):
        with pytest.raises(svc.McpRuntimeDisabledError):
            svc.start(_make_instance(ORG_A))


def test_sweep_is_a_real_zero_count_noop_when_flag_is_off():
    _make_instance(ORG_A, status="running")
    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", False):
        result = svc.sweep()
    assert result == {"checked": 0, "restarted": 0, "idle_stopped": 0}


# ── start() launches a container with the reused security posture ────────

def test_start_uses_docker_executors_resource_limits():
    instance_id = _make_instance(ORG_A, package_kind="npm", package_ref="@acme/mcp-server")
    fake_container = MagicMock(id="container-123")
    fake_client = MagicMock()
    fake_client.containers.run.return_value = fake_container

    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", True):
        result = svc.start(instance_id, docker_client_factory=lambda: fake_client)

    assert result == {"status": "starting", "container_id": "container-123"}
    _, kwargs = fake_client.containers.run.call_args
    from sandbox.docker_executor import CPU_QUOTA, MEM_LIMIT

    assert kwargs["mem_limit"] == MEM_LIMIT
    assert kwargs["cpu_quota"] == CPU_QUOTA
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["network_disabled"] is True
    assert kwargs["command"] == "npx -y @acme/mcp-server@1.0.0"


def test_start_rejects_unsupported_package_kind():
    instance_id = _make_instance(ORG_A, package_kind="npm", package_ref="x")

    # Force an unsupported kind straight in the DB (the CHECK constraint
    # only allows npm/pypi/oci, so simulate the "unsupported" branch by
    # monkeypatching the runner table instead of writing an invalid row).
    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", True), \
         patch.dict(svc._PACKAGE_RUNNERS, {}, clear=True):
        with pytest.raises(svc.McpRuntimeError):
            svc.start(instance_id, docker_client_factory=lambda: MagicMock())


# ── health_check(): restart-backoff sequencing ────────────────────────────

def test_health_check_marks_running_and_resets_restart_count():
    instance_id = _make_instance(ORG_A, status="running")
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        row.container_id = "container-abc"
        row.restart_count = 3
        db.commit()
    finally:
        db.close()

    fake_container = MagicMock(status="running")
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_container

    result = svc.health_check(instance_id, docker_client_factory=lambda: fake_client)
    assert result == {"status": "running"}

    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        assert row.status == "running"
        assert row.restart_count == 0
    finally:
        db.close()


def test_health_check_computes_exponential_backoff_on_repeated_failure():
    instance_id = _make_instance(ORG_A, status="running")
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        row.container_id = "container-dead"
        db.commit()
    finally:
        db.close()

    fake_client = MagicMock()
    fake_client.containers.get.side_effect = Exception("no such container")

    first = svc.health_check(instance_id, docker_client_factory=lambda: fake_client)
    assert first == {"status": "unhealthy", "restart_backoff_seconds": 10}

    second = svc.health_check(instance_id, docker_client_factory=lambda: fake_client)
    assert second == {"status": "unhealthy", "restart_backoff_seconds": 20}

    third = svc.health_check(instance_id, docker_client_factory=lambda: fake_client)
    assert third == {"status": "unhealthy", "restart_backoff_seconds": 40}


def test_sweep_restarts_an_unhealthy_instance():
    instance_id = _make_instance(ORG_A, status="running")
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        row.container_id = "container-dead"
        row.idle_since = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    fake_new_container = MagicMock(id="container-new")
    fake_client = MagicMock()
    fake_client.containers.get.side_effect = Exception("gone")
    fake_client.containers.run.return_value = fake_new_container

    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", True):
        result = svc.sweep(docker_client_factory=lambda: fake_client)

    assert result["checked"] == 1
    assert result["restarted"] == 1


# ── idle shutdown ──────────────────────────────────────────────────────────

def test_sweep_idle_stops_a_quiet_running_instance():
    instance_id = _make_instance(ORG_A, status="running")
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        row.container_id = "container-idle"
        row.idle_since = datetime.now(timezone.utc) - timedelta(seconds=svc.IDLE_SHUTDOWN_SECONDS + 1)
        db.commit()
    finally:
        db.close()

    fake_client = MagicMock()

    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", True):
        result = svc.sweep(docker_client_factory=lambda: fake_client)

    assert result["idle_stopped"] == 1
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        assert row.status == "stopped"
        assert row.container_id is None
    finally:
        db.close()


def test_mark_used_resets_the_idle_clock():
    instance_id = _make_instance(ORG_A, status="running")
    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        row.idle_since = datetime.now(timezone.utc) - timedelta(seconds=svc.IDLE_SHUTDOWN_SECONDS + 1)
        db.commit()
    finally:
        db.close()

    svc.mark_used(instance_id)

    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).one()
        idle_seconds = (datetime.now(timezone.utc) - row.idle_since).total_seconds()
        assert idle_seconds < 5
    finally:
        db.close()


# ── Router: admin-only auth + cross-org isolation ─────────────────────────

def _client(org_id: str, user_id: str = "u1", role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(connectors_router, prefix="/ainxt/v1/api")
    app.dependency_overrides[get_current_user] = lambda: {"sub": user_id, "user_id": user_id, "org_id": org_id, "role": role}
    return TestClient(app)


def test_list_mcp_runtime_requires_admin_permission():
    _make_instance(ORG_A)
    client = _client(ORG_A, role="developer")
    resp = client.get("/ainxt/v1/api/ecosystem/admin/mcp-runtime")
    assert resp.status_code == 403


def test_list_mcp_runtime_is_scoped_to_the_callers_org():
    instance_a = _make_instance(ORG_A)
    _make_instance(ORG_B)

    client_a = _client(ORG_A)
    resp_a = client_a.get("/ainxt/v1/api/ecosystem/admin/mcp-runtime")
    assert resp_a.status_code == 200
    ids_a = {i["id"] for i in resp_a.json()["instances"]}
    assert instance_a in ids_a

    client_b = _client(ORG_B)
    resp_b = client_b.get("/ainxt/v1/api/ecosystem/admin/mcp-runtime")
    assert instance_a not in {i["id"] for i in resp_b.json()["instances"]}


def test_mcp_runtime_logs_cross_org_returns_404():
    instance_a = _make_instance(ORG_A)
    client_b = _client(ORG_B)
    resp = client_b.get(f"/ainxt/v1/api/ecosystem/admin/mcp-runtime/{instance_a}/logs")
    assert resp.status_code == 404


def test_mcp_runtime_restart_cross_org_returns_404():
    instance_a = _make_instance(ORG_A)
    client_b = _client(ORG_B)
    resp = client_b.post(f"/ainxt/v1/api/ecosystem/admin/mcp-runtime/{instance_a}/restart")
    assert resp.status_code == 404


def test_mcp_runtime_restart_returns_422_when_flag_is_off():
    instance_a = _make_instance(ORG_A)
    client_a = _client(ORG_A)
    with patch("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", False):
        resp = client_a.post(f"/ainxt/v1/api/ecosystem/admin/mcp-runtime/{instance_a}/restart")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "MCP_RUNTIME_DISABLED"


# ── Fork-safety: --mcp-runtime never shares a process with --gate/--gate-sweeper ──

def test_mcp_runtime_worker_flag_is_its_own_dispatch_branch_not_combined_with_gate():
    import ast

    with open("workers/start_workers.py", "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)

    main_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    # Find the if/elif chain that dispatches on args.<flag> and confirm
    # args.mcp_runtime is its OWN elif branch (own `return` after calling
    # _run_mcp_runtime_loop), never combined into the same branch as
    # args.gate or args.gate_sweeper.
    dispatch_source = ast.get_source_segment(source, main_fn)
    assert "elif args.mcp_runtime:" in dispatch_source
    assert "_run_mcp_runtime_loop(stop_event)" in dispatch_source
    # The gate branch (queue_names = ECOSYSTEM_GATE_QUEUES_BY_PRIORITY) and
    # the gate-sweeper branch (_run_gate_sweeper_loop) must not appear in
    # the same elif block as the mcp-runtime one.
    mcp_branch_start = dispatch_source.index("elif args.mcp_runtime:")
    next_elif = dispatch_source.index("elif ", mcp_branch_start + 1)
    mcp_branch_body = dispatch_source[mcp_branch_start:next_elif]
    assert "_run_gate_sweeper_loop" not in mcp_branch_body
    assert "ECOSYSTEM_GATE_QUEUES_BY_PRIORITY" not in mcp_branch_body
