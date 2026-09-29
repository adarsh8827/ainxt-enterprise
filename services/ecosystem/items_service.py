# SPDX-License-Identifier: MIT
# ============================================================
# Items service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3 skeleton).
#
# get_or_create_local_source() and upsert_legacy_pointer_item() are real,
# not stubs — task B-4's backfill job (M1) needs them now, ahead of the
# create/list/get lifecycle (task B-6/B-10, M2) that fills in the rest of
# this file. See docs/ecosystem/design/LLD/data-model.md.
# ============================================================

from __future__ import annotations

import base64
import json as _json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from db.database import SessionLocal
from db.models import (
    EcosystemFeaturedOverride, EcosystemGateFinding, EcosystemGateRun,
    EcosystemInstall, EcosystemItem, EcosystemItemVersion,
    EcosystemPublisher, EcosystemShare, EcosystemSource,
)
from services.ecosystem.errors import NotFoundError, PolicyForbiddenError

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# CONTRACTS.md §6's full allowed_actions value set.
_ALL_ACTIONS = (
    "install", "uninstall", "enable", "disable", "update", "rollback",
    "share", "unshare", "report", "deprecate", "edit_content", "delete_draft",
    "force_disable", "unyank", "edit_policy",
)


def get_or_create_local_source(org_id: str, created_by: str = "system") -> str:
    """Return the id of org_id's 'local' ecosystem_sources row, creating it
    if this is the org's first user/agent-created (or backfilled) item.

    Exactly one 'local' source per org (db/migrate.py's
    ux_ecosystem_sources_one_local_per_org partial unique index, task B-1) —
    every item an org creates directly, or that gets backfilled from a
    legacy table on that org's behalf, points at this one row rather than a
    shared platform-wide row (M0-review fix, see CHANGELOG.md).
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.org_id == org_id, EcosystemSource.kind == "local")
            .first()
        )
        if existing is not None:
            return existing.id

        row = EcosystemSource(
            kind="local",
            org_id=org_id,
            created_by=created_by,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def get_or_create_import_source(kind: str, url: str, created_by: str, tos_notes: str) -> str:
    """Return the id of the ecosystem_sources row for this exact external
    location, creating it on first import (task I, pre-M3).

    Instance-level, not per-org (org_id=None) -- github_repo/well_known
    content is the same external repo/domain regardless of which org
    imports it, unlike get_or_create_local_source()'s deliberately
    per-org 'local' row. One row per distinct (kind, url) records ToS
    acknowledgement (tos_checked_at/tos_notes) the first time that exact
    location is imported from; a later import of the same location reuses
    it and does not re-stamp tos_checked_at.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.kind == kind, EcosystemSource.url == url)
            .first()
        )
        if existing is not None:
            return existing.id

        from datetime import datetime, timezone

        row = EcosystemSource(
            kind=kind,
            url=url,
            org_id=None,
            created_by=created_by,
            tos_checked_at=datetime.now(timezone.utc),
            tos_notes=tos_notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        source_id = row.id
    finally:
        db.close()
    try:
        from services.ecosystem.audit_service import write_audit_event
        write_audit_event(
            org_id="default", actor=created_by, action="source_change", item_id=None,
            details={"source_id": source_id, "kind": kind, "url": url, "change": "created"},
        )
    except Exception:
        pass
    return source_id


def get_or_create_builtin_source(created_by: str = "system") -> str:
    """The one platform-level (org_id=NULL) 'local' source row every
    scope='builtin' item (task B-22) points at. Distinct from the per-org
    'local' sources get_or_create_local_source() manages — builtin items
    are org-independent, so they can't use an org-scoped source (and the
    DB's ux_ecosystem_sources_one_local_per_org partial index doesn't
    reliably dedupe NULL org_id rows on its own, since a plain UNIQUE index
    allows multiple NULLs — this function's own existing-row check is what
    actually keeps it to exactly one)."""
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemSource)
            .filter(EcosystemSource.org_id.is_(None), EcosystemSource.kind == "local")
            .first()
        )
        if existing is not None:
            return existing.id
        row = EcosystemSource(kind="local", org_id=None, created_by=created_by)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def upsert_legacy_pointer_item(
    *,
    namespace: str,
    item_type: str,
    category: str,
    display_name: str,
    description: str,
    org_id: str,
    legacy_source: str,
    legacy_ref: str,
    license: str = "MIT",
    trust_tier: str = "org",
) -> tuple[str, bool]:
    """Upsert a pointer-only ecosystem_items row for a legacy-bridged item
    (task B-4's backfill job). Matched by (legacy_source, legacy_ref) —
    re-running the backfill job is a no-op for an already-mirrored row
    (its metadata is refreshed in place, no duplicate is created).

    Returns (item_id, created) — created=True only the first time this
    (legacy_source, legacy_ref) pair is seen.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.legacy_source == legacy_source, EcosystemItem.legacy_ref == legacy_ref)
            .first()
        )
        source_id = get_or_create_local_source(org_id)

        if existing is not None:
            existing.display_name = display_name
            existing.description = description
            existing.category = category
            existing.source_id = source_id
            db.commit()
            return existing.id, False

        row = EcosystemItem(
            namespace=namespace,
            item_type=item_type,
            category=category,
            display_name=display_name,
            description=description,
            source_id=source_id,
            scope="org_private",
            org_id=org_id,
            trust_tier=trust_tier,
            license=license,
            legacy_source=legacy_source,
            legacy_ref=legacy_ref,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, True
    finally:
        db.close()


def upsert_builtin_item(
    *,
    namespace: str,
    item_type: str,
    category: str,
    display_name: str,
    description: str,
    license: str = "MIT",
) -> tuple[str, bool]:
    """Upsert a scope='builtin' item (task B-22's seeding). Matched by
    namespace+item_type — re-running the seed step twice updates metadata
    in place rather than creating a duplicate row (the global namespace
    partial unique index from task B-1 would reject a literal duplicate
    anyway; this makes the upsert explicit rather than relying on catching
    that constraint violation).

    Returns (item_id, created).
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(EcosystemItem)
            .filter(EcosystemItem.namespace == namespace, EcosystemItem.item_type == item_type)
            .first()
        )
        source_id = get_or_create_builtin_source()

        if existing is not None:
            existing.display_name = display_name
            existing.description = description
            existing.category = category
            existing.source_id = source_id
            db.commit()
            return existing.id, False

        row = EcosystemItem(
            namespace=namespace, item_type=item_type, category=category,
            display_name=display_name, description=description, source_id=source_id,
            scope="builtin", org_id=None, trust_tier="builtin", license=license,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, True
    finally:
        db.close()


def get_item_row(item_id: str) -> EcosystemItem:
    """Raise NotFoundError if item_id doesn't exist — the ORM-row form used
    internally by other services (compute_allowed_actions, create_service,
    installs_service). get_item() below is the public, dict-shaped read."""
    db = SessionLocal()
    try:
        row = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if row is None:
            raise NotFoundError(f"no ecosystem item {item_id!r}")
        db.expunge(row)
        return row
    finally:
        db.close()


def _resolve_item_by_id_or_namespace(db: Any, id_or_namespace: str) -> EcosystemItem | None:
    """CONTRACTS.md §15: GET /ecosystem/items/{id} accepts either the UUID
    id or the namespace string."""
    if _UUID_RE.match(id_or_namespace):
        row = db.query(EcosystemItem).filter(EcosystemItem.id == id_or_namespace).first()
        if row is not None:
            return row
    return db.query(EcosystemItem).filter(EcosystemItem.namespace == id_or_namespace).first()


def _visible_to_caller(item: EcosystemItem, caller_org_id: str) -> bool:
    if item.scope in ("builtin", "optional", "central_index"):
        return True
    if item.scope == "org_private":
        return item.org_id == caller_org_id
    return False


def _is_share_recipient(db: Any, item_id: str, *, caller_user_id: str, caller_org_id: str) -> bool:
    """True if `caller_user_id` is the named recipient of a real
    EcosystemShare row for this item -- shared_with_type='user' matching
    the caller directly, or 'org' matching the caller's own org (an
    org-wide share). Disclosed limitation: shared_with_type='group'
    membership is not resolved here (no group-membership lookup exists
    in this module) -- a group share currently does not, on its own,
    grant detail-page visibility via this check; group recipients reach
    the item through their own EcosystemInstall row (origin/scope set at
    share time), which _visible_to_caller_for_detail() below also checks."""
    row = (
        db.query(EcosystemShare)
        .join(EcosystemInstall, EcosystemShare.install_id == EcosystemInstall.id)
        .filter(
            EcosystemInstall.item_id == item_id,
            (
                ((EcosystemShare.shared_with_type == "user") & (EcosystemShare.shared_with_id == caller_user_id))
                | ((EcosystemShare.shared_with_type == "org") & (EcosystemShare.shared_with_id == caller_org_id))
            ),
        )
        .first()
    )
    return row is not None


def _visible_to_caller_for_detail(
    db: Any, item: EcosystemItem, *, caller_org_id: str, caller_user_id: str, caller_permissions: set[str],
) -> bool:
    """Stricter visibility check for the actual "direct URL" detail path
    (GET /ecosystem/items/{id}) -- review round, 2026-09-29: the earlier
    item-7 fix excluded `org_private` from Discover's *list* entirely,
    but left `_visible_to_caller()` (used by get_item() and every other
    admin/versions/gate-run call site) unchanged on purpose, since admin
    flows there legitimately need to see ANY item in their own org
    regardless of ownership. That's still correct for those call sites --
    but it means hitting a private item's detail endpoint directly by id/
    namespace, as a same-org caller who is neither the creator nor a
    share recipient, returned a full 200, not a 404 -- the exact bug
    class item 7 was about, just on the detail path instead of the list
    path. `get_item()` alone now calls this instead of the plain
    `_visible_to_caller()`; every other call site (admin force_disable/
    unyank/deprecate, versions_service, gate_service's list_gate_runs,
    create_service's _require_owner_or_admin) is intentionally left on
    the org-wide check -- those are already gated by their own explicit
    is_owner/marketplace:admin_sources check layered on top, and widening
    THIS function under them too would risk 404ing an admin acting on a
    teammate's private item, a real regression this round must not cause."""
    if item.scope != "org_private":
        return _visible_to_caller(item, caller_org_id)
    if item.org_id != caller_org_id:
        return False
    if "marketplace:admin_sources" in caller_permissions:
        return True
    if caller_user_id and item.created_by == caller_user_id:
        return True
    if caller_user_id and _is_owner(db, item.id, caller_user_id):
        return True
    if caller_user_id and _is_share_recipient(db, item.id, caller_user_id=caller_user_id, caller_org_id=caller_org_id):
        return True
    return False


def _is_new(db: Any, item_id: str, new_badge_days: int) -> bool:
    earliest = (
        db.query(EcosystemItemVersion)
        .filter(EcosystemItemVersion.item_id == item_id)
        .order_by(EcosystemItemVersion.created_at.asc())
        .first()
    )
    if earliest is None:
        return False
    return (datetime.now(timezone.utc) - earliest.created_at) < timedelta(days=new_badge_days)


def _is_featured(db: Any, item: EcosystemItem, org_id: str) -> bool:
    override = (
        db.query(EcosystemFeaturedOverride)
        .filter(EcosystemFeaturedOverride.org_id == org_id, EcosystemFeaturedOverride.item_id == item.id)
        .first()
    )
    return override.featured if override is not None else item.is_featured


def _is_owner(db: Any, item_id: str, caller_user_id: str) -> bool:
    """Real bug found live, 2026-09-28: deriving ownership ENTIRELY from a
    mutable `EcosystemInstall(origin='created')` row meant that losing
    that one row -- by any means, including the ordinary, by-design
    uninstall() action (Detail.tsx/Yours.tsx's plain "Uninstall" button,
    which removes only the caller's own install row and never touches
    the item) -- permanently orphaned the item: no longer owned by
    anyone, invisible in Yours, and delete_draft never offered again,
    even though the item itself is still there. `EcosystemItem.created_by`
    (db/migrate.py Part AD16) is a durable, install-row-independent
    signal set once at creation; checked here as a second, OR'd path so
    an existing install row is still sufficient on its own (unchanged
    behavior for every item created before this column existed and
    correctly backfilled)."""
    if not caller_user_id:
        return False
    has_created_install = (
        db.query(EcosystemInstall)
        .filter(
            EcosystemInstall.item_id == item_id, EcosystemInstall.origin == "created",
            EcosystemInstall.installed_by == caller_user_id,
        )
        .first()
        is not None
    )
    if has_created_install:
        return True
    item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
    return item is not None and item.created_by == caller_user_id


def _install_for_caller(db: Any, item_id: str, caller_org_id: str, caller_user_id: str) -> EcosystemInstall | None:
    query = db.query(EcosystemInstall).filter(
        EcosystemInstall.item_id == item_id, EcosystemInstall.org_id == caller_org_id
    )
    query = query.filter(EcosystemInstall.installed_for.is_(None)) if not caller_user_id else query.filter(
        EcosystemInstall.installed_for == caller_user_id
    )
    return query.first()


def _share_id_for_recipient(db: Any, item_id: str, caller_user_id: str) -> str | None:
    """Task 3c fix: compute_allowed_actions() has always offered "unshare"
    to a caller whose own install has scope == "shared" -- but
    EcosystemShare.id (needed by policy_service.unshare()/POST /ecosystem/
    shares/{share_id}/unshare) lives on the SHARER's own install row
    (EcosystemShare.install_id), with no column anywhere linking back to
    the recipient's own install. Resolved here the same way `_install_for_
    caller()` resolves the recipient's own install: join through to
    whichever share, for this item, names this caller as its recipient by
    user id. Ties (more than one share naming the same user for the same
    item) resolve to the most recently-created one -- a real but narrow
    edge case, not solved further here. Returns None (never raises) when
    no such share row exists, or the caller isn't named by user id at all
    (e.g. shared to a group/org the caller belongs to some other way) --
    that second case is a disclosed, narrower gap than the one this fixes:
    unshare would still show in allowed_actions with nothing to call for
    a group/org-addressed share, same shape as the bug before this fix,
    just for a rarer sharing mode."""
    if not caller_user_id:
        return None
    row = (
        db.query(EcosystemShare)
        .join(EcosystemInstall, EcosystemShare.install_id == EcosystemInstall.id)
        .filter(
            EcosystemInstall.item_id == item_id,
            EcosystemShare.shared_with_type == "user",
            EcosystemShare.shared_with_id == caller_user_id,
        )
        .order_by(EcosystemShare.created_at.desc())
        .first()
    )
    return row.id if row is not None else None


def _item_to_summary(
    db: Any, item: EcosystemItem, *, caller_user_id: str, caller_org_id: str,
    caller_permissions: set[str], new_badge_days: int,
) -> dict[str, Any]:
    latest = get_latest_version(item.id)
    install = _install_for_caller(db, item.id, caller_org_id, caller_user_id)
    other_installs = (
        db.query(EcosystemInstall)
        .filter(EcosystemInstall.item_id == item.id, EcosystemInstall.installed_by != caller_user_id)
        .first()
        is not None
    )
    version_count = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item.id).count()
    # Local import: policy_service imports _visible_to_caller from this
    # module, so a top-level import here would be circular.
    from services.ecosystem.policy_service import get_policy as _get_policy
    caller_can_share = _get_policy(caller_org_id).get("who_can_share", "all_users") == "all_users"
    allowed = compute_allowed_actions(
        item=item, caller_user_id=caller_user_id, caller_org_id=caller_org_id,
        caller_permissions=caller_permissions, install=install,
        is_owner=_is_owner(db, item.id, caller_user_id),
        has_other_installs=other_installs, has_multiple_versions=version_count > 1,
        newer_version_available=bool(install and latest and install.version_id != latest.id),
        caller_can_share=caller_can_share,
    )
    return {
        "id": item.id, "namespace": item.namespace, "item_type": item.item_type,
        "display_name": item.display_name, "description": item.description,
        "category": item.category, "tags": item.tags or [],
        "icon_url": item.icon_url, "trust_tier": item.trust_tier, "license": item.license,
        "status": item.status,
        # Item-level scope (builtin|optional|central_index|org_private) --
        # was never exposed to the frontend before this round (only
        # Install.scope was). Needed so the frontend can tell a catalog
        # item nobody has added yet (item_scope == "central_index" AND
        # latest_version is None, per docs/ecosystem/design/LLD/gate.md's
        # "Item-state model" -- no gate run exists for that state) apart
        # from an item genuinely still being verified (latest_version set,
        # gate run pending) -- real bug found live: both cases collapsed
        # into the SAME "Verifying..." badge before this field existed,
        # because latest_verdict alone can't distinguish them (it defaults
        # to "pending" below for either case).
        "item_scope": item.scope,
        "is_featured": _is_featured(db, item, caller_org_id),
        "is_new": _is_new(db, item.id, new_badge_days),
        "latest_version": latest.version if latest else None,
        "latest_verdict": latest.gate_verdict if latest else "pending",
        # Compatibility tag (explicit review request): "chat" or
        # "tool_dependent", computed once at creation time and stored on
        # the version's own manifest (services/ecosystem/compatibility.py)
        # -- None only for a version created before this field existed.
        "compatibility": (latest.manifest or {}).get("compatibility") if latest else None,
        "allowed_actions": allowed,
        # The caller's own install for this item, if any (Detail.tsx's
        # installed-state header: kebab menu + enable/disable toggle
        # replace Add/Copy once this is non-null). Every install-mutation
        # endpoint (setEnabled/uninstall/share) needs install_id, not
        # item_id -- ItemSummary/ItemDetail never exposed it before.
        "install_id": install.id if install else None,
        "enabled": install.enabled if install else None,
        # Item 2 (M5 UI-polish round): Detail.tsx's "Installed ▾" popover
        # must lock Uninstall (and explain why) for a scope='required'
        # install, matching the real server-side refusal already enforced
        # in installs_service.uninstall() -- the UI has no other signal to
        # know this without also seeing the install's own scope.
        "install_scope": install.scope if install else None,
        # Detail.tsx's Overview tab ("enabled surfaces") -- the caller's
        # own install's surfaces list, None when never installed.
        "install_surfaces": install.surfaces if install else None,
        # "Delete permanently" vs. "Retire" review (2026-09-28): the UI
        # can't otherwise tell "delete_draft is absent because someone
        # else also has this installed/shared" apart from "absent because
        # I'm not the owner" or "absent because it's built-in/required" --
        # this is the exact boolean compute_allowed_actions() already
        # derives internally (has_other_installs), just not previously
        # returned to the client. True only means "some OTHER install
        # exists," not who or how many.
        "has_other_installs": other_installs,
        # Task 3c fix: only ever non-None when "unshare" is actually in
        # allowed_actions (install.scope == "shared" is the same condition
        # compute_allowed_actions() itself gates "unshare" on) -- no point
        # doing the extra join otherwise.
        "share_id": _share_id_for_recipient(db, item.id, caller_user_id) if (install is not None and install.scope == "shared") else None,
    }


