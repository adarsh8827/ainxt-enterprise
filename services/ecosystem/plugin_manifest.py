# SPDX-License-Identifier: MIT
# ============================================================
# Plugin manifest composition validation (docs/ecosystem/
# PLUGINS_PHASE_PLAN.md item 1). Used by both routers/ecosystem_router.py's
# POST /ecosystem/items/{id}/plugin-compose (synchronous pre-check, raises
# PluginComposeInvalidError) and services/ecosystem/gate/manifest_stage.py's
# plugin-bundle branch (async gate re-check, produces Findings) -- same
# underlying validate_composition(), two different error-surfacing
# mechanisms, matching this codebase's existing pre-check + gate pattern
# for license checks (see errors.py's LicenseNotAllowedError docstring).
#
# Real scope boundary, disclosed rather than papered over: ItemType (
# CONTRACTS.md §1) is only skill|plugin|mcp_server|connector today -- there
# is no backing EcosystemItem item_type for "command", "agent", or "hook".
# Those three part kinds are therefore validated for SHAPE only (a
# non-empty namespace string) -- existence against a real catalog item is
# only checked for skills/connectors/mcp_servers, which DO have a backing
# item_type. This is not a bug to fix here; it's a real gap in the current
# schema this task was not scoped to close.
# ============================================================

from __future__ import annotations

from typing import Any

PART_KINDS = ("skills", "commands", "agents", "connectors", "mcp_servers", "hooks")

# Only these three part kinds have a real, checkable backing item_type today.
_PART_KIND_TO_ITEM_TYPE = {
    "skills": "skill",
    "connectors": "connector",
    "mcp_servers": "mcp_server",
}


class CompositionError(Exception):
    """Raised by validate_composition(). `code` matches one of the
    PLUGIN_COMPOSE_INVALID sub-reasons documented in CONTRACTS.md §20."""

    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _all_namespaces(parts: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Flattens {kind: [namespace, ...]} into [(kind, namespace), ...],
    preserving which part-kind each namespace came from."""
    out: list[tuple[str, str]] = []
    for kind in PART_KINDS:
        for ns in parts.get(kind, []) or []:
            out.append((kind, ns))
    return out


def validate_composition(parts: dict[str, list[str]], *, org_id: str) -> None:
    """Raises CompositionError on the first real problem found:
      - PLUGIN_UNKNOWN_PART_KIND: a key in `parts` isn't one of PART_KINDS.
      - PLUGIN_DUPLICATE_NAMESPACE: the same namespace appears twice, even
        across different part kinds (the plan's own "no duplicate namespace
        across parts" rule -- one namespace, one identity, regardless of
        which bucket it's declared under).
      - PLUGIN_PART_NOT_FOUND: a skills/connectors/mcp_servers namespace
        doesn't resolve to a real EcosystemItem of the matching item_type.
      - PLUGIN_LICENSE_NOT_ALLOWED: a referenced part's own current version
        has a license that fails services.ecosystem.license_policy.
        is_allowed_license() -- defense in depth; every part SHOULD have
        already passed this at its own creation time, but a grandfathered
        or self-authored-bypass item could still carry a disallowed one.

    Empty `parts` (a plugin with zero bundled parts) is not itself an
    error here -- that is a product decision for the caller/gate to make,
    not a composition-validity question.
    """
    from db.database import SessionLocal
    from db.models import EcosystemItem, EcosystemItemVersion
    from services.ecosystem.license_policy import is_allowed_license

    unknown_kinds = set(parts.keys()) - set(PART_KINDS)
    if unknown_kinds:
        raise CompositionError(
            f"unknown plugin part kind(s): {sorted(unknown_kinds)!r}",
            code="PLUGIN_UNKNOWN_PART_KIND", details={"unknown_kinds": sorted(unknown_kinds)},
        )

    flattened = _all_namespaces(parts)
    seen: dict[str, str] = {}
    for kind, ns in flattened:
        if ns in seen:
            raise CompositionError(
                f"namespace {ns!r} is declared more than once (as {seen[ns]!r} and {kind!r})",
                code="PLUGIN_DUPLICATE_NAMESPACE", details={"namespace": ns},
            )
        seen[ns] = kind

    from services.ecosystem.items_service import _visible_to_caller

    db = SessionLocal()
    try:
        for kind, ns in flattened:
            expected_item_type = _PART_KIND_TO_ITEM_TYPE.get(kind)
            if expected_item_type is None:
                # commands/agents/hooks: shape-only check, no backing item_type exists yet.
                if not ns or not isinstance(ns, str):
                    raise CompositionError(
                        f"{kind} entry must be a non-empty namespace string",
                        code="PLUGIN_PART_NOT_FOUND", details={"kind": kind, "namespace": ns},
                    )
                continue

            item = db.query(EcosystemItem).filter(EcosystemItem.namespace == ns).first()
            # _visible_to_caller() also closes a real cross-org probe: without
            # it, a caller could learn "this namespace exists" for another
            # org's org_private item by seeing PLUGIN_LICENSE_NOT_ALLOWED
            # instead of PLUGIN_PART_NOT_FOUND -- same NOT_FOUND-not-
            # PolicyForbidden convention used elsewhere in this codebase for
            # cross-org lookups (installs_service._authorize_install_mutation()'s
            # own docstring documents the same reasoning).
            if item is None or item.item_type != expected_item_type or not _visible_to_caller(item, org_id):
                raise CompositionError(
                    f"{kind} part {ns!r} does not resolve to a real {expected_item_type!r} item",
                    code="PLUGIN_PART_NOT_FOUND",
                    details={"kind": kind, "namespace": ns, "expected_item_type": expected_item_type},
                )

            version = (
                db.query(EcosystemItemVersion)
                .filter(EcosystemItemVersion.item_id == item.id)
                .order_by(EcosystemItemVersion.created_at.desc())
                .first()
            )
            declared_license = version.license if version is not None else None
            if not is_allowed_license(declared_license):
                raise CompositionError(
                    f"{kind} part {ns!r} has a disallowed license {declared_license!r}",
                    code="PLUGIN_LICENSE_NOT_ALLOWED",
                    details={"kind": kind, "namespace": ns, "license": declared_license},
                )
    finally:
        db.close()
