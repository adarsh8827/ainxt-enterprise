# SPDX-License-Identifier: MIT
# ============================================================
# Creation service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-6):
# one service, three payload shapes (write/upload/import). Upload/import
# always go through the exact same full async gate. Write has one
# exception (task D): a private, no-script skill takes a synchronous fast
# path (services/ecosystem/gate_service.py's run_fast_path_gate()) instead
# — see create_via_write()'s own attempt_fast_path computation below.
#
# Upload path reuses the exact path-traversal/zip-bomb guard logic already
# proven in AgentStudio/backend/app/api/catalog.py's .zip upload handler —
# ported here (not re-derived) since that handler is itself unmodified,
# only its validation functions are reused. SKILL.md frontmatter parsing
# reuses AgentStudio/backend/skill_factory/pipeline.py's parse_frontmatter()
# directly, no second implementation.
# ============================================================

from __future__ import annotations

import io
import zipfile
from typing import Any

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem
from services.ecosystem import policy_service
from services.ecosystem.compatibility import classify_compatibility, default_surfaces_for, enforce_compatibility_on_surfaces
from services.ecosystem.errors import (
    EcosystemError, LicenseAcknowledgementRequiredError, LicenseNotAllowedByOrgPolicyError,
    LicenseNotAllowedError, NotFoundError, PolicyForbiddenError,
)
from services.ecosystem.gate_service import enqueue_gate_run, run_fast_path_gate
from services.ecosystem.items_service import _is_owner, _visible_to_caller, get_or_create_import_source, get_or_create_local_source
from services.ecosystem.license_policy import is_allowed_license
from services.ecosystem.publishers_service import resolve_publisher
from services.ecosystem.versions_service import create_version_for_content, encode_envelope

# Any one of these (B-18's admin tier) satisfies an org policy of
# who_can_add='admins_only' -- matches CONFIG_AND_PRODUCTS.md §3's layering
# (org policy narrows what the product profile allows; RBAC narrows further).
_ADMIN_TIER_MARKETPLACE_PERMISSIONS = ("marketplace:provision", "marketplace:admin_sources", "marketplace:admin_policy")

# Task D's fast path: the gate run is already resolved by the time the
# create call returns, so the response's own `status` must reflect the
# real outcome immediately -- "verifying" (the async path's only ever
# value here) would be a lie. Matches CreateResult.status's existing
# JobStatus values (packages/ecosystem-ui/src/types.ts) -- no new value.
_VERDICT_TO_STATUS = {"pass": "active", "warn": "warn", "fail": "blocked", "pending": "verifying"}

# Mirrors AgentStudio/backend/app/api/catalog.py:443-449 exactly — same
# limits, same reasoning (a zip-bomb guard checked before decompressing).
_UPLOAD_MAX_SIZE_BYTES = 5 * 1024 * 1024
_UPLOAD_MAX_BUNDLE_FILES = 8
_UPLOAD_MAX_BUNDLE_FILE_BYTES = 64 * 1024
_UPLOAD_MAX_SKILL_MD_BYTES = 256 * 1024
_UPLOAD_MAX_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024

_VALID_PROVISION_SCOPES = ("private", "org_default_on", "required")
# CONFIG_AND_PRODUCTS.md §12 point 4's mapping.
_PROVISION_SCOPE_TO_INSTALL = {
    None: ("private", "created"),
    "private": ("private", "created"),
    "org_default_on": ("provisioned", "provisioned"),
    "required": ("required", "required"),
}


def _require_provision_permission(provision_scope: str | None, caller_permissions: set[str]) -> None:
    if provision_scope not in (None, "private") and "marketplace:provision" not in caller_permissions:
        raise PolicyForbiddenError(
            f"provision_scope={provision_scope!r} requires marketplace:provision"
        )
    if provision_scope is not None and provision_scope not in _VALID_PROVISION_SCOPES:
        raise EcosystemError(f"invalid provision_scope {provision_scope!r}")


def _require_who_can_add_permission(org_id: str, caller_permissions: set[str]) -> None:
    """CONFIG_AND_PRODUCTS.md §3 point 2 / task B-19's own (previously
    unmet) test requirement: an org policy of who_can_add='admins_only'
    actually narrows this endpoint's behavior on the next request, not
    just policy_summary's read-only display copy."""
    policy = policy_service.get_policy(org_id)
    if policy["who_can_add"] == "admins_only" and not (caller_permissions & set(_ADMIN_TIER_MARKETPLACE_PERMISSIONS)):
        raise PolicyForbiddenError(f"org {org_id!r} policy restricts creation to admins")


