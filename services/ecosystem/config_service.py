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

from db.database import SessionLocal
from db.models import EcosystemInstall, EcosystemItem, EcosystemItemVersion, EcosystemOrgProduct, EcosystemProductProfile, EcosystemSurface
from services.ecosystem.errors import NotFoundError, PolicyForbiddenError

# CONFIG_AND_PRODUCTS.md §12 point 4's provision_scope -> (scope, origin)
# mapping, reused verbatim from create_service.py/gate_service.py's own
# _AUTO_INSTALL hook -- kept as a second literal copy rather than a shared
# import, since the two call sites' surrounding logic differs enough
# (this one branches on "is this item already required in the org", not
# on a caller-supplied provision_scope) that importing would obscure more
# than it'd save.
_PROVISIONED = ("provisioned", "provisioned")
_REQUIRED = ("required", "required")


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


def get_effective_config(org_id: str, user_id: str, requested_product: str | None) -> dict[str, Any]:
    """CONTRACTS.md §8's exact response shape."""
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
        "policy_summary": {
            "who_can_add": "all_users", "allowed_sources": ["central_index"], "auto_update_default": False,
        },
        "taxonomy": {
            "categories": [
                "productivity", "dev-tools", "communication", "data-analytics", "design", "finance",
                "crm", "marketing", "automation", "documents", "research", "hr-people",
                "security-compliance", "travel", "legal", "sales", "support", "general",
            ],
            "trust_tiers": ["builtin", "verified", "org", "community", "agent_created"],
        },
        "new_badge_days": 14,
        "enums_version": "2026.09.1",
    }
