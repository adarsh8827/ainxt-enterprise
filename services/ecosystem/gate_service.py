# SPDX-License-Identifier: MIT
# ============================================================
# Gate orchestrator (docs/ecosystem/SKILLS_PHASE_PLAN.md tasks B-8/B-9;
# referred to as "gate_orchestrator.py" in the plan's prose — kept in this
# file, gate_service.py, rather than a second file, since B-3's original
# skeleton already named this the service's home and the two names refer
# to the same orchestration role).
#
# Runs stages in order: manifest -> license -> static_safety -> supply_chain
# -> [cache check] -> sandbox -> ethics -> mcp_connector. Records every
# stage's findings to ecosystem_gate_findings, the run's overall verdict to
# ecosystem_gate_runs, and the resolved verdict back onto
# ecosystem_item_versions.gate_verdict.
#
# enqueue_gate_run() genuinely enqueues (core/job_queue.py's
# enqueue_ecosystem_gate_job, ecosystem_gate_queue) rather than running the
# stages in-process — workers/ecosystem_gate_worker.py, running in the
# dedicated gate-worker container, is what actually calls run_gate(). This
# is what lets the sandbox stage's Docker access live only in that one
# container, never the gateway (docs/ecosystem/design/LLD/gate.md). The
# wire contract (job_id/status:"verifying", GET /ecosystem/jobs/{id}) is
# unchanged — callers were always written against an async-shaped
# response, even while this ran synchronously (M2).
# ============================================================

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable

from db.database import SessionLocal
from db.models import EcosystemGateFinding, EcosystemGateRun, EcosystemItem, EcosystemItemVersion
from services.ecosystem.errors import EcosystemError, NotFoundError
from services.ecosystem.gate import license_stage, manifest_stage, mcp_connector_stage, sandbox_stage, static_safety_stage, supply_chain_stage
from services.ecosystem.gate.ethics_stage import run as run_ethics_stage
from services.ecosystem.gate.types import Finding
from services.ecosystem.items_service import _visible_to_caller
from services.ecosystem.versions_service import decode_envelope
from store.ecosystem_object_storage import get_ecosystem_object_storage

_SCANNER_VERSION = "2026.09.1"

# Triggers for which a pass/warn verdict auto-installs the version's
# creator (Review round following M1, item E) — never for legacy-bridge
# backfills or builtin seeding, neither of which has a single "creator" in
# the same sense.
_AUTO_INSTALL_TRIGGERS = ("ui_add", "chat_create")

# Item 6's "Update my <skill>" -- a pass/warn verdict on a re-gated version
# of an EXISTING item bumps the caller's own already-existing install onto
# it (never creates a new install row, unlike _AUTO_INSTALL_TRIGGERS above).
# Trigger value is "new_version", not a "chat_"-prefixed name -- reuses a
# value db/migrate.py's own ecosystem_gate_runs_trigger_check CHECK
# constraint already allowed (seeded ahead of any Python caller ever using
# it) rather than needing a schema migration for a brand-new one. Found
# live: the first draft of this feature invented "chat_update_version"
# instead, which the DB constraint rejected outright (a real
# IntegrityError on every call, caught only once pytest could finally run
# against the real database again after other live-environment work
# freed it up).
_UPDATE_VERSION_TRIGGERS = ("new_version",)


def enqueue_gate_run(
    version_id: str,
    trigger: str,
    *,
    installed_by: str | None = None,
    installed_for: str | None = None,
    org_id: str | None = None,
    surfaces: list[str] | None = None,
    provision_scope: str | None = None,
    license_tier: str = "strict",
    priority: str = "normal",
) -> str:
    """Create a gate_runs row for version_id and enqueue it to
    ecosystem_gate_queue for the dedicated gate-worker to actually run
    (see module docstring). Returns the gate_run id immediately; the row
    stays verdict='pending' until the worker calls run_gate().

    license_tier ('strict' default, or 'relaxed' -- task C, ECOSYSTEM_PLAN.md
    §11.2): set by create_service.py once it has already re-validated a
    disallowed license under Tier 2/3's own rules. Persisted on the row
    (db/migrate.py's Part AD6) for the same reason installed_by etc. are --
    run_gate() below reads it back to tell license_stage.run() whether a
    disallowed license should warn or block; never derived here.

    installed_by/installed_for/org_id/surfaces/provision_scope are only
    used for triggers in _AUTO_INSTALL_TRIGGERS — task B-4/B-22's callers
    never pass them (their triggers never auto-install regardless). They
    are persisted onto the row itself (task B-6) precisely so a later
    recovery attempt (the sweeper below, or a manual retry) can rebuild
    the exact same enqueue call without depending on the original RQ job
    payload, which is the only place this context lived before B-6.

    Root cause of "gate jobs occasionally never picked up" (task B-6): the
    DB commit above always happened before the RQ enqueue call below (this
    was already correct — an enqueued job always has a backing row), but a
    transient failure enqueueing the RQ job itself (queue at capacity, a
    Redis blip) used to propagate out of this function as an exception —
    the row was left committed at verdict='pending' with NO RQ job ever
    created for it, and the caller (e.g. create_via_write) would see its
    otherwise-successful item creation fail outright. That failure is now
    caught and logged here instead of re-raised: the item/version the
    caller already committed stays valid either way, and
    gate_health_service.sweep_stuck_gate_runs() (called periodically by
    the gate-worker process, task B-6) re-enqueues any row that's still
    'pending' past STUCK_VERIFYING_THRESHOLD_SECONDS with no RQ job
    actually in flight for it — using the columns persisted below, not
    the caller's now long-gone in-memory arguments.
    """
    gate_run_id = _create_gate_run_row(
        version_id, trigger, installed_by=installed_by, installed_for=installed_for, org_id=org_id,
        surfaces=surfaces, provision_scope=provision_scope, license_tier=license_tier,
    )

    from core.job_queue import enqueue_ecosystem_gate_job
    from core.logger import logger

    try:
        enqueue_ecosystem_gate_job(
            gate_run_id,
            installed_by=installed_by, installed_for=installed_for, org_id=org_id,
            surfaces=surfaces, provision_scope=provision_scope, priority=priority,
        )
    except Exception as exc:
        # Do not fail the caller's otherwise-successful create/update over a
        # queue-availability problem — the row above is already a valid,
        # sweeper-recoverable 'pending' run (see docstring). Re-raising here
        # would make e.g. create_via_write() report an error for an item
        # that was, in fact, created.
        logger.warning(
            f"gate_service: failed to enqueue gate_run_id={gate_run_id} "
            f"({exc}) -- left 'pending' for gate_health_service's sweeper to retry"
        )
    return gate_run_id


