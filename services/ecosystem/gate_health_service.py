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

    sweep_summary = None
    try:
        kv = get_kv(RDB_CACHE, decode_responses=True)
        raw = kv.get(_LAST_SWEEP_KEY)
        if raw:
            import json

            sweep_summary = json.loads(raw)
    except Exception as exc:
        logger.warning(f"gate_health_service: last-sweep read failed: {exc}")

    return {
        "gate_worker_healthy": healthy,
        "last_heartbeat": last_heartbeat,
        "heartbeat_stale_after_seconds": _HEARTBEAT_TTL_SECONDS,
        "stuck_verifying_count": stuck_count,
        "stuck_verifying_threshold_seconds": STUCK_VERIFYING_THRESHOLD_SECONDS,
        "message": message,
        "last_sweep": sweep_summary,
    }


# ── Stuck-run sweeper (task B-6) ────────────────────────────────────────────
#
# Root cause this exists for: enqueue_gate_run() commits its ecosystem_gate_
# runs row before enqueueing the RQ job for it (correct — no job is ever
# enqueued without a backing row) but a transient failure enqueueing that RQ
# job (queue at capacity, a Redis blip) used to leave the row committed at
# verdict='pending' with NO RQ job ever created for it — "gate jobs
# occasionally never picked up". gate_service.enqueue_gate_run() now catches
# that failure instead of raising, and this sweeper is the recovery path: it
# finds ecosystem_gate_runs rows that have been 'pending' longer than
# STUCK_VERIFYING_THRESHOLD_SECONDS, confirms (via the RQ job's own
# deterministic id) that nothing is actually in flight for them, and
# re-enqueues using the installed_by/installed_for/org_id/surfaces/
# provision_scope columns persisted on the row itself (db/migrate.py's Part
# AD5) -- never the original caller's arguments, which are long gone by the
# time this runs.
_LAST_SWEEP_KEY = "ecosystem:gate_worker:last_sweep"

# A swept row is left alone for at least this long before being eligible for
# another sweep — otherwise a run whose worker is genuinely just slow (or
# whose re-enqueued job is itself taking a while) would get re-enqueued
# every single sweep tick. Reusing the same threshold as "stuck enough to
# need sweeping in the first place" keeps this to one extra constant, not two.
_RESWEEP_COOLDOWN_SECONDS = STUCK_VERIFYING_THRESHOLD_SECONDS

# RQ job states that mean "genuinely in flight right now, do not touch".
_IN_FLIGHT_STATUSES = {"queued", "started", "deferred", "scheduled"}


def sweep_stuck_gate_runs() -> dict[str, Any]:
    """Find gate runs stuck 'pending' past STUCK_VERIFYING_THRESHOLD_SECONDS
    with no RQ job actually in flight for them, and re-enqueue each one.

    Idempotent: a row already swept within _RESWEEP_COOLDOWN_SECONDS is
    skipped; a row whose RQ job is genuinely still queued/running (checked
    by the deterministic job id, never guessed) is left untouched rather
    than double-enqueued. Safe to call on a fixed interval forever — never
    raises (a DB/Redis hiccup here must not take down the gate-worker's
    process loop that calls it).

    Returns {"checked": int, "reenqueued": int, "still_in_flight": int,
    "reenqueued_gate_run_ids": [...]} — logged by the caller and also
    persisted to Redis so get_health() can surface it to admins.
    """
    from datetime import datetime, timezone

    from core.job_queue import ecosystem_gate_job_id, enqueue_ecosystem_gate_job, get_job_status
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    result = {"checked": 0, "reenqueued": 0, "still_in_flight": 0, "reenqueued_gate_run_ids": []}
    now = datetime.now(timezone.utc)
    stuck_cutoff = now - timedelta(seconds=STUCK_VERIFYING_THRESHOLD_SECONDS)
    resweep_cutoff = now - timedelta(seconds=_RESWEEP_COOLDOWN_SECONDS)

    try:
        db = SessionLocal()
        try:
            candidates = (
                db.query(EcosystemGateRun)
                .filter(
                    EcosystemGateRun.verdict == "pending",
                    EcosystemGateRun.finished_at.is_(None),
                    EcosystemGateRun.started_at < stuck_cutoff,
                )
                .filter(
                    (EcosystemGateRun.swept_at.is_(None)) | (EcosystemGateRun.swept_at < resweep_cutoff)
                )
                .all()
            )
            result["checked"] = len(candidates)

            for run in candidates:
                status = get_job_status(ecosystem_gate_job_id(run.id)).get("status")
                if status in _IN_FLIGHT_STATUSES:
                    result["still_in_flight"] += 1
                    continue

                try:
                    enqueue_ecosystem_gate_job(
                        run.id,
                        installed_by=run.installed_by,
                        installed_for=run.installed_for,
                        org_id=run.org_id,
                        surfaces=run.surfaces or [],
                        provision_scope=run.provision_scope,
                    )
                except Exception as exc:
                    logger.warning(f"gate_health_service: sweep re-enqueue failed for gate_run_id={run.id}: {exc}")
                    continue

                run.swept_at = now
                result["reenqueued"] += 1
                result["reenqueued_gate_run_ids"].append(run.id)
                logger.warning(
                    f"gate_health_service: swept and re-enqueued stuck gate_run_id={run.id} "
                    f"(pending since {run.started_at.isoformat()}, rq status was {status!r})"
                )

            if result["reenqueued"] > 0:
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"gate_health_service: sweep_stuck_gate_runs failed: {exc}")
        return result

    try:
        import json

        kv = get_kv(RDB_CACHE, decode_responses=True)
        kv.setex(
            _LAST_SWEEP_KEY,
            _HEARTBEAT_TTL_SECONDS * 10,  # far outlives one sweep interval — a stale value is still informative
            json.dumps({**result, "swept_at": now.isoformat()}),
        )
    except Exception as exc:
        logger.warning(f"gate_health_service: last-sweep write failed: {exc}")

    return result
