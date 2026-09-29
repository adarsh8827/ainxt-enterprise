# SPDX-License-Identifier: MIT
# ============================================================
# LOCAL/STDIO MCP SERVER RUNTIME (docs/ecosystem/CONNECTORS_PHASE_PLAN.md
# §1 item 7, Stage 3).
#
# Long-running-container analogue of sandbox/docker_executor.py's one-shot
# DockerExecutor. Reuses that file's exact resource-limit/no-privilege-
# escalation security posture (MEM_LIMIT, CPU_QUOTA, security_opt) --
# it does NOT reinvent container security -- but adds a genuinely new
# lifecycle layer docker_executor.py never needed: health-check polling,
# exponential-backoff restart, and idle shutdown, because a managed MCP
# server stays up between calls instead of running once and exiting.
#
# Flag-gated: ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME (core/config.py). With the
# flag off, start()/sweep() are real no-ops (raise / return zero counts) --
# never a silent "pretend it worked" path.
#
# Runs from its own dedicated worker process (workers/start_workers.py
# --mcp-runtime), never combined with --gate/--gate-sweeper -- see that
# file's _run_gate_sweeper_loop() docstring for the real fork+lock
# deadlock incident (2026-09-28) this constraint exists to avoid.
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.logger import logger

IDLE_SHUTDOWN_SECONDS = 30 * 60          # stop a quiet-since running container after 30 min
HEALTH_CHECK_INTERVAL_SECONDS = 60       # the --mcp-runtime loop's own tick interval
MAX_RESTART_BACKOFF_SECONDS = 15 * 60
_BASE_BACKOFF_SECONDS = 10

# package_kind -> how to run it. "oci" has no template: package_ref IS the
# image, run its own entrypoint/cmd unmodified.
_PACKAGE_RUNNERS: dict[str, dict[str, Optional[str]]] = {
    "npm":  {"image": "node:20-alpine",   "command_tpl": "npx -y {package_ref}@{pinned_version}"},
    "pypi": {"image": "python:3.11-slim", "command_tpl": "pip install --no-input {package_ref}=={pinned_version} && python -m {package_ref}"},
    "oci":  {"image": None, "command_tpl": None},
}


class McpRuntimeDisabledError(RuntimeError):
    """Raised by start()/stop()/health_check() when
    ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME is off -- callers must not treat this
    as a transient failure to retry."""


class McpRuntimeError(RuntimeError):
    pass


def _default_docker_client():
    import docker
    from docker.errors import DockerException

    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise McpRuntimeError(f"Docker unavailable: {exc}") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_instance(db, instance_id: str):
    from db.models import EcosystemMcpRuntimeInstance

    row = db.query(EcosystemMcpRuntimeInstance).filter(EcosystemMcpRuntimeInstance.id == instance_id).first()
    if not row:
        raise McpRuntimeError(f"no such mcp runtime instance {instance_id!r}")
    return row


def _require_enabled() -> None:
    from core.config import ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME

    if not ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME:
        raise McpRuntimeDisabledError("ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME is off")


def start(instance_id: str, *, docker_client_factory: Callable[[], Any] = _default_docker_client) -> dict:
    _require_enabled()

    from db.database import SessionLocal

    db = SessionLocal()
    try:
        row = _get_instance(db, instance_id)
        runner = _PACKAGE_RUNNERS.get(row.package_kind)
        if runner is None:
            raise McpRuntimeError(f"unsupported package_kind {row.package_kind!r}")

        image = runner["image"] or row.package_ref
        command = (
            runner["command_tpl"].format(package_ref=row.package_ref, pinned_version=row.pinned_version)
            if runner["command_tpl"] else None
        )

        client = docker_client_factory()
        from sandbox.docker_executor import CPU_QUOTA, MEM_LIMIT

        run_kwargs: dict[str, Any] = dict(
            image=image,
            detach=True,
            mem_limit=MEM_LIMIT,
            cpu_quota=CPU_QUOTA,
            network_disabled=True,
            security_opt=["no-new-privileges"],
            read_only=False,
        )
        if command:
            run_kwargs["command"] = command
        container = client.containers.run(**run_kwargs)

        row.status = "starting"
        row.container_id = container.id
        row.last_health_check_at = _now()
        row.idle_since = _now()
        db.commit()
        return {"status": row.status, "container_id": row.container_id}
    finally:
        db.close()