def _license_allowed_by_org_policy(license: str, org_id: str) -> bool:
    """Tier 2 (ECOSYSTEM_PLAN.md §11.2, task C): a substring check against
    the org's own allowed_licenses_shared, mirroring is_allowed_license()'s
    own substring approach so a dual-license string like "MIT OR GPL-3.0"
    still matches an allowlist entry of "GPL-3.0". Can only ever widen
    Tier 1, never narrow it -- callers always try is_allowed_license()
    first and only fall back to this."""
    allowed = policy_service.get_policy(org_id).get("allowed_licenses_shared") or ["MIT", "Apache-2.0"]
    normalized = license.lower()
    return any(a.strip().lower() in normalized for a in allowed if a and a.strip())


def _resolve_creation_license(
    license: str, *, is_private: bool, org_id: str,
    license_acknowledged: bool, self_authored: bool,
) -> tuple[str, str]:
    """The tiered license policy's single decision point (task C,
    ECOSYSTEM_PLAN.md §11.2), shared by every creation/update path below.
    Returns (resolved_license, license_tier) -- license_tier is 'strict'
    whenever the license passed is_allowed_license() outright (Tier 1 --
    the only case where every existing gate/import/CI check downstream
    also agrees it's fine). It's 'relaxed' for BOTH remaining paths that
    let a disallowed license through -- Tier 3's private-scope-with-
    acknowledgement case, and Tier 2's org-approved case -- since either
    way, gate_service.run_gate()'s own license_stage.run() would otherwise
    call is_allowed_license() itself and hard-block a license this
    function just finished approving. Tier 2's "share allowed" outcome
    would silently break without this: the item would still get created,
    but its gate run would come back gate_verdict='fail'. Raises
    LicenseAcknowledgementRequiredError (Tier 3, caller must acknowledge or
    declare self_authored) or LicenseNotAllowedByOrgPolicyError (Tier 2,
    the org hasn't opted into this license) otherwise.

    is_private: True for provision_scope in (None, 'private') at creation,
    or (for an existing item) when it currently has no install with a
    non-private scope -- see _item_has_shared_install() below. Tier 1
    (is_allowed_license) always wins outright regardless of is_private.
    """
    if not license:
        if is_private and self_authored:
            return "MIT", "strict"
        raise LicenseAcknowledgementRequiredError(
            "a license is required, or set self_authored=true to default it to MIT in your private space",
            reason="missing_license",
        )
    if is_allowed_license(license):
        return license, "strict"
    if is_private:
        if not license_acknowledged:
            raise LicenseAcknowledgementRequiredError(
                f"license {license!r} is not MIT/Apache-2.0-compatible — set license_acknowledged=true "
                f"to save it in your private space anyway; you're responsible for complying with it",
                reason="acknowledgement_required", declared_license=license,
            )
        return license, "relaxed"
    if _license_allowed_by_org_policy(license, org_id):
        return license, "relaxed"
    raise LicenseNotAllowedByOrgPolicyError(
        f"license {license!r} is not on org {org_id!r}'s allowed_licenses_shared list", declared_license=license,
    )


def _item_has_shared_install(item_id: str) -> bool:
    """Tier resolution for add_version_to_existing_item*() below, which has
    no provision_scope of its own (it only ever bumps an EXISTING item's
    content) -- an item is treated as still-private (Tier 3-eligible) only
    if every install of it anywhere is scope='private'; a single
    shared/org/provisioned/required install anywhere makes it Tier 2 for
    this purpose, matching the spec's "changing a private item's scope...
    re-runs the license check against tier 2" framing in reverse (an
    ALREADY-shared item's own content updates should be held to tier 2,
    not silently regain tier 3 just because this particular call has no
    scope concept)."""
    db = SessionLocal()
    try:
        return (
            db.query(EcosystemInstall)
            .filter(EcosystemInstall.item_id == item_id, EcosystemInstall.scope != "private")
            .first()
            is not None
        )
    finally:
        db.close()


