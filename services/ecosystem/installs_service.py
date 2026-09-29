# SPDX-License-Identifier: MIT
# ============================================================
# Installs service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-10):
# install/uninstall/enable/disable/update/rollback. share/unshare/report/
# force_disable/unyank/deprecate/delete_draft/require/unrequire are task
# B-19's own additions in policy_service.py — this file owns the install
# row's own lifecycle only.
# ============================================================

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion
from services.ecosystem.compatibility import CHAT, enforce_compatibility_on_surfaces
from services.ecosystem.errors import EcosystemError, NotFoundError, PolicyForbiddenError


#  ecosystem.changed's own "change" vocabulary ("installed"/"uninstalled"/
# "enabled"/"disabled"/"updated") differs from ecosystem_audit.action's
# ("install"/"uninstall"/"enable"/"disable"/"update") -- this is the one
# translation table between them, so _publish_change() below can write
# both from a single call site instead of every caller doing it twice.
_CHANGE_TO_AUDIT_ACTION = {
    "installed": "install",
    "uninstalled": "uninstall",
    "enabled": "enable",
    "disabled": "disable",
    "updated": "update",
}


def _publish_change(
    item_id: str, org_id: str, version_id: str, scope: str, change: str,
    installed_for: str | None = None, *, actor: str | None = None,
) -> None:
    """Best-effort ecosystem.changed publish (task B-13) -- looks up the
    item_type/version string this event needs, since callers below only
    have the ids at hand. Never raises: a lookup or publish failure must
    never turn a successful mutation into a request-handler error.

    Also directly invalidates resolver_service's capabilities cache for
    the affected user (task B-11) -- an in-process call, not a reaction to
    the pub/sub publish just above, so the cache is never stale even if
    nothing is currently subscribed to the event channel.

    Also writes the ecosystem_audit row for this mutation (task B-20,
    wired up for real 2026-09-29 -- write_audit_event() existed with its
    own unit test since task B-20 but was never actually called from any
    real mutating code path until now). Same best-effort contract as the
    rest of this function -- a caller's real mutation (already committed
    by this point) must never fail because the audit write did.
    """
    try:
        from services.ecosystem.resolver_service import invalidate_capabilities_cache
        invalidate_capabilities_cache(org_id, installed_for)
    except Exception:
        pass
    try:
        from services.ecosystem.events_service import publish_ecosystem_changed

        db = SessionLocal()
        try:
            item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
            version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).first()
        finally:
            db.close()
        if item is None:
            return
        publish_ecosystem_changed(
            org_id, item_type=item.item_type, item_id=item_id, scope=scope,
            change=change, version=version.version if version else None,
        )
    except Exception:
        pass
    if actor is not None:
        try:
            from services.ecosystem.audit_service import write_audit_event
            write_audit_event(
                org_id=org_id, actor=actor, action=_CHANGE_TO_AUDIT_ACTION.get(change, change),
                item_id=item_id, details={"scope": scope, "version_id": version_id, "installed_for": installed_for},
            )
        except Exception:
            pass


class ConflictError(EcosystemError):
    """A second install of the same item already exists for this
    (item_id, org_id, installed_for) — maps to CONTRACTS.md §3's CONFLICT."""


