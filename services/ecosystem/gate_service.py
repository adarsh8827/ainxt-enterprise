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

from typing import Any

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
        gate_run_id = row.id
    finally:
        db.close()

    from core.job_queue import enqueue_ecosystem_gate_job
    from core.logger import logger

    try:
        enqueue_ecosystem_gate_job(
            gate_run_id,
            installed_by=installed_by, installed_for=installed_for, org_id=org_id,
            surfaces=surfaces, provision_scope=provision_scope,
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
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    manifest, files = decode_envelope(store.get(object_key))

    findings: list[Finding] = []
    stage_verdicts: dict[str, str] = {}

    for stage_name, result in (
        ("manifest", manifest_stage.run(manifest, files)),
        ("license", license_stage.run(license, relaxed=(license_tier == "relaxed"))),
        ("static_safety", static_safety_stage.run(files, manifest_text=str(manifest))),
        ("supply_chain", supply_chain_stage.run()),
    ):
        stage_verdicts[stage_name] = result.verdict
        findings.extend(result.findings)

    # Cache short-circuit before the expensive stages (task B-9) — but only
    # if stages 1-4 haven't already doomed this to 'fail' (no point invoking
    # the sandbox on something that's already blocked on license/manifest).
    already_failed = stage_verdicts.get("license") == "fail" or "fail" in stage_verdicts.values()
    cached_verdict = None if already_failed else _lookup_cached_verdict(content_hash_value, _SCANNER_VERSION, gate_run_id)

    if already_failed:
        stage_verdicts["sandbox"] = stage_verdicts["ethics"] = stage_verdicts["mcp_connector"] = "fail"
    elif cached_verdict is not None:
        stage_verdicts["sandbox"] = stage_verdicts["ethics"] = stage_verdicts["mcp_connector"] = cached_verdict
        findings.append(Finding(
            stage="sandbox", severity="info", code="CACHE_HIT",
            message=f"reusing cached verdict for content_hash={content_hash_value[:12]}...",
        ))
    else:
        sandbox_result = sandbox_stage.run(files, manifest)
        stage_verdicts["sandbox"] = sandbox_result.verdict
        findings.extend(sandbox_result.findings)

        ethics_result = run_ethics_stage(manifest)
        stage_verdicts["ethics"] = ethics_result.verdict
        findings.extend(ethics_result.findings)

        mcp_result = mcp_connector_stage.run(item_type, manifest)
        stage_verdicts["mcp_connector"] = mcp_result.verdict
        findings.extend(mcp_result.findings)

    overall = _aggregate(stage_verdicts)

    db = SessionLocal()
    try:
        gate_run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        gate_run.verdict = overall
        from datetime import datetime, timezone

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
    elif trigger == "admin_provision" and overall in ("pass", "warn") and installed_by is not None:
        # ensure_full_gate_for_scope_widen() below enqueues this trigger
        # with provision_scope="org_default_on" once an admin
        # shares/widens a fast-pathed item's scope -- once the real full
        # gate actually passes, auto-provision it org-wide the same way
        # a creation-time provision_scope would (seeds one 'provisioned'
        # install; config_service.ensure_provisioned()'s existing lazy
        # per-user rollout takes it from there for the rest of the org).
        _auto_install(
            item_id=item_id, version_id=version_id, org_id=org_id or "default",
            installed_by=installed_by, installed_for=installed_for,
            surfaces=surfaces or [], provision_scope=provision_scope,
        )

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

    findings: list[Finding] = []
    manifest_result = manifest_stage.run(manifest, files)
    findings.extend(manifest_result.findings)
    safety_result = static_safety_stage.run_fast_path(files, manifest_text=manifest_text)
    findings.extend(safety_result.findings)

    stage_verdicts = {"manifest": manifest_result.verdict, "static_safety": safety_result.verdict}
    if "pending" in stage_verdicts.values():
        overall = "pending"
    elif "fail" in stage_verdicts.values():
        overall = "fail"
    elif "warn" in stage_verdicts.values():
        overall = "warn"
    else:
        overall = "pass"

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        gate_run = EcosystemGateRun(
            version_id=version_id, trigger=trigger, verdict=overall,
            scanner_version=f"{_SCANNER_VERSION} ({_FAST_PATH_MARKER})",
            started_at=now, finished_at=now,
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
) -> None:
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

    provision_scope="org_default_on" on the enqueued run (product decision,
    user-confirmed): once THIS real full gate actually passes/warns,
    run_gate()'s own post-verdict hook auto-provisions the item org-wide
    the same way a creation-time provision_scope would -- an admin
    widening scope past private is itself the trust signal that makes
    this item an org default, once (and only once) it's actually verified,
    not before."""
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
        return

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
        if version is not None:
            version.gate_verdict = "pending"
            db.commit()
    finally:
        db.close()

    enqueue_gate_run(
        version_id, trigger="admin_provision", org_id=org_id, installed_by=requested_by,
        surfaces=surfaces or [], provision_scope="org_default_on",
    )


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
        for run in runs:
            findings = (
                db.query(EcosystemGateFinding)
                .filter(EcosystemGateFinding.gate_run_id == run.id)
                .all()
            )
            result.append({
                "id": run.id, "version_id": run.version_id, "trigger": run.trigger,
                "verdict": run.verdict, "scanner_version": run.scanner_version,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
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
