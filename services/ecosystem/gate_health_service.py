# SPDX-License-Identifier: MIT
# ============================================================
# Gate-worker health signal (item 2's follow-up, pre-M3).
#
# The ecosystem gate's sandbox stage only ever runs inside the dedicated
# gate-worker process (docs/ecosystem/design/LLD/gate.md) -- if nothing is
# consuming ecosystem_gate_queue, every new/updated item silently sits at
# verdict='pending' forever, with nothing in the wire contract distinguishing
# "still verifying, wait" from "no worker is running, this will never
# resolve." get_health() (the read side -- wired into GET /ecosystem/config
# for admins once that endpoint exists, task B-12/M3; until then, use this
# module directly for an admin-visible signal) closes that gap.
#
# Liveness used to be a hand-rolled Redis heartbeat key, written by a
# daemon thread (workers/start_workers.py's _gate_heartbeat_thread) living
# in the SAME top-level process that also forks RQ work-horses per job.
# Real incident, 2026-09-28: a background thread holding a lock (e.g. the
# DB connection pool's internal lock) at the exact instant RQ forked a
# work-horse left that lock permanently acquired in the child (fork() only
# duplicates the calling thread, not the one holding the lock) -- every
# job forked while that race landed deadlocked forever on its first DB
# call, with RQ's 450s job timeout as the only thing that ever killed it.
# Fix: no more custom thread/heartbeat key in the forking process at all --
# liveness now reads RQ's OWN worker registry (core/job_queue.py's
# get_queue_worker_liveness()), which RQ keeps alive itself with no thread
# of ours in the picture. See docs/ecosystem/design/CHANGELOG.md.
# ============================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import RDB_CACHE
from core.kv import get_kv
from core.logger import logger

# How often the stuck-run sweeper ticks (now running in its own dedicated
# process/service, not alongside the gate RQ workers -- see
# workers/start_workers.py's --gate-sweeper mode).
HEARTBEAT_INTERVAL_SECONDS = 30
_HEARTBEAT_TTL_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3

# A gate run still 'pending' this long after it started almost certainly
# means no worker ever picked it up, not that it's "still verifying" --
# stages 1-4 are pure Python/regex and stage 5's sandbox timeout
# (sandbox/ecosystem_gate_executor.py's GATE_EXECUTION_TIMEOUT) is 120s, so
# a real, actively-processing run resolves in well under a minute.
STUCK_VERIFYING_THRESHOLD_SECONDS = 600


def get_health() -> dict[str, Any]:
    """Read-side: whether a gate-worker has reported in recently, plus how
    many gate runs look stuck (pending, unfinished, started too long ago
    to still legitimately be "verifying"). Never raises -- a Redis/DB
    hiccup here must not break whatever admin surface calls this; it
    degrades to reporting unhealthy/unknown instead.
    """
    from core.job_queue import Q_ECOSYSTEM_GATE, get_queue_worker_liveness

    liveness = get_queue_worker_liveness(Q_ECOSYSTEM_GATE)
    healthy = liveness["healthy"]
    last_heartbeat = None  # no longer a single timestamp -- see 'workers' below

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
        "gate_worker_count": liveness["worker_count"],
        "gate_workers": liveness["workers"],
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
# every single sweep tick. Starts at the same threshold as "stuck enough to
# need sweeping in the first place" and DOUBLES per attempt (capped at
# _MAX_RESWEEP_COOLDOWN_SECONDS) -- real incident, 2026-09-28: a work-horse
# killed out-of-band (confirmed not a kernel OOM -- dmesg showed no
# OOM-killer activity at all) was re-enqueued by this sweeper repeatedly
# with no backoff and no attempt limit, meaning a row whose underlying
# cause keeps recurring (a flaky external dependency, a genuinely
# oversized item) would retry forever with a fixed cadence instead of
# backing off, and would never surface as a clear, actionable failure --
# just an item stuck in "Verifying..." indefinitely with no signal that
# something was actually wrong versus "still verifying, almost done."
_RESWEEP_COOLDOWN_SECONDS = STUCK_VERIFYING_THRESHOLD_SECONDS
_MAX_RESWEEP_COOLDOWN_SECONDS = 3600  # never wait more than an hour between attempts

# Past this many sweep-triggered re-enqueues, stop retrying and mark the
# run permanently failed instead -- an admin sees a real GATE_WORKER_
# INTERRUPTED finding, not an item silently stuck forever. 3 gives a
# transient blip (a Redis hiccup, one bad work-horse kill) real room to
# self-heal without looping indefinitely on a row that's never going to
# resolve on its own.
_MAX_SWEEP_ATTEMPTS = 3

# RQ job states that mean "genuinely in flight right now, do not touch".
_IN_FLIGHT_STATUSES = {"queued", "started", "deferred", "scheduled"}


def _resweep_cooldown_for(attempts: int) -> int:
    """Exponential backoff keyed on how many times this row has already
    been swept: attempt 0 -> base cooldown, 1 -> 2x, 2 -> 4x, ... capped."""
    return min(_RESWEEP_COOLDOWN_SECONDS * (2 ** attempts), _MAX_RESWEEP_COOLDOWN_SECONDS)