def _authorize_install_mutation(
    row: EcosystemInstall, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> None:
    """uninstall()/set_enabled()/update_to_version() each mutate exactly
    one install row by id -- this is the one place that decides who is
    allowed to. Cross-org: raises NotFoundError, never PolicyForbiddenError
    -- a caller outside the install's org must not learn (via a 403 vs. a
    404) that the id even refers to something real, matching the
    cross-org-lookup convention already used elsewhere in this router
    (e.g. GET /ecosystem/items/{id} for a namespace outside the caller's
    org). Same-org, wrong caller: a real 403 -- the caller is already
    inside the org boundary, so revealing the install exists is not itself
    a leak. `marketplace:provision` (the same permission require_item()/
    unrequire_item() already use to act org-wide on installs) is what lets
    an org admin mutate a teammate's install; a plain non-admin caller may
    only ever act on their own (installed_for == caller_user_id)."""
    if row.org_id != caller_org_id:
        raise NotFoundError(f"no install {row.id!r}")
    is_owner = bool(caller_user_id) and row.installed_for == caller_user_id
    is_org_admin = "marketplace:provision" in caller_permissions
    if not (is_owner or is_org_admin):
        raise PolicyForbiddenError(f"install {row.id!r} does not belong to this caller")


def install(
    *,
    item_id: str,
    version_id: str,
    org_id: str,
    installed_by: str,
    installed_for: str | None,
    surfaces: list[str],
    scope: str = "private",
    origin: str = "added",
    auto_update: bool = False,
    managed_by_plugin_install_id: str | None = None,
    _skip_plugin_fanout: bool = False,
) -> dict[str, Any]:
    """Create an install row. Raises ConflictError (not a silent duplicate)
    if one already exists for (item_id, org_id, installed_for) — the
    UNIQUE NULLS NOT DISTINCT constraint from task B-1 enforces this at the
    DB level; this function turns that constraint violation into a typed,
    catchable error rather than a raw IntegrityError leaking to the router.

    managed_by_plugin_install_id: Plugins phase (PLUGINS_PHASE_PLAN.md item
    2) — set by _fan_out_plugin_parts() below when creating a CHILD install
    on behalf of a plugin; every ordinary caller (the router, gate_service's
    _auto_install()) omits it, which is byte-identical to before this
    parameter existed.

    _skip_plugin_fanout: internal-only, used by _fan_out_plugin_parts()
    itself when creating a CHILD install, so a plugin-of-plugins (not a
    real product concept today, but not schema-forbidden either) can never
    recurse — a child install is never itself treated as a fan-out trigger.
    """
    db = SessionLocal()
    try:
        row = EcosystemInstall(
            item_id=item_id,
            version_id=version_id,
            org_id=org_id,
            installed_by=installed_by,
            installed_for=installed_for,
            scope=scope,
            origin=origin,
            surfaces=surfaces,
            auto_update=auto_update,
            managed_by_plugin_install_id=managed_by_plugin_install_id,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictError(
                f"an install already exists for item {item_id!r} in org {org_id!r}"
            ) from exc
        db.refresh(row)
        result = _row_to_dict(row)
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        item_type = item.item_type if item is not None else None
    finally:
        db.close()
    _publish_change(item_id, org_id, version_id, scope, "installed", installed_for, actor=installed_by)
    if item_type == "plugin" and not _skip_plugin_fanout:
        _fan_out_plugin_parts(
            parent_install_id=result["install_id"], version_id=version_id, org_id=org_id,
            installed_by=installed_by, installed_for=installed_for, surfaces=surfaces,
        )
    return result


def _fan_out_plugin_parts(
    *, parent_install_id: str, version_id: str, org_id: str,
    installed_by: str, installed_for: str | None, surfaces: list[str],
) -> list[dict[str, Any]]:
    """Installing a plugin item creates/attaches a CHILD install for every
    part in its manifest["parts"] that has a real backing EcosystemItem
    (skills/connectors/mcp_servers — see plugin_manifest.py's own docstring
    for why commands/agents/hooks are skipped here: no backing item_type
    exists for them yet, so there is nothing to install).

    If an install for that part's item already exists for this caller
    (either a standalone install created independently, or a child already
    claimed by ANOTHER plugin), this does NOT touch it — it is not
    duplicated (the DB's own UNIQUE constraint would refuse it anyway) and
    ownership is never reassigned just because a second plugin also wants
    it. Only a genuinely NEW install (nothing existed yet) gets
    managed_by_plugin_install_id set to this plugin's own install id — see
    uninstall()'s docstring for how a later uninstall of THIS plugin
    reconciles a part that turns out to still be needed by another still-
    active plugin.
    """
    from services.ecosystem.items_service import _resolve_item_by_id_or_namespace, get_latest_version
    from services.ecosystem.plugin_manifest import _PART_KIND_TO_ITEM_TYPE
    from services.ecosystem.versions_service import get_manifest

    manifest = get_manifest(version_id)
    parts = (manifest or {}).get("parts") or {}

    created: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        for kind, expected_item_type in _PART_KIND_TO_ITEM_TYPE.items():
            for ns in parts.get(kind, []) or []:
                item = _resolve_item_by_id_or_namespace(db, ns)
                if item is None or item.item_type != expected_item_type:
                    continue  # already validated at compose/gate time; skip defensively rather than raise mid-fanout
                existing = get_install_for_caller(item.id, org_id, installed_for)
                if existing is not None:
                    continue  # already installed (standalone or owned by another plugin) -- leave it exactly as-is
                child_version = get_latest_version(item.id)
                if child_version is None:
                    continue
                try:
                    child = install(
                        item_id=item.id, version_id=child_version.id, org_id=org_id,
                        installed_by=installed_by, installed_for=installed_for, surfaces=surfaces,
                        scope="private", origin="added",
                        managed_by_plugin_install_id=parent_install_id, _skip_plugin_fanout=True,
                    )
                    created.append(child)
                except ConflictError:
                    continue  # lost a race with a concurrent install of the same part -- not this call's problem
    finally:
        db.close()
    return created


def get_install(install_id: str) -> EcosystemInstall:
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        db.expunge(row)
        return row
    finally:
        db.close()


def get_install_for_caller(item_id: str, org_id: str, installed_for: str | None) -> EcosystemInstall | None:
    """The (item_id, org_id, installed_for) triple is exactly the unique
    key from task B-1 — this is the canonical "does the caller already
    have this installed" lookup every allowed_actions computation needs."""
    db = SessionLocal()
    try:
        query = db.query(EcosystemInstall).filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == org_id
        )
        query = query.filter(EcosystemInstall.installed_for.is_(None)) if installed_for is None else query.filter(
            EcosystemInstall.installed_for == installed_for
        )
        row = query.first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def uninstall(install_id: str, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str]) -> None:
    """Removes only the caller's own install row. Never touches
    ecosystem_items — uninstalling is never a way to affect the item
    itself (CONTRACTS.md §6's deprecate/uninstall distinction).

    Item 4b (pre-M3): scope='required' rows can never be uninstalled by a
    user, matching set_enabled()'s existing disable-refusal above — a
    required item was reachable via delete-then-nothing-there before this
    fix, since uninstall() had no such check at all (disable did, but
    that only blocks the *disable* action, not deletion of the row
    entirely). Only policy_service's unrequire (task B-19) may remove the
    required-ness first; only then can the row be uninstalled normally.

    caller_org_id/caller_user_id/caller_permissions: authorization, added
    after this function shipped with none at all -- see
    _authorize_install_mutation()'s own docstring.

    Plugins phase (PLUGINS_PHASE_PLAN.md item 2): a CHILD install (
    managed_by_plugin_install_id is set) cannot be uninstalled directly --
    same refusal shape as the scope='required' case immediately below
    (plain EcosystemError, maps to CONTRACTS.md §3's generic BAD_REQUEST,
    not a new typed subclass -- this is a lock-reason, not a distinct
    error category). Uninstalling the PLUGIN's own (parent) install cascades:
    every child exclusively owned by this parent (managed_by_plugin_install_id
    == this install's id) is freed. "Freed" means reassigned to another
    still-active plugin install that also references the same item (a
    genuinely shared part, kept alive for that other plugin) if one exists,
    else actually uninstalled (recursively, so it publishes its own
    ecosystem.changed/audit row exactly like a normal uninstall would).
    """
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        _authorize_install_mutation(
            row, caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
        )
        if row.managed_by_plugin_install_id is not None:
            raise EcosystemError(
                f"install {install_id!r} is managed by plugin install "
                f"{row.managed_by_plugin_install_id!r} and cannot be uninstalled directly"
            )
        if row.scope == "required":
            raise EcosystemError(f"install {install_id!r} is required and cannot be uninstalled")
        item_id, org_id, version_id, scope = row.item_id, row.org_id, row.version_id, row.scope
        installed_for = row.installed_for
        children = db.query(EcosystemInstall).filter(EcosystemInstall.managed_by_plugin_install_id == row.id).all()
        child_ids = [c.id for c in children]
        child_items = [(c.id, c.item_id) for c in children]
        db.delete(row)
        db.commit()
    finally:
        db.close()
    _publish_change(item_id, org_id, version_id, scope, "uninstalled", installed_for, actor=caller_user_id)
    for child_install_id, child_item_id in child_items:
        _reconcile_orphaned_plugin_child(
            child_install_id, child_item_id, org_id=org_id, installed_for=installed_for,
            exclude_parent_install_id=install_id, caller_user_id=caller_user_id,
        )


