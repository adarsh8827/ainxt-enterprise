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
from services.ecosystem.gate import license_stage, manifest_stage, mcp_connector_stage, sandbox_stage, static_safety_stage, supply_chain_stage
from services.ecosystem.gate.ethics_stage import run as run_ethics_stage
from services.ecosystem.gate.types import Finding
from services.ecosystem.versions_service import decode_envelope
from store.ecosystem_object_storage import get_ecosystem_object_storage

_SCANNER_VERSION = "2026.09.1"

# Triggers for which a pass/warn verdict auto-installs the version's
# creator (Review round following M1, item E) — never for legacy-bridge
# backfills or builtin seeding, neither of which has a single "creator" in
# the same sense.
_AUTO_INSTALL_TRIGGERS = ("ui_add", "chat_create")


def enqueue_gate_run(
    version_id: str,
    trigger: str,
    *,
    installed_by: str | None = None,
    installed_for: str | None = None,
    org_id: str | None = None,
    surfaces: list[str] | None = None,
    provision_scope: str | None = None,
) -> str:
    """Create a gate_runs row for version_id and enqueue it to
    ecosystem_gate_queue for the dedicated gate-worker to actually run
    (see module docstring). Returns the gate_run id immediately; the row
    stays verdict='pending' until the worker calls run_gate().

    installed_by/installed_for/org_id/surfaces/provision_scope are only
    used for triggers in _AUTO_INSTALL_TRIGGERS — task B-4/B-22's callers
    never pass them (their triggers never auto-install regardless).

    No thread fallback if Redis/rq is unavailable (core/job_queue.py's
    documented platform-wide convention) — enqueue_job() raises
    RuntimeError, and the gate_runs row this created is left at 'pending'
    for a future retry rather than silently gating in this process.
    """
    db = SessionLocal()
    try:
        row = EcosystemGateRun(
            version_id=version_id,
            trigger=trigger,
            verdict="pending",
            scanner_version=_SCANNER_VERSION,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        gate_run_id = row.id
    finally:
        db.close()

    from core.job_queue import enqueue_ecosystem_gate_job

    enqueue_ecosystem_gate_job(
        gate_run_id,
        installed_by=installed_by, installed_for=installed_for, org_id=org_id,
        surfaces=surfaces, provision_scope=provision_scope,
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
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    manifest, files = decode_envelope(store.get(object_key))

    findings: list[Finding] = []
    stage_verdicts: dict[str, str] = {}

    for stage_name, result in (
        ("manifest", manifest_stage.run(manifest, files)),
        ("license", license_stage.run(license)),
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

    return {"gate_run_id": gate_run_id, "verdict": overall, "stage_verdicts": stage_verdicts}


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
