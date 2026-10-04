# SPDX-License-Identifier: MIT
# ============================================================
# Policy service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-19):
# sharing, reporting, force-disable/unyank, featured overrides, and the
# require/unrequire actions from the Review round following M1 (item F).
#
# Org policy CRUD (who_can_add/allowed_sources/auto_update_default) landed
# in task M4/F-13 -- get_policy()/set_policy() below, backed by the
# ecosystem_org_policy table (db/migrate.py Part AD4, added once F-13's
# AdminPolicies.tsx needed a real endpoint to call).
# ============================================================

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from db.database import SessionLocal
from db.models import (
    EcosystemFeaturedOverride, EcosystemInstall, EcosystemItem,
    EcosystemOrgExcludedDefault, EcosystemOrgPolicy, EcosystemReport, EcosystemShare,
)
from services.ecosystem.errors import EcosystemError, LicenseNotAllowedByOrgPolicyError, NotFoundError
from services.ecosystem.gate_service import ensure_full_gate_for_scope_widen
from services.ecosystem.items_service import _UUID_RE, _visible_to_caller
from services.ecosystem.license_policy import is_allowed_license

_VALID_WHO_CAN_ADD = ("all_users", "admins_only")
_VALID_ETHICS_REVIEW_POLICY = ("always", "scripts_or_noncatalog", "never")


def _require_valid_item_id(item_id: str) -> None:
    """BUG-05 fix: force_disable/unyank/require_item/unrequire_item/
    set_featured_override/delete_featured_override all pass item_id
    straight into a `WHERE id = :item_id` query against a uuid column --
    Postgres rejects a non-UUID string with a raw, unhandled DataError
    (not an EcosystemError, so routers/ecosystem_router.py's
    `except EcosystemError` never catches it), surfacing as a bare 500
    instead of a clean validation error. A bare EcosystemError already
    maps to a clean 400 BAD_REQUEST in _handle_ecosystem_error() -- no new
    error type needed. Same _UUID_RE items_service.py's own
    _resolve_item_by_id_or_namespace() already uses for the identical
    purpose."""
    if not _UUID_RE.match(item_id):
        raise EcosystemError(f"{item_id!r} is not a valid item id")


def _write_audit_best_effort(*, org_id: str, actor: str | None, action: str, item_id: str | None, details: dict) -> None:
    """Same best-effort contract as installs_service._publish_change()'s
    own audit write -- never allowed to turn an already-committed real
    mutation into a request-handler error. `actor` is optional here (some
    of this module's own callers don't have one threaded through yet) --
    a None actor is skipped, not recorded as a fake/empty actor string."""
    if actor is None:
        return
    try:
        from services.ecosystem.audit_service import write_audit_event
        write_audit_event(org_id=org_id, actor=actor, action=action, item_id=item_id, details=details)
    except Exception:
        pass

# Task B-19's own test requirement names this exact scenario; a small,
# deliberately conservative threshold for a first-party marketplace where
# reporting is unrestricted (never permission-gated, so it must not be too
# easy to accidentally auto-hide something on a couple of spurious reports).
_AUTO_HIDE_REPORT_THRESHOLD = 3