def get_item(
    item_id_or_namespace: str, *, caller_org_id: str = "", caller_user_id: str = "",
    caller_permissions: set[str] | None = None, new_badge_days: int = 14,
) -> dict[str, Any] | None:
    """GET /ecosystem/items/{id} (CONTRACTS.md §9 ItemDetail) — accepts
    either the UUID id or the namespace string (§15). Returns None (never
    raises) for "doesn't exist" or "exists but not visible to this org" —
    the router maps a None result to NOT_FOUND, deliberately not
    distinguishing the two (a caller must not learn an org-private item
    exists elsewhere from the error shape alone)."""
    caller_permissions = caller_permissions or set()
    db = SessionLocal()
    try:
        row = _resolve_item_by_id_or_namespace(db, item_id_or_namespace)
        if row is None or not _visible_to_caller_for_detail(
            db, row, caller_org_id=caller_org_id, caller_user_id=caller_user_id, caller_permissions=caller_permissions,
        ):
            return None
        summary = _item_to_summary(
            db, row, caller_user_id=caller_user_id, caller_org_id=caller_org_id,
            caller_permissions=caller_permissions, new_badge_days=new_badge_days,
        )
        latest = get_latest_version(row.id)
        publisher_slug = row.namespace.split("/", 1)[0] if "/" in row.namespace else row.namespace
        publisher = db.query(EcosystemPublisher).filter(EcosystemPublisher.slug == publisher_slug).first()
        source = db.query(EcosystemSource).filter(EcosystemSource.id == row.source_id).first()
        summary.update({
            # Item 6.2 (2026-09-29 live-test round, real user report):
            # "Publisher: google-labs-code (user)" -- (user) was a
            # hardcoded fallback here that never actually checked whether
            # the publisher is a real individual or an organization; it
            # fired for exactly the items least able to answer that
            # (item_scope='central_index' crawled catalog items, which
            # never get an ecosystem_publishers row at all -- nobody in
            # THIS install owns that external namespace). A real
            # ecosystem_publishers row's own owner_type IS a genuine
            # signal (resolve_publisher()'s own 'org'|'user' -- who inside
            # this AiNxt install owns the slug), kept as-is when one
            # exists. When one doesn't, this now reports type=None rather
            # than guessing -- packages/ecosystem-ui's RiskSidePanel.tsx
            # falls back to showing the item's real, already-known source
            # (source.kind/url below) instead of a fabricated label.
            # Threading the REAL upstream distinction (GitHub's own
            # Organization-vs-User on the owner account, e.g.
            # repo_meta["owner"]["type"] from import_adapters/
            # github_repo.py's own already-fetched response) further back
            # into ecosystem_publishers/ecosystem_sources for a crawled
            # item is a larger, catalog-crawler-side change (that
            # pipeline lives on feature/ecosystem-external-sources, out of
            # this fix's scope) -- not done here.
            "publisher": (
                {"slug": publisher.slug, "type": publisher.owner_type} if publisher
                else {"slug": publisher_slug, "type": None}
            ),
            "attribution": latest.attribution if latest else "",
            "source": {"kind": source.kind, "url": source.url} if source else {"kind": "local", "url": None},
            "manifest": latest.manifest if latest else {},
            "deprecated_at": row.deprecated_at.isoformat() if row.deprecated_at else None,
            "deprecated_by": row.deprecated_by,
        })
        return summary
    finally:
        db.close()