def _create_gate_run_row(
    version_id: str, trigger: str, *, installed_by: str | None = None, installed_for: str | None = None,
    org_id: str | None = None, surfaces: list[str] | None = None, provision_scope: str | None = None,
    license_tier: str = "strict",
) -> str:
    """Shared by enqueue_gate_run() (async) and run_gate_synchronously()
    (the instructions-only fast path below) -- both need the exact same
    'pending' row shape; only what happens after creating it differs
    (enqueue vs. run in-process with a timeout)."""
    db = SessionLocal()
    try:
        row = EcosystemGateRun(
            version_id=version_id,
            trigger=trigger,
            verdict="pending",
            scanner_version=_SCANNER_VERSION,
            installed_by=installed_by,
            installed_for=installed_for,
            org_id=org_id,
            surfaces=surfaces or [],
            provision_scope=provision_scope,
            license_tier=license_tier,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def run_gate_synchronously(
    version_id: str,
    trigger: str,
    *,
    timeout_seconds: float = 3.0,
    installed_by: str | None = None,
    installed_for: str | None = None,
    org_id: str | None = None,
    surfaces: list[str] | None = None,
    provision_scope: str | None = None,
    license_tier: str = "strict",
    fallback_priority: str = "high",
) -> dict[str, Any]:
    """Catalog-checking round (2026-09-28), section 3's "instructions-only
    catalog skills should go Add -> Active in about a second": creates the
    gate_runs row (same shape enqueue_gate_run() creates) and runs
    run_gate() SYNCHRONOUSLY, inside the caller's own request, with a
    short wall-clock budget -- never enqueues up front. Only ever worth
    calling for a gate_run whose proportionate stage set is expected to be
    trivial (an instructions-only signed catalog item -- see
    catalog_sync.materialize_from_catalog()'s own eligibility check, which
    is what actually decides whether to call this at all rather than the
    plain async enqueue_gate_run() path).

    On success within timeout_seconds: returns run_gate()'s own result
    dict (+ "timed_out": False), verdict already resolved and (for an
    auto-install trigger) already installed -- identical end state to the
    async path, just faster; nothing was ever enqueued.

    On timeout: the calling thread gives up waiting (Python has no
    portable way to forcibly kill a running thread -- same documented
    limitation as gate_service._run_stage_with_timeout() -- so the
    started run_gate() call keeps executing in the background and WILL
    still resolve the row on its own), and THIS is the point where the
    job actually falls back to the async queue, exactly as the spec asks:
    enqueues the SAME gate_run_id. run_gate()'s own mutual-exclusion lock
    (see its docstring) makes whichever of "the original background
    thread" or "this fallback job" gets there first the sole executor;
    the other is a safe, idempotent no-op. The caller gets back
    {"gate_run_id": ..., "verdict": "pending", "timed_out": True}
    immediately and should respond "Verifying" to the end user rather
    than blocking further.
    """
    import concurrent.futures

    gate_run_id = _create_gate_run_row(
        version_id, trigger, installed_by=installed_by, installed_for=installed_for, org_id=org_id,
        surfaces=surfaces, provision_scope=provision_scope, license_tier=license_tier,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_gate, gate_run_id, installed_by=installed_by, installed_for=installed_for,
            org_id=org_id, surfaces=surfaces, provision_scope=provision_scope,
        )
        try:
            result = future.result(timeout=timeout_seconds)
            return {**result, "timed_out": False}
        except concurrent.futures.TimeoutError:
            from core.job_queue import enqueue_ecosystem_gate_job
            from core.logger import logger

            try:
                enqueue_ecosystem_gate_job(
                    gate_run_id, installed_by=installed_by, installed_for=installed_for, org_id=org_id,
                    surfaces=surfaces, provision_scope=provision_scope, priority=fallback_priority,
                )
            except Exception as exc:
                logger.warning(
                    f"gate_service: sync-fast-path timeout fallback enqueue failed for "
                    f"gate_run_id={gate_run_id} ({exc}) -- the already-started background run will still resolve it"
                )
            return {"gate_run_id": gate_run_id, "verdict": "pending", "stage_verdicts": {}, "timed_out": True}


def _lookup_cached_verdict(content_hash_value: str, scanner_version: str, exclude_gate_run_id: str) -> str | None:
    """(content_hash, scanner_version) cache lookup (task B-9) — if another,
    already-resolved gate run exists for the exact same content and scanner
    version, its stages-5-7 verdict is reused rather than re-invoking the
    sandbox executor. Returns None on a cache miss (never on a cache hit
    with a 'pending' verdict — a pending run isn't a resolved cache entry)."""
    db = SessionLocal()
    try:
        cached = (
            db.query(EcosystemGateRun)
            .join(EcosystemItemVersion, EcosystemGateRun.version_id == EcosystemItemVersion.id)
            .filter(
                EcosystemItemVersion.content_hash == content_hash_value,
                EcosystemGateRun.scanner_version == scanner_version,
                EcosystemGateRun.verdict != "pending",
                EcosystemGateRun.id != exclude_gate_run_id,
            )
            .order_by(EcosystemGateRun.started_at.desc())
            .first()
        )
        return cached.verdict if cached else None
    finally:
        db.close()


def _aggregate(stage_verdicts: dict[str, str]) -> str:
    """ECOSYSTEM_PLAN.md §6 stage 8's aggregation rule: license is
    pass/block only and independent of everything else; pending beats
    everything (an item never reaches pass/warn on unrun stages); fail
    beats warn; warn beats pass."""
    if stage_verdicts.get("license") == "fail":
        return "fail"
    if "pending" in stage_verdicts.values():
        return "pending"
    if "fail" in stage_verdicts.values():
        return "fail"
    if "warn" in stage_verdicts.values():
        return "warn"
    return "pass"


# Item 8 (real incident, 2026-09-27): no stage had a timeout of its own
# before this -- the ethics stage (a single LLM call) and the sandbox
# stage (Docker image pull + container run; container.wait() itself
# already caps at 120s, sandbox/ecosystem_gate_executor.py's own
# GATE_EXECUTION_TIMEOUT, but a slow/stalled image PULL before that call
# has no timeout at all) could both hang the whole gate-worker job
# indefinitely, with only RQ's own blunt, job-level 300s default eventually
# killing it -- producing a confusing traceback (the deferred SIGALRM
# lands wherever the interpreter happens to be, often deep in an unrelated
# import), not a clean "stage X timed out" finding. These per-stage
# timeouts are a second, tighter, per-stage backstop underneath that.
_STAGE_TIMEOUT_SECONDS: dict[str, int] = {
    "manifest": 30, "license": 30, "static_safety": 30, "supply_chain": 30,
    "sandbox": 180, "ethics": 60, "mcp_connector": 30,
}

# Script-like file extensions supply_chain_stage.run()/sandbox_stage.run()
# actually have something to check -- matches sandbox_stage.py's own
# Python-only scope (.py) plus the other extensions a skill bundle could
# realistically carry, kept intentionally small: this only decides
# whether to SKIP a stage, never whether to trust content it does run.
_SCRIPT_EXTENSIONS = (".py", ".sh", ".js", ".rb", ".pl")


def _has_scripts_or_dependencies(manifest: dict[str, Any] | None, files: dict[str, str]) -> bool:
    """Catalog-checking round (2026-09-28): supply_chain/sandbox exist to
    vet script/dependency content -- an instructions-only skill (the
    overwhelming majority of the external-sources catalog) has neither,
    so both stages are pure overhead for it. True if any bundled file
    looks like a script, the manifest declares a `test` entrypoint (which
    only makes sense pointing at a script), or a non-empty `dependencies`
    list is declared."""
    if any(rel_path.endswith(_SCRIPT_EXTENSIONS) for rel_path in files):
        return True
    if isinstance(manifest, dict):
        if manifest.get("test"):
            return True
        if manifest.get("dependencies"):
            return True
    return False


def _run_stage_with_timeout(stage_name: str, fn: Callable[[], Any]) -> Any:
    """Runs one stage's already-built `fn` (a zero-arg closure) with a
    per-stage wall-clock timeout. On timeout, returns a StageResult with
    verdict='pending' (not 'fail' -- a timeout is not evidence the content
    is bad) and a STAGE_TIMEOUT finding, instead of letting the caller hang
    or raising an unhandled exception.

    Known limitation, disclosed rather than silently assumed away: Python
    has no portable way to forcibly kill a running thread, so the
    ThreadPoolExecutor thread this starts keeps running in the background
    even after this function gives up waiting on it -- it will eventually
    finish (or the process will end) on its own. This still achieves the
    actual goal (run_gate() itself never blocks past the timeout, so the
    gate-worker's job queue keeps moving), which is what matters here.

    What this does NOT (and cannot) protect against, confirmed by a real
    incident (2026-09-28): the work-horse PROCESS itself being killed
    out-of-band mid-stage (dmesg showed zero kernel OOM-killer activity for
    the incident -- the kill's exact origin outside this process's own
    control couldn't be pinned down further, but it was categorically not
    a graceful, catchable Python-level event). No in-process timeout
    mechanism -- thread-based or otherwise -- can intercept an external,
    uncatchable kill signal; that failure mode is handled one layer up, by
    gate_health_service.py's sweep_stuck_gate_runs() running in a separate
    process, with its own retry/backoff and a bounded max-attempts before
    surfacing a clear, permanent failure instead of retrying forever.
    """
    from services.ecosystem.gate.types import Finding, StageResult

    timeout = _STAGE_TIMEOUT_SECONDS[stage_name]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return StageResult(verdict="pending", findings=[Finding(
                stage=stage_name, severity="warn", code="STAGE_TIMEOUT",
                message=f"{stage_name} stage exceeded its {timeout}s timeout and was abandoned",
                details={"timeout_seconds": timeout},
            )])


def run_gate(
    gate_run_id: str,
    *,
    installed_by: str | None = None,
    installed_for: str | None = None,
    org_id: str | None = None,
    surfaces: list[str] | None = None,
    provision_scope: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        gate_run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == gate_run.version_id).one()
        item = db.query(EcosystemItem).filter(EcosystemItem.id == version.item_id).one()
        trigger = gate_run.trigger
        version_id = version.id
        item_id = item.id
        content_hash_value = version.content_hash
        object_key = version.object_key
        license = item.license
        item_type = item.item_type
        license_tier = gate_run.license_tier
        # Catalog-checking round, instructions-only synchronous fast path
        # (2026-09-28): if a prior call ALREADY resolved this exact run
        # (the sync attempt below finished just as -- or before -- an
        # async fallback job for the same gate_run_id got dequeued),
        # re-running the stage pipeline would double-execute it for no
        # reason. Idempotent short-circuit: a run with finished_at already
        # set is done: return its existing resolved verdict, never
        # re-invoke a single stage.
        if gate_run.finished_at is not None:
            return {"gate_run_id": gate_run_id, "verdict": gate_run.verdict, "stage_verdicts": {
                name: entry.get("status") for name, entry in (gate_run.stage_timings or {}).items()
            }}
    finally:
        db.close()

    # Mutual-exclusion lock, same reason as the short-circuit above but for
    # the narrower window where the sync fast-path's timed-out background
    # thread (still running, per Python's documented inability to forcibly
    # kill a thread) and its own async fallback job could otherwise both be
    # mid-execution on this exact gate_run_id at once -- whichever caller
    # gets here first actually runs the stages; a second concurrent caller
    # for the SAME id is a safe no-op (the first one will still resolve and
    # write the final verdict). TTL (500s) matches this module's own
    # documented job-level worst case (450s, core/job_queue.py's
    # enqueue_ecosystem_gate_job timeout) plus a small buffer, so a holder
    # that crashed mid-run self-heals instead of wedging this id forever.
    from core.config import RDB_CACHE
    from core.kv import get_kv
    from core.logger import logger

    run_lock_key = f"ecosystem:gate:running:{gate_run_id}"
    kv = get_kv(RDB_CACHE, decode_responses=True)
    if not kv.set(run_lock_key, "1", ex=500, nx=True):
        logger.info(f"gate_service: gate_run_id={gate_run_id} already being executed elsewhere -- skipping duplicate run")
        return {"gate_run_id": gate_run_id, "verdict": "pending", "stage_verdicts": {}}

    try:
        return _run_gate_locked(
            gate_run_id, installed_by=installed_by, installed_for=installed_for, org_id=org_id,
            surfaces=surfaces, provision_scope=provision_scope,
        )
    finally:
        kv.delete(run_lock_key)


def _run_gate_locked(
    gate_run_id: str,
    *,
    installed_by: str | None = None,
    installed_for: str | None = None,
    org_id: str | None = None,
    surfaces: list[str] | None = None,
    provision_scope: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        gate_run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == gate_run.version_id).one()
        item = db.query(EcosystemItem).filter(EcosystemItem.id == version.item_id).one()
        trigger = gate_run.trigger
        version_id = version.id
        item_id = item.id
        content_hash_value = version.content_hash
        object_key = version.object_key
        license = item.license
        item_type = item.item_type
        license_tier = gate_run.license_tier
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    manifest, files = decode_envelope(store.get(object_key))

    findings: list[Finding] = []
    stage_verdicts: dict[str, str] = {}
    stage_timings: dict[str, dict[str, Any]] = {}
    any_stage_timed_out = False

    def _run_and_record(stage_name: str, stage_fn: Callable[[], Any]) -> None:
        # Item 6: records real per-stage status/duration on stage_timings
        # (db/migrate.py's Part AD9) as each stage actually finishes, so
        # the Verification tab can show live progress on a run that's
        # still executing, not just the final resolved verdict.
        nonlocal any_stage_timed_out
        import time
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        result = _run_stage_with_timeout(stage_name, stage_fn)
        duration_ms = int((time.monotonic() - t0) * 1000)
        timed_out = any(f.code == "STAGE_TIMEOUT" for f in result.findings)
        any_stage_timed_out = any_stage_timed_out or timed_out
        stage_verdicts[stage_name] = result.verdict
        stage_timings[stage_name] = {
            "status": result.verdict, "duration_ms": duration_ms, "started_at": started_at.isoformat(),
        }
        findings.extend(result.findings)

    def _skip(stage_name: str, *, verdict: str, reason: str) -> None:
        # Catalog-checking round (2026-09-28): a skipped stage still gets
        # a real stage_timings entry (Verification tab needs to show
        # *why* every stage that didn't run was skipped, not just omit
        # it) -- "reason" is additive on top of the pre-existing
        # status/duration_ms/started_at shape so nothing that already
        # reads this JSONB column breaks.
        stage_verdicts[stage_name] = verdict
        stage_timings[stage_name] = {
            "status": "skipped", "duration_ms": 0, "started_at": None, "reason": reason,
        }

    # Catalog-checking round (2026-09-28): proportionate gating. A signed
    # catalog item's bytes were already scanned once, at crawl time, by
    # the exact same static_safety_stage.run_fast_path() this repo's own
    # crawler runs before ever writing the pointer to the signed index
    # (services/ecosystem/catalog_crawler/crawl.py).
    #
    # Real bug found and fixed in this same round: the original version of
    # this check compared version.content_hash (versions_service.
    # create_version_for_content()'s content_hash(), a sha256 of the
    # ENCODED ENVELOPE bytes) against item.catalog_pointer["content_hash"]
    # (catalog_sync.compute_content_hash(), a sha256 of manifest_text+files
    # separately) -- two DIFFERENT hash functions over two different
    # representations of the same content, which can never be equal even
    # for a genuinely verified item. Caught by
    # test_materialize_from_catalog_instructions_only_resolves_synchronously_and_installs
    # actually invoking the (real, network-unavailable) ethics stage when
    # it should have been skipped. Fixed: the real proof a version's
    # content was verified against the signed index is that
    # materialize_from_catalog() ALREADY ran that exact drift check
    # (raising CatalogContentDriftError on any mismatch) before ever
    # calling create_version_for_content() -- for this phase, a
    # scope="central_index" item with a catalog_pointer can only ever
    # reach run_gate() via that path (no other creator of a first version
    # for a central_index item exists yet), so the presence of the
    # pointer itself is the signal, not a second, redundant hash compare.
    catalog_pointer = item.catalog_pointer if hasattr(item, "catalog_pointer") else None
    is_signed_catalog_hash_verified = bool(item.scope == "central_index" and catalog_pointer)
    has_scripts_or_deps = _has_scripts_or_dependencies(manifest, files)

    _run_and_record("manifest", lambda: manifest_stage.run(manifest, files))
    _run_and_record("license", lambda: license_stage.run(license, relaxed=(license_tier == "relaxed")))

    if is_signed_catalog_hash_verified:
        _skip(
            "static_safety", verdict="pass",
            reason="signed catalog hash matched the crawled index -- CI already scanned these exact bytes at crawl time",
        )
    else:
        _run_and_record("static_safety", lambda: static_safety_stage.run(files, manifest_text=str(manifest)))

    if has_scripts_or_deps:
        _run_and_record("supply_chain", lambda: supply_chain_stage.run((manifest or {}).get("dependencies")))
    else:
        _skip("supply_chain", verdict="pass", reason="no scripts or dependencies declared -- nothing for this stage to check")

    # Cache short-circuit before the expensive stages (task B-9) — but only
    # if stages 1-4 haven't already doomed this to 'fail' (no point invoking
    # the sandbox on something that's already blocked on license/manifest).
    already_failed = stage_verdicts.get("license") == "fail" or "fail" in stage_verdicts.values()
    cached_verdict = None if already_failed else _lookup_cached_verdict(content_hash_value, _SCANNER_VERSION, gate_run_id)
    if org_id:
        from services.ecosystem.policy_service import get_ethics_review_policy  # lazy: policy_service imports this module
        ethics_policy = get_ethics_review_policy(org_id)
    else:
        ethics_policy = "scripts_or_noncatalog"
    should_run_ethics = (
        ethics_policy == "always"
        or (ethics_policy == "scripts_or_noncatalog" and (has_scripts_or_deps or not is_signed_catalog_hash_verified))
    )

    if already_failed:
        for skipped in ("sandbox", "ethics", "mcp_connector"):
            stage_verdicts[skipped] = "fail"
            stage_timings[skipped] = {"status": "skipped", "duration_ms": 0, "started_at": None, "reason": "an earlier stage already failed"}
    elif cached_verdict is not None:
        for cached in ("sandbox", "ethics", "mcp_connector"):
            stage_verdicts[cached] = cached_verdict
            stage_timings[cached] = {
                "status": "skipped", "duration_ms": 0, "started_at": None,
                "reason": f"reusing cached verdict for content_hash={content_hash_value[:12]}...",
            }
        findings.append(Finding(
            stage="sandbox", severity="info", code="CACHE_HIT",
            message=f"reusing cached verdict for content_hash={content_hash_value[:12]}...",
        ))
    else:
        if has_scripts_or_deps:
            _run_and_record("sandbox", lambda: sandbox_stage.run(files, manifest))
        else:
            _skip("sandbox", verdict="pass", reason="no scripts or dependencies declared -- nothing for this stage to execute")

        if should_run_ethics:
            _run_and_record("ethics", lambda: run_ethics_stage(manifest))
        else:
            _skip("ethics", verdict="pass", reason=f"org ethics_review_policy={ethics_policy!r} -- not required for this item")

        _run_and_record("mcp_connector", lambda: mcp_connector_stage.run(item_type, manifest))

    overall = _aggregate(stage_verdicts)

    db = SessionLocal()
    try:
        gate_run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        gate_run.verdict = overall
        gate_run.stage_timings = stage_timings
        from datetime import datetime, timezone

        # Item 8: deliberately leave finished_at unset when a stage timed
        # out -- this run isn't really "done", it gave up on one stage
        # and should be retried, not just left showing a resolved 'pending'
        # verdict forever. gate_health_service.sweep_stuck_gate_runs()'s
        # existing query (verdict='pending' AND finished_at IS NULL AND
        # started_at old enough) picks this up automatically on its next
        # tick and re-enqueues it with its own cooldown/backoff -- no
        # second, parallel retry mechanism needed for this case.
        #
        # Real bug found live, 2026-09-29: the original condition only
        # covered an actual Python-level timeout -- a stage that instead
        # explicitly RETURNS verdict="pending" as its own result (e.g.
        # ethics_stage.py's REVIEWER_UNAVAILABLE/REVIEWER_RESPONSE_
        # UNPARSEABLE, when the real LLM call itself failed or returned
        # something unparseable -- a genuine "please retry me", not a
        # resolved verdict) is NOT a timeout, so any_stage_timed_out
        # stayed False and finished_at got set anyway -- producing
        # exactly the orphaned state the comment above says this is
        # supposed to prevent: verdict='pending' AND finished_at IS NOT
        # NULL, which the sweeper's own query can never match, so the
        # run was stuck forever with no automatic repair path. The real
        # condition for "still not actually resolved" is the overall
        # verdict itself, not merely whether a stage timed out.
        if any_stage_timed_out or overall == "pending":
            pass
        else:
            gate_run.finished_at = datetime.now(timezone.utc)
        for f in findings:
            db.add(EcosystemGateFinding(
                gate_run_id=gate_run_id, stage=f.stage, severity=f.severity,
                code=f.code, message=f.message, details=f.details,
            ))
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == gate_run.version_id).one()
        version.gate_verdict = overall
        db.commit()
    finally:
        db.close()

    if trigger in _AUTO_INSTALL_TRIGGERS and overall in ("pass", "warn") and installed_by is not None:
        _auto_install(
            item_id=item_id, version_id=version_id, org_id=org_id or "default",
            installed_by=installed_by, installed_for=installed_for,
            surfaces=surfaces or [], provision_scope=provision_scope,
        )
    elif trigger in _UPDATE_VERSION_TRIGGERS and overall in ("pass", "warn") and installed_by is not None:
        _bump_own_install_on_pass(item_id=item_id, version_id=version_id, org_id=org_id or "default", caller_id=installed_by)
    # NOTE: trigger == "admin_provision" (ensure_full_gate_for_scope_widen()
    # below) deliberately does NOT auto-install/auto-provision anything on
    # pass -- reverted (product correction, 2026-09-27). A share/scope-widen
    # re-gates a fast-pathed version so the wider audience can trust its
    # verdict once they actually see it; it must never itself grant that
    # wider audience an install or promote the item to an org default.

    return {"gate_run_id": gate_run_id, "verdict": overall, "stage_verdicts": stage_verdicts}