def check_tier2_license(item_id: str, org_id: str) -> None:
    """Tier 2 of the tiered license policy (task C, ECOSYSTEM_PLAN.md
    §11.2): re-run at the exact point an item's scope becomes
    shared/org/provisioned/required -- covers both this function (sharing
    to a user/group) and the install-scope check in
    routers/ecosystem_router.py's install_item (provisioning/required).
    Tier 1 (MIT/Apache) always passes outright; otherwise the target org's
    own allowed_licenses_shared list decides. Raises
    LicenseNotAllowedByOrgPolicyError, never silently narrows an install
    that's already there -- this only gates the NEW share/scope-change."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        item_license = item.license if item is not None else ""
    finally:
        db.close()
    if is_allowed_license(item_license):
        return
    # BUG-09 fix: this used to be `... or ["MIT", "Apache-2.0"]`, a falsy
    # check that silently resurrected the default whenever an admin
    # intentionally cleared the list to [] -- `.get(..., [])` here is only
    # a defensive fallback for the key being absent, never a value-based
    # override of a genuinely empty, intentional list.
    allowed = get_policy(org_id).get("allowed_licenses_shared", [])
    normalized = item_license.lower()
    if any(a.strip().lower() in normalized for a in allowed if a and a.strip()):
        return
    raise LicenseNotAllowedByOrgPolicyError(
        f"license {item_license!r} is not on org {org_id!r}'s allowed_licenses_shared list", declared_license=item_license,
    )


def share(install_id: str, shared_with_type: str, shared_with_id: str, *, caller_org_id: str, actor: str | None = None) -> dict[str, Any]:
    """caller_org_id: added after this shipped with no check that the
    caller-supplied install_id actually belongs to the caller's own org --
    a caller could otherwise share (and, via unshare below, revoke)
    another org's install just by knowing its UUID.

    Authorization for WHO may call this at all lives in
    routers/ecosystem_router.py's share_item, not here: sharing is gated
    by the org's own who_can_share policy (default "all_users" -- a normal
    user can share their own item's install with specific users/groups by
    default), with marketplace:provision always passing regardless of that
    policy. A share only records an EcosystemShare row visible to the named
    recipient as "Shared with me" -- it never auto-installs for anyone and
    never changes any install's own scope/provision state."""
    db = SessionLocal()
    try:
        install = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if install is None or install.org_id != caller_org_id:
            raise NotFoundError(f"no install {install_id!r}")
        item_id, version_id, installed_by, surfaces = install.item_id, install.version_id, install.installed_by, install.surfaces
    finally:
        db.close()
    check_tier2_license(item_id, caller_org_id)
    # Task D: sharing is exactly the kind of scope-widen that must upgrade
    # a fast-pathed (private-only) version to the full 7-stage gate before
    # anyone else is meant to trust its verdict -- no-op if this version
    # already went through the full gate.
    ensure_full_gate_for_scope_widen(item_id, version_id, org_id=caller_org_id, requested_by=installed_by, surfaces=surfaces)
    db = SessionLocal()
    try:
        row = EcosystemShare(install_id=install_id, shared_with_type=shared_with_type, shared_with_id=shared_with_id)
        db.add(row)
        db.commit()
        db.refresh(row)
        result = {"share_id": row.id, "install_id": install_id, "shared_with_type": shared_with_type, "shared_with_id": shared_with_id}
    finally:
        db.close()
    _write_audit_best_effort(
        org_id=caller_org_id, actor=actor, action="share", item_id=item_id,
        details={"install_id": install_id, "shared_with_type": shared_with_type, "shared_with_id": shared_with_id},
    )
    return result


def unshare(share_id: str, *, caller_org_id: str, actor: str | None = None) -> None:
    """caller_org_id: same fix as share() above -- joins through to the
    underlying install's org, since EcosystemShare itself has no org_id
    column of its own."""
    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemShare)
            .join(EcosystemInstall, EcosystemShare.install_id == EcosystemInstall.id)
            .filter(EcosystemShare.id == share_id, EcosystemInstall.org_id == caller_org_id)
            .first()
        )
        if row is None:
            raise NotFoundError(f"no share {share_id!r}")
        install_id = row.install_id
        install_row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        item_id = install_row.item_id if install_row is not None else None
        db.delete(row)
        db.commit()
    finally:
        db.close()
    _write_audit_best_effort(
        org_id=caller_org_id, actor=actor, action="unshare", item_id=item_id,
        details={"share_id": share_id, "install_id": install_id},
    )
    # Real gap found live (2026-09-29, install-state-consistency round):
    # unshare() never published ecosystem.changed at all -- Yours/Detail/
    # Discover had no signal that a share the caller could see just
    # disappeared. Best-effort, same as every other publish call site.
    if item_id:
        try:
            from services.ecosystem.events_service import publish_ecosystem_changed

            db = SessionLocal()
            try:
                item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
                item_type = item.item_type if item else None
            finally:
                db.close()
            if item_type:
                publish_ecosystem_changed(caller_org_id, item_type=item_type, item_id=item_id, scope="org", change="updated")
        except Exception:
            pass