def _safe_rel_path(rel_path: str, allowed_exts: set[str], prefix: str) -> str | None:
    """Port of AgentStudio/backend/skill_factory/pipeline.py:1284-1306's
    _safe_rel_path — same traversal/extension guard, generalized to a
    caller-supplied prefix/extension set rather than hardcoded scripts/references."""
    if not rel_path or not isinstance(rel_path, str):
        return None
    cleaned = rel_path.strip().lstrip("/").replace("\\", "/")
    if ".." in cleaned.split("/") or cleaned.startswith("/"):
        return None
    if not cleaned.startswith(prefix):
        cleaned = f"{prefix}{cleaned.split('/')[-1]}"
    ext = "." + cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
    if ext not in allowed_exts:
        return None
    return cleaned


def _create_item_and_version(
    *,
    org_id: str,
    created_by: str,
    item_type: str,
    namespace: str,
    display_name: str,
    description: str,
    category: str,
    tags: list[str],
    license: str,
    manifest: dict[str, Any],
    files: dict[str, str],
    trigger: str,
    provision_scope: str | None,
    surfaces: list[str],
    source_id: str | None = None,
    attribution: str = "",
    license_tier: str = "strict",
    attempt_fast_path: bool = False,
    created_via_ai: bool = False,
    scope: str = "org_private",
) -> dict[str, Any]:
    """attempt_fast_path (task D): only ever True from create_via_write()
    when its own eligibility conditions hold (private scope, no bundled
    files, item_type='skill') -- create_via_upload()/create_via_import()
    never pass it, so uploads/imports always keep the full async gate,
    per the task's own "uploads/imports from outside sources keep the
    normal gate" requirement, regardless of what trigger string happens
    to be passed (upload/import also use trigger="ui_add", the same value
    write uses -- eligibility here is driven by this explicit flag, not
    by re-deriving it from `trigger`).

    scope (item 6, M5 UI-parity review, 2026-09-28): real bug found live --
    every creation path, including create_via_import(), unconditionally
    created `scope='org_private', org_id=<importing org>` -- fine for a
    normal user's own import, but wrong for the admin starter-catalog
    batch (scripts/ecosystem/admin_import.py), whose own docstring and
    docs/ecosystem/catalog/starter-approved.md both describe those 8
    skills as "Discover catalog items (community tier, not org-wide
    auto-provisioned)" -- i.e. globally visible in Discover, not scoped
    to whichever one org happened to run the import. An org_private item
    is only ever visible to its own org's Discover feed at best (and, as
    of item 7's fix just above, never even that -- org_private is now
    excluded from Discover entirely), so those 8 skills were invisible to
    every org's Discover, including the importing org's own. Only
    create_via_import() actually exposes this (as `catalog_scope`) --
    create_via_write()/create_via_upload() keep the hardcoded
    'org_private' default unchanged, since a normal user's own
    write/upload was never meant to land in the global catalog.

    created_via_ai (item 7, M5 UI-parity review, 2026-09-28): real bug
    found live -- every item created through this function, regardless of
    path, was hardcoded to `trust_tier="community"`, so a skill built via
    Create-with-AI (drafts_service.submit_draft(), the only caller that
    passes True here) showed the same "Community" badge as a plain manual
    Write/upload/import. `TrustTier.agent_created` ("Agent-created") has
    existed in packages/ecosystem-ui/src/types.ts and Badges.tsx's own
    TRUST_LABEL map since the M4 frontend milestone, but nothing on the
    backend ever set it. Only drafts_service.submit_draft() passes True --
    create_via_write()'s own direct/manual callers (the plain "Write"
    flow, and everything create_via_upload()/create_via_import() do)
    default to False, unchanged."""
    # Defense-in-depth only: by the time callers reach this point, license
    # has already been through _resolve_creation_license() (task C) for
    # write/upload, or import's own always-strict pre-check -- this repeats
    # the Tier-1 check but never blocks a 'relaxed' license_tier caller
    # already re-validated under Tier 2/3.
    if license_tier == "strict" and not is_allowed_license(license):
        raise LicenseNotAllowedError(
            f"license {license!r} is not MIT/Apache-2.0-compatible", stage="import_precheck", declared_license=license
        )

    resolve_publisher(namespace, owner_type="org", owner_ref=org_id)
    # source_id is only passed by create_via_import (points at the real
    # external ecosystem_sources row) -- write/upload keep their existing
    # per-org 'local' source.
    if source_id is None:
        source_id = get_or_create_local_source(org_id, created_by=created_by)

    # Compatibility tag (explicit review request): a chat-only surface
    # can't follow instructions that assume shell/git/file-edit access.
    # Computed here -- the one choke point every creation path (write,
    # upload, import) already passes through -- rather than duplicated in
    # each caller. Stored on the manifest itself (no schema migration
    # needed; manifest is already an arbitrary JSONB blob every reader of
    # a version already parses) so ItemDetail/ItemSummary and the "add"
    # UI can surface it without a new column.
    compatibility = classify_compatibility(manifest.get("instructions", "") if isinstance(manifest, dict) else "")
    if isinstance(manifest, dict):
        manifest = {**manifest, "compatibility": compatibility}
    surfaces = (
        default_surfaces_for(compatibility) if not surfaces
        else enforce_compatibility_on_surfaces(compatibility, surfaces)
    )

    db = SessionLocal()
    try:
        item = EcosystemItem(
            namespace=namespace,
            item_type=item_type,
            category=category,
            tags=tags,
            display_name=display_name,
            description=description,
            source_id=source_id,
            scope=scope,
            # ECOSYSTEM_PLAN.md §4: org_id is non-NULL only for
            # scope='org_private' -- builtin/optional/central_index are
            # org-independent, matching upsert_builtin_item()'s own
            # org_id=None convention (item 6 fix, 2026-09-28).
            org_id=org_id if scope == "org_private" else None,
            trust_tier="agent_created" if created_via_ai else "community",
            license=license,
            # Durable ownership signal (db/migrate.py Part AD16) -- see
            # EcosystemItem.created_by's own docstring for why this can't
            # just be derived from the EcosystemInstall row the way
            # is_owner() used to.
            created_by=created_by,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
    finally:
        db.close()

    # Deterministic content encoding so identical (manifest, files) always
    # hashes identically, matching versions_service's own convention.
    payload = encode_envelope(manifest, files)
    version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=manifest, license=license, attribution=attribution,
    )

    if attempt_fast_path and not files:
        result = run_fast_path_gate(
            version_id, trigger=trigger, org_id=org_id,
            installed_by=created_by, installed_for=created_by,
            surfaces=surfaces, provision_scope=provision_scope, license_tier=license_tier,
        )
        return {
            "item_id": item_id,
            "version_id": version_id,
            "gate_run_id": result["gate_run_id"],
            "status": _VERDICT_TO_STATUS.get(result["verdict"], "verifying"),
            "provision_scope": provision_scope or "private",
            "compatibility": compatibility,
        }

    gate_run_id = enqueue_gate_run(
        version_id, trigger=trigger,
        installed_by=created_by, installed_for=created_by, org_id=org_id,
        surfaces=surfaces, provision_scope=provision_scope, license_tier=license_tier,
    )

    return {
        "item_id": item_id,
        "version_id": version_id,
        "gate_run_id": gate_run_id,
        "status": "verifying",
        "provision_scope": provision_scope or "private",
        "compatibility": compatibility,
    }