# Task D: fast path for private, self-created, no-script skills (Create
# with AI / Write / Save as skill). scanner_version is tagged with this
# marker so ensure_full_gate_for_scope_widen() below can tell a fast-
# pathed version apart from one that's actually been through all 7 stages.
_FAST_PATH_MARKER = "fast-path-private"


def run_fast_path_gate(
    version_id: str, *, trigger: str, org_id: str, installed_by: str,
    installed_for: str | None, surfaces: list[str], provision_scope: str | None,
    license_tier: str = "strict",
) -> dict[str, Any]:
    """Runs only stage 1 (manifest) + stage 3 (static_safety, which now
    also covers the hidden-text/prompt-injection heuristic) synchronously
    in the request -- no license_stage (create_service._resolve_creation_license()
    already resolved Tier 3's self-authored/acknowledged license; re-
    deriving it via license_stage.run() would just re-block a license
    that's already been approved for this private scope), no
    supply_chain/sandbox/ethics/mcp_connector. Only ever called by
    create_service.create_via_write() when eligible (private scope, no
    bundled files, item_type='skill') -- never for uploads/imports, which
    keep the full async gate unconditionally.

    Writes the same ecosystem_gate_runs/ecosystem_gate_findings/
    ecosystem_item_versions.gate_verdict rows run_gate() would, just
    resolved immediately instead of dispatched to the async gate-worker --
    the HTTP response this feeds into already carries the final verdict,
    which is the whole point (no "Verifying…" step for the common case)."""
    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
        item = db.query(EcosystemItem).filter(EcosystemItem.id == version.item_id).one()
        object_key = version.object_key
        item_id = item.id
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    manifest, files = decode_envelope(store.get(object_key))
    manifest_text = str(manifest)

    import time
    from datetime import datetime, timezone

    findings: list[Finding] = []
    stage_timings: dict[str, dict[str, Any]] = {}

    _t0 = time.monotonic()
    _started = datetime.now(timezone.utc).isoformat()
    manifest_result = manifest_stage.run(manifest, files)
    findings.extend(manifest_result.findings)
    stage_timings["manifest"] = {"status": manifest_result.verdict, "duration_ms": int((time.monotonic() - _t0) * 1000), "started_at": _started}

    _t0 = time.monotonic()
    _started = datetime.now(timezone.utc).isoformat()
    safety_result = static_safety_stage.run_fast_path(files, manifest_text=manifest_text)
    findings.extend(safety_result.findings)
    stage_timings["static_safety"] = {"status": safety_result.verdict, "duration_ms": int((time.monotonic() - _t0) * 1000), "started_at": _started}

    stage_verdicts = {"manifest": manifest_result.verdict, "static_safety": safety_result.verdict}
    if "pending" in stage_verdicts.values():
        overall = "pending"
    elif "fail" in stage_verdicts.values():
        overall = "fail"
    elif "warn" in stage_verdicts.values():
        overall = "warn"
    else:
        overall = "pass"

    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        gate_run = EcosystemGateRun(
            version_id=version_id, trigger=trigger, verdict=overall,
            scanner_version=f"{_SCANNER_VERSION} ({_FAST_PATH_MARKER})",
            started_at=now, finished_at=now, stage_timings=stage_timings,
            installed_by=installed_by, installed_for=installed_for, org_id=org_id,
            surfaces=surfaces or [], provision_scope=provision_scope, license_tier=license_tier,
        )
        db.add(gate_run)
        db.commit()
        db.refresh(gate_run)
        gate_run_id = gate_run.id
        for f in findings:
            db.add(EcosystemGateFinding(
                gate_run_id=gate_run_id, stage=f.stage, severity=f.severity,
                code=f.code, message=f.message, details=f.details,
            ))
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
        version.gate_verdict = overall
        db.commit()
    finally:
        db.close()

    if trigger in _AUTO_INSTALL_TRIGGERS and overall in ("pass", "warn") and installed_by is not None:
        _auto_install(
            item_id=item_id, version_id=version_id, org_id=org_id,
            installed_by=installed_by, installed_for=installed_for,
            surfaces=surfaces or [], provision_scope=provision_scope,
        )

    return {"gate_run_id": gate_run_id, "verdict": overall, "stage_verdicts": stage_verdicts}


