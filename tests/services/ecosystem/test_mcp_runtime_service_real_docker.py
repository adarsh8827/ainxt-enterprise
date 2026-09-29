# SPDX-License-Identifier: MIT
# ============================================================
# Stage 3 (Advanced: MCP servers) -- REAL Docker daemon test.
#
# Every other test for services/ecosystem/mcp_runtime_service.py
# (tests/services/ecosystem/test_mcp_runtime_service.py) mocks Docker
# entirely via the injectable docker_client_factory param -- proving the
# state-machine logic, never that a real container actually gets created,
# health-checked, and torn down. This file exercises start()/health_check()/
# stop() against a REAL container on the real Docker daemon reachable from
# this environment (the ainxt-gateway container has the Docker socket
# mounted -- `docker --version`/`docker images` both work inside it).
#
# Uses redis:7-alpine (already cached locally, confirmed via `docker
# images` before writing this file) via the "oci" package_kind path --
# its default CMD (`redis-server`) runs in the foreground indefinitely,
# giving the health-check step something real to observe as "running"
# rather than a container that exits immediately.
# ============================================================

from __future__ import annotations

import os
import uuid

import pytest

from db.database import SessionLocal
from db.models import EcosystemItem, EcosystemMcpRuntimeInstance

pytestmark = pytest.mark.docker

ORG = "mcp-runtime-real-docker-org"


def _make_instance() -> str:
    from db.models import EcosystemSource

    db = SessionLocal()
    try:
        source = db.query(EcosystemSource).filter(EcosystemSource.kind == "local").first()
        if not source:
            source = EcosystemSource(id=str(uuid.uuid4()), kind="local", org_id=None, created_by="test-fixture")
            db.add(source)
            db.commit()

        item = EcosystemItem(
            id=str(uuid.uuid4()), namespace=f"acme/mcp-runtime-real-{uuid.uuid4().hex[:8]}", item_type="mcp_server",
            category="productivity", display_name="Real Docker Runtime Test", description="d", license="MIT",
            org_id=ORG, created_by="user-a", source_id=source.id,
        )
        db.add(item)
        db.flush()
        instance = EcosystemMcpRuntimeInstance(
            id=str(uuid.uuid4()), org_id=ORG, item_id=item.id, package_kind="oci",
            package_ref="redis:7-alpine", pinned_version="7-alpine", status="stopped",
        )
        db.add(instance)
        db.commit()
        return instance.id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _enable_local_runtime(monkeypatch):
    # Scoped to this test file only -- not a global config change. Both the
    # module-level import inside start()/sweep() (`from core.config import
    # ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME`) read the live attribute each call,
    # so patching core.config's module attribute is sufficient.
    monkeypatch.setattr("core.config.ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME", True)


@pytest.fixture
def instance_id():
    iid = _make_instance()
    yield iid
    # Teardown: always attempt a real stop, even if the test failed
    # partway through, so no orphaned container is left on the host.
    from services.ecosystem import mcp_runtime_service as svc

    try:
        svc.stop(iid)
    except Exception:
        pass


def test_real_container_start_health_check_stop_lifecycle(instance_id):
    from services.ecosystem import mcp_runtime_service as svc

    client = svc._default_docker_client()

    # -- start(): real container must be created and running --
    result = svc.start(instance_id)
    assert result["status"] == "starting"
    container_id = result["container_id"]
    assert container_id

    container = client.containers.get(container_id)
    container.reload()
    print(f"\n[real-docker-test] created container id={container.id} status={container.status}")
    assert container.status in ("running", "created")

    # Give redis-server a moment to actually enter the running state if it
    # was still "created" the instant after client.containers.run() returned.
    import time
    for _ in range(20):
        container.reload()
        if container.status == "running":
            break
        time.sleep(0.5)
    assert container.status == "running", f"container never reached running state, ended at {container.status!r}"

    # -- resource-limit / no-priv-escalation posture on the REAL container --
    attrs = container.attrs
    host_config = attrs["HostConfig"]
    from sandbox.docker_executor import CPU_QUOTA, MEM_LIMIT

    print(f"[real-docker-test] HostConfig.Memory={host_config.get('Memory')} "
          f"CpuQuota={host_config.get('CpuQuota')} SecurityOpt={host_config.get('SecurityOpt')} "
          f"NetworkMode={attrs.get('NetworkSettings', {}).get('Networks')}")

    # MEM_LIMIT is Docker's own shorthand string (e.g. "512m"); the real
    # daemon reports the resolved byte count on the real container -- parse
    # the same way Docker itself does rather than comparing string to int.
    _units = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
    _mem_limit_bytes = int(MEM_LIMIT[:-1]) * _units[MEM_LIMIT[-1].lower()]
    assert host_config.get("Memory") == _mem_limit_bytes, "real container's real Memory limit must match sandbox/docker_executor.py's MEM_LIMIT"
    assert host_config.get("CpuQuota") == CPU_QUOTA, "real container's real CpuQuota must match sandbox/docker_executor.py's CPU_QUOTA"
    assert host_config.get("SecurityOpt") and "no-new-privileges" in host_config["SecurityOpt"][0], \
        "real container must genuinely carry the no-new-privileges security_opt, not just have it in the mock call args"
    assert attrs.get("NetworkSettings", {}).get("Networks") == {} or all(
        v.get("IPAddress") in ("", None) for v in attrs.get("NetworkSettings", {}).get("Networks", {}).values()
    ), "network_disabled=True must genuinely leave the real container with no assigned network IP"

    # -- health_check(): must observe the REAL running container as healthy --
    hc = svc.health_check(instance_id)
    assert hc["status"] == "running"

    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).first()
        assert row.status == "running"
        assert row.restart_count == 0
    finally:
        db.close()

    # -- stop(): the real container must actually be gone afterward --
    stop_result = svc.stop(instance_id)
    assert stop_result["status"] == "stopped"

    from docker.errors import NotFound
    with pytest.raises(NotFound):
        client.containers.get(container_id)
    print(f"[real-docker-test] confirmed container id={container_id} no longer exists after stop()")


def test_real_container_health_check_detects_a_manually_killed_container(instance_id):
    """health_check() must report unhealthy (not silently 'running') when the
    real container was removed out-of-band -- e.g. an operator `docker rm -f`,
    an OOM kill, or a crash -- not just when this service's own stop() ran."""
    from services.ecosystem import mcp_runtime_service as svc

    result = svc.start(instance_id)
    container_id = result["container_id"]
    client = svc._default_docker_client()

    container = client.containers.get(container_id)
    container.remove(force=True)  # simulate an out-of-band kill, bypassing stop()

    hc = svc.health_check(instance_id)
    assert hc["status"] == "unhealthy"
    assert "restart_backoff_seconds" in hc

    db = SessionLocal()
    try:
        row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).first()
        assert row.status == "unhealthy"
        assert row.restart_count == 1
        # Clear container_id so the fixture teardown's stop() doesn't try to
        # look up an already-removed container.
        row.container_id = None
        db.commit()
    finally:
        db.close()