def stop(instance_id: str, *, docker_client_factory: Callable[[], Any] = _default_docker_client) -> dict:
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        row = _get_instance(db, instance_id)
        if row.container_id:
            try:
                client = docker_client_factory()
                container = client.containers.get(row.container_id)
                container.stop(timeout=10)
                container.remove(force=True)
            except Exception as exc:
                # Best-effort cleanup -- same convention as
                # sandbox/docker_executor.py's own _cleanup_container().
                logger.warning(f"mcp_runtime_service.stop({instance_id}): container cleanup failed (non-fatal): {exc}")
        row.status = "stopped"
        row.container_id = None
        row.idle_since = None
        db.commit()
        return {"status": "stopped"}
    finally:
        db.close()


def health_check(instance_id: str, *, docker_client_factory: Callable[[], Any] = _default_docker_client) -> dict:
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        row = _get_instance(db, instance_id)
        if not row.container_id:
            return {"status": row.status}

        try:
            client = docker_client_factory()
            container = client.containers.get(row.container_id)
            container.reload()
            is_running = container.status == "running"
        except Exception:
            is_running = False

        if is_running:
            row.status = "running"
            row.last_health_check_at = _now()
            row.restart_count = 0
            db.commit()
            return {"status": "running"}

        row.status = "unhealthy"
        backoff = min(_BASE_BACKOFF_SECONDS * (2 ** row.restart_count), MAX_RESTART_BACKOFF_SECONDS)
        row.restart_count += 1
        db.commit()
        # The sweep loop -- not this function -- is responsible for actually
        # waiting `backoff` seconds before calling start() again; health_check()
        # only ever reports state, it never sleeps.
        return {"status": "unhealthy", "restart_backoff_seconds": backoff}
    finally:
        db.close()


def mark_used(instance_id: str) -> None:
    """Reset the idle clock. Called by whatever invokes a tool against this
    running server -- NOT wired into any chat/tool-call path yet in this
    pass (that integration is a separate, not-yet-built piece); calling
    this is how a future caller keeps a busy server from being idle-shut-
    down under it."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        row = _get_instance(db, instance_id)
        row.idle_since = _now()
        db.commit()
    finally:
        db.close()


def get_status(instance_id: str) -> dict:
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        row = _get_instance(db, instance_id)
        return {
            "id": str(row.id),
            "status": row.status,
            "container_id": row.container_id,
            "last_health_check_at": row.last_health_check_at.isoformat() if row.last_health_check_at else None,
            "restart_count": row.restart_count,
        }
    finally:
        db.close()


def sweep(*, docker_client_factory: Callable[[], Any] = _default_docker_client) -> dict:
    """One tick of the --mcp-runtime worker's polling loop: health-check
    every starting/running/unhealthy instance, restart an unhealthy one
    (backoff is advisory -- health_check() reports it, this loop's own
    tick interval is the real pacing since restart_count only increases
    on a genuine failed check), and idle-shut-down anything quiet past
    IDLE_SHUTDOWN_SECONDS. Real counts, never fabricated. A real no-op
    (zero counts) when the flag is off."""
    from core.config import ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME

    if not ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME:
        return {"checked": 0, "restarted": 0, "idle_stopped": 0}

    from db.database import SessionLocal
    from db.models import EcosystemMcpRuntimeInstance

    db = SessionLocal()
    try:
        rows = (
            db.query(EcosystemMcpRuntimeInstance)
            .filter(EcosystemMcpRuntimeInstance.status.in_(("starting", "running", "unhealthy")))
            .all()
        )
        instances = [(str(r.id), r.status, r.idle_since) for r in rows]
    finally:
        db.close()

    checked = 0
    restarted = 0
    idle_stopped = 0
    now = _now()
    for instance_id, status, idle_since in instances:
        checked += 1
        if status == "running" and idle_since is not None:
            idle_seconds = (now - idle_since).total_seconds()
            if idle_seconds > IDLE_SHUTDOWN_SECONDS:
                try:
                    stop(instance_id, docker_client_factory=docker_client_factory)
                    idle_stopped += 1
                    continue
                except Exception as exc:
                    logger.error(f"mcp_runtime sweep: idle-stop of {instance_id} failed: {exc}")

        try:
            result = health_check(instance_id, docker_client_factory=docker_client_factory)
        except Exception as exc:
            logger.error(f"mcp_runtime sweep: health_check of {instance_id} failed: {exc}")
            continue

        if result["status"] == "unhealthy":
            try:
                start(instance_id, docker_client_factory=docker_client_factory)
                restarted += 1
            except Exception as exc:
                logger.error(f"mcp_runtime sweep: restart of {instance_id} failed: {exc}")

    return {"checked": checked, "restarted": restarted, "idle_stopped": idle_stopped}
