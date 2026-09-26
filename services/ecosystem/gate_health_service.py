# SPDX-License-Identifier: MIT
# ============================================================
# Gate-worker health signal (item 2's follow-up, pre-M3).
#
# The ecosystem gate's sandbox stage only ever runs inside the dedicated
# gate-worker process (docs/ecosystem/design/LLD/gate.md) -- if nothing is
# consuming ecosystem_gate_queue, every new/updated item silently sits at
# verdict='pending' forever, with nothing in the wire contract distinguishing
# "still verifying, wait" from "no worker is running, this will never
# resolve." record_heartbeat() (called by workers/ecosystem_gate_worker.py's
# process loop) and get_health() (the read side -- wired into
# GET /ecosystem/config for admins once that endpoint exists, task B-12/M3;
# until then, use this module directly for an admin-visible signal) close
# that gap.
# ============================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import RDB_CACHE
from core.kv import get_kv
from core.logger import logger

_HEARTBEAT_KEY = "ecosystem:gate_worker:heartbeat"

# The worker calls record_heartbeat() every HEARTBEAT_INTERVAL_SECONDS
# (workers/ecosystem_gate_worker.py); the TTL is 3x that so a single missed
# tick (a long-running sandbox execution blocking the loop, say) doesn't
# flip the signal to "down" -- only a genuinely stalled/crashed/never-started
# worker does.
HEARTBEAT_INTERVAL_SECONDS = 30
_HEARTBEAT_TTL_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3

# A gate run still 'pending' this long after it started almost certainly
# means no worker ever picked it up, not that it's "still verifying" --
# stages 1-4 are pure Python/regex and stage 5's sandbox timeout
# (sandbox/ecosystem_gate_executor.py's GATE_EXECUTION_TIMEOUT) is 120s, so
# a real, actively-processing run resolves in well under a minute.
STUCK_VERIFYING_THRESHOLD_SECONDS = 600


def record_heartbeat() -> None:
    """Called by the gate-worker's own process loop, not per-job -- a
    worker that's alive but idle (queue empty) must still report healthy."""
    try:
        kv = get_kv(RDB_CACHE, decode_responses=True)
        kv.setex(_HEARTBEAT_KEY, _HEARTBEAT_TTL_SECONDS, datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        # Never let a heartbeat-recording failure take down the worker
        # loop itself -- worst case, the health signal just goes stale.
        logger.warning(f"gate_health_service: record_heartbeat failed: {exc}")


def get_health() -> dict[str, Any]:
    """Read-side: whether a gate-worker has reported in recently, plus how
    many gate runs look stuck (pending, unfinished, started too long ago
    to still legitimately be "verifying"). Never raises -- a Redis/DB
    hiccup here must not break whatever admin surface calls this; it
    degrades to reporting unhealthy/unknown instead.
    """
    last_heartbeat: str | None = None
    healthy = False
    try:
        kv = get_kv(RDB_CACHE, decode_responses=True)
        last_heartbeat = kv.get(_HEARTBEAT_KEY)
        healthy = last_heartbeat is not None
    except Exception as exc:
        logger.warning(f"gate_health_service: heartbeat read failed: {exc}")

    stuck_count = 0
    try:
        from db.database import SessionLocal
        from db.models import EcosystemGateRun

        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=STUCK_VERIFYING_THRESHOLD_SECONDS)
            stuck_count = (
                db.query(EcosystemGateRun)
                .filter(
                    EcosystemGateRun.verdict == "pending",
                    EcosystemGateRun.finished_at.is_(None),
                    EcosystemGateRun.started_at < cutoff,
                )
                .count()
            )
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"gate_health_service: stuck-run query failed: {exc}")

    message = None
    if not healthy:
        message = (
            "No gate-worker has reported in -- items will stay 'verifying' "
            "indefinitely until one is started (docker compose up -d gate-worker; "
            "see docs/ecosystem/design/LLD/gate.md)."
        )
    elif stuck_count > 0:
        message = (
            f"{stuck_count} item(s) have been 'verifying' for longer than "
            f"{STUCK_VERIFYING_THRESHOLD_SECONDS}s despite a healthy heartbeat -- "
            "check the gate-worker's own logs for a stuck or crashing job."
        )

    return {
        "gate_worker_healthy": healthy,
        "last_heartbeat": last_heartbeat,
        "heartbeat_stale_after_seconds": _HEARTBEAT_TTL_SECONDS,
        "stuck_verifying_count": stuck_count,
        "stuck_verifying_threshold_seconds": STUCK_VERIFYING_THRESHOLD_SECONDS,
        "message": message,
    }