def list_items(
    *, caller_org_id: str = "", caller_user_id: str = "", caller_permissions: set[str] | None = None,
    item_type: str | None = None, cursor: str | None = None, limit: int = 50, q: str | None = None,
    category: list[str] | None = None, trust: list[str] | None = None, status: list[str] | None = None,
    verdict: list[str] | None = None, surface: list[str] | None = None, sort: str = "featured",
    new_badge_days: int = 14,
) -> dict[str, Any]:
    """GET /ecosystem/items (CONTRACTS.md §7). Cursor is an opaque
    base64-encoded offset — simple, not a true keyset cursor, but matches
    the "opaque, client never parses it" contract and is correct for this
    phase's catalog sizes."""
    caller_permissions = caller_permissions or set()
    offset = 0
    if cursor:
        try:
            offset = int(_json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())["offset"])
        except Exception:
            offset = 0

    db = SessionLocal()
    try:
        query = db.query(EcosystemItem)
        if item_type:
            query = query.filter(EcosystemItem.item_type == item_type)
        # Item 7 (M5 UI-parity review, 2026-09-28) — real bug found live: a
        # caller's own `org_private` item (a personal Create-with-AI skill,
        # for example) was showing up in Discover for the caller AND for
        # every other member of the same org, mislabeled/mis-stated (task's
        # own "Community"/"+ Add" symptom) since Discover has no concept of
        # "this is MY private thing" vs. "this is the catalog." Discover is
        # the browse-the-whole-catalog surface; `org_private` items are
        # reachable via Yours (the creator's own installs) or a direct
        # share, never discovery — so `org_private` is now excluded here
        # entirely, for every caller, not just narrowed to the owner's own
        # view. `_visible_to_caller()`/`get_item()` below are UNCHANGED —
        # the detail page, install, and share/admin flows still need an
        # org member to reach an `org_private` item by direct id/namespace
        # (e.g. a share link, or an admin managing an org-forked builtin);
        # only the *list* (browse) surface is narrowed. See
        # test_list_items_excludes_org_private_from_everyones_discover_feed in
        # tests/services/ecosystem/test_items_list_get_delete_policy.py and
        # CHANGELOG.md's 2026-09-28 entry.
        query = query.filter(EcosystemItem.scope.in_(("builtin", "optional", "central_index")))
        if category:
            query = query.filter(EcosystemItem.category.in_(category))
        if trust:
            query = query.filter(EcosystemItem.trust_tier.in_(trust))
        if status:
            query = query.filter(EcosystemItem.status.in_(status))
        else:
            # "coming_soon" (external-sources sync, catalog_sync.py) is a
            # deliberate hold state -- an mcp_server central_index pointer
            # is stored (so it's ready the moment install support lands)
            # but never shown unless a caller explicitly asks for that
            # status, same treatment as "yanked".
            query = query.filter(~EcosystemItem.status.in_(("yanked", "coming_soon")))
        if q:
            like = f"%{q}%"
            query = query.filter(
                EcosystemItem.display_name.ilike(like) | EcosystemItem.description.ilike(like)
            )
        if verdict:
            latest_ids = (
                db.query(
                    EcosystemItemVersion.item_id.label("item_id"),
                    func.max(EcosystemItemVersion.created_at).label("max_created"),
                )
                .group_by(EcosystemItemVersion.item_id)
                .subquery()
            )
            latest_version = (
                db.query(EcosystemItemVersion.item_id, EcosystemItemVersion.gate_verdict)
                .join(
                    latest_ids,
                    (EcosystemItemVersion.item_id == latest_ids.c.item_id)
                    & (EcosystemItemVersion.created_at == latest_ids.c.max_created),
                )
                .subquery()
            )
            query = query.join(latest_version, latest_version.c.item_id == EcosystemItem.id).filter(
                latest_version.c.gate_verdict.in_(verdict)
            )

        if sort == "newest":
            query = query.order_by(EcosystemItem.created_at.desc())
        elif sort == "updated":
            query = query.order_by(EcosystemItem.updated_at.desc())
        elif sort == "name":
            query = query.order_by(EcosystemItem.display_name.asc())
        else:
            query = query.order_by(EcosystemItem.is_featured.desc(), EcosystemItem.created_at.desc())

        total_hint = query.count()
        rows = query.offset(offset).limit(limit).all()

        summaries: list[dict[str, Any]] = []
        for row in rows:
            if surface:
                install = _install_for_caller(db, row.id, caller_org_id, caller_user_id)
                if install is None or not any(s in (install.surfaces or []) for s in surface):
                    continue
            summaries.append(_item_to_summary(
                db, row, caller_user_id=caller_user_id, caller_org_id=caller_org_id,
                caller_permissions=caller_permissions, new_badge_days=new_badge_days,
            ))

        next_cursor = None
        if offset + limit < total_hint:
            next_cursor = base64.urlsafe_b64encode(
                _json.dumps({"offset": offset + limit}).encode()
            ).decode()

        return {"items": summaries, "next_cursor": next_cursor, "total_hint": total_hint}
    finally:
        db.close()


