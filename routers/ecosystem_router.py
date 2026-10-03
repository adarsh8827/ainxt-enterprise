# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM ROUTER — /ecosystem/*
#
# Thin request/response glue only, per the standing rule (no business logic
# here — every handler parses the request, calls a services/ecosystem/
# function, and serializes the result). Covers tasks B-6, B-7, B-10, B-19,
# and the require/unrequire actions added in the Review round following M1.
#
# GET /ecosystem/config and GET /ecosystem/capabilities landed at M3
# (task B-11/B-12). List/detail/versions/gate-runs, delete-draft, and
# admin policy/gate-findings landed at M4 (this milestone's own backend
# prerequisite work — see docs/ecosystem/design/CHANGELOG.md). Still not
# implemented: drafts endpoints (M5, task B-14), admin sources CRUD (no
# backing table/UI task needs it this phase), OpenAPI generation/contract
# tests (task B-17, already landed separately — see generate_openapi.py).
# ============================================================

from __future__ import annotations

from typing import Any, Optional

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Header, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.dependencies import get_current_user
from auth.rbac import get_all_permissions, require_permission
from core.config import DEFAULT_ORG_ID
from services.ecosystem import (
    config_service, create_service, drafts_service, gate_service, icon_service, idempotency_service,
    installs_service, items_service, policy_service, resolver_service, versions_service,
)
from services.ecosystem.errors import (
    EcosystemError, ImportFetchError, ImportRateLimitedError,
    LicenseAcknowledgementRequiredError, LicenseNotAllowedByOrgPolicyError,
    LicenseNotAllowedError, NeutralityViolationError, NotFoundError,
    PluginComposeInvalidError, PolicyForbiddenError,
)
from services.ecosystem.installs_service import ConflictError
from services.ecosystem.compatibility import CHAT, enforce_compatibility_on_surfaces

# Every route in this router requires authentication by default -- added
# after a real gap was found where 4 install-lifecycle endpoints (uninstall/
# set-enabled/update/rollback) and GET /ecosystem/jobs/{id} declared no
# `current_user: Depends(get_current_user)` at all, letting a fully
# unauthenticated caller mutate any org's install or read any org's gate
# job by UUID. This router-level dependency is the backstop: even if a
# future endpoint here forgets its own `current_user` parameter, FastAPI
# still runs get_current_user (cached per-request, so a route that ALSO
# declares its own `current_user: dict = Depends(get_current_user)`
# parameter -- most of them, since they need the actual payload, not just
# the auth check -- never calls it twice). No route in this router is
# exempt; every one of them handles caller-specific or org-scoped data.
router = APIRouter(tags=["ecosystem"], dependencies=[Depends(get_current_user)])


def _caller_context(current_user: dict) -> tuple[str, str, set[str]]:
    user_id = current_user.get("sub") or current_user.get("user_id") or current_user.get("id") or ""
    org_id = current_user.get("org_id") or DEFAULT_ORG_ID
    permissions = set(get_all_permissions(current_user.get("role", "viewer")))
    return user_id, org_id, permissions


def _handle_ecosystem_error(exc: EcosystemError) -> None:
    if isinstance(exc, LicenseNotAllowedError):
        raise HTTPException(status_code=422, detail={
            "code": "LICENSE_NOT_ALLOWED", "message": str(exc), "stage": exc.stage,
        })
    if isinstance(exc, LicenseAcknowledgementRequiredError):
        # `reason` nested under `details` (not top-level) to match
        # EcosystemApiError's own constructor contract on the client side
        # (packages/ecosystem-ui/src/client/RealEcosystemClient.ts reads
        # detail.details, not arbitrary top-level fields).
        raise HTTPException(status_code=400, detail={
            "code": "LICENSE_ACKNOWLEDGEMENT_REQUIRED", "message": str(exc),
            "details": {"reason": exc.reason, "declared_license": exc.declared_license},
        })
    if isinstance(exc, LicenseNotAllowedByOrgPolicyError):
        raise HTTPException(status_code=422, detail={
            "code": "LICENSE_NOT_ALLOWED_BY_ORG_POLICY", "message": str(exc),
            "details": {"declared_license": exc.declared_license},
        })
    if isinstance(exc, PolicyForbiddenError):
        raise HTTPException(status_code=403, detail={"code": "POLICY_FORBIDDEN", "message": str(exc)})
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(exc)})
    if isinstance(exc, ImportRateLimitedError):
        raise HTTPException(status_code=429, detail={
            "code": "IMPORT_RATE_LIMITED", "message": str(exc), "retry_after": exc.retry_after,
        })
    if isinstance(exc, ImportFetchError):
        raise HTTPException(status_code=502, detail={"code": "IMPORT_FETCH_FAILED", "message": str(exc)})
    if isinstance(exc, NeutralityViolationError):
        raise HTTPException(status_code=422, detail={"code": "NEUTRALITY_VIOLATION", "message": str(exc)})
    if isinstance(exc, PluginComposeInvalidError):
        raise HTTPException(status_code=422, detail={
            "code": "PLUGIN_COMPOSE_INVALID", "message": str(exc),
            "details": {"reason_code": exc.code, **exc.details},
        })
    raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)})


# ── Create (task B-6) ────────────────────────────────────────────────────

class CreateWriteRequest(BaseModel):
    create_via: str = "write"
    item_type: str
    namespace: str
    display_name: str = ""
    description: str = ""
    category: str
    tags: Optional[list[str]] = None
    license: str = "MIT"
    content: dict[str, Any] = {}
    surfaces: list[str] = []
    provision_scope: Optional[str] = None
    # create_via='import' only (task I, pre-M3): kind='github_repo'
    # ("owner/repo", "owner/repo@branch_or_sha", or -- starter-catalog
    # subdirectory extension -- "owner/repo[@branch_or_sha]#path/to/skill"
    # as ref) or kind='well_known' ("domain/skill_slug" as ref).
    kind: Optional[str] = None
    ref: Optional[str] = None
    # Tiered license policy (task C, ECOSYSTEM_PLAN.md §11.2) -- 'write'
    # only; ignored by create_via='import', which is always Tier 1/strict.
    license_acknowledged: bool = False
    self_authored: bool = False