def _mark_permanently_failed(db, run) -> None:
    """Past _MAX_SWEEP_ATTEMPTS, stop retrying: resolve the run to a real
    'fail' verdict with a clear, admin-visible finding, exactly like a
    genuine gate-stage failure would -- never leave it silently pending
    forever. Mirrors gate_service.run_gate()'s own end-of-run shape
    (verdict/finished_at on the run, gate_verdict mirrored onto the
    version, a real EcosystemGateFinding row) so every existing consumer
    of "how did this run resolve" already knows how to render it, with no
    special-cased UI path needed for this outcome.
    """
    from datetime import datetime, timezone

    from db.models import EcosystemGateFinding, EcosystemItemVersion

    run.verdict = "fail"
    run.finished_at = datetime.now(timezone.utc)
    db.add(EcosystemGateFinding(
        gate_run_id=run.id, stage="sweep", severity="block", code="GATE_WORKER_INTERRUPTED",
        message=(
            f"Gate processing was interrupted {run.sweep_attempts + 1} time(s) and gave up retrying. "
            "This is not a finding about the item's own content -- the worker process itself did not "
            "complete the check. Re-submitting a new version (or asking an admin to investigate the "
            "gate-worker) is the way forward, not waiting for this run to resolve on its own."
        ),
        details={"sweep_attempts": run.sweep_attempts + 1},
    ))
    version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == run.version_id).one_or_none()
    if version is not None:
        version.gate_verdict = "fail"


def sweep_stuck_gate_runs() -> dict[str, Any]:
    """Find gate runs stuck 'pending' past STUCK_VERIFYING_THRESHOLD_SECONDS
    with no RQ job actually in flight for them, and re-enqueue each one --
    up to _MAX_SWEEP_ATTEMPTS times, with exponential backoff between
    attempts; past that, the run is marked permanently failed with a clear
    GATE_WORKER_INTERRUPTED finding instead of being retried forever.

    Idempotent: a row already swept more recently than its own current
    backoff window (_resweep_cooldown_for(sweep_attempts)) is skipped; a
    row whose RQ job is genuinely still queued/running (checked by the
    deterministic job id, never guessed) is left untouched rather than
    double-enqueued. Safe to call on a fixed interval forever — never
    raises (a DB/Redis hiccup here must not take down the gate-worker's
    process loop that calls it).

    Why this exists instead of relying on gate_service.py's own per-stage
    timeouts: those protect against a single stage that runs long but
    returns cleanly (a real, in-process Python timeout, converted to a
    STAGE_TIMEOUT finding). They cannot protect against the process itself
    being killed out-of-band (confirmed real incident, 2026-09-28: a
    work-horse's "Work-horse terminated unexpectedly; waitpid returned
    None" with zero corresponding kernel OOM-killer activity in dmesg) --
    no in-process timeout of any kind can catch an external, uncatchable
    kill signal. This sweeper, running in a SEPARATE process/thread from
    the one that might get killed, is the only layer that actually can.

    Returns {"checked": int, "reenqueued": int, "still_in_flight": int,
    "permanently_failed": int, "reenqueued_gate_run_ids": [...],
    "permanently_failed_gate_run_ids": [...]} — logged by the caller and
    also persisted to Redis so get_health() can surface it to admins.
    """
    from datetime import datetime, timezone

    from core.job_queue import ecosystem_gate_job_id, enqueue_ecosystem_gate_job, get_job_status
    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    result = {
        "checked": 0, "reenqueued": 0, "still_in_flight": 0, "permanently_failed": 0,
        "reenqueued_gate_run_ids": [], "permanently_failed_gate_run_ids": [],
    }
    now = datetime.now(timezone.utc)
    stuck_cutoff = now - timedelta(seconds=STUCK_VERIFYING_THRESHOLD_SECONDS)
    # Widest net a candidate could possibly need (attempt-0 cooldown) --
    # rows not yet due for THEIR OWN (possibly longer, backed-off) cooldown
    # are filtered out per-row below, since SQL can't express a per-row
    # variable cutoff without a computed column.
    widest_resweep_cutoff = now - timedelta(seconds=_RESWEEP_COOLDOWN_SECONDS)

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
                    (EcosystemGateRun.swept_at.is_(None)) | (EcosystemGateRun.swept_at < widest_resweep_cutoff)
                )
                .all()
            )
            result["checked"] = len(candidates)

            for run in candidates:
                own_cooldown = _resweep_cooldown_for(run.sweep_attempts)
                if run.swept_at is not None and (now - run.swept_at).total_seconds() < own_cooldown:
                    continue  # this row's own (backed-off) cooldown hasn't elapsed yet

                status = get_job_status(ecosystem_gate_job_id(run.id)).get("status")
                if status in _IN_FLIGHT_STATUSES:
                    result["still_in_flight"] += 1
                    continue

                if run.sweep_attempts >= _MAX_SWEEP_ATTEMPTS:
                    _mark_permanently_failed(db, run)
                    result["permanently_failed"] += 1
                    result["permanently_failed_gate_run_ids"].append(run.id)
                    logger.warning(
                        f"gate_health_service: gate_run_id={run.id} exceeded {_MAX_SWEEP_ATTEMPTS} sweep "
                        "attempts -- marked permanently failed (GATE_WORKER_INTERRUPTED), no further retries"
                    )
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
                run.sweep_attempts = run.sweep_attempts + 1
                result["reenqueued"] += 1
                result["reenqueued_gate_run_ids"].append(run.id)
                logger.warning(
                    f"gate_health_service: swept and re-enqueued stuck gate_run_id={run.id} "
                    f"(pending since {run.started_at.isoformat()}, rq status was {status!r})"
                )

            if result["reenqueued"] > 0 or result["permanently_failed"] > 0:
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