def _reconcile_orphaned_plugin_child(
    child_install_id: str, child_item_id: str, *, org_id: str, installed_for: str | None,
    exclude_parent_install_id: str, caller_user_id: str,
) -> None:
    """Called once per child after its owning plugin install has just been
    deleted. If another still-active plugin install (for the same caller)
    also references child_item_id in its manifest["parts"], reassign
    ownership to it (the part is genuinely still needed) -- else actually
    uninstall the child for real, publishing its own event/audit row."""
    from services.ecosystem.items_service import get_item_row
    from services.ecosystem.versions_service import get_manifest

    try:
        child_item = get_item_row(child_item_id)
    except NotFoundError:
        return
    child_namespace = child_item.namespace

    db = SessionLocal()
    try:
        candidate_parents = (
            db.query(EcosystemInstall)
            .join(EcosystemItem, EcosystemInstall.item_id == EcosystemItem.id)
            .filter(
                EcosystemInstall.org_id == org_id,
                EcosystemInstall.id != exclude_parent_install_id,
                EcosystemInstall.managed_by_plugin_install_id.is_(None),
                EcosystemItem.item_type == "plugin",
            )
        )
        candidate_parents = (
            candidate_parents.filter(EcosystemInstall.installed_for.is_(None))
            if installed_for is None else candidate_parents.filter(EcosystemInstall.installed_for == installed_for)
        )
        new_owner_id = None
        for parent in candidate_parents.all():
            manifest = get_manifest(parent.version_id)
            parts = (manifest or {}).get("parts") or {}
            all_namespaces = {ns for names in parts.values() for ns in (names or [])}
            if child_namespace in all_namespaces:
                new_owner_id = parent.id
                break

        child_row = db.query(EcosystemInstall).filter(EcosystemInstall.id == child_install_id).first()
        if child_row is None:
            return
        if new_owner_id is not None:
            child_row.managed_by_plugin_install_id = new_owner_id
            db.commit()
            return
    finally:
        db.close()

    # No other plugin still needs it -- actually uninstall it. Re-fetch
    # permissions is unnecessary: this is a system-driven cascade, not a
    # fresh caller-authorized mutation, so it bypasses _authorize_install_
    # mutation() the same way _publish_change()'s own actor= parameter
    # already treats cascades as attributable to the ORIGINAL caller.
    db2 = SessionLocal()
    try:
        row = db2.query(EcosystemInstall).filter(EcosystemInstall.id == child_install_id).first()
        if row is None:
            return
        item_id, org_id2, version_id, scope = row.item_id, row.org_id, row.version_id, row.scope
        installed_for2 = row.installed_for
        db2.delete(row)
        db2.commit()
    finally:
        db2.close()
    _publish_change(item_id, org_id2, version_id, scope, "uninstalled", installed_for2, actor=caller_user_id)