def get_latest_version(item_id: str) -> EcosystemItemVersion | None:
    db = SessionLocal()
    try:
        row = (
            db.query(EcosystemItemVersion)
            .filter(EcosystemItemVersion.item_id == item_id)
            .order_by(EcosystemItemVersion.created_at.desc())
            .first()
        )
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def compute_allowed_actions(
    *,
    item: EcosystemItem,
    caller_user_id: str,
    caller_org_id: str,
    caller_permissions: set[str],
    install: EcosystemInstall | None = None,
    is_owner: bool = False,
    has_other_installs: bool = False,
    has_multiple_versions: bool = False,
    newer_version_available: bool = False,
    caller_can_share: bool = True,
) -> list[str]:
    """The single source of truth for CONTRACTS.md §6's allowed_actions —
    every router endpoint that mutates an item/install re-derives this
    itself server-side rather than trusting whatever the client last saw,
    per the standing "allowed_actions enforced server-side" rule.

    Pure function, no DB access — callers gather the boolean context
    (there's an install? multiple versions? etc.) so this stays trivially
    unit-testable without a database. caller_can_share is one of these:
    sharing is gated by the org's own who_can_share policy (default
    "all_users"), not a fixed RBAC permission, so the caller resolves that
    policy lookup (services/ecosystem/policy_service.get_policy()) and
    passes the result in — this function never touches the DB itself.
    Defaults True (matching who_can_share's own "all_users" default) so
    every existing caller/test that doesn't pass it keeps prior behavior.
    """
    actions: set[str] = set()

    item_retired = item.status in ("deprecated", "yanked", "source_unavailable")

    if install is None:
        if not item_retired:
            actions.add("install")
    else:
        actions.add("uninstall")
        if install.scope != "required":
            actions.add("enable" if not install.enabled else "disable")
        if newer_version_available and not item_retired:
            actions.add("update")
        if has_multiple_versions:
            actions.add("rollback")
        # Sharing is policy-driven (product correction, 2026-09-27): a
        # normal user CAN share by default (who_can_share org policy,
        # default "all_users") -- marketplace:provision always passes
        # regardless of that policy, same as install_item's own
        # enforcement for this action.
        if caller_can_share or "marketplace:provision" in caller_permissions:
            actions.add("share")
        if install.scope == "shared":
            actions.add("unshare")

    # Reporting a suspect item is deliberately never permission-gated —
    # restricting who can flag a problem works against the gate's own
    # safety goals (task B-19).
    actions.add("report")

    if item.status == "active" and (is_owner or "marketplace:admin_sources" in caller_permissions):
        actions.add("deprecate")

    # edit_content: item A3's own new action -- "may this caller edit this
    # item's own SKILL.md/files," distinct from the pre-existing `update`
    # above (which means "bump MY install to a newer version someone else
    # already published"). Gates identically to
    # create_service._require_owner_or_admin() (marketplace:provision, not
    # marketplace:admin_sources like deprecate above -- a deliberately
    # different permission tier, matched to the real backend enforcement
    # this action's own endpoint uses, not copied from the nearest-looking
    # existing gate). Never offered on a retired item -- edit is not a
    # substitute for unyank/undelete.
    if not item_retired and (is_owner or "marketplace:provision" in caller_permissions):
        actions.add("edit_content")

    # delete_draft: owner-only, item still private, and no OTHER install
    # exists besides the owner's own (CONTRACTS.md §6, Review fix 6).
    if is_owner and item.scope == "org_private" and item.org_id == caller_org_id and not has_other_installs:
        actions.add("delete_draft")

    if "marketplace:admin_sources" in caller_permissions:
        if item.status != "yanked":
            actions.add("force_disable")
        else:
            actions.add("unyank")

    if "marketplace:admin_policy" in caller_permissions:
        actions.add("edit_policy")

    # Stable, documented order — never set iteration order, which is
    # insertion-order-dependent and not something a client should rely on
    # but shouldn't be gratuitously random between calls either.
    return [a for a in _ALL_ACTIONS if a in actions]