def create_via_write(
    *,
    org_id: str,
    created_by: str,
    item_type: str,
    namespace: str,
    display_name: str,
    description: str,
    category: str,
    tags: list[str] | None,
    license: str = "MIT",
    content: dict[str, Any],
    surfaces: list[str],
    provision_scope: str | None = None,
    caller_permissions: set[str] | None = None,
    license_acknowledged: bool = False,
    self_authored: bool = False,
    created_via_ai: bool = False,
) -> dict[str, Any]:
    _require_provision_permission(provision_scope, caller_permissions or set())
    _require_who_can_add_permission(org_id, caller_permissions or set())
    resolved_license, license_tier = _resolve_creation_license(
        license, is_private=provision_scope in (None, "private"), org_id=org_id,
        license_acknowledged=license_acknowledged, self_authored=self_authored,
    )
    manifest = {"name": display_name, "description": description, "instructions": content.get("instructions", "")}
    files = {f["name"]: f["content"] for f in content.get("files", [])}
    # Task D: Create with AI / Write / Save as skill all submit here (the
    # AI-draft and save-as-skill flows both go through drafts_service.py's
    # own call into this same function) -- eligible for the fast path when
    # private, no bundled scripts, and item_type='skill' (plugins/
    # connectors/MCP servers aren't buildable via this path today anyway,
    # but the check is explicit rather than assumed).
    attempt_fast_path = item_type == "skill" and provision_scope in (None, "private") and not files
    return _create_item_and_version(
        org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
        display_name=display_name, description=description, category=category, tags=tags or [],
        license=resolved_license, manifest=manifest, files=files, trigger="ui_add",
        provision_scope=provision_scope, surfaces=surfaces, license_tier=license_tier,
        attempt_fast_path=attempt_fast_path, created_via_ai=created_via_ai,
    )


