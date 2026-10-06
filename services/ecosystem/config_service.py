# SPDX-License-Identifier: MIT
# ============================================================
# Config service (task B-12, M3): GET /ecosystem/config's entitlement
# resolution (CONTRACTS.md §4/§8, CONFIG_AND_PRODUCTS.md §4) plus the
# lazy default-install provisioning mechanism CONFIG_AND_PRODUCTS.md §12
# designed at M1 and item 4 (pre-M3) laid the groundwork for
# (admin_disable_org_default()/is_org_default_excluded(),
# policy_service.py) but deliberately did not wire in yet -- this is
# where it actually gets consumed.
# ============================================================

from __future__ import annotations

from typing import Any

from core.build_info import get_build_info
from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion, EcosystemOrgProduct, EcosystemProductProfile, EcosystemSurface
from services.ecosystem import policy_service
from services.ecosystem.errors import NotFoundError, PolicyForbiddenError
from services.ecosystem.live_search_service import live_search_enabled
from services.ecosystem.publishers_service import resolve_caller_publisher_slug

# CONFIG_AND_PRODUCTS.md §12 point 4's provision_scope -> (scope, origin)
# mapping, reused verbatim from create_service.py/gate_service.py's own
# _AUTO_INSTALL hook -- kept as a second literal copy rather than a shared
# import, since the two call sites' surrounding logic differs enough
# (this one branches on "is this item already required in the org", not
# on a caller-supplied provision_scope) that importing would obscure more
# than it'd save.
_PROVISIONED = ("provisioned", "provisioned")
_REQUIRED = ("required", "required")

# The real, enforced taxonomy -- pulled out to a module-level constant
# (2026-09-29) so it has exactly one source of truth. Previously inlined
# directly inside get_effective_config()'s return dict; that meant nothing
# outside this function could validate a category against it without a
# full DB-backed get_effective_config() call, which is why the "operations"
# gap (scripts/ecosystem/admin_import.py's own STARTER_CATALOG) and the
# earlier "engineering"/"security" gap (docs/ecosystem/catalog/sources.yaml)
# both had to be found live rather than caught at load/crawl time.
# services/ecosystem/catalog_crawler/sources_config.py's load_sources() now
# imports this directly to reject an unknown category before any crawl runs
# at all, rather than after an item has already landed invisibly in the DB.
TAXONOMY_CATEGORIES: list[str] = [
    "productivity", "dev-tools", "communication", "data-analytics", "design", "finance",
    "crm", "marketing", "automation", "documents", "research", "hr-people",
    "security-compliance", "travel", "legal", "sales", "support", "general",
    "engineering", "security", "operations",
]


def get_org_enabled_surfaces(org_id: str, requested_product: str | None = None) -> list[str]:
    """Per-surface toggles round (2026-09-29): "all allowed surfaces from
    the product profile" -- the new DEFAULT for a fresh install now that
    the manual per-surface toggle UI is gone for normal users. A light
    read-only counterpart to get_effective_config() (below): resolves the
    same `EcosystemProductProfile.enabled_surfaces` that function already
    computes, WITHOUT also running ensure_provisioned()'s own DB writes or
    building the rest of CONTRACTS.md §8's response shape -- this is
    called from the install path itself, which must not have a side
    effect of re-provisioning every org-default item as a side quest.
    """
    db = SessionLocal()
    try:
        product_key = _resolve_product(org_id, requested_product)
        profile = (
            db.query(EcosystemProductProfile)
            .filter(EcosystemProductProfile.product_key == product_key)
            .first()
        )
        return list(profile.enabled_surfaces or []) if profile is not None else []
    finally:
        db.close()