def report(item_id: str, reported_by: str, reason: str) -> dict[str, Any]:
    """Reporting a suspect item is deliberately never permission-gated
    (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-19) — restricting who can
    flag a problem works against the gate's own safety goals."""
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise NotFoundError(f"no item {item_id!r}")

        row = EcosystemReport(item_id=item_id, reported_by=reported_by, reason=reason)
        db.add(row)
        db.commit()
        db.refresh(row)

        open_count = (
            db.query(EcosystemReport)
            .filter(EcosystemReport.item_id == item_id, EcosystemReport.status == "open")
            .count()
        )
        if open_count >= _AUTO_HIDE_REPORT_THRESHOLD:
            db.query(EcosystemReport).filter(
                EcosystemReport.item_id == item_id, EcosystemReport.status == "open"
            ).update({"status": "auto_hidden"}, synchronize_session=False)
            db.commit()

        return {"report_id": row.id, "item_id": item_id, "status": row.status}
    finally:
        db.close()


def force_disable(item_id: str, *, caller_org_id: str, actor: str | None = None) -> None:
    """Admin-only (enforced by the router's require_permission dependency,
    not here — this function trusts its caller has marketplace:admin_sources).
    Maps to ecosystem_items.status='yanked', the same status an
    upstream-source-initiated removal already uses — force_disable is the
    platform-initiated equivalent.

    caller_org_id: added after this shipped with no org boundary at all --
    an org's admin role is a global role string (auth/rbac.py has no
    per-org role concept), so without this check ANY org's admin could
    force-disable/unyank ANY OTHER org's private item. Reuses
    items_service's own `_visible_to_caller()` -- a global/builtin item has
    no single owning org and stays reachable by any admin, matching how
    every admin can already see it; an org_private item only by its own
    org's admin."""
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, caller_org_id):
            raise NotFoundError(f"no item {item_id!r}")
        item.status = "yanked"
        db.commit()
    finally:
        db.close()
    _write_audit_best_effort(org_id=caller_org_id, actor=actor, action="force_disable", item_id=item_id, details={})


def unyank(item_id: str, *, caller_org_id: str, actor: str | None = None) -> None:
    """caller_org_id: same fix as force_disable() above."""
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, caller_org_id):
            raise NotFoundError(f"no item {item_id!r}")
        item.status = "active"
        db.commit()
    finally:
        db.close()
    _write_audit_best_effort(org_id=caller_org_id, actor=actor, action="unyank", item_id=item_id, details={})


def set_featured_override(org_id: str, item_id: str, featured: bool, set_by: str) -> dict[str, Any]:
    # BUG-05/BUG-07 fix: validate shape, then confirm the item actually
    # exists before touching ecosystem_featured_overrides at all --
    # item_id is a real FK to ecosystem_items.id, so inserting against a
    # syntactically-valid but nonexistent id previously hit a raw,
    # unhandled IntegrityError (500) instead of a clean 404.
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        if db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first() is None:
            raise NotFoundError(f"no item {item_id!r}")
        existing = (
            db.query(EcosystemFeaturedOverride)
            .filter(EcosystemFeaturedOverride.org_id == org_id, EcosystemFeaturedOverride.item_id == item_id)
            .first()
        )
        if existing is not None:
            existing.featured = featured
            existing.set_by = set_by
            db.commit()
            return {"org_id": org_id, "item_id": item_id, "featured": featured}
        row = EcosystemFeaturedOverride(org_id=org_id, item_id=item_id, featured=featured, set_by=set_by)
        db.add(row)
        db.commit()
        return {"org_id": org_id, "item_id": item_id, "featured": featured}
    finally:
        db.close()


