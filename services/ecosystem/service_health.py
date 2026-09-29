# SPDX-License-Identifier: MIT
# ============================================================
# Real incident, 2026-09-29: three separate "stale process serving old
# code" bugs surfaced as false live bugs in the same session --
# `ainxt-gateway` serving a mismatched pair of files mid-merge, the
# `ainxt-gate-worker` container (up 27 hours) still only consuming the
# single legacy `ecosystem_gate_queue` while every real Add had moved to
# the new `_high`/`_low` priority lanes weeks... hours earlier, and a
# leftover `ai-ui` dev server pointed at a stale worktree. Each was only
# found by manually inspecting `docker top`/logs/queue depths -- nothing
# reported "you're running old code" on its own.
#
# This module gives every ecosystem-related process a way to say, at its
# own startup: "I am running commit X, I started at time Y" -- written
# to Redis (the one channel every process here can reach without cross-
# container introspection, same convention as catalog_sync.py's own
# _persist_last_sync_status()) -- and a single read that surfaces every
# reporting service's own state plus real, computed warnings (a commit
# that doesn't match the gateway's own, or a gate worker that didn't
# register all three priority-lane queue names) for the admin Sources
# screen to render directly, rather than a human having to go looking
# for the same symptoms by hand again next time.
# ============================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SERVICE_HEALTH_KV_PREFIX = "ecosystem:service_health:"
_KNOWN_SERVICES = ("gateway", "gate_worker", "gate_sweeper")

# Written by scripts/ecosystem/sync_and_restart_ecosystem_services.py
# immediately before it restarts a service -- the one reliable way to
# know "what commit is this container's /app tree actually at" in this
# dev workflow, where `docker cp` syncs source files into an already-
# built image without ever rebuilding it (so the image's own baked-in
# GIT_COMMIT env var, a real production/CI mechanism -- see
# config_service.py's get_build_info() -- goes stale the moment a file
# is copied in and never reflects it). A real deployment that builds a
# fresh image per commit and never docker-cp's into a running container
# never needs this file at all; GIT_COMMIT is authoritative there, which
# is exactly the fallback below.
_SYNC_MARKER_PATH = Path(__file__).resolve().parents[2] / ".ecosystem_sync_commit"


def _current_commit() -> str:
    try:
        if _SYNC_MARKER_PATH.exists():
            value = _SYNC_MARKER_PATH.read_text(encoding="utf-8").strip()
            if value:
                return value
    except Exception:
        pass
    return os.getenv("GIT_COMMIT", "unknown")


def report_service_startup(service_name: str, *, extra: dict[str, Any] | None = None) -> None:
    """Call once, at the real startup of a long-running ecosystem-related
    process (gateway's own FastAPI startup event, each gate-worker
    subprocess, the gate-sweeper's own process). Never raises -- a Redis
    hiccup here must never block or crash the service it's reporting
    for, same fail-open convention as catalog_sync.py's own
    _persist_last_sync_status()."""
    from core.config import RDB_CACHE
    from core.kv import get_kv
    from core.logger import logger

    commit = _current_commit()
    started_at = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {"service": service_name, "commit": commit, "started_at": started_at, "pid": os.getpid()}
    if extra:
        payload.update(extra)

    try:
        get_kv(RDB_CACHE, decode_responses=True).set(
            f"{_SERVICE_HEALTH_KV_PREFIX}{service_name}", json.dumps(payload),
        )
    except Exception:
        pass

    logger.info(
        f"[ecosystem service startup] service={service_name!r} commit={commit!r} "
        f"started_at={started_at!r} pid={os.getpid()}" + (f" extra={extra}" if extra else "")
    )


def report_gate_worker_startup(queue_names: list[str]) -> None:
    """Gate-worker-specific wrapper around report_service_startup() --
    computes the real, fail-loudly check the user asked for: a gate
    worker that doesn't cover EVERY configured priority lane is exactly
    the 2026-09-29 incident (a stale worker only knowing about the old
    single queue while real Adds moved to new lanes it never listens
    to) -- jobs pile up in the uncovered lane forever, silently, with
    "0 started" the only visible symptom anywhere. Computed once, at
    this worker's own startup, and logged loudly (logger.error, not
    .info) rather than only ever discoverable by a human inspecting
    queue depths by hand."""
    from core.job_queue import ECOSYSTEM_GATE_QUEUES_BY_PRIORITY
    from core.logger import logger

    missing_lanes = [q for q in ECOSYSTEM_GATE_QUEUES_BY_PRIORITY if q not in queue_names]
    if missing_lanes:
        logger.error(
            f"[ecosystem gate-worker] STARTED WITHOUT covering every configured priority "
            f"lane -- missing={missing_lanes!r}, covering only={queue_names!r}. Jobs enqueued "
            f"to a missing lane will queue forever with nothing consuming them. This worker is "
            f"almost certainly running code older than the priority-lane feature -- restart it "
            f"after syncing current code."
        )
    report_service_startup("gate_worker", extra={"queue_names": queue_names, "missing_lanes": missing_lanes})


def get_all_service_health() -> dict[str, Any]:
    """Admin Sources screen's read of every ecosystem-related process's
    own self-reported state, plus computed warnings -- never raises;
    Redis unreachable reads back as every service unknown, not an error
    the caller has to handle specially."""
    from core.config import RDB_CACHE
    from core.kv import get_kv

    services: dict[str, dict[str, Any] | None] = {}
    try:
        kv = get_kv(RDB_CACHE, decode_responses=True)
        for name in _KNOWN_SERVICES:
            raw = kv.get(f"{_SERVICE_HEALTH_KV_PREFIX}{name}")
            services[name] = json.loads(raw) if raw else None
    except Exception:
        for name in _KNOWN_SERVICES:
            services[name] = None

    gateway_info = services.get("gateway")
    gateway_commit = gateway_info.get("commit") if gateway_info else None

    warnings: list[str] = []
    for name, info in services.items():
        if info is None:
            warnings.append(f"{name}: never reported a startup (not running, or running code from before this feature)")
            continue
        info["commit_mismatch"] = bool(gateway_commit) and info.get("commit") != gateway_commit
        if info["commit_mismatch"]:
            warnings.append(f"{name}: commit {info.get('commit')!r} does not match gateway's {gateway_commit!r} -- restart it")
        if info.get("missing_lanes"):
            warnings.append(f"{name}: not consuming every configured priority lane -- missing {info['missing_lanes']!r}")

    return {"services": services, "gateway_commit": gateway_commit, "warnings": warnings}
