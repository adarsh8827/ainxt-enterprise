# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM ROUTER — /ecosystem/*
#
# Thin request/response glue only, per the standing rule (no business logic
# here — every handler parses the request, calls a services/ecosystem/
# function, and serializes the result). Covers tasks B-6, B-7, B-10, B-19,
# and the require/unrequire actions added in the Review round following M1.
#
# Not yet implemented in this router (later milestones): GET /ecosystem/
# items, GET /ecosystem/items/{id}, GET /ecosystem/config, GET /ecosystem/
# capabilities (M3, need the resolver/config_service — task B-11/B-12),
# drafts endpoints (M5, task B-14), admin sources/policy CRUD (no backing
# table exists yet, policy_service.py's own module docstring), OpenAPI
# generation/contract tests (task B-17, M3).
# ============================================================

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth.dependencies import get_current_user
from auth.rbac import get_all_permissions, require_permission
from services.ecosystem import create_service, icon_service, installs_service, policy_service
from services.ecosystem.errors import EcosystemError, LicenseNotAllowedError, NotFoundError, PolicyForbiddenError
from services.ecosystem.installs_service import ConflictError

router = APIRouter(tags=["ecosystem"])


def _caller_context(current_user: dict) -> tuple[str, str, set[str]]:
    user_id = current_user.get("sub") or current_user.get("user_id") or current_user.get("id") or ""
    org_id = current_user.get("org_id") or "default"
    permissions = set(get_all_permissions(current_user.get("role", "viewer")))
    return user_id, org_id, permissions


def _handle_ecosystem_error(exc: EcosystemError) -> None:
    if isinstance(exc, LicenseNotAllowedError):
        raise HTTPException(status_code=422, detail={
            "code": "LICENSE_NOT_ALLOWED", "message": str(exc), "stage": exc.stage,
        })
    if isinstance(exc, PolicyForbiddenError):
        raise HTTPException(status_code=403, detail={"code": "POLICY_FORBIDDEN", "message": str(exc)})
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(exc)})
    raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)})


# ── Create (task B-6) ────────────────────────────────────────────────────

class CreateWriteRequest(BaseModel):
    create_via: str = "write"
    item_type: str
    namespace: str
    display_name: str
    description: str
    category: str
    tags: Optional[list[str]] = None
    license: str = "MIT"
    content: dict[str, Any]
    surfaces: list[str] = []
    provision_scope: Optional[str] = None