def _resolve_product(org_id: str, requested_product: str | None) -> str:
    """CONTRACTS.md §4's exact three-step resolution."""
    db = SessionLocal()
    try:
        if requested_product is None:
            primary = (
                db.query(EcosystemOrgProduct)
                .filter(EcosystemOrgProduct.org_id == org_id, EcosystemOrgProduct.is_primary.is_(True))
                .first()
            )
            if primary is not None:
                return primary.product_key
            # No entitlement row at all for this org -- pre-entitlement-system
            # behavior, so existing callers from before this header existed
            # keep working unchanged.
            return "enterprise"

        profile = (
            db.query(EcosystemProductProfile)
            .filter(EcosystemProductProfile.product_key == requested_product)
            .first()
        )
        if profile is None:
            raise NotFoundError(f"no such product {requested_product!r}")

        entitlement = (
            db.query(EcosystemOrgProduct)
            .filter(EcosystemOrgProduct.org_id == org_id, EcosystemOrgProduct.product_key == requested_product)
            .first()
        )
        if entitlement is None:
            raise PolicyForbiddenError(f"org {org_id!r} is not entitled to product {requested_product!r}")
        return requested_product
    finally:
        db.close()


def get_org_product_key(org_id: str) -> str:
    """Task B-16's own surface-derivation needs "which product is this org
    on" on every chat turn, without paying get_effective_config()'s lazy-
    provisioning side effects (DB writes) on every single message -- this
    is _resolve_product()'s exact side-effect-free entitlement-resolution
    read, exposed as its own public function rather than duplicated."""
    return _resolve_product(org_id, None)


def resolve_chat_ecosystem_surface(client_source: str, org_id: str) -> str:
    """Task B-16/B-10: which ecosystem `surface` value (CONTRACTS.md's
    KnownSurface) a chat turn's skill index should resolve against.

    `client_source` is `request.state.client_source` as set by
    `middleware/client_source_middleware.py` from the `x-ainxt-surface`/
    `x-ainxt-client` headers (`desktop` when the Electron app's
    `webRequest.onBeforeSendHeaders` interceptor tagged the request --
    `desktop/src/main.js`). A desktop-app chat turn always resolves to the
    `desktop` surface regardless of the org's product, matching
    resolver_service.get_effective_capabilities()'s recognized surface set
    (`chat`/`agent_studio`/`cowork`/`desktop`/`workspace_chat`).

    Extracted from gateway.py's own inline chat-streaming logic (previously
    untestable without invoking the full streaming pipeline) into this pure
    function so it can be pinned by a direct unit test -- behavior is
    unchanged, this is a refactor for testability only."""
    if client_source == "desktop":
        return "desktop"
    return "workspace_chat" if get_org_product_key(org_id) == "workspace" else "chat"


def _latest_version_id(db, item_id: str) -> str | None:
    version = (
        db.query(EcosystemItemVersion)
        .filter(EcosystemItemVersion.item_id == item_id)
        .order_by(EcosystemItemVersion.created_at.desc())
        .first()
    )
    return version.id if version else None


def _provisioning_targets(db, org_id: str) -> list[EcosystemItem]:
    """Every scope='builtin' item (org-independent), union any item with
    an existing origin IN ('provisioned','required') install row for this
    org (an admin-provisioned org-wide item, CONFIG_AND_PRODUCTS.md §12
    point 4) -- the exact target set point 2/point 4 together specify.
    """
    builtin_items = db.query(EcosystemItem).filter(EcosystemItem.scope == "builtin").all()

    org_wide_item_ids = {
        row[0] for row in (
            db.query(EcosystemInstall.item_id)
            .filter(EcosystemInstall.org_id == org_id, EcosystemInstall.origin.in_(("provisioned", "required")))
            .distinct()
            .all()
        )
    }
    seen = {item.id for item in builtin_items}
    extra_items = [
        item for item in (
            db.query(EcosystemItem).filter(EcosystemItem.id.in_(org_wide_item_ids)).all()
            if org_wide_item_ids else []
        )
        if item.id not in seen
    ]
    return builtin_items + extra_items