def set_enabled(
    install_id: str, enabled: bool, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> dict[str, Any]:
    """Toggle enable/disable. Refuses on scope='required' rows — those are
    only reachable via policy_service's unrequire (task B-19), never a
    plain disable, matching CONFIG_AND_PRODUCTS.md §12 point 3."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        _authorize_install_mutation(
            row, caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
        )
        if row.scope == "required" and not enabled:
            raise EcosystemError(f"install {install_id!r} is required and cannot be disabled")
        row.enabled = enabled
        db.commit()
        db.refresh(row)
        result = _row_to_dict(row)
        item_id, org_id, version_id, scope = row.item_id, row.org_id, row.version_id, row.scope
        installed_for = row.installed_for
    finally:
        db.close()
    _publish_change(item_id, org_id, version_id, scope, "enabled" if enabled else "disabled", installed_for, actor=caller_user_id)
    return result


def set_surfaces(
    install_id: str, surfaces: list[str], *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> dict[str, Any]:
    """Task 4 (live user report): "surface checkboxes (Chat / Agent Studio /
    Desktop) can't be toggled" -- no endpoint existed to change an
    install's surfaces at all until this. Same ownership/required-lock
    shape as set_enabled() above -- a required install's surfaces aren't
    user-editable either, consistent with it also refusing a plain
    disable/uninstall."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        _authorize_install_mutation(
            row, caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
        )
        if row.scope == "required":
            raise EcosystemError(f"install {install_id!r} is required and its surfaces cannot be changed")
        # Per-surface toggles round (2026-09-29): this is now the ONLY
        # remaining write path for an install's surfaces (the admin-only
        # "Advanced" override -- the router requires marketplace:
        # admin_surfaces to reach here at all). Still not a manual escape
        # hatch around the file/terminal-tools compatibility exception --
        # that's a computed constraint, never something the UI (removed
        # or not) is allowed to override.
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == row.version_id).first()
        compatibility = (version.manifest or {}).get("compatibility", CHAT) if version is not None else CHAT
        row.surfaces = enforce_compatibility_on_surfaces(compatibility, surfaces)
        db.commit()
        db.refresh(row)
        result = _row_to_dict(row)
        item_id, org_id, version_id, scope = row.item_id, row.org_id, row.version_id, row.scope
        installed_for = row.installed_for
    finally:
        db.close()
    # Reuses ChangeKind's existing "updated" value -- surfaces is a
    # property of the install being updated, not a distinct lifecycle
    # event; a new enum value would only fragment ecosystem.changed
    # subscribers (useEcosystemChatSkills.js etc.) into caring about one
    # more case for no behavioral difference from a plain "updated".
    _publish_change(item_id, org_id, version_id, scope, "updated", installed_for, actor=caller_user_id)
    return result