def _require_owner_or_admin(item_id: str, org_id: str, caller_id: str, caller_permissions: set[str]) -> EcosystemItem:
    """Shared gate for add_version_to_existing_item*() -- item 6's own
    'Update my <skill>' flow (chat and Marketplace both, since both call
    into this same function). Only the item's owner (the caller who
    originally created it, origin='created') or an org admin
    (marketplace:provision) may add a new version -- mirrors
    compute_allowed_actions()'s own is_owner-or-admin pattern for
    'deprecate', the closest existing precedent for "who may change this
    item's own record" (as opposed to installing/uninstalling it)."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, org_id):
            raise NotFoundError(f"no such item {item_id!r}")
        is_owner = _is_owner(db, item_id, caller_id)
        db.expunge(item)
    finally:
        db.close()
    if not (is_owner or "marketplace:provision" in caller_permissions):
        raise PolicyForbiddenError(f"item {item_id!r} can only get a new version from its owner or an org admin")
    return item


def add_version_to_existing_item(
    *,
    item_id: str,
    org_id: str,
    updated_by: str,
    caller_permissions: set[str] | None = None,
    content: dict[str, Any],
    license: str | None = None,
    attribution: str = "",
    license_acknowledged: bool = False,
    self_authored: bool = False,
) -> dict[str, Any]:
    """Item 6's 'Update my <skill>' -- an immutable NEW version of an
    EXISTING item, never a new EcosystemItem row. Same content shape as
    create_via_write's own `content` (`{"instructions": ..., "files": [...]}`)
    so both the chat and Marketplace UIs can share one payload builder.
    Reuses versions_service.create_version_for_content()/gate_service.
    enqueue_gate_run() exactly -- the same two calls create_via_write's own
    _create_item_and_version() makes, just without creating the item row.

    trigger="new_version" (gate_service._bump_own_install_on_pass()) is
    what makes a passing/warn-ing re-gate automatically move the caller's
    OWN existing install onto the new version once it resolves -- "Update
    my skill" should feel like an update, not a second, separate install
    the caller has to notice and switch to by hand. "new_version" (not a
    "chat_"-prefixed name) reuses a trigger value db/migrate.py's own
    ecosystem_gate_runs_trigger_check CHECK constraint already allows --
    found live, a first draft using an unlisted trigger string got a real
    IntegrityError on every call.
    """
    item = _require_owner_or_admin(item_id, org_id, updated_by, caller_permissions or set())
    effective_license = license or item.license
    resolved_license, license_tier = _resolve_creation_license(
        effective_license, is_private=not _item_has_shared_install(item_id), org_id=org_id,
        license_acknowledged=license_acknowledged, self_authored=self_authored,
    )
    manifest = {"name": item.display_name, "description": item.description, "instructions": content.get("instructions", "")}
    files = {f["name"]: f["content"] for f in content.get("files", [])}
    payload = encode_envelope(manifest, files)
    version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=manifest, license=resolved_license, attribution=attribution,
    )
    gate_run_id = enqueue_gate_run(
        version_id, trigger="new_version",
        installed_by=updated_by, installed_for=updated_by, org_id=org_id, surfaces=[],
        license_tier=license_tier,
    )
    return {"item_id": item_id, "version_id": version_id, "gate_run_id": gate_run_id, "status": "verifying"}


def _parse_upload_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Extracted from create_via_upload() so item 6's add_version_to_
    existing_item_from_upload() ("attach a .zip/.skill in chat + 'add as
    skill'"/"update my skill from a file") can reuse the exact same
    parsing/validation -- path-traversal guards, zip-bomb guard,
    SKILL.md frontmatter license extraction -- rather than a second,
    divergent implementation of any of it. Returns
    {license, display_name, description, manifest, files} on success;
    raises the same EcosystemError/LicenseNotAllowedError create_via_upload
    always has.

    Deliberately NOT wired into create_via_upload() itself in this pass --
    that function's own tests already pin its exact current behavior
    (display_name falling back to the namespace's own last segment when
    frontmatter omits `name`, a namespace-aware default this function
    can't replicate since it has no namespace at parse time); swapping
    create_via_upload()'s internals for this shared helper is a safe
    follow-up, not bundled here to avoid any risk to tested behavior.
    """
    if len(zip_bytes) > _UPLOAD_MAX_SIZE_BYTES:
        raise EcosystemError(f"archive exceeds the {_UPLOAD_MAX_SIZE_BYTES // 1024}KB limit")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise EcosystemError("file is not a valid zip archive") from exc

    if sum(zi.file_size for zi in zf.infolist()) > _UPLOAD_MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise EcosystemError("archive contents are too large")

    def _read_entry(entry: str, limit: int) -> bytes:
        if zf.getinfo(entry).file_size > limit:
            raise EcosystemError(f"{entry!r} exceeds the {limit // 1024}KB limit")
        raw = zf.read(entry)
        if len(raw) > limit:
            raise EcosystemError(f"{entry!r} exceeds the {limit // 1024}KB limit")
        return raw

    names = [n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")]
    skill_md_entries = [n for n in names if n.split("/")[-1] == "SKILL.md"]
    if not skill_md_entries:
        raise EcosystemError("archive does not contain a SKILL.md")

    skill_md_bytes = _read_entry(skill_md_entries[0], _UPLOAD_MAX_SKILL_MD_BYTES)
    skill_md_text = skill_md_bytes.decode("utf-8", errors="replace")

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    # Deliberately NOT raising on a missing license: field here any more --
    # task C's tiered policy lets a private-scope item omit it if the
    # caller declares self_authored=true (defaults to MIT). The caller
    # (add_version_to_existing_item_from_upload) runs the real check via
    # _resolve_creation_license() right after this returns.
    license = frontmatter.get("license", "")
    display_name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")

    files: dict[str, str] = {}
    bundle_entries = [n for n in names if n not in skill_md_entries]
    if len(bundle_entries) > _UPLOAD_MAX_BUNDLE_FILES:
        raise EcosystemError(f"archive has more than {_UPLOAD_MAX_BUNDLE_FILES} bundled files")
    for entry in bundle_entries:
        rel = entry.split("/", 1)[-1] if "/" in entry else entry
        kind_prefix, allowed_exts = ("scripts/", {".py", ".sh", ".js"})
        safe = _safe_rel_path(rel, allowed_exts, kind_prefix) or _safe_rel_path(rel, {".md"}, "references/")
        if safe is None:
            continue
        files[safe] = _read_entry(entry, _UPLOAD_MAX_BUNDLE_FILE_BYTES).decode("utf-8", errors="replace")

    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}
    return {"license": license, "display_name": display_name, "description": description, "manifest": manifest, "files": files}