def ensure_full_gate_for_scope_widen(
    item_id: str, version_id: str, *, org_id: str, requested_by: str, surfaces: list[str] | None = None,
) -> str | None:
    """Task D: "full gate ... runs automatically when the skill ... is
    shared to a group/org, provisioned, or published" -- a version whose
    only gate run so far was run_fast_path_gate() above never actually ran
    sandbox/ethics/supply_chain/a real license check; scope widening past
    private is exactly the point that gap must close, before the wider
    audience is trusted to see it as verified. No-op for a version that's
    already been through the full gate (a one-time upgrade, not a re-run
    on every subsequent share/provision click) or was never fast-pathed
    in the first place (the ordinary async gate already covers it).

    Resets the version's gate_verdict to 'pending' synchronously, in the
    SAME call that widens scope, before enqueueing the real async run --
    so the moment scope changes, anything reading latest_verdict (Detail.tsx,
    resolver_service, an admin dashboard) sees 'pending', never the stale
    fast-path 'pass', until that real run actually finishes. Reuses the
    'admin_provision' trigger for every scope-widen case (shared/org/
    provisioned/required alike) rather than adding a new trigger value to
    ecosystem_gate_runs' CHECK constraint for one narrow case -- this is a
    policy-driven re-gate regardless of which specific scope widened.

    Deliberately does NOT pass a provision_scope, and run_gate() no longer
    auto-installs/auto-provisions anything for this trigger on pass
    (reverted, product correction, 2026-09-27): re-gating a shared item so
    its recipients can trust the verdict must never itself grant those
    recipients an install or promote the item to an org default -- sharing
    only ever produces an EcosystemShare row a recipient can act on
    themselves; org-wide provisioning stays a distinct, explicit,
    marketplace:provision-only action.

    Returns the newly-enqueued gate run's id, or None on the no-op path
    (already fully gated / never fast-pathed) -- item 2 (2026-09-29 live-
    test round): install_item() uses this as the job id to hand back to
    the client immediately, so a scope-widening install has a real id to
    poll from the very first response instead of nothing at all."""
    db = SessionLocal()
    try:
        latest_run = (
            db.query(EcosystemGateRun)
            .filter(EcosystemGateRun.version_id == version_id)
            .order_by(EcosystemGateRun.started_at.desc())
            .first()
        )
        was_fast_pathed = bool(latest_run and _FAST_PATH_MARKER in latest_run.scanner_version)
    finally:
        db.close()
    if not was_fast_pathed:
        return None

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
        if version is not None:
            version.gate_verdict = "pending"
            db.commit()
    finally:
        db.close()

    return enqueue_gate_run(
        version_id, trigger="admin_provision", org_id=org_id, installed_by=requested_by,
        surfaces=surfaces or [],
    )