@router.post("/ecosystem/items", status_code=202)
def create_item(body: CreateWriteRequest, current_user: dict = Depends(get_current_user)):
    """Only the 'write' payload shape this pass — 'upload' is its own
    multipart endpoint below (POST /ecosystem/items/upload) since FastAPI
    can't dispatch JSON vs multipart bodies on one route by a body field;
    'import' has no fetcher wired up yet (create_service.create_via_import's
    own documented gap)."""
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return create_service.create_via_write(
            org_id=org_id, created_by=user_id, item_type=body.item_type,
            namespace=body.namespace, display_name=body.display_name,
            description=body.description, category=body.category, tags=body.tags,
            license=body.license, content=body.content, surfaces=body.surfaces,
            provision_scope=body.provision_scope, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/items/upload", status_code=202)
def upload_item(
    file: UploadFile = File(...),
    item_type: str = Form(...),
    namespace: str = Form(...),
    category: str = Form(...),
    surfaces: str = Form(""),  # comma-separated — multipart forms have no native array type
    provision_scope: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
):
    user_id, org_id, permissions = _caller_context(current_user)
    zip_bytes = file.file.read()
    surfaces_list = [s for s in surfaces.split(",") if s]
    try:
        return create_service.create_via_upload(
            org_id=org_id, created_by=user_id, item_type=item_type, namespace=namespace,
            category=category, zip_bytes=zip_bytes, surfaces=surfaces_list,
            provision_scope=provision_scope, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── Icon upload (task B-7) ───────────────────────────────────────────────

@router.post("/ecosystem/uploads/icon")
def upload_icon(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = file.file.read()
    try:
        icon_url = icon_service.upload_icon(content, content_type=file.content_type or "")
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
        return  # unreachable, satisfies type checkers
    return {"icon_url": icon_url}


# ── Install lifecycle (task B-10) ────────────────────────────────────────

class InstallRequest(BaseModel):
    version_id: str
    surfaces: list[str] = []
    scope: str = "private"
    origin: str = "added"


@router.post("/ecosystem/items/{item_id}/install", status_code=201)
def install_item(item_id: str, body: InstallRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, _ = _caller_context(current_user)
    installed_for = user_id if body.scope in ("private", "provisioned", "required") else None
    try:
        return installs_service.install(
            item_id=item_id, version_id=body.version_id, org_id=org_id,
            installed_by=user_id, installed_for=installed_for, surfaces=body.surfaces,
            scope=body.scope, origin=body.origin,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/installs/{install_id}/uninstall", status_code=204)
def uninstall_item(install_id: str):
    try:
        installs_service.uninstall(install_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class SetEnabledRequest(BaseModel):
    enabled: bool


@router.post("/ecosystem/installs/{install_id}/set-enabled")
def set_install_enabled(install_id: str, body: SetEnabledRequest):
    try:
        return installs_service.set_enabled(install_id, body.enabled)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class UpdateVersionRequest(BaseModel):
    version_id: str


@router.post("/ecosystem/installs/{install_id}/update")
def update_install(install_id: str, body: UpdateVersionRequest):
    try:
        return installs_service.update_to_version(install_id, body.version_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/installs/{install_id}/rollback")
def rollback_install(install_id: str, body: UpdateVersionRequest):
    try:
        return installs_service.rollback(install_id, body.version_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.get("/ecosystem/installs")
def list_installs(item_type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    user_id, org_id, _ = _caller_context(current_user)
    installs, has_any = installs_service.list_installs(org_id, user_id, item_type)
    # legacy_items (task C, Review round following M1) requires the
    # legacy-bridge read path (services/ecosystem/legacy_bridge.py) to be
    # wired in with org-scoped visibility — not done this pass; returned
    # as an always-empty array so the response shape matches CONTRACTS.md
    # §9 exactly rather than omitting the field.
    return {"installs": installs, "legacy_items": [], "has_any": has_any, "next_cursor": None}


# ── Sharing / reporting (task B-19) ──────────────────────────────────────

class ShareRequest(BaseModel):
    install_id: str
    shared_with_type: str
    shared_with_id: str


@router.post("/ecosystem/items/{item_id}/share", status_code=201)
def share_item(item_id: str, body: ShareRequest, current_user: dict = Depends(require_permission("marketplace:share"))):
    try:
        return policy_service.share(body.install_id, body.shared_with_type, body.shared_with_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/shares/{share_id}/unshare", status_code=204)
def unshare_item(share_id: str, current_user: dict = Depends(get_current_user)):
    try:
        policy_service.unshare(share_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class ReportRequest(BaseModel):
    reason: str


@router.post("/ecosystem/items/{item_id}/report", status_code=201)
def report_item(item_id: str, body: ReportRequest, current_user: dict = Depends(get_current_user)):
    # Deliberately no permission dependency — reporting a suspect item is
    # never gated (task B-19), any authenticated user may report.
    user_id, _, _ = _caller_context(current_user)
    try:
        return policy_service.report(item_id, user_id, body.reason)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── Deprecate / delete-draft (task B-10) ─────────────────────────────────

@router.post("/ecosystem/items/{item_id}/deprecate")
def deprecate_item(item_id: str, current_user: dict = Depends(get_current_user)):
    from db.database import SessionLocal
    from db.models import EcosystemItem

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such item"})
        user_id, _, permissions = _caller_context(current_user)
        if "marketplace:admin_sources" not in permissions:
            # Ownership check deferred — no created_by column exists on
            # ecosystem_items yet (a real, disclosed schema gap); admin-
            # only enforcement is what's actually enforced this pass.
            raise HTTPException(status_code=403, detail={"code": "POLICY_FORBIDDEN", "message": "deprecate requires marketplace:admin_sources this phase"})
        item.status = "deprecated"
        from datetime import datetime, timezone

        item.deprecated_at = datetime.now(timezone.utc)
        item.deprecated_by = user_id
        db.commit()
        return {"item_id": item_id, "status": "deprecated"}
    finally:
        db.close()


# ── Admin: force-disable / unyank / require / unrequire (task B-19 + item F) ──

@router.post("/ecosystem/items/{item_id}/force-disable")
def force_disable_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    try:
        policy_service.force_disable(item_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
    return {"item_id": item_id, "status": "yanked"}


@router.post("/ecosystem/items/{item_id}/unyank")
def unyank_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    try:
        policy_service.unyank(item_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
    return {"item_id": item_id, "status": "active"}


@router.post("/ecosystem/items/{item_id}/require")
def require_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:provision"))):
    _, org_id, _ = _caller_context(current_user)
    count = policy_service.require_item(item_id, org_id)
    return {"item_id": item_id, "promoted_installs": count}


@router.post("/ecosystem/items/{item_id}/unrequire")
def unrequire_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:provision"))):
    _, org_id, _ = _caller_context(current_user)
    count = policy_service.unrequire_item(item_id, org_id)
    return {"item_id": item_id, "demoted_installs": count}


# ── Admin: featured overrides (task B-19) ────────────────────────────────

class FeaturedOverrideRequest(BaseModel):
    featured: bool


@router.put("/ecosystem/featured/{item_id}")
def set_featured(item_id: str, body: FeaturedOverrideRequest, current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    _, org_id, _ = _caller_context(current_user)
    user_id, _, _ = _caller_context(current_user)
    return policy_service.set_featured_override(org_id, item_id, body.featured, user_id)


@router.delete("/ecosystem/featured/{item_id}", status_code=204)
def delete_featured(item_id: str, current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    _, org_id, _ = _caller_context(current_user)
    policy_service.delete_featured_override(org_id, item_id)


# ── Jobs (async envelope, CONTRACTS.md §5) ───────────────────────────────

@router.get("/ecosystem/jobs/{job_id}")
def get_job(job_id: str):
    """job_id IS the gate_run_id this pass (no separate jobs table exists —
    the gate run itself is the unit of async work). As of item 2 (pre-M3)
    the gate genuinely runs asynchronously — a dedicated gate-worker
    process consumes ecosystem_gate_queue (see docs/ecosystem/design/
    LLD/gate.md) — so 'pending' here can mean either "still queued/
    running" or "no worker has ever picked this up." A pending run whose
    started_at is older than gate_health_service's stuck-verifying
    threshold gets an explicit `stuck_message` rather than leaving the
    caller to guess why nothing has resolved (item 2's follow-up)."""
    from datetime import datetime, timedelta, timezone

    from db.database import SessionLocal
    from db.models import EcosystemGateRun
    from services.ecosystem.gate_health_service import STUCK_VERIFYING_THRESHOLD_SECONDS

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == job_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such job"})
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
        return {
            "job_id": job_id, "status": status_map.get(run.verdict, "verifying"),
            "item_id": None, "version_id": run.version_id, "gate_run_id": job_id, "error": None,
            "stuck_message": stuck_message,
        }
    finally:
        db.close()


# ── Admin: gate-worker health (item 2's follow-up, pre-M3) ──────────────
# Not yet folded into GET /ecosystem/config (task B-12/M3 — that endpoint
# doesn't exist yet) — a standalone admin endpoint so this signal is
# visible now rather than waiting on the resolver/config milestone.

@router.get("/ecosystem/admin/gate-health")
def get_gate_health(current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    from services.ecosystem.gate_health_service import get_health

    return get_health()