def add_version_to_existing_item_from_upload(
    *, item_id: str, org_id: str, updated_by: str, caller_permissions: set[str] | None = None, zip_bytes: bytes,
    license_acknowledged: bool = False, self_authored: bool = False,
) -> dict[str, Any]:
    """Item 6: 'attach a .zip/.skill in chat + add as skill,' when the
    target is an EXISTING item the caller owns (an update, not a new
    item) -- same parsing as create_via_upload(), via _parse_upload_zip()."""
    _require_owner_or_admin(item_id, org_id, updated_by, caller_permissions or set())
    parsed = _parse_upload_zip(zip_bytes)
    resolved_license, license_tier = _resolve_creation_license(
        parsed["license"], is_private=not _item_has_shared_install(item_id), org_id=org_id,
        license_acknowledged=license_acknowledged, self_authored=self_authored,
    )
    payload = encode_envelope(parsed["manifest"], parsed["files"])
    version_id = create_version_for_content(
        item_id=item_id, content=payload, manifest=parsed["manifest"], license=resolved_license, attribution="",
    )
    gate_run_id = enqueue_gate_run(
        version_id, trigger="new_version",
        installed_by=updated_by, installed_for=updated_by, org_id=org_id, surfaces=[],
        license_tier=license_tier,
    )
    return {"item_id": item_id, "version_id": version_id, "gate_run_id": gate_run_id, "status": "verifying"}