def ensure_provisioned(user_id: str, org_id: str, surfaces: list[str]) -> int:
    """Idempotent: install()'s own UNIQUE-constraint-backed ConflictError
    is exactly the "INSERT ... ON CONFLICT DO NOTHING" semantics
    CONFIG_AND_PRODUCTS.md §12 point 2 specifies -- calling this a
    thousand times is as cheap as calling it once after the first,
    matching that section's own claim precisely (this is what proves it).
    Returns the number of NEW rows actually created this call.
    """
    from services.ecosystem.installs_service import ConflictError, install
    from services.ecosystem.policy_service import is_org_default_excluded

    db = SessionLocal()
    try:
        targets = _provisioning_targets(db, org_id)
        required_item_ids = {
            row[0] for row in (
                db.query(EcosystemInstall.item_id)
                .filter(EcosystemInstall.org_id == org_id, EcosystemInstall.origin == "required")
                .distinct()
                .all()
            )
        }
        provisioned_count = 0
        for item in targets:
            if is_org_default_excluded(item.id, org_id):
                continue
            version_id = _latest_version_id(db, item.id)
            if version_id is None:
                continue  # a builtin item with no version yet -- nothing to install
            scope, origin = _REQUIRED if item.id in required_item_ids else _PROVISIONED
            try:
                install(
                    item_id=item.id, version_id=version_id, org_id=org_id,
                    installed_by="system", installed_for=user_id,
                    surfaces=surfaces, scope=scope, origin=origin,
                )
                provisioned_count += 1
            except ConflictError:
                pass
        return provisioned_count
    finally:
        db.close()