def update_to_version(
    install_id: str, new_version_id: str, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> dict[str, Any]:
    """Point an install at a newer (already-gated) version. Never mutates
    ecosystem_item_versions — versions are immutable; this only moves which
    version_id the install row references.

    Plugins phase (PLUGINS_PHASE_PLAN.md item 2): when the install being
    updated is a PLUGIN's own (parent) install -- managed_by_plugin_install_id
    is NULL and the item is item_type="plugin" -- this also diffs the old
    version's manifest["parts"] against the new one's: a part namespace
    present in the old version but absent from the new one gets its child
    install reconciled (freed to another still-active plugin if one still
    needs it, else actually uninstalled) via the same helper uninstall()
    uses; a namespace newly present gets a new child install via the same
    _fan_out_plugin_parts() helper install() uses -- one code path each,
    not a third, parallel implementation. This one function backs both the
    manual "update"/"rollback" endpoints AND gate_service._bump_own_install_
    on_pass()'s automatic bump, so a plugin's parts stay in sync with its
    currently-pointed-at version either way.
    """
    db = SessionLocal()
    try:
        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).first()
        if row is None:
            raise NotFoundError(f"no install {install_id!r}")
        _authorize_install_mutation(
            row, caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
        )
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == new_version_id).first()
        if version is None or version.item_id != row.item_id:
            raise NotFoundError(f"version {new_version_id!r} does not belong to this install's item")
        old_version_id = row.version_id
        row.version_id = new_version_id
        db.commit()
        db.refresh(row)
        result = _row_to_dict(row)
        item_id, org_id, scope = row.item_id, row.org_id, row.scope
        installed_for = row.installed_for
        managed_by = row.managed_by_plugin_install_id
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        item_type = item.item_type if item is not None else None
    finally:
        db.close()
    _publish_change(item_id, org_id, new_version_id, scope, "updated", installed_for, actor=caller_user_id)
    if item_type == "plugin" and managed_by is None:
        _reconcile_plugin_parts_diff(
            parent_install_id=install_id, org_id=org_id, installed_for=installed_for,
            installed_by=caller_user_id, surfaces=result["surfaces"] or [],
            old_version_id=old_version_id, new_version_id=new_version_id,
        )
    return result