def create_via_upload(
    *,
    org_id: str,
    created_by: str,
    item_type: str,
    namespace: str,
    category: str,
    zip_bytes: bytes,
    surfaces: list[str],
    provision_scope: str | None = None,
    caller_permissions: set[str] | None = None,
    license_acknowledged: bool = False,
    self_authored: bool = False,
) -> dict[str, Any]:
    _require_provision_permission(provision_scope, caller_permissions or set())
    _require_who_can_add_permission(org_id, caller_permissions or set())

    if len(zip_bytes) > _UPLOAD_MAX_SIZE_BYTES:
        raise EcosystemError(f"archive exceeds the {_UPLOAD_MAX_SIZE_BYTES // 1024}KB limit")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise EcosystemError("file is not a valid zip archive") from exc

    # Zip-bomb guard: reject on the *declared* inflated total before reading
    # anything, same defense as the reference handler.
    if sum(zi.file_size for zi in zf.infolist()) > _UPLOAD_MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise EcosystemError("archive contents are too large")

    def _read_entry(entry: str, limit: int) -> bytes:
        if zf.getinfo(entry).file_size > limit:
            raise EcosystemError(f"{entry!r} exceeds the {limit // 1024}KB limit")
        raw = zf.read(entry)
        if len(raw) > limit:
            raise EcosystemError(f"{entry!r} exceeds the {limit // 1024}KB limit")
        return raw

    names = [n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")]
    skill_md_entries = [n for n in names if n.split("/")[-1] == "SKILL.md"]
    if not skill_md_entries:
        raise EcosystemError("archive does not contain a SKILL.md")

    skill_md_bytes = _read_entry(skill_md_entries[0], _UPLOAD_MAX_SKILL_MD_BYTES)
    skill_md_text = skill_md_bytes.decode("utf-8", errors="replace")

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    # Missing license: no longer an unconditional block (task C) -- a
    # private-scope upload may still proceed if self_authored=true is set,
    # resolved below via _resolve_creation_license() alongside every other
    # tier rule, instead of a separate ad-hoc check here.
    license = frontmatter.get("license", "")
    display_name = frontmatter.get("name", namespace.split("/")[-1])
    description = frontmatter.get("description", "")

    files: dict[str, str] = {}
    bundle_entries = [n for n in names if n not in skill_md_entries]
    if len(bundle_entries) > _UPLOAD_MAX_BUNDLE_FILES:
        raise EcosystemError(f"archive has more than {_UPLOAD_MAX_BUNDLE_FILES} bundled files")
    for entry in bundle_entries:
        rel = entry.split("/", 1)[-1] if "/" in entry else entry
        kind_prefix, allowed_exts = ("scripts/", {".py", ".sh", ".js"})
        safe = _safe_rel_path(rel, allowed_exts, kind_prefix) or _safe_rel_path(rel, {".md"}, "references/")
        if safe is None:
            continue  # skip unsafe/unrecognized entries, mirroring the reference handler's per-entry tolerance
        files[safe] = _read_entry(entry, _UPLOAD_MAX_BUNDLE_FILE_BYTES).decode("utf-8", errors="replace")

    resolved_license, license_tier = _resolve_creation_license(
        license, is_private=provision_scope in (None, "private"), org_id=org_id,
        license_acknowledged=license_acknowledged, self_authored=self_authored,
    )
    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}
    return _create_item_and_version(
        org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
        display_name=display_name, description=description, category=category, tags=[],
        license=resolved_license, manifest=manifest, files=files, trigger="ui_add",
        provision_scope=provision_scope, surfaces=surfaces, license_tier=license_tier,
    )


