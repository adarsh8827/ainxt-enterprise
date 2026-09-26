# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM MARKETPLACE GATE WORKER
#
# RQ job: run the ecosystem gate's 7 stages (manifest, license, static
# safety, supply chain, sandbox, ethics, mcp_connector) for one gate run,
# via services/ecosystem/gate_service.py's run_gate().
#
# Deployment note (docs/ecosystem/design/LLD/gate.md): this is the ONLY
# process that should ever be granted Docker socket access for the gate's
# sandbox stage. docker-compose.yml's gate-worker service sets
# ECOSYSTEM_GATE_SANDBOX_ALLOWED=true and mounts /var/run/docker.sock; no
# other service does. sandbox/ecosystem_gate_executor.py refuses to touch
# Docker in any process where that env var isn't set — this worker module
# does not set it itself (that would defeat the guard for any process that
# happens to import this module), it only relies on the container having it.
# ============================================================

from __future__ import annotations

from typing import Any

from core.logger import logger


def run_ecosystem_gate_job(payload: dict) -> dict[str, Any]:
    """
    RQ entry point. payload keys (see core/job_queue.py's
    enqueue_ecosystem_gate_job):
      gate_run_id      str            required
      installed_by     str | None
      installed_for    str | None
      org_id           str | None
      surfaces         list[str]
      provision_scope  str | None
    """
    from services.ecosystem.gate_service import run_gate

    gate_run_id = payload["gate_run_id"]
    logger.info(f"[EcosystemGate] starting gate_run_id={gate_run_id}")

    result = run_gate(
        gate_run_id,
        installed_by=payload.get("installed_by"),
        installed_for=payload.get("installed_for"),
        org_id=payload.get("org_id"),
        surfaces=payload.get("surfaces") or [],
        provision_scope=payload.get("provision_scope"),
    )

    logger.info(
        f"[EcosystemGate] finished gate_run_id={gate_run_id} "
        f"verdict={result.get('verdict')}"
    )
    return result
