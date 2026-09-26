# SPDX-License-Identifier: MIT
# ============================================================
# Creation service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-6):
# one service, three payload shapes (write/upload/import), all going
# through the exact same gate — no fast path for any creation method.
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
from db.models import EcosystemItem
from services.ecosystem.errors import EcosystemError, LicenseNotAllowedError, PolicyForbiddenError
from services.ecosystem.gate_service import enqueue_gate_run
from services.ecosystem.items_service import get_or_create_import_source, get_or_create_local_source
from services.ecosystem.license_policy import is_allowed_license
from services.ecosystem.publishers_service import resolve_publisher
from services.ecosystem.versions_service import create_version_for_content, encode_envelope

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
) -> dict[str, Any]:
    if not is_allowed_license(license):
        raise LicenseNotAllowedError(
            f"license {license!r} is not MIT/Apache-2.0-compatible", stage="import_precheck", declared_license=license
        )

    resolve_publisher(namespace, owner_type="org", owner_ref=org_id)
    # source_id is only passed by create_via_import (points at the real
    # external ecosystem_sources row) -- write/upload keep their existing
    # per-org 'local' source.
    if source_id is None:
        source_id = get_or_create_local_source(org_id, created_by=created_by)

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
            scope="org_private",
            org_id=org_id,
            trust_tier="community",
            license=license,
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
    gate_run_id = enqueue_gate_run(
        version_id, trigger=trigger,
        installed_by=created_by, installed_for=created_by, org_id=org_id,
        surfaces=surfaces, provision_scope=provision_scope,
    )

    return {
        "item_id": item_id,
        "version_id": version_id,
        "gate_run_id": gate_run_id,
        "status": "verifying",
        "provision_scope": provision_scope or "private",
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
) -> dict[str, Any]:
    _require_provision_permission(provision_scope, caller_permissions or set())
    manifest = {"name": display_name, "description": description, "instructions": content.get("instructions", "")}
    files = {f["name"]: f["content"] for f in content.get("files", [])}
    return _create_item_and_version(
        org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
        display_name=display_name, description=description, category=category, tags=tags or [],
        license=license, manifest=manifest, files=files, trigger="ui_add",
        provision_scope=provision_scope, surfaces=surfaces,
    )


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
) -> dict[str, Any]:
    _require_provision_permission(provision_scope, caller_permissions or set())

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
    license = frontmatter.get("license", "")
    if not license:
        raise LicenseNotAllowedError(
            "uploaded SKILL.md is missing a license: frontmatter field", stage="import_precheck", declared_license=None
        )
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

    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}
    return _create_item_and_version(
        org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
        display_name=display_name, description=description, category=category, tags=[],
        license=license, manifest=manifest, files=files, trigger="ui_add",
        provision_scope=provision_scope, surfaces=surfaces,
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
) -> dict[str, Any]:
    """Task I (pre-M3): real fetchers for kind='github_repo' (ref is
    "owner/repo" or "owner/repo@branch_or_sha") and kind='well_known'
    (ref is "domain/skill_slug") — each adapter discovers and verifies its
    own license from the actual source content (repo SPDX + SKILL.md
    frontmatter for github_repo; the index entry for well_known), so the
    caller-supplied `license` param is not used for either.

    Every other kind ('url', 'mcp_registry', 'private_git',
    'skills_sh_indirect') keeps task B-6's original scope: a pre-check
    against the caller-DECLARED `license`, rejected before any fetch,
    then NotImplementedError — no fetcher exists for these yet, disclosed
    rather than silently faked.
    """
    _require_provision_permission(provision_scope, caller_permissions or set())
    surfaces = surfaces or []

    if kind == "github_repo":
        from services.ecosystem.import_adapters.github_repo import import_from_github

        repo, _, branch_or_sha = ref.partition("@")
        result = import_from_github(repo, branch_or_sha or None)
        source_id = get_or_create_import_source(
            kind="github_repo", url=result["source_url"], created_by=created_by,
            tos_notes=f"GitHub repository {repo!r} — public contents only, read-only import access.",
        )
        return _create_item_and_version(
            org_id=org_id, created_by=created_by, item_type=item_type, namespace=namespace,
            display_name=result["display_name"], description=result["description"], category=category,
            tags=[], license=result["license"], manifest=result["manifest"], files=result["files"],
            trigger="ui_add", provision_scope=provision_scope, surfaces=surfaces,
            source_id=source_id, attribution=f"github_repo:{repo}@{result['resolved_sha']}",
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