def get_effective_config(
    org_id: str, user_id: str, requested_product: str | None, *, caller_permissions: set[str] | None = None,
) -> dict[str, Any]:
    """CONTRACTS.md §8's exact response shape.

    caller_permissions: added after a real bug -- CreateForm.tsx's own
    provisioning picker and AddDialog.tsx's scope radio group were both
    gating on `features.provisioning`/`features.share`, which are
    per-*product* flags (every caller under a given product sees the same
    value), not per-caller permissions. A normal, non-admin user under the
    `enterprise` profile (features.provisioning: true for that whole
    product) saw the same "Everyone in org"/provisioning UI an admin
    would. `caller_permissions` in the response is the real, caller-
    specific signal those two screens should gate on instead."""
    caller_permissions = caller_permissions or set()
    product_key = _resolve_product(org_id, requested_product)

    db = SessionLocal()
    try:
        profile = (
            db.query(EcosystemProductProfile)
            .filter(EcosystemProductProfile.product_key == product_key)
            .first()
        )
        if profile is None:
            raise NotFoundError(f"no product profile for {product_key!r}")
        surfaces = db.query(EcosystemSurface).all()
        enabled_item_types = list(profile.enabled_item_types or [])
        visible_item_types = list(profile.visible_item_types or [])
        enabled_surfaces_keys = list(profile.enabled_surfaces or [])
        layout = profile.layout
        default_view = profile.default_view
        features = dict(profile.features or {})
        surface_list = [{"key": s.key, "label": s.label} for s in surfaces if s.key in enabled_surfaces_keys]
    finally:
        db.close()

    ensure_provisioned(user_id, org_id, enabled_surfaces_keys)

    _ROUTE_SLUGS = {"skill": "skills", "plugin": "plugins", "connector": "connectors", "mcp_server": "mcp"}
    item_types = [
        {
            "type": t,
            "state": "available" if t in enabled_item_types else "coming_soon",
            "slug": _ROUTE_SLUGS.get(t, t),
        }
        for t in visible_item_types
    ]

    return {
        "product": product_key,
        "layout": layout,
        "default_view": default_view,
        "item_types": item_types,
        "route_slugs": _ROUTE_SLUGS,
        "surfaces": surface_list,
        "features": features,
        "caller_permissions": {
            # Sharing is policy-driven, not RBAC-permission-driven (product
            # correction, 2026-09-27): a normal user CAN share by default --
            # who_can_share org policy (services/ecosystem/policy_service.py,
            # default "all_users") is the actual gate, same pattern as
            # who_can_add. marketplace:provision always passes regardless of
            # that policy (an admin can always share, same as they can
            # always provision). marketplace:share itself is a real,
            # separate RBAC permission that grants nothing here on its own --
            # kept only because removing it would be an unrelated RBAC
            # schema change, not because it still does anything in this path.
            "can_share": (
                "marketplace:provision" in caller_permissions
                or policy_service.get_policy(org_id).get("who_can_share", "all_users") == "all_users"
            ),
            "can_provision": "marketplace:provision" in caller_permissions,
            # Per-surface toggles round (2026-09-29): the real, caller-
            # specific signal Yours.tsx/AddDialog.tsx gate the admin-only
            # "Advanced" surfaces override on -- same "real RBAC, not a
            # product feature flag" correction this whole caller_permissions
            # block exists for (see can_provision's own comment above).
            "can_admin_surfaces": "marketplace:admin_surfaces" in caller_permissions,
            # Admin-tabs regression round (2026-10-06, real user report):
            # AdminScreen.jsx's own nav only ever filtered on
            # config.features[...] -- a per-PRODUCT flag, same for every
            # caller under that product -- never on a real per-caller
            # signal, so a caller with none of these permissions still saw
            # the full 7-tab admin nav and could open/interact with every
            # tab (only failing, server-side, on actual submit). Same exact
            # bug class can_provision/can_admin_surfaces above already
            # exist to fix -- AdminScreen.jsx just never had an equivalent
            # signal to gate on for these two.
            "can_admin_policy": "marketplace:admin_policy" in caller_permissions,
            "can_admin_sources": "marketplace:admin_sources" in caller_permissions,
        },
        # A caller's own default publisher-namespace prefix (task: one-click
        # "Copy to my skills" -- no create flow in this codebase previously
        # had any notion of this, per CreateForm.tsx's own disclosed gap).
        # Auto-provisioned via the same ecosystem_publishers path any
        # explicit namespace uses; empty only if user_id itself is empty
        # (shouldn't happen for an authenticated caller -- this endpoint
        # requires one -- but this is a config-read path, not worth a 500
        # over a defensive fallback).
        "caller_default_namespace_prefix": resolve_caller_publisher_slug(user_id, org_id) if user_id else "",
        # Build-info (real incident, 2026-09-27: testing against a stale
        # image with no way to tell). Admin-only, same "marketplace:provision"
        # signal caller_permissions.can_provision above uses -- never sent to
        # a non-admin caller, not just hidden client-side.
        "build_info": (
            get_build_info() if "marketplace:provision" in caller_permissions else None
        ),
        "policy_summary": {
            k: v for k, v in policy_service.get_policy(org_id).items() if k != "org_id"
        },
        # Discover's "From the web" section (2026-09-29): real gap found
        # closing this out -- policy_summary.live_sources_enabled above is
        # only the org's own raw toggle, never combined with the instance-
        # wide ECOSYSTEM_LIVE_SOURCES flag, so a frontend gating on that
        # alone could show the section on an instance where the flag is off
        # (every search would then silently return [] -- correct per
        # live_search_service's own contract, but a broken-looking UI). This
        # is the real, effective "is live search actually usable for this
        # caller" signal -- the SAME live_search_enabled() GET /ecosystem/
        # search/live itself calls to decide whether to search at all, so
        # this can never disagree with that endpoint's own behavior.
        "live_search_enabled": live_search_enabled(org_id),
        "taxonomy": {
            "categories": list(TAXONOMY_CATEGORIES),
            "trust_tiers": ["builtin", "verified", "org", "community", "agent_created"],
        },
        "new_badge_days": 14,
        "enums_version": "2026.09.1",
    }