def get_latest_gate_run_id(version_id: str) -> str | None:
    """Latest (by started_at) gate run id for a version, or None if the
    version has somehow never been gated at all (shouldn't happen in
    practice -- every version gets a synchronous fast-path run at creation
    time, see run_fast_path_gate() above -- but a caller that needs a job
    id to hand back to a client, e.g. install_item(), must not assume one
    exists)."""
    db = SessionLocal()
    try:
        run = (
            db.query(EcosystemGateRun)
            .filter(EcosystemGateRun.version_id == version_id)
            .order_by(EcosystemGateRun.started_at.desc())
            .first()
        )
        return run.id if run else None
    finally:
        db.close()


def get_job_status(job_id: str, *, caller_org_id: str) -> dict[str, Any] | None:
    """The async-envelope status for job_id (CONTRACTS.md §5) -- job_id IS
    a gate_run_id, no separate jobs table exists (the gate run itself is
    the unit of async work). Returns None if no such job is visible to
    caller_org_id (caller should turn that into a 404).

    Item 2 (2026-09-29 live-test round): factored out of GET
    /ecosystem/jobs/{id} so install_item() can hand back this exact same
    shape in its OWN response too, immediately, rather than the client
    having no id to poll until a separate round trip. This is the single
    source of truth for the verdict -> status mapping -- one gate run
    resolving into two different envelope shapes depending on which
    endpoint asked would be its own new class of bug."""
    from datetime import datetime, timedelta, timezone

    from services.ecosystem.gate_health_service import STUCK_VERIFYING_THRESHOLD_SECONDS

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == job_id).first()
        item = None
        if run is not None:
            version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == run.version_id).first()
            item = db.query(EcosystemItem).filter(EcosystemItem.id == version.item_id).first() if version else None
        if run is None or item is None or not _visible_to_caller(item, caller_org_id):
            return None
        status_map = {"pending": "verifying", "pass": "active", "warn": "warn", "fail": "blocked"}
        stuck_message = None
        if run.verdict == "pending" and run.finished_at is None:
            age = datetime.now(timezone.utc) - run.started_at
            if age > timedelta(seconds=STUCK_VERIFYING_THRESHOLD_SECONDS):
                stuck_message = (
                    f"Still 'verifying' after {int(age.total_seconds())}s — this usually means "
                    "no gate-worker is currently running. An administrator can check "
                    "GET /ecosystem/admin/gate-health."
                )
        queue_position = None
        if run.verdict == "pending" and run.finished_at is None:
            from core.job_queue import ecosystem_gate_job_id, get_ecosystem_gate_queue_position

            queue_position = get_ecosystem_gate_queue_position(ecosystem_gate_job_id(job_id))

        return {
            "job_id": job_id, "status": status_map.get(run.verdict, "verifying"),
            "item_id": None, "version_id": run.version_id, "gate_run_id": job_id, "error": None,
            "stuck_message": stuck_message, "queue_position": queue_position,
        }
    finally:
        db.close()