def _reconcile_plugin_parts_diff(
    *, parent_install_id: str, org_id: str, installed_for: str | None, installed_by: str,
    surfaces: list[str], old_version_id: str, new_version_id: str,
) -> None:
    from services.ecosystem.versions_service import get_manifest

    old_parts = (get_manifest(old_version_id) or {}).get("parts") or {} if old_version_id else {}
    new_parts = (get_manifest(new_version_id) or {}).get("parts") or {}
    old_ns = {ns for names in old_parts.values() for ns in (names or [])}
    new_ns = {ns for names in new_parts.values() for ns in (names or [])}
    removed_namespaces = old_ns - new_ns

    if removed_namespaces:
        db = SessionLocal()
        try:
            to_reconcile = (
                db.query(EcosystemInstall.id, EcosystemInstall.item_id)
                .join(EcosystemItem, EcosystemInstall.item_id == EcosystemItem.id)
                .filter(
                    EcosystemInstall.managed_by_plugin_install_id == parent_install_id,
                    EcosystemItem.namespace.in_(removed_namespaces),
                )
                .all()
            )
        finally:
            db.close()
        for child_install_id, child_item_id in to_reconcile:
            _reconcile_orphaned_plugin_child(
                child_install_id, child_item_id, org_id=org_id, installed_for=installed_for,
                exclude_parent_install_id=parent_install_id, caller_user_id=installed_by,
            )

    # Idempotent: only creates a child for a namespace that doesn't already
    # have an install for this caller -- safe to call unconditionally
    # rather than pre-computing "added" separately.
    _fan_out_plugin_parts(
        parent_install_id=parent_install_id, version_id=new_version_id, org_id=org_id,
        installed_by=installed_by, installed_for=installed_for, surfaces=surfaces,
    )