def create_via_import(
    *,
    org_id: str,
    created_by: str,
    item_type: str,
    namespace: str,
    category: str,
    kind: str,
    ref: str,
    surfaces: list[str] | None = None,
    license: str = "",
    provision_scope: str | None = None,
    caller_permissions: set[str] | None = None,
    catalog_scope: str = "org_private",
) -> dict[str, Any]:
    """Task I (pre-M3): real fetchers for kind='github_repo' (ref is
    "owner/repo", "owner/repo@branch_or_sha", or -- starter-catalog
    subdirectory extension, 2026-09-28 -- "owner/repo[@branch_or_sha]#path/
    to/skill" to import ONE candidate previously identified by
    discover_skills_in_repo() at that path, via import_from_github_path()
    instead of the root-only import_from_github()) and kind='well_known'
    (ref is "domain/skill_slug") — each adapter discovers and verifies its
    own license from the actual source content (repo SPDX + SKILL.md
    frontmatter for github_repo; the fetched SKILL.md's own license: field
    for well_known), so the caller-supplied `license` param is not used
    for either.

    Every other kind ('url', 'mcp_registry', 'private_git',
    'skills_sh_indirect') keeps task B-6's original scope: a pre-check
    against the caller-DECLARED `license`, rejected before any fetch,
    then NotImplementedError — no fetcher exists for these yet, disclosed
    rather than silently faked.

    catalog_scope (item 6, M5 UI-parity review, 2026-09-28): 'org_private'
    (default, unchanged behavior) or 'central_index' -- the latter is how
    scripts/ecosystem/admin_import.py's starter-catalog batch makes an
    imported item globally visible in every org's Discover feed (see
    docs/ecosystem/catalog/starter-approved.md's own "Discover catalog
    items (community tier, not org-wide auto-provisioned)" framing, which
    the prior hardcoded 'org_private' silently contradicted -- those 8
    skills were never actually visible to Discover for ANY org). Gated
    behind marketplace:admin_sources, the same tier force_disable()/
    unyank() already use for "this caller may act on the shared catalog
    itself," not just their own org's corner of it -- admin_import.py
    itself runs in-process (no HTTP caller_permissions to check), so this
    only matters for a future router-exposed import endpoint reusing this
    same function; unvalidated here would be a silent privilege gap the
    day one exists.
    """
    if catalog_scope not in ("org_private", "central_index"):
        raise EcosystemError(f"invalid catalog_scope {catalog_scope!r}")
    if catalog_scope != "org_private" and "marketplace:admin_sources" not in (caller_permissions or set()):
        raise PolicyForbiddenError("catalog_scope='central_index' requires marketplace:admin_sources")
    _require_provision_permission(provision_scope, caller_permissions or set())
    _require_who_can_add_permission(org_id, caller_permissions or set())
    surfaces = surfaces or []

    if kind == "github_repo":
        repo_and_ref, has_path, path = ref.partition("#")
        repo, _, branch_or_sha = repo_and_ref.partition("@")

        if has_path:
            from services.ecosystem.import_adapters.github_repo import import_from_github_path

            result = import_from_github_path(repo, path, branch_or_sha or None)
            attribution = f"github_repo:{repo}@{result['resolved_sha']}#{path}"
        else:
            from services.ecosystem.import_adapters.github_repo import import_from_github

            result = import_from_github(repo, branch_or_sha or None)
            attribution = f"github_repo:{repo}@{result['resolved_sha']}"

        source_id = get_or_create_import_source(
            kind="github_repo", url=result["source_url"], created_by=created_by,
            tos_notes=f"GitHub repository {repo!r} — public contents only, read-only import access.",
        )
        return _create_item_and_version(
            org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
            display_name=result["display_name"], description=result["description"], category=category,
            tags=[], license=result["license"], manifest=result["manifest"], files=result["files"],
            trigger="ui_add", provision_scope=provision_scope, surfaces=surfaces,
            source_id=source_id, attribution=attribution, scope=catalog_scope,
        )

    if kind == "well_known":
        from services.ecosystem.import_adapters.well_known import import_from_well_known

        domain, _, skill_slug = ref.partition("/")
        result = import_from_well_known(domain, skill_slug)
        source_id = get_or_create_import_source(
            kind="well_known", url=result["source_url"], created_by=created_by,
            tos_notes=f"Well-known skill index at {result['source_url']!r}.",
        )
        return _create_item_and_version(
            org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
            display_name=result["display_name"], description=result["description"], category=category,
            tags=[], license=result["license"], manifest=result["manifest"], files=result["files"],
            trigger="ui_add", provision_scope=provision_scope, surfaces=surfaces,
            source_id=source_id, attribution=f"well_known:{domain}/{skill_slug}#{result['resolved_sha']}",
            scope=catalog_scope,
        )

    if not is_allowed_license(license):
        raise LicenseNotAllowedError(
            f"declared license {license!r} is not MIT/Apache-2.0-compatible — rejected before fetching {ref!r}",
            stage="import_precheck", declared_license=license,
        )

    raise NotImplementedError(
        f"create_via_import: license pre-check passed, but no external-source "
        f"fetcher is wired up for kind={kind!r} this phase"
    )