def _auto_install(
    *, item_id: str, version_id: str, org_id: str, installed_by: str,
    installed_for: str | None, surfaces: list[str], provision_scope: str | None,
) -> None:
    """Post-verdict auto-install hook (Review round following M1, item E).
    CONFIG_AND_PRODUCTS.md §12 point 4's provision_scope -> (scope, origin)
    mapping."""
    from services.ecosystem.installs_service import ConflictError, install

    scope_origin = {
        None: ("private", "created"),
        "private": ("private", "created"),
        "org_default_on": ("provisioned", "provisioned"),
        "required": ("required", "required"),
    }
    scope, origin = scope_origin.get(provision_scope, ("private", "created"))
    target_installed_for = installed_by if provision_scope in (None, "private") else installed_for

    try:
        install(
            item_id=item_id, version_id=version_id, org_id=org_id,
            installed_by=installed_by, installed_for=target_installed_for,
            surfaces=surfaces, scope=scope, origin=origin,
        )
    except ConflictError:
        pass  # already installed (e.g. a re-gated version bump) — not an error


def _bump_own_install_on_pass(*, item_id: str, version_id: str, org_id: str, caller_id: str) -> None:
    """Item 6's "Update my <skill>" -- once a re-gated new version of an
    EXISTING item resolves pass/warn, move the caller's own existing
    install onto it, exactly like update_to_version() already does for a
    caller-initiated version bump (POST /ecosystem/installs/{id}/update),
    just triggered automatically instead of by a second manual call. If
    the caller has no install of this item at all (e.g. an admin who owns
    it but never installed their own copy), there's nothing to bump --
    silently a no-op, never an error; the new version still exists and
    gates correctly either way."""
    from services.ecosystem.installs_service import get_install_for_caller, update_to_version

    install = get_install_for_caller(item_id, org_id, caller_id)
    if install is None:
        return
    try:
        update_to_version(
            install.id, version_id, caller_org_id=org_id, caller_user_id=caller_id, caller_permissions=set(),
        )
    except EcosystemError:
        pass  # best-effort -- the new version itself is unaffected either way