def delete_featured_override(org_id: str, item_id: str) -> None:
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        db.query(EcosystemFeaturedOverride).filter(
            EcosystemFeaturedOverride.org_id == org_id, EcosystemFeaturedOverride.item_id == item_id
        ).delete()
        db.commit()
    finally:
        db.close()


def require_item(item_id: str, org_id: str, *, actor: str | None = None) -> int:
    """Promotes every existing 'provisioned' install of item_id in org_id to
    'required' (CONFIG_AND_PRODUCTS.md §12 point 3/Review round item F) —
    removing 'disable' from their allowed_actions. Future lazy-provisioning
    calls (task B-12) are expected to check for this via the same
    origin='required' rows this creates, so a not-yet-provisioned user gets
    'required' from their first call rather than 'provisioned'. Returns the
    number of rows promoted.

    BUG-05/BUG-06 fix: validates item_id's shape and confirms the item
    actually exists (same _visible_to_caller() check force_disable/unyank
    already do) before running the UPDATE -- previously a malformed id hit
    a raw 500, and a syntactically-valid but nonexistent id silently
    "succeeded" with promoted_installs=0 and no indication anything was
    wrong. A real item that simply has nothing left to promote (e.g.
    already fully required) is a legitimate, distinct case and still
    returns count=0 without erroring -- only a genuinely nonexistent item
    now 404s."""
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, org_id):
            raise NotFoundError(f"no item {item_id!r}")
        count = (
            db.query(EcosystemInstall)
            .filter(
                EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id,
                EcosystemInstall.origin == "provisioned",
            )
            .update({"scope": "required", "origin": "required"}, synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()
    _write_audit_best_effort(org_id=org_id, actor=actor, action="provision", item_id=item_id, details={"promoted_installs": count})
    return count


def unrequire_item(item_id: str, org_id: str, *, actor: str | None = None) -> int:
    """BUG-05/BUG-06 fix: same existence check as require_item() above."""
    _require_valid_item_id(item_id)
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None or not _visible_to_caller(item, org_id):
            raise NotFoundError(f"no item {item_id!r}")
        count = (
            db.query(EcosystemInstall)
            .filter(
                EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id,
                EcosystemInstall.origin == "required",
            )
            .update({"scope": "provisioned", "origin": "provisioned"}, synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()
    _write_audit_best_effort(org_id=org_id, actor=actor, action="unprovision", item_id=item_id, details={"demoted_installs": count})
    return count


def admin_disable_org_default(item_id: str, org_id: str, disabled_by: str) -> dict[str, Any]:
    """Item 4a (pre-M3): an admin removes a builtin/provisioned default for
    their whole org (docs/ecosystem/design/LLD/install-lifecycle.md's
    lazy-provisioning section). Two effects, both immediate:

    1. Every EXISTING install row for (item_id, org_id) with
       origin IN ('provisioned', 'required') is disabled right now --
       "applies to all users immediately," not just future ones. A
       required install is included: an admin explicitly removing a
       default overrides the required-lock, which only exists to stop a
       normal user's disable action, not this one.
    2. An ecosystem_org_excluded_defaults row is recorded so B-12's future
       config_service lazy-provisioning sweep skips this (item_id, org_id)
       pair when it considers a not-yet-provisioned user in this org --
       without this, a brand-new org member would silently get the
       excluded default re-provisioned on their first request.

    Idempotent: calling this twice never errors and never duplicates the
    exclusion row (caught-and-ignored on a duplicate key); the returned
    installs_disabled count only ever reflects rows *newly* disabled by
    this call (the filter excludes already-disabled rows), so a second
    call reports 0 rather than re-counting the same rows.
    """
    db = SessionLocal()
    try:
        affected = (
            db.query(EcosystemInstall)
            .filter(
                EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id,
                EcosystemInstall.origin.in_(("provisioned", "required")),
                EcosystemInstall.enabled.is_(True),
            )
            .update({"enabled": False}, synchronize_session=False)
        )
        db.commit()

        existing = (
            db.query(EcosystemOrgExcludedDefault)
            .filter(EcosystemOrgExcludedDefault.org_id == org_id, EcosystemOrgExcludedDefault.item_id == item_id)
            .first()
        )
        if existing is None:
            db.add(EcosystemOrgExcludedDefault(org_id=org_id, item_id=item_id, excluded_by=disabled_by))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # a concurrent caller already inserted the same key
    finally:
        db.close()

    return {"item_id": item_id, "org_id": org_id, "installs_disabled": affected, "excluded": True}


def admin_restore_org_default(item_id: str, org_id: str) -> dict[str, Any]:
    """Reverses admin_disable_org_default()'s exclusion so future
    lazy-provisioning calls resume creating rows for new users. Disclosed,
    deliberate limitation: this does NOT retroactively re-enable installs
    that were disabled by admin_disable_org_default() (or by a user's own,
    independent disable action -- the enabled=False flag alone can't
    distinguish the two). A future admin-tooling task (F-13/M4) that wants
    "restore means re-enable for everyone" needs its own marker to tell
    those two cases apart; not built here since nothing currently reads
    the difference.
    """
    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemOrgExcludedDefault)
            .filter(EcosystemOrgExcludedDefault.org_id == org_id, EcosystemOrgExcludedDefault.item_id == item_id)
            .first()
        )
        was_excluded = row is not None
        if row is not None:
            db.delete(row)
            db.commit()
        return {"item_id": item_id, "org_id": org_id, "excluded": False, "was_excluded": was_excluded}
    finally:
        db.close()


def _policy_to_dict(org_id: str, row: EcosystemOrgPolicy | None) -> dict[str, Any]:
    if row is None:
        return {
            "org_id": org_id, "who_can_add": "all_users",
            "allowed_sources": ["central_index"], "auto_update_default": False,
            "allowed_licenses_shared": ["MIT", "Apache-2.0"],
            "who_can_share": "all_users",
            "ethics_review_policy": "scripts_or_noncatalog",
            "gate_precheck_enabled": False, "gate_precheck_cap_per_hour": 20,
            "live_sources_enabled": False,
        }
    return {
        "org_id": org_id, "who_can_add": row.who_can_add,
        "allowed_sources": row.allowed_sources or [], "auto_update_default": row.auto_update_default,
        # BUG-09 fix: this used to be `row.allowed_licenses_shared or
        # ["MIT", "Apache-2.0"]` -- a falsy check. The column is
        # nullable=False (db/models.py), so this value is NEVER actually
        # None; the `row is None` case (an org with no policy row at all)
        # is already handled separately above. The only thing the old `or`
        # fallback could ever actually catch here was a genuinely,
        # intentionally cleared empty list -- silently resurrecting the
        # default on every single read, so "clear this field" visibly
        # never took effect no matter how many times an admin saved it.
        "allowed_licenses_shared": row.allowed_licenses_shared,
        "who_can_share": row.who_can_share,
        "ethics_review_policy": row.ethics_review_policy,
        "gate_precheck_enabled": row.gate_precheck_enabled,
        "gate_precheck_cap_per_hour": row.gate_precheck_cap_per_hour,
        "live_sources_enabled": row.live_sources_enabled,
    }


def get_ethics_review_policy(org_id: str) -> str:
    """gate_service.run_gate()'s own lookup (catalog-checking round,
    2026-09-28) -- a narrow accessor rather than the full get_policy()
    dict, since run_gate() needs exactly this one value and importing
    this whole module already crosses gate_service.py's own import of
    ensure_full_gate_for_scope_widen() from this module (broken by making
    that specific call site's import lazy, not by this function's shape).
    """
    return get_policy(org_id)["ethics_review_policy"]


def get_policy(org_id: str) -> dict[str, Any]:
    """GET /ecosystem/policy (task F-13's AdminPolicies.tsx). An org with
    no row yet gets the documented defaults (never a 404 — "no policy set"
    is a valid, meaningful state, not a missing resource) — matches
    CONFIG_AND_PRODUCTS.md §5's policy_summary defaults exactly, so a
    freshly-migrated org's admin screen and its GET /ecosystem/config
    projection never disagree."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemOrgPolicy).filter(EcosystemOrgPolicy.org_id == org_id).first()
        return _policy_to_dict(org_id, row)
    finally:
        db.close()


def set_policy(
    org_id: str, *, who_can_add: str | None = None, allowed_sources: list[str] | None = None,
    auto_update_default: bool | None = None, allowed_licenses_shared: list[str] | None = None,
    who_can_share: str | None = None, ethics_review_policy: str | None = None,
    gate_precheck_enabled: bool | None = None, gate_precheck_cap_per_hour: int | None = None,
    live_sources_enabled: bool | None = None,
    updated_by: str,
) -> dict[str, Any]:
    """PUT /ecosystem/policy — partial update; an omitted field keeps its
    current (or default) value rather than being reset."""
    if who_can_add is not None and who_can_add not in _VALID_WHO_CAN_ADD:
        raise EcosystemError(f"who_can_add must be one of {_VALID_WHO_CAN_ADD!r}, got {who_can_add!r}")
    if who_can_share is not None and who_can_share not in _VALID_WHO_CAN_ADD:
        raise EcosystemError(f"who_can_share must be one of {_VALID_WHO_CAN_ADD!r}, got {who_can_share!r}")
    if ethics_review_policy is not None and ethics_review_policy not in _VALID_ETHICS_REVIEW_POLICY:
        raise EcosystemError(f"ethics_review_policy must be one of {_VALID_ETHICS_REVIEW_POLICY!r}, got {ethics_review_policy!r}")
    db = SessionLocal()
    try:
        row = db.query(EcosystemOrgPolicy).filter(EcosystemOrgPolicy.org_id == org_id).first()
        if row is None:
            row = EcosystemOrgPolicy(org_id=org_id)
            db.add(row)
        if who_can_add is not None:
            row.who_can_add = who_can_add
        if allowed_sources is not None:
            row.allowed_sources = allowed_sources
        if auto_update_default is not None:
            row.auto_update_default = auto_update_default
        if allowed_licenses_shared is not None:
            row.allowed_licenses_shared = allowed_licenses_shared
        if who_can_share is not None:
            row.who_can_share = who_can_share
        if ethics_review_policy is not None:
            row.ethics_review_policy = ethics_review_policy
        if gate_precheck_enabled is not None:
            row.gate_precheck_enabled = gate_precheck_enabled
        if gate_precheck_cap_per_hour is not None:
            row.gate_precheck_cap_per_hour = gate_precheck_cap_per_hour
        if live_sources_enabled is not None:
            row.live_sources_enabled = live_sources_enabled
        row.updated_by = updated_by
        db.commit()
        result = _policy_to_dict(org_id, row)
    finally:
        db.close()
    _write_audit_best_effort(org_id=org_id, actor=updated_by, action="policy_change", item_id=None, details=result)
    return result


def is_org_default_excluded(item_id: str, org_id: str) -> bool:
    """The check B-12's future config_service lazy-provisioning sweep must
    call before creating a new provisioned install row for a
    not-yet-provisioned user (CONFIG_AND_PRODUCTS.md §12 point 2)."""
    db = SessionLocal()
    try:
        return (
            db.query(EcosystemOrgExcludedDefault)
            .filter(EcosystemOrgExcludedDefault.org_id == org_id, EcosystemOrgExcludedDefault.item_id == item_id)
            .first()
            is not None
        )
    finally:
        db.close()