@router.post("/ecosystem/items", status_code=202)
def create_item(body: CreateWriteRequest, current_user: dict = Depends(get_current_user)):
    """'write' and 'import' (task I, pre-M3: kind='github_repo'/'well_known')
    payload shapes — 'upload' is its own multipart endpoint below
    (POST /ecosystem/items/upload) since FastAPI can't dispatch JSON vs
    multipart bodies on one route by a body field."""
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        if body.create_via == "import":
            if not body.kind or not body.ref:
                raise EcosystemError("create_via='import' requires 'kind' and 'ref'")
            return create_service.create_via_import(
                org_id=org_id, created_by=user_id, item_type=body.item_type,
                namespace=body.namespace, category=body.category,
                kind=body.kind, ref=body.ref, surfaces=body.surfaces,
                license=body.license, provision_scope=body.provision_scope,
                caller_permissions=permissions,
            )
        return create_service.create_via_write(
            org_id=org_id, created_by=user_id, item_type=body.item_type,
            namespace=body.namespace, display_name=body.display_name,
            description=body.description, category=body.category, tags=body.tags,
            license=body.license, content=body.content, surfaces=body.surfaces,
            provision_scope=body.provision_scope, caller_permissions=permissions,
            license_acknowledged=body.license_acknowledged, self_authored=body.self_authored,
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
    license_acknowledged: bool = Form(False),
    self_authored: bool = Form(False),
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
            license_acknowledged=license_acknowledged, self_authored=self_authored,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── New version of an EXISTING item (item 6, "Update my <skill>") ───────
# Never creates a new EcosystemItem row -- an immutable version, re-gated,
# on the item the caller already owns (or administers). Two payload
# shapes, mirroring POST /ecosystem/items' own write-vs-upload split.

class NewVersionRequest(BaseModel):
    content: dict[str, Any]
    license: Optional[str] = None
    # Tiered license policy (task C, ECOSYSTEM_PLAN.md §11.2).
    license_acknowledged: bool = False
    self_authored: bool = False


@router.post("/ecosystem/items/{item_id}/new-version", status_code=202)
def new_version_item(item_id: str, body: NewVersionRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return create_service.add_version_to_existing_item(
            item_id=item_id, org_id=org_id, updated_by=user_id, caller_permissions=permissions,
            content=body.content, license=body.license,
            license_acknowledged=body.license_acknowledged, self_authored=body.self_authored,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/items/{item_id}/new-version/upload", status_code=202)
def new_version_item_upload(
    item_id: str, file: UploadFile = File(...),
    license_acknowledged: bool = Form(False), self_authored: bool = Form(False),
    current_user: dict = Depends(get_current_user),
):
    user_id, org_id, permissions = _caller_context(current_user)
    zip_bytes = file.file.read()
    try:
        return create_service.add_version_to_existing_item_from_upload(
            item_id=item_id, org_id=org_id, updated_by=user_id, caller_permissions=permissions, zip_bytes=zip_bytes,
            license_acknowledged=license_acknowledged, self_authored=self_authored,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── Plugin compose (Plugins phase, docs/ecosystem/PLUGINS_PHASE_PLAN.md
# item 1; contract in CONTRACTS.md §20) — adds a new version to an
# EXISTING plugin item whose manifest["parts"] is the given composition,
# validated synchronously here (fast, friendly PLUGIN_COMPOSE_INVALID)
# before ever creating a version/dispatching the gate, which then
# independently re-validates the same composition (manifest_stage.py's
# plugin branch) as defense in depth. A brand-new plugin item is created
# via the existing POST /ecosystem/items (create_via="write",
# item_type="plugin", content={"parts": ...}) -- no second creation path
# is needed for that case, matching the Connectors phase Stage 3 finding
# that the general item-creation endpoint already covers a new item once
# its manifest carries the right keys.

class PluginComposeRequest(BaseModel):
    parts: dict[str, list[str]]


@router.post("/ecosystem/items/{item_id}/plugin-compose", status_code=202)
def plugin_compose(item_id: str, body: PluginComposeRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        from services.ecosystem.plugin_manifest import CompositionError, validate_composition

        try:
            validate_composition(body.parts, org_id=org_id)
        except CompositionError as exc:
            raise PluginComposeInvalidError(str(exc), code=exc.code, details=exc.details) from exc
        return create_service.add_version_to_existing_item(
            item_id=item_id, org_id=org_id, updated_by=user_id, caller_permissions=permissions,
            content={"parts": body.parts},
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── List / detail / versions / gate-runs (CONTRACTS.md §7/§9, M4) ───────

@router.get("/ecosystem/items")
def list_items(
    response: Response,
    item_type: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
    q: Optional[str] = None,
    category: Optional[list[str]] = Query(None, alias="category[]"),
    trust: Optional[list[str]] = Query(None, alias="trust[]"),
    status: Optional[list[str]] = Query(None, alias="status[]"),
    verdict: Optional[list[str]] = Query(None, alias="verdict[]"),
    surface: Optional[list[str]] = Query(None, alias="surface[]"),
    sort: str = "featured",
    current_user: dict = Depends(get_current_user),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    user_id, org_id, permissions = _caller_context(current_user)
    result = items_service.list_items(
        caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
        item_type=item_type, cursor=cursor, limit=limit, q=q, category=category,
        trust=trust, status=status, verdict=verdict, surface=surface, sort=sort,
    )
    # Catalog-checking round (2026-09-28), section 6 (performance for
    # large catalogs): ETag on the list response so a client that
    # already has this exact page doesn't re-transfer it. The response
    # is per-caller (install/allowed_actions differ by org/user), so the
    # cache directive is "private" (this exact browser only), never a
    # shared/CDN cache -- the hash already covers every caller-specific
    # field, so an ETag match genuinely means "identical for THIS
    # caller," not just "identical catalog content."
    import hashlib
    import json as _json

    etag = '"' + hashlib.sha256(_json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:32] + '"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=15"
    if if_none_match == etag:
        response.status_code = 304
        return None
    return result


@router.get("/ecosystem/items/{item_id}/versions")
def get_item_versions(item_id: str, current_user: dict = Depends(get_current_user)):
    _, org_id, _ = _caller_context(current_user)
    try:
        return {"versions": versions_service.list_versions(item_id, caller_org_id=org_id)}
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.get("/ecosystem/items/{item_id}/gate-runs")
def get_item_gate_runs(item_id: str, current_user: dict = Depends(get_current_user)):
    _, org_id, _ = _caller_context(current_user)
    try:
        runs = gate_service.list_gate_runs(item_id, caller_org_id=org_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
        return
    # Item 6: average recent per-stage durations for whichever path the
    # LATEST run actually took (fast path vs. full gate have unrelated
    # stage sets/costs) -- lets the Verification tab show a live ETA
    # while a run is still in progress, without a second endpoint.
    is_fast_path = bool(runs and runs[0]["is_fast_path"])
    averages = gate_service.average_stage_durations_ms(is_fast_path=is_fast_path) if runs else {}
    return {"gate_runs": runs, "average_stage_durations_ms": averages}


@router.get("/ecosystem/search/live")
def search_live_items(q: str = "", current_user: dict = Depends(get_current_user)):
    """Discover's "From the web" live search (external sources plan §10;
    real gap found live, 2026-09-29 -- the flags existed with nothing
    behind them). Returns pointer-shaped results only, never full skill
    content; installing one reuses the exact same POST /ecosystem/items
    (create_via="import", kind="github_repo", ref=<result's own "ref">)
    a manual "Import from URL" already uses, which already runs the real
    per-skill license + neutrality check before creating anything.
    Off (empty list, never an error) unless BOTH the instance-wide
    ECOSYSTEM_LIVE_SOURCES flag and this org's own live_sources_enabled
    policy toggle are true.
    """
    _, org_id, _ = _caller_context(current_user)
    from services.ecosystem.live_search_service import search_live

    try:
        results = search_live(q, org_id=org_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
        return
    return {"results": results}


@router.get("/ecosystem/items/{item_id:path}")
def get_item_detail(item_id: str, current_user: dict = Depends(get_current_user)):
    """CONTRACTS.md §15: accepts either the UUID id or the namespace
    string, and namespaces are always publisher/name-shaped -- containing
    a literal "/". A plain `{item_id}` path parameter never receives that
    slash: Starlette/uvicorn decode a URL-encoded %2F into a literal `/`
    before route matching, so GET /ecosystem/items/acme%2Ffoo would 404 at
    the routing layer before ever reaching this handler (confirmed via a
    real HTTP round-trip against this router, not just unit-tested at the
    service-layer). `{item_id:path}` matches the rest of the path greedily,
    including embedded slashes -- registered after the two GET sub-routes
    above so `.../versions` and `.../gate-runs` still match first (route
    order matters for a greedy path converter; every other item_id route
    below is POST, a different method, so it can't collide regardless of
    registration order).
    """
    user_id, org_id, permissions = _caller_context(current_user)
    result = items_service.get_item(
        item_id, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
    )
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"no such item {item_id!r}"})
    return result


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


# ── Create-with-AI drafts (task B-14, M5) ────────────────────────────────
# Idempotency-Key required (CONTRACTS.md §4) -- missing it is a client bug
# surfaced as a real 400, not silently tolerated. A cache hit here guards
# against creating a SECOND draft row on retry; it does not re-play the
# SSE stream verbatim (streams aren't cacheable the way a plain JSON
# response is) -- a retried POST with an already-generated draft just
# streams that same draft's current state as a single "assembled" frame
# instead of re-running the whole generation pipeline a second time.

class CreateDraftRequest(BaseModel):
    item_type: str = "skill"
    intent: str


def _sse_frame(turn) -> str:
    return "data: " + json.dumps({"stage": turn.stage, "text": turn.text, "data": turn.data}) + "\n\n"


@router.post("/ecosystem/drafts")
async def create_draft_stream(
    body: CreateDraftRequest,
    current_user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Idempotency-Key header is required"})
    user_id, org_id, _ = _caller_context(current_user)

    cached = idempotency_service.get_cached_response(user_id, idempotency_key)

    async def stream():
        if cached is not None:
            draft = drafts_service.get_draft(cached["draft_id"], org_id=org_id)
            if draft is not None:
                yield "data: " + json.dumps({"stage": "draft_ready", "text": "Draft already generated.", "data": {"draft": draft}}) + "\n\n"
                return

        draft = drafts_service.create_draft(org_id=org_id, created_by=user_id, item_type=body.item_type)
        idempotency_service.store_response(user_id, idempotency_key, {"draft_id": draft["id"]})
        # The client has no other way to learn draft_id -- every subsequent
        # GET/PATCH/submit call needs it, and it's never embedded in any of
        # SkillFactoryAdapter's own turns (that module has no notion of an
        # ecosystem_drafts row at all -- it's a pure generation adapter).
        yield "data: " + json.dumps({"stage": "created", "text": "", "data": {"draft_id": draft["id"]}}) + "\n\n"
        try:
            async for turn in drafts_service.stream_draft_generation(draft["id"], body.intent, org_id=org_id):
                yield _sse_frame(turn)
            # SkillFactoryAdapter's own "assembled" turn carries the raw
            # SkillAssembler output, not ecosystem_drafts.draft_content's
            # shape (namespace/license defaulting happens inside
            # stream_draft_generation() AFTER that turn is yielded) -- a
            # final re-fetch gives the client one clean, correctly-shaped
            # frame to build its preview/edit card from, rather than making
            # it reconcile two different shapes itself.
            final_draft = drafts_service.get_draft(draft["id"], org_id=org_id)
            if final_draft is not None:
                yield "data: " + json.dumps({"stage": "draft_ready", "text": "Draft ready to review.", "data": {"draft": final_draft}}) + "\n\n"
        except EcosystemError as exc:
            yield "data: " + json.dumps({"stage": "error", "text": str(exc), "data": None}) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/ecosystem/drafts/{draft_id}")
def get_draft(draft_id: str, current_user: dict = Depends(get_current_user)):
    _, org_id, _ = _caller_context(current_user)
    draft = drafts_service.get_draft(draft_id, org_id=org_id)
    if draft is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"no such draft {draft_id!r}"})
    return draft


class PatchDraftRequest(BaseModel):
    namespace: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    license: Optional[str] = None
    instructions: Optional[str] = None
    files: Optional[list[dict[str, str]]] = None
    surfaces: Optional[list[str]] = None


@router.patch("/ecosystem/drafts/{draft_id}")
def patch_draft(draft_id: str, body: PatchDraftRequest, current_user: dict = Depends(get_current_user)):
    _, org_id, _ = _caller_context(current_user)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return drafts_service.patch_draft(draft_id, org_id=org_id, patch=patch)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/drafts/{draft_id}/submit", status_code=201)
def submit_draft(
    draft_id: str,
    current_user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Idempotency-Key header is required"})
    user_id, org_id, permissions = _caller_context(current_user)

    cached = idempotency_service.get_cached_response(user_id, idempotency_key)
    if cached is not None:
        return cached

    try:
        result = drafts_service.submit_draft(draft_id, org_id=org_id, created_by=user_id, caller_permissions=permissions)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
        return  # unreachable, satisfies type checkers
    idempotency_service.store_response(user_id, idempotency_key, result)
    return result


# ── Install lifecycle (task B-10) ────────────────────────────────────────

class InstallRequest(BaseModel):
    # Optional (external sources plan §5): a scope="central_index" catalog
    # item has no version at all until its first install -- omitting
    # version_id there triggers materialize_from_catalog() to fetch real
    # content on demand. Every other item still requires it, same as
    # before (checked in install_item() below, not by Pydantic, since the
    # requirement is conditional on the item, not the request shape).
    version_id: str | None = None
    surfaces: list[str] = []
    scope: str = "private"
    origin: str = "added"


@router.post("/ecosystem/items/{item_id}/install", status_code=201)
def install_item(
    item_id: str, body: InstallRequest, current_user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    user_id, org_id, permissions = _caller_context(current_user)
    # Item 2 (2026-09-29 live-test round): the client has always sent an
    # Idempotency-Key on this call (packages/ecosystem-ui/src/client/
    # RealEcosystemClient.ts's install()), but this endpoint never read it
    # -- a retried/duplicated Add (e.g. a caller that lost track of an
    # in-flight request and clicked Add again) hit the UNIQUE constraint
    # in installs_service.install() as a genuine ConflictError, surfacing
    # to the user as a false "install failed" rather than silently
    # returning the original, still-succeeding result. Unlike
    # submit_draft()'s own use of this same idempotency_service, the key
    # is optional here, not required -- existing/external callers that
    # never sent one (e.g. this router's own test suite) must keep working
    # unchanged; idempotency is only ever a bonus when the header IS sent.
    if idempotency_key:
        cached = idempotency_service.get_cached_response(user_id, idempotency_key)
        if cached is not None:
            return cached
    # A real, disclosed gap found while investigating why a normal user
    # could see -- and successfully submit -- "Everyone in org"/"Required"
    # scope options: this endpoint never validated `scope` against the
    # caller's permissions at all, unlike create_service.py's own
    # _require_provision_permission() for provision_scope at creation
    # time. Any authenticated user could set scope="org"/"provisioned"/
    # "required" on an existing catalog item's install and it would
    # silently succeed. `_auto_install()` (services/ecosystem/
    # gate_service.py) also calls installs_service.install() directly with
    # these same scope values, but that call is downstream of
    # create_service.py's own already-checked provision_scope -- this
    # check belongs here, at the one endpoint representing an arbitrary
    # live HTTP caller, not inside install() itself (which would
    # incorrectly block that legitimate internal auto-install path).
    # org/provisioned/required (org-wide install) stay marketplace:provision-
    # only. "shared" is policy-driven, not RBAC-permission-driven (product
    # correction, 2026-09-27): a normal user CAN install at scope="shared"
    # subject to the org's own who_can_share policy (default "all_users") --
    # see config_service.get_effective_config()'s caller_permissions.can_share
    # for the same policy lookup surfaced to the UI.
    if body.scope in ("org", "provisioned", "required") and "marketplace:provision" not in permissions:
        raise HTTPException(status_code=403, detail={
            "code": "POLICY_FORBIDDEN", "message": f"scope={body.scope!r} requires marketplace:provision",
        })
    if body.scope == "shared" and "marketplace:provision" not in permissions:
        who_can_share = policy_service.get_policy(org_id).get("who_can_share", "all_users")
        if who_can_share != "all_users":
            raise HTTPException(status_code=403, detail={
                "code": "POLICY_FORBIDDEN", "message": "scope='shared' requires marketplace:provision under this org's who_can_share policy",
            })
    # BUG-004 fix (Marketplace/Skills QA pass): "shared" was missing from this
    # tuple, so an accepted share's install row got installed_for=None instead
    # of the recipient's own user id -- installs_service.list_installs()'s
    # GET /ecosystem/installs query filters by installed_for == caller_user_id
    # for any identified caller, so a NULL row can never match and the
    # accepted share silently never appeared in the recipient's own "Yours"
    # list, even though both the share and this install call each returned a
    # clean 2xx. Confirmed live before this fix. The project's own unit test
    # for this flow (tests/services/ecosystem/test_policy_service.py's
    # test_recipient_own_item_summary_resolves_their_own_share_id) calls
    # installs_service.install() directly with installed_for hardcoded,
    # bypassing this router entirely, so it never caught the gap.
    installed_for = user_id if body.scope in ("private", "provisioned", "required", "shared") else None
    # BUG-005 fix (Marketplace/Skills QA pass): body.version_id is `str |
    # None` -- an empty string "" is a valid str, so it passed Pydantic and
    # then slipped past the `if version_id is None:` check below untouched,
    # reaching installs_service.install() -> a raw EcosystemInstall insert
    # with version_id="" -- a 500 (DB-level invalid-UUID error) instead of
    # the clean VERSION_ID_REQUIRED 400 every other missing-version case
    # already gets. Normalizing falsy here (empty string treated the same
    # as omitted) makes it share that same validated path.
    version_id = body.version_id or None
    resolved_via_catalog_materialize = version_id is None
    if version_id is None:
        # No version supplied -- only valid for a scope="central_index"
        # catalog pointer with no version yet (external sources plan §5).
        # Every other item must supply version_id, same as before.
        from services.ecosystem import catalog_sync

        item = items_service.get_item_row(item_id)
        if item.scope != "central_index" or items_service.get_latest_version(item_id) is not None:
            raise HTTPException(status_code=400, detail={
                "code": "VERSION_ID_REQUIRED", "message": "version_id is required for this item",
            })
        try:
            version_id = catalog_sync.materialize_from_catalog(item_id, requested_by=user_id, org_id=org_id)
        except catalog_sync.CatalogInstallNotSupportedError as exc:
            raise HTTPException(status_code=409, detail={"code": "CATALOG_INSTALL_NOT_SUPPORTED", "message": str(exc)})
        except catalog_sync.CatalogContentDriftError as exc:
            raise HTTPException(status_code=409, detail={"code": "CATALOG_CONTENT_DRIFT", "message": str(exc)})
        except EcosystemError as exc:
            _handle_ecosystem_error(exc)
    try:
        # Tier 2 of the tiered license policy (task C, ECOSYSTEM_PLAN.md
        # §11.2): re-checked here, not just at creation time, since an
        # item created privately can later be installed shared/org-wide/
        # required by anyone permitted to -- same check policy_service.share()
        # runs for its own separate share() endpoint.
        if body.scope in ("shared", "org", "provisioned", "required"):
            policy_service.check_tier2_license(item_id, org_id)
        # Per-surface toggles round (2026-09-29): the manual per-surface
        # toggle UI is gone for normal users -- an install request that
        # doesn't explicitly name surfaces (body.surfaces == [], the
        # Pydantic default; the old AddDialog always sent an explicit list
        # from its own toggle state, a new client simply omits it) now
        # defaults to every surface the org's product profile allows,
        # rather than an empty list installing onto no surface at all.
        # Whichever list is in play (defaulted or an explicit admin-only
        # override) is run through enforce_compatibility_on_surfaces() --
        # a REAL, PRE-EXISTING gap closed here: that function was
        # previously only ever called at item-CREATE time
        # (create_service.py), never re-checked when a DIFFERENT caller
        # later installs an EXISTING item, so a tool-dependent skill could
        # still land on the chat surface via this endpoint. Same
        # exception either way: a tool-dependent item never gets `chat`.
        effective_surfaces = body.surfaces or config_service.get_org_enabled_surfaces(org_id)
        compatibility = versions_service.get_manifest(version_id).get("compatibility", CHAT)
        effective_surfaces = enforce_compatibility_on_surfaces(compatibility, effective_surfaces)
        # Task D: any scope beyond private is a widen -- upgrade a
        # fast-pathed version to the full gate before this wider audience
        # is meant to trust its verdict (no-op if already fully gated).
        widen_gate_run_id = None
        if body.scope in ("shared", "org", "provisioned", "required"):
            widen_gate_run_id = gate_service.ensure_full_gate_for_scope_widen(
                item_id, version_id, org_id=org_id, requested_by=user_id, surfaces=effective_surfaces,
            )
        try:
            install_row = installs_service.install(
                item_id=item_id, version_id=version_id, org_id=org_id,
                installed_by=user_id, installed_for=installed_for, surfaces=effective_surfaces,
                scope=body.scope, origin=body.origin,
            )
        except ConflictError:
            # materialize_from_catalog() above (catalog items only, i.e.
            # body.version_id was None) enqueues the gate with
            # trigger="ui_add" -- same as a normal creation -- which
            # auto-installs scope="private" for this caller once it
            # resolves pass/warn (gate_service._auto_install()). If that
            # already happened (synchronously in tests; possibly before
            # this request returns, in production too, if the gate is
            # fast) by the time we reach here, this is the SAME install the
            # caller just asked for, not a real conflict -- use it instead
            # of raising a spurious 409. Scoped to ONLY that catalog-
            # materialize path (real bug found during a merge, 2026-09-29):
            # applying this fallback unconditionally silently turned a
            # genuine duplicate-install attempt (any item, caller-supplied
            # version_id) into a fake 201 instead of the real 409 it must
            # stay -- idempotency for THAT case is the client's own
            # Idempotency-Key, not this fallback.
            if not resolved_via_catalog_materialize:
                raise
            existing = installs_service.get_install_for_caller(item_id, org_id, installed_for)
            if existing is None:
                raise
            install_row = installs_service._row_to_dict(existing)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
        return  # unreachable, satisfies type checkers

    # Item 2 (2026-09-29 live-test round): "Add returns immediately with
    # the install/run id; the UI shows status from the server (and live
    # events), never from an in-flight browser request" -- this response
    # is now the SAME async-envelope shape GET /ecosystem/jobs/{id} itself
    # returns (gate_service.get_job_status()), so the client always has a
    # real, server-owned id to poll from the very first response, keyed to
    # survive a page navigation/remount rather than a component's own
    # in-flight-promise state. A plain private install (no scope widen)
    # has no NEW gate run of its own -- its version was already gated at
    # creation time -- so job_id falls back to that existing run, which
    # resolves to an already-terminal status (e.g. "active") on the very
    # first poll rather than there being nothing to poll at all.
    job_id = widen_gate_run_id or gate_service.get_latest_gate_run_id(install_row["version_id"])
    job_status = gate_service.get_job_status(job_id, caller_org_id=org_id) if job_id else None
    response = {
        "job_id": job_id,
        "status": job_status["status"] if job_status else "active",
        "item_id": item_id,
        "version_id": install_row["version_id"],
        "gate_run_id": widen_gate_run_id,
        "error": None,
        "stuck_message": job_status["stuck_message"] if job_status else None,
        # Additive (Job's own optional field, types.ts) -- lets the client
        # show "Added" the instant this response lands, with no separate
        # GET round trip required just to learn the id an install() call
        # itself just created.
        "install_id": install_row["install_id"],
    }
    if idempotency_key:
        idempotency_service.store_response(user_id, idempotency_key, response)
    return response


@router.post("/ecosystem/installs/{install_id}/uninstall", status_code=204)
def uninstall_item(install_id: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        installs_service.uninstall(install_id, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class SetEnabledRequest(BaseModel):
    enabled: bool


@router.post("/ecosystem/installs/{install_id}/set-enabled")
def set_install_enabled(install_id: str, body: SetEnabledRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return installs_service.set_enabled(
            install_id, body.enabled, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class SetSurfacesRequest(BaseModel):
    surfaces: list[str]


@router.post("/ecosystem/installs/{install_id}/set-surfaces")
def set_install_surfaces(
    install_id: str, body: SetSurfacesRequest,
    current_user: dict = Depends(require_permission("marketplace:admin_surfaces")),
):
    # Per-surface toggles round (2026-09-29): normal users no longer get a
    # manual per-surface toggle UI at all -- a new install now defaults to
    # every surface the org's product profile allows (see
    # config_service.get_effective_config()'s own enabled_surfaces, applied
    # at install time), with the file/terminal-tools compatibility
    # exception still enforced (enforce_compatibility_on_surfaces()). This
    # endpoint survives ONLY for the admin-only "Advanced" override on the
    # Detail page -- previously gated by ownership alone (any caller who
    # could mutate their own install could hit it), now real RBAC, matching
    # every other admin-only ecosystem endpoint's own pattern.
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return installs_service.set_surfaces(
            install_id, body.surfaces, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


class UpdateVersionRequest(BaseModel):
    version_id: str


@router.post("/ecosystem/installs/{install_id}/update")
def update_install(install_id: str, body: UpdateVersionRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return installs_service.update_to_version(
            install_id, body.version_id, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/installs/{install_id}/rollback")
def rollback_install(install_id: str, body: UpdateVersionRequest, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return installs_service.rollback(
            install_id, body.version_id, caller_org_id=org_id, caller_user_id=user_id, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# Pydantic response_model (task B-17's own convention, until now only
# applied to /config and /capabilities) -- added after a real bug shipped
# silently because this endpoint had no schema enforcement at all: the
# backend's dict just omitted `item` entirely and FastAPI had nothing to
# validate that against, so it 200'd with an incomplete body instead of
# ever failing loudly. With a response_model, a future regression of this
# exact shape (a required field silently missing) fails the request with
# a real 500 in any test or manual check that hits this endpoint, rather
# than shipping a body the frontend's own (already-correct) TypeScript
# contract didn't actually get.
class ItemSummaryModel(BaseModel):
    id: str
    namespace: str
    item_type: str
    display_name: str
    description: str
    category: str
    tags: list[str]
    icon_url: Optional[str] = None
    trust_tier: str
    license: str
    status: str
    # Item-level scope (builtin|optional|central_index|org_private) --
    # distinct from Install.scope (private|shared|org|provisioned|
    # required) below. Needed by the frontend to tell a not-yet-added
    # catalog item (item_scope == "central_index", no version exists yet)
    # apart from one actually mid-verification (docs/ecosystem/design/
    # LLD/gate.md's "Item-state model").
    item_scope: str
    is_featured: bool
    is_new: bool
    latest_version: Optional[str] = None
    latest_verdict: str
    allowed_actions: list[str]
    # The caller's own install for this item, if any (Detail.tsx's
    # installed-state header). None/None when never installed by this caller.
    install_id: Optional[str] = None
    enabled: Optional[bool] = None
    # Item 2 (M5 UI-polish): Detail.tsx's "Installed ▾" popover needs this
    # to lock Uninstall for a scope='required' install, matching the real
    # server-side refusal in installs_service.uninstall().
    install_scope: Optional[str] = None
    install_surfaces: Optional[list[str]] = None
    # Plugins phase: mirrors install_scope/install_surfaces above -- without
    # this, FastAPI's response_model would silently strip the field from the
    # wire (the exact regression class CONTRACTS.md §9 already documents
    # once for Install.version_id).
    managed_by_plugin_install_id: Optional[str] = None
    # "chat" | "tool_dependent" | None (a version created before this field
    # existed) -- services/ecosystem/compatibility.py's classification,
    # shown as a card/detail badge and in the create/import result.
    compatibility: Optional[str] = None
    has_other_installs: bool = False
    # Task 3c fix: the RECIPIENT's own relevant EcosystemShare.id, when
    # "unshare" is in allowed_actions (items_service._share_id_for_
    # recipient()) -- None otherwise. Lets the frontend actually call
    # POST /ecosystem/shares/{share_id}/unshare, which previously had no
    # id to call it with from the recipient's side.
    share_id: Optional[str] = None


class InstallModel(BaseModel):
    install_id: str
    item: ItemSummaryModel
    # version_id: not in CONTRACTS.md §9's own documented Install example,
    # but installs_service._row_to_dict() already returned it before this
    # response_model existed -- found live (item 6's "Update my <skill>"
    # test expects to read it back after a version bump) that declaring
    # this model without it silently DROPPED an already-real, already-
    # useful field (Pydantic response_model filters to declared fields
    # only), a real regression this response_model's own addition
    # introduced rather than one it was meant to catch. Restored, and
    # worth documenting in CONTRACTS.md alongside this fix.
    version_id: str
    scope: str
    origin: str
    installed_by: str
    installed_for: Optional[str] = None
    enabled: bool
    surfaces: list[str]
    auto_update: bool
    installed_at: Optional[str] = None
    # Plugins phase: null for the plugin's own (parent) install and for any
    # normal non-plugin-managed install; set to the parent plugin's own
    # install_id for a fanned-out child. installs_service.py's row-to-dict
    # already returns this -- declaring it here too, not just on
    # ItemSummaryModel above, so /ecosystem/installs itself carries it per
    # row (not just via the nested `item`).
    managed_by_plugin_install_id: Optional[str] = None


class LegacyItemModel(BaseModel):
    item: ItemSummaryModel
    legacy_source: str
    allowed_actions: list[str] = ["open"]


class InstallsResponse(BaseModel):
    installs: list[InstallModel]
    legacy_items: list[LegacyItemModel]
    has_any: bool
    next_cursor: Optional[str] = None


@router.get("/ecosystem/installs", response_model=InstallsResponse)
def list_installs(item_type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    installs, has_any = installs_service.list_installs(org_id, user_id, item_type, caller_permissions=permissions)
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
def share_item(item_id: str, body: ShareRequest, current_user: dict = Depends(get_current_user)):
    # Sharing is policy-driven, not RBAC-permission-driven (product
    # correction, 2026-09-27): a normal user CAN share their own items,
    # subject to the org's own who_can_share policy (default "all_users").
    # marketplace:provision always passes regardless of that policy -- an
    # admin can always share, same as they can always provision.
    user_id, org_id, permissions = _caller_context(current_user)
    if "marketplace:provision" not in permissions:
        who_can_share = policy_service.get_policy(org_id).get("who_can_share", "all_users")
        if who_can_share != "all_users":
            raise HTTPException(status_code=403, detail={
                "code": "POLICY_FORBIDDEN", "message": "sharing requires marketplace:provision under this org's who_can_share policy",
            })
    try:
        return policy_service.share(body.install_id, body.shared_with_type, body.shared_with_id, caller_org_id=org_id, actor=user_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.post("/ecosystem/shares/{share_id}/unshare", status_code=204)
def unshare_item(share_id: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id, _ = _caller_context(current_user)
    try:
        policy_service.unshare(share_id, caller_org_id=org_id, actor=user_id)
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
    from services.ecosystem.items_service import _is_owner, _visible_to_caller

    user_id, org_id, permissions = _caller_context(current_user)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        # Cross-org: 404, not 403 -- don't reveal another org's item exists
        # at all (added alongside "marketplace:admin_sources is a global
        # role string with no per-org concept" fix below).
        if item is None or not _visible_to_caller(item, org_id):
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such item"})
        # Item 9 fix (M5 UI-parity review, 2026-09-28): real bug found live
        # -- this endpoint 403'd EVERY non-admin caller, including the
        # item's own owner, even though items_service.compute_allowed_
        # actions() (the single source of truth every ItemSummary/
        # ItemDetail response's allowed_actions is built from) has always
        # offered "deprecate" to `is_owner or marketplace:admin_sources`.
        # The prior comment here ("ownership check deferred -- no
        # created_by column exists") was stale: _is_owner() already
        # derives ownership from ecosystem_installs (origin='created' +
        # installed_by), the exact same mechanism compute_allowed_actions
        # itself uses -- no schema change needed. A real owner clicking
        # "Retire" on their own shared/multi-installed item (exactly item
        # 9's "Shared/installed-by-others -> offers Retire" spec) got a
        # 403 despite the UI legitimately offering the button, since
        # allowed_actions said "deprecate" was allowed but this endpoint
        # never agreed.
        if "marketplace:admin_sources" not in permissions and not _is_owner(db, item_id, user_id):
            raise HTTPException(status_code=403, detail={"code": "POLICY_FORBIDDEN", "message": "deprecate requires ownership or marketplace:admin_sources"})
        item.status = "deprecated"
        from datetime import datetime, timezone

        item.deprecated_at = datetime.now(timezone.utc)
        item.deprecated_by = user_id
        item_type = item.item_type
        db.commit()
    finally:
        db.close()
    try:
        from services.ecosystem.audit_service import write_audit_event
        write_audit_event(org_id=org_id, actor=user_id, action="deprecate", item_id=item_id, details={})
    except Exception:
        pass
    try:
        # Real gap found live (2026-09-29, install-state-consistency round):
        # deprecate/retire never published ecosystem.changed at all -- a
        # Yours/Detail screen sitting open elsewhere (or another tab) had
        # no signal that this item's status just changed underneath it.
        from services.ecosystem.events_service import publish_ecosystem_changed
        publish_ecosystem_changed(org_id, item_type=item_type, item_id=item_id, scope="org", change="updated")
    except Exception:
        pass
    return {"item_id": item_id, "status": "deprecated"}


@router.post("/ecosystem/items/{item_id}/delete-draft", status_code=204)
def delete_draft_item(item_id: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        items_service.delete_draft(
            item_id, caller_user_id=user_id, caller_org_id=org_id, caller_permissions=permissions,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── Admin: force-disable / unyank / require / unrequire (task B-19 + item F) ──

@router.post("/ecosystem/items/{item_id}/force-disable")
def force_disable_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    user_id, org_id, _ = _caller_context(current_user)
    try:
        policy_service.force_disable(item_id, caller_org_id=org_id, actor=user_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
    return {"item_id": item_id, "status": "yanked"}


@router.post("/ecosystem/items/{item_id}/unyank")
def unyank_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    user_id, org_id, _ = _caller_context(current_user)
    try:
        policy_service.unyank(item_id, caller_org_id=org_id, actor=user_id)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)
    return {"item_id": item_id, "status": "active"}


@router.post("/ecosystem/items/{item_id}/require")
def require_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:provision"))):
    user_id, org_id, _ = _caller_context(current_user)
    count = policy_service.require_item(item_id, org_id, actor=user_id)
    return {"item_id": item_id, "promoted_installs": count}


@router.post("/ecosystem/items/{item_id}/unrequire")
def unrequire_item(item_id: str, current_user: dict = Depends(require_permission("marketplace:provision"))):
    user_id, org_id, _ = _caller_context(current_user)
    count = policy_service.unrequire_item(item_id, org_id, actor=user_id)
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
def get_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """job_id IS the gate_run_id this pass (no separate jobs table exists —
    the gate run itself is the unit of async work). As of item 2 (pre-M3)
    the gate genuinely runs asynchronously — a dedicated gate-worker
    process consumes ecosystem_gate_queue (see docs/ecosystem/design/
    LLD/gate.md) — so 'pending' here can mean either "still queued/
    running" or "no worker has ever picked this up." A pending run whose
    started_at is older than gate_health_service's stuck-verifying
    threshold gets an explicit `stuck_message` rather than leaving the
    caller to guess why nothing has resolved (item 2's follow-up).

    This endpoint originally took no auth dependency at all -- see the
    install-lifecycle fix in this same router for the full account.
    caller_org_id is resolved here and checked via a join through
    version_id -> item_id (a gate run has no org_id of its own).

    The actual verdict -> status mapping now lives in gate_service.
    get_job_status() (item 2, 2026-09-29 live-test round) -- install_item()
    below returns that exact same shape from its own response, so this
    endpoint and a fresh install's immediate response can never drift
    apart on what a given gate run's status means."""
    _, org_id, _ = _caller_context(current_user)
    status = gate_service.get_job_status(job_id, caller_org_id=org_id)
    if status is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such job"})
    return status


# ── Config + capabilities (task B-11/B-12, M3) ───────────────────────────
# Pydantic response_model on both (task B-17): without one, FastAPI's
# generated OpenAPI schema for a plain-dict-returning route is an untyped
# blob, not something a "response shape vs. spec" contract test could
# meaningfully check -- these two give B-17's generator (scripts/ecosystem/
# generate_openapi.py) real schemas, and FastAPI itself validates every
# actual response against them at request time (a structural conformance
# guarantee, not just a doc artifact).

class ItemTypeState(BaseModel):
    type: str
    state: str
    slug: str


class SurfaceRef(BaseModel):
    key: str
    label: str


class TaxonomyModel(BaseModel):
    categories: list[str]
    trust_tiers: list[str]


class CallerPermissionsModel(BaseModel):
    can_share: bool
    can_provision: bool
    # Real gap found and fixed (2026-09-30): declared without this field,
    # response_model=ConfigResponse silently stripped can_admin_surfaces
    # from the wire -- the same regression class already documented twice
    # this session (CONTRACTS.md §9's Install.version_id, and
    # managed_by_plugin_install_id) -- get_effective_config() (services/
    # ecosystem/config_service.py) has always computed this correctly;
    # FastAPI's response_model just never declared it. This is the actual
    # root cause of Marketplace.tsx's collapseConnectorsAdvanced never
    # activating for a real admin session, found live via a real browser
    # session, not assumed.
    can_admin_surfaces: bool = False


class BuildInfoModel(BaseModel):
    commit: str
    built_at: str


class ConfigResponse(BaseModel):
    product: str
    layout: str
    default_view: str
    item_types: list[ItemTypeState]
    route_slugs: dict[str, str]
    surfaces: list[SurfaceRef]
    features: dict[str, bool]
    caller_permissions: CallerPermissionsModel
    policy_summary: dict[str, Any]
    taxonomy: TaxonomyModel
    new_badge_days: int
    enums_version: str
    caller_default_namespace_prefix: str
    # Discover "From the web" section (2026-09-29): the real, effective
    # "both ECOSYSTEM_LIVE_SOURCES AND this org's own live_sources_enabled
    # policy toggle are true" signal (services/ecosystem/config_service.py's
    # get_effective_config()) -- distinct from policy_summary's raw
    # live_sources_enabled, which only reflects the org toggle on its own.
    live_search_enabled: bool = False
    # Admin-only (real incident, 2026-09-27: a full day of testing against
    # a stale image, no way to tell from the app) -- None for a non-admin
    # caller, never sent, not just hidden client-side. See core/build_info.py.
    build_info: Optional[BuildInfoModel] = None


class CapabilitySkill(BaseModel):
    namespace: str
    display_name: str
    description: str
    slash_command: str
    # Info-popover fix (2026-09-29): both already plain columns on the same
    # EcosystemItem row resolver_service.get_effective_capabilities() reads
    # -- no new fetch needed for the chat UI's "ⓘ" popover.
    license: str = ""
    source: str = ""


class CapabilitiesResponse(BaseModel):
    surface: str
    skills: list[CapabilitySkill]
    plugins: list[Any] = []
    connectors: list[Any] = []
    mcp_tools: list[Any] = []


@router.get("/ecosystem/config", response_model=ConfigResponse)
def get_config(
    current_user: dict = Depends(get_current_user),
    x_ainxt_product: Optional[str] = Header(None, alias="x-ainxt-product"),
):
    user_id, org_id, permissions = _caller_context(current_user)
    try:
        return config_service.get_effective_config(org_id, user_id, x_ainxt_product, caller_permissions=permissions)
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


@router.get("/ecosystem/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(surface: str, current_user: dict = Depends(get_current_user)):
    user_id, org_id, _ = _caller_context(current_user)
    skills = resolver_service.get_effective_capabilities(org_id, user_id, surface)
    connectors = resolver_service.get_effective_connector_capabilities(org_id, user_id, surface)
    mcp_tools = resolver_service.get_effective_mcp_tool_capabilities(org_id, user_id, surface)
    return {"surface": surface, "skills": skills, "plugins": [], "connectors": connectors, "mcp_tools": mcp_tools}


# ── Admin: org policy CRUD (task F-13's AdminPolicies.tsx) ──────────────

class PolicyUpdateRequest(BaseModel):
    who_can_add: Optional[str] = None
    allowed_sources: Optional[list[str]] = None
    auto_update_default: Optional[bool] = None
    # Tier 2 of the tiered license policy (task C, ECOSYSTEM_PLAN.md §11.2).
    allowed_licenses_shared: Optional[list[str]] = None
    # Who may share their own items with specific users/groups (product
    # correction, 2026-09-27) -- same "all_users"|"admins_only" values as
    # who_can_add, default "all_users". Independent of org-wide
    # provisioning (org/provisioned/required scope), which stays
    # marketplace:provision-only regardless of this policy.
    who_can_share: Optional[str] = None
    # Admin Sources screen (Task 3a): per-org on/off for Discover's "From
    # the web" live-search section -- the live-search feature itself is
    # separately, instance-wide flag-gated (ECOSYSTEM_LIVE_SOURCES); this
    # is only the org-level toggle on top of that.
    live_sources_enabled: Optional[bool] = None


@router.get("/ecosystem/policy")
def get_policy(current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    _, org_id, _ = _caller_context(current_user)
    return policy_service.get_policy(org_id)


@router.put("/ecosystem/policy")
def put_policy(body: PolicyUpdateRequest, current_user: dict = Depends(require_permission("marketplace:admin_policy"))):
    user_id, org_id, _ = _caller_context(current_user)
    try:
        return policy_service.set_policy(
            org_id, who_can_add=body.who_can_add, allowed_sources=body.allowed_sources,
            auto_update_default=body.auto_update_default,
            allowed_licenses_shared=body.allowed_licenses_shared, who_can_share=body.who_can_share,
            live_sources_enabled=body.live_sources_enabled,
            updated_by=user_id,
        )
    except EcosystemError as exc:
        _handle_ecosystem_error(exc)


# ── Admin: gate findings dashboard (task F-13's AdminGateFindings.tsx) ──

@router.get("/ecosystem/gate-findings")
def get_gate_findings(
    limit: int = 100,
    current_user: dict = Depends(require_permission("marketplace:admin_sources")),
):
    _, org_id, _ = _caller_context(current_user)
    return {"findings": gate_service.list_recent_findings(org_id=org_id, limit=limit)}


# ── Admin: gate-worker health (item 2's follow-up, pre-M3) ──────────────
# Not yet folded into GET /ecosystem/config (task B-12/M3 — that endpoint
# doesn't exist yet) — a standalone admin endpoint so this signal is
# visible now rather than waiting on the resolver/config milestone.

@router.get("/ecosystem/admin/gate-health")
def get_gate_health(current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    from services.ecosystem.gate_health_service import get_health

    return get_health()


# ── Admin: external-sources catalog sync (external sources plan §5/§8) ──
# "Sync now" -- runs synchronously and returns the real report (which
# shard(s) succeeded/failed and why), so a rejected/unsigned index has
# somewhere concrete to surface to rather than a silent background-job
# failure. No dedicated admin "Sources" screen exists yet on the
# frontend this phase -- disclosed gap, not built here; this endpoint is
# what that screen will call once it exists, and is directly usable via
# curl/Postman/an admin script in the meantime.

@router.post("/ecosystem/admin/catalog-sync")
def sync_catalog_now(current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    # Delegates the online-vs-bundle decision entirely to catalog_sync.
    # run_configured_sync() (porting-pack round) -- this endpoint no
    # longer has its own copy of that branching logic, so it can never
    # drift out of sync with what the scheduler itself does.
    from services.ecosystem import catalog_sync

    try:
        report = catalog_sync.run_configured_sync()
    except catalog_sync.CatalogSyncNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail={"code": "NOT_CONFIGURED", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TRUSTED_SIGNER", "message": str(exc)})

    return report.to_dict()


# ── Admin: Sources screen aggregate (Task 3a) ────────────────────────────
# One read endpoint backing the whole admin Sources screen -- catalog
# URL/last-sync status, approved well-known sites (read-only, sources.yaml
# is a reviewed-PR-only file), this org's own EcosystemSource rows, and
# whether an instance-level GitHub import credential is configured. Ethics/
# auto-update/pre-check/live-search-toggle policy fields are already
# covered by the existing GET/PUT /ecosystem/policy (task F-13) -- this
# endpoint doesn't duplicate them, the frontend fetches both.

@router.get("/ecosystem/admin/sources")
def get_admin_sources(current_user: dict = Depends(require_permission("marketplace:admin_sources"))):
    import os

    from core.config import (
        ECOSYSTEM_CATALOG_BUNDLE_PATH, ECOSYSTEM_CATALOG_SOURCE_MODE, ECOSYSTEM_CATALOG_TRUSTED_SIGNER,
        ECOSYSTEM_CATALOG_URL, ECOSYSTEM_LIVE_SOURCES,
    )
    from services.ecosystem import catalog_sync
    from services.ecosystem.catalog_crawler.sources_config import load_sources
    from services.ecosystem.import_adapters.github_credential import (
        configure_github_access_hint, get_github_import_token,
    )

    _, org_id, _ = _caller_context(current_user)

    sources_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "ecosystem", "catalog", "sources.yaml",
    )
    well_known_sites: list[dict[str, Any]] = []
    sources_yaml_error: Optional[str] = None
    try:
        parsed = load_sources(sources_path)
        well_known_sites = [
            {
                "domain": w.domain, "category": w.category, "tags": w.tags,
                "needs_product": w.needs_product or None, "account_required": w.account_required,
                "tos_note": w.tos_note, "enabled": w.enabled,
            }
            for w in parsed.well_known_sites
        ]
    except (OSError, ValueError) as exc:
        # sources.yaml is a reviewed-PR-only file (external-sources-catalog
        # plan §7) -- a parse failure here is a real, admin-visible signal
        # (a bad merge, a missing file on this deployment), never a 500.
        sources_yaml_error = str(exc)

    from services.ecosystem.service_health import get_all_service_health

    return {
        "catalog_url": ECOSYSTEM_CATALOG_URL or None,
        "catalog_signer_configured": bool(ECOSYSTEM_CATALOG_TRUSTED_SIGNER),
        # Offline catalog bundle mode (porting-pack round, 2026-09-29):
        # which source mode is active, and the bundle path/URL if so --
        # an admin looking at this screen on an air-gapped instance needs
        # to see it's reading from a local bundle, not silently expecting
        # ECOSYSTEM_CATALOG_URL to be reachable.
        "catalog_source_mode": ECOSYSTEM_CATALOG_SOURCE_MODE,
        "catalog_bundle_path": ECOSYSTEM_CATALOG_BUNDLE_PATH or None,
        "last_sync": catalog_sync.get_last_sync_status(),
        "well_known_sites": well_known_sites,
        "sources_yaml_error": sources_yaml_error,
        "org_sources": catalog_sync.list_org_sources(org_id),
        "github_credential_configured": bool(get_github_import_token()),
        "github_credential_hint": configure_github_access_hint(),
        "live_sources_flag_enabled": ECOSYSTEM_LIVE_SOURCES,
        # Real incident, 2026-09-29: stale gateway/gate-worker/gate-sweeper
        # processes serving old code repeatedly surfaced as false live
        # bugs -- see services/ecosystem/service_health.py's own header
        # comment. Each service self-reports its own commit/start time;
        # surfaced here so a stale process is a visible admin warning,
        # not something only found by manually inspecting docker logs.
        "service_health": get_all_service_health(),
    }