def list_gate_runs(item_id: str, *, caller_org_id: str) -> list[dict[str, Any]]:
    """GET /ecosystem/items/{id}/gate-runs (CONTRACTS.md §9 `GateRun` +
    `Finding`), newest first across every version of item_id.

    caller_org_id: same fix as versions_service.list_versions() -- this had
    no visibility check at all, letting any authenticated caller in any org
    read another org's gate-run/finding history (compliance-sensitive
    detail) by item id."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, caller_org_id):
            raise NotFoundError(f"no such item {item_id!r}")
        version_ids = [
            v.id for v in db.query(EcosystemItemVersion.id).filter(EcosystemItemVersion.item_id == item_id).all()
        ]
        if not version_ids:
            return []
        runs = (
            db.query(EcosystemGateRun)
            .filter(EcosystemGateRun.version_id.in_(version_ids))
            .order_by(EcosystemGateRun.started_at.desc())
            .all()
        )
        result = []
        for index, run in enumerate(runs):
            findings = (
                db.query(EcosystemGateFinding)
                .filter(EcosystemGateFinding.gate_run_id == run.id)
                .all()
            )
            # Real gap found live, 2026-09-29: "queue position while
            # waiting" had nothing to compute it from -- only worth
            # attempting for the newest run (runs is newest-first) while
            # its verdict is still unresolved, so older/finished runs
            # never pay for this lookup. get_ecosystem_gate_queue_position()
            # itself is what actually distinguishes "genuinely still
            # queued" from "already running" (via RQ's own job status,
            # not this row's own started_at -- that column is set at
            # ENQUEUE time by a DB default, not when a worker actually
            # picks the job up, so it's already non-null for every real
            # row and can't be used to tell the two states apart).
            queue_position = None
            if index == 0 and run.verdict == "pending":
                from core.job_queue import ecosystem_gate_job_id, get_ecosystem_gate_queue_position

                queue_position = get_ecosystem_gate_queue_position(ecosystem_gate_job_id(run.id))
            result.append({
                "id": run.id, "version_id": run.version_id, "trigger": run.trigger,
                "verdict": run.verdict, "scanner_version": run.scanner_version,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                # Item 6: real per-stage status/duration (db/migrate.py's
                # Part AD9) so the Verification tab can show live
                # progress, not just the final resolved verdict --
                # is_fast_path lets it explain WHY this run only has 3
                # stages instead of 7 (task D's _FAST_PATH_MARKER, already
                # recorded on scanner_version for this exact purpose).
                "stage_timings": run.stage_timings or {},
                "is_fast_path": _FAST_PATH_MARKER in (run.scanner_version or ""),
                "queue_position": queue_position,
                "findings": [
                    {
                        "stage": f.stage, "severity": f.severity, "code": f.code,
                        "message": f.message, "details": f.details or {},
                    }
                    for f in findings
                ],
            })
        return result
    finally:
        db.close()


def average_stage_durations_ms(*, is_fast_path: bool, sample_size: int = 20) -> dict[str, int]:
    """Item 6's "estimated time remaining, based on recent average stage
    durations": a simple recency-windowed mean over the last `sample_size`
    resolved runs of the SAME path (fast path and full gate have entirely
    different stage sets/costs, so they're never averaged together).
    Deliberately not a real statistics feature (no percentiles/decay) --
    the user's own spec only asked for "an estimated time remaining based
    on recent average stage durations", nothing fancier. Global across
    orgs (gate-run timing is an operational signal, not tenant-private
    data), matching gate_health_service.get_health()'s own scope."""
    db = SessionLocal()
    try:
        query = db.query(EcosystemGateRun.stage_timings).filter(EcosystemGateRun.finished_at.isnot(None))
        query = (
            query.filter(EcosystemGateRun.scanner_version.like(f"%{_FAST_PATH_MARKER}%"))
            if is_fast_path
            else query.filter(EcosystemGateRun.scanner_version.notlike(f"%{_FAST_PATH_MARKER}%"))
        )
        rows = query.order_by(EcosystemGateRun.started_at.desc()).limit(sample_size).all()
    finally:
        db.close()

    totals: dict[str, list[int]] = {}
    for (timings,) in rows:
        for stage, info in (timings or {}).items():
            duration = info.get("duration_ms")
            if isinstance(duration, (int, float)) and info.get("status") != "skipped":
                totals.setdefault(stage, []).append(duration)

    return {stage: round(sum(durations) / len(durations)) for stage, durations in totals.items() if durations}


def list_recent_findings(*, org_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """GET /ecosystem/gate-findings (task F-13's AdminGateFindings.tsx) —
    the org's own items' most recent findings, newest gate-run first.
    Scoped to org_id (plus org-independent builtin items, which every org's
    admin can legitimately see the gate history of) so one org's admin can
    never see another org's private items' findings."""
    db = SessionLocal()
    try:
        item_ids = [
            i.id for i in db.query(EcosystemItem.id).filter(
                (EcosystemItem.org_id == org_id) | (EcosystemItem.scope == "builtin")
            ).all()
        ]
        if not item_ids:
            return []
        version_ids = [
            v.id for v in db.query(EcosystemItemVersion.id).filter(EcosystemItemVersion.item_id.in_(item_ids)).all()
        ]
        if not version_ids:
            return []
        runs = (
            db.query(EcosystemGateRun)
            .filter(EcosystemGateRun.version_id.in_(version_ids))
            .order_by(EcosystemGateRun.started_at.desc())
            .limit(limit)
            .all()
        )
        version_to_item = {
            v.id: v.item_id for v in db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id.in_(version_ids)).all()
        }
        result = []
        for run in runs:
            findings = db.query(EcosystemGateFinding).filter(EcosystemGateFinding.gate_run_id == run.id).all()
            if not findings:
                continue
            result.append({
                "gate_run_id": run.id, "item_id": version_to_item.get(run.version_id),
                "version_id": run.version_id, "trigger": run.trigger, "verdict": run.verdict,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "findings": [
                    {"stage": f.stage, "severity": f.severity, "code": f.code, "message": f.message}
                    for f in findings
                ],
            })
        return result
    finally:
        db.close()