def rollback(
    install_id: str, target_version_id: str, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> dict[str, Any]:
    """Same mechanism as update_to_version — rollback is just "update to an
    older, still-immutable version" rather than a distinct code path."""
    return update_to_version(
        install_id, target_version_id,
        caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
    )


def list_installs(
    org_id: str, installed_for: str | None, item_type: str | None = None, *, caller_permissions: set[str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Returns (installs, has_any) — has_any backs CONTRACTS.md §7's
    default-view rule (Review fix 8) and is computed from installs alone;
    the legacy_items half of has_any (Review round following M1, item C)
    is the router's job to OR in, since this service has no legacy-bridge
    awareness.

    Two real, disclosed-and-fixed gaps found live while investigating a
    crash report against the running Yours screen (`packages/ecosystem-ui/
    src/components/Yours.tsx` reads `install.item.allowed_actions` — every
    field CONTRACTS.md §7 documents an `Install` carrying under `item`):
    (1) `item_type` was accepted as a parameter but never actually used to
    filter the query -- `?item_type=skill` silently returned every type.
    (2) `_row_to_dict()` never embedded `item` at all, so `install.item`
    was always `undefined` client-side. Fixed by joining to EcosystemItem
    for the filter and building each row's `item` via items_service's own
    `_item_to_summary()` -- the exact same shape/allowed_actions logic the
    catalog list/detail endpoints already use, not a second, parallel
    implementation that could drift out of sync with it.
    """
    from services.ecosystem.items_service import _item_to_summary

    db = SessionLocal()
    try:
        query = db.query(EcosystemInstall).join(EcosystemItem, EcosystemInstall.item_id == EcosystemItem.id).filter(
            EcosystemInstall.org_id == org_id,
        )
        query = query.filter(EcosystemInstall.installed_for.is_(None)) if installed_for is None else query.filter(
            EcosystemInstall.installed_for == installed_for
        )
        if item_type is not None:
            query = query.filter(EcosystemItem.item_type == item_type)
        rows = query.all()
        results = []
        for row in rows:
            item = db.query(EcosystemItem).filter(EcosystemItem.id == row.item_id).first()
            entry = _row_to_dict(row)
            entry["item"] = _item_to_summary(
                db, item, caller_user_id=installed_for or "", caller_org_id=org_id,
                caller_permissions=caller_permissions or set(), new_badge_days=14,
            ) if item is not None else None
            results.append(entry)
        return results, len(rows) > 0
    finally:
        db.close()


def cleanup_installs_for_inactive_users(org_id: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Item 4d (pre-M3): row-growth cleanup for lazily-provisioned installs
    belonging to a deactivated user (users.is_active=False — the same flag
    routers/scim_router.py's SCIM deprovisioning flow already sets; this
    function does not hook into that flow itself, additive-only, since
    doing so would mean editing that existing router).

    A deactivated user never makes another API call, so their
    lazily-provisioned rows (origin IN ('provisioned','required')) are
    pure dead weight from that point on -- never functionally harmful
    (no code path re-reads a stale row and does anything wrong with it),
    but they accumulate forever without this. User-created content
    (origin='created') and rows a still-active teammate shared with them
    (origin='shared') are left alone -- only the mechanically-provisioned
    subset is this function's business.

    Returns {"candidates": N, "deleted": N} — dry_run=True (the default)
    only counts; a caller must pass dry_run=False to actually delete.
    Not wired into any scheduler/trigger this task — a maintenance
    utility for now, matching the milestone's own scope boundary (the
    lazy-provisioning mechanism this cleans up after is B-12/M3's, not
    yet built).
    """
    from sqlalchemy import String, cast

    from db.models import User

    db = SessionLocal()
    try:
        # Cast User.id (UUID) to text rather than installed_for (varchar) to
        # UUID -- a cast the other direction always succeeds, so a stray
        # non-UUID-shaped installed_for value (should never happen, but this
        # column has no FK) can never make the whole query raise instead of
        # just not matching.
        query = (
            db.query(EcosystemInstall)
            .join(User, EcosystemInstall.installed_for == cast(User.id, String))
            .filter(User.is_active.is_(False))
            .filter(EcosystemInstall.origin.in_(("provisioned", "required")))
        )
        if org_id is not None:
            query = query.filter(EcosystemInstall.org_id == org_id)
        rows = query.all()
        candidates = len(rows)
        deleted = 0
        if not dry_run:
            for row in rows:
                db.delete(row)
            db.commit()
            deleted = candidates
        return {"candidates": candidates, "deleted": deleted}
    finally:
        db.close()


def _row_to_dict(row: EcosystemInstall) -> dict[str, Any]:
    return {
        "install_id": row.id, "item_id": row.item_id, "version_id": row.version_id,
        "org_id": row.org_id, "scope": row.scope, "origin": row.origin,
        "installed_by": row.installed_by, "installed_for": row.installed_for,
        "enabled": row.enabled, "surfaces": row.surfaces, "auto_update": row.auto_update,
        "installed_at": row.installed_at.isoformat() if row.installed_at else None,
        "managed_by_plugin_install_id": row.managed_by_plugin_install_id,
    }