def delete_draft(
    item_id: str, *, caller_user_id: str, caller_org_id: str, caller_permissions: set[str],
) -> None:
    """POST /ecosystem/items/{id}/delete-draft (CONTRACTS.md §6/§17, Review
    fix 6) — hard-deletes the item, its versions, gate runs/findings, and
    installs. Re-derives allowed_actions itself rather than trusting the
    caller's own prior GET response, per the standing "server independently
    re-checks, never trusts a client-supplied allowed_actions array" rule.

    Never deletes the underlying object-storage blob — versions_service's
    content-hash addressing means another version (even from a different
    item, if content happens to be byte-identical) could reference the same
    object_key; object-storage cleanup for genuinely orphaned keys is a
    separate, not-yet-built garbage-collection concern, disclosed rather
    than solved here.
    """
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).first()
        if item is None:
            raise NotFoundError(f"no ecosystem item {item_id!r}")

        other_installs = (
            db.query(EcosystemInstall)
            .filter(EcosystemInstall.item_id == item_id, EcosystemInstall.installed_by != caller_user_id)
            .first()
            is not None
        )
        own_install = _install_for_caller(db, item_id, caller_org_id, caller_user_id)
        allowed = compute_allowed_actions(
            item=item, caller_user_id=caller_user_id, caller_org_id=caller_org_id,
            caller_permissions=caller_permissions,
            install=own_install,
            is_owner=_is_owner(db, item_id, caller_user_id),
            has_other_installs=other_installs,
        )
        if "delete_draft" not in allowed:
            raise PolicyForbiddenError("delete_draft is not allowed for this item/caller")

        # Item 9 fix (M5 UI-parity review, 2026-09-28): captured BEFORE the
        # deletes below -- once the item/install rows are gone, there's
        # nothing left to look up for the ecosystem.changed publish/cache
        # invalidation that has to happen after commit (see the bottom of
        # this function).
        item_type = item.item_type
        own_installed_for = own_install.installed_for if own_install else caller_user_id
        own_scope = own_install.scope if own_install else "private"

        version_ids = [
            v.id for v in db.query(EcosystemItemVersion.id).filter(EcosystemItemVersion.item_id == item_id).all()
        ]
        if version_ids:
            gate_run_ids = [
                g.id for g in db.query(EcosystemGateRun.id).filter(EcosystemGateRun.version_id.in_(version_ids)).all()
            ]
            if gate_run_ids:
                db.query(EcosystemGateFinding).filter(
                    EcosystemGateFinding.gate_run_id.in_(gate_run_ids)
                ).delete(synchronize_session=False)
                db.query(EcosystemGateRun).filter(EcosystemGateRun.id.in_(gate_run_ids)).delete(synchronize_session=False)
        db.query(EcosystemInstall).filter(EcosystemInstall.item_id == item_id).delete(synchronize_session=False)
        db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).delete(synchronize_session=False)
        db.delete(item)
        db.commit()
    finally:
        db.close()

    # Item 9 fix (M5 UI-parity review, 2026-09-28): real gap found live --
    # unlike every install-lifecycle mutation (installs_service.py's
    # install()/uninstall()/set_enabled()/etc., which all call
    # installs_service._publish_change()), delete_draft() bulk-deletes the
    # EcosystemInstall row directly with a raw query, never going through
    # that helper -- so nothing ever invalidated resolver_service's
    # per-caller capabilities cache or published an ecosystem.changed
    # event. A deleted skill kept showing up in chat's skill menu (a stale
    # cache hit) until that cache happened to expire on its own, and no
    # connected client (SSE) ever heard about the deletion at all. Can't
    # reuse installs_service._publish_change() verbatim -- it re-queries
    # EcosystemItem by id to build the event, which is exactly the row
    # delete_draft() just deleted; using the item_type/scope/installed_for
    # captured above instead, same two effects (cache invalidation +
    # Redis pub/sub publish), never allowed to turn a successful delete
    # into a request error.
    try:
        from services.ecosystem.resolver_service import invalidate_capabilities_cache
        invalidate_capabilities_cache(caller_org_id, own_installed_for)
    except Exception:
        pass
    try:
        # write_audit_event() wired in for real, 2026-09-29. item_id is
        # deliberately omitted (None), not item_id -- the row is already
        # gone by this point, and ecosystem_audit.item_id is a live FK;
        # inserting a NEW row that points at an id that no longer exists
        # would itself raise a FK violation (ON DELETE SET NULL only
        # protects EXISTING rows when the referent disappears later, not a
        # brand-new insert against an already-missing id). The deleted
        # item's own identity goes in `details` instead, same as any other
        # "the thing this refers to is gone" audit record.
        from services.ecosystem.audit_service import write_audit_event
        write_audit_event(
            org_id=caller_org_id, actor=caller_user_id, action="delete_draft", item_id=None,
            details={"deleted_item_id": item_id, "item_type": item_type},
        )
    except Exception:
        pass
    try:
        from services.ecosystem.events_service import publish_ecosystem_changed

        # "uninstalled" is the closest existing ChangeKind (CONTRACTS.md
        # §13 has no dedicated "deleted" value) -- from every OTHER
        # connected client's perspective, the caller's own install of this
        # item just disappeared, exactly what "uninstalled" already means.
        publish_ecosystem_changed(
            caller_org_id, item_type=item_type, item_id=item_id, scope=own_scope,
            change="uninstalled", version=None,
        )
    except Exception:
        pass


def create_item(**payload: Any) -> dict[str, Any]:
    """Stub — filled in by task B-6 (M2), see services/ecosystem/create_service.py."""
    raise NotImplementedError("items_service.create_item lands in task B-6 (M2) — see create_service.py")
