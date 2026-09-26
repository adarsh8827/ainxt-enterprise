# LLD — Config and products

**Purpose**: the product-profile/entitlement system that lets two different products share one backend and one UI package — which item types, surfaces, and features each product exposes, and how a caller's organization is authorized to use a given product at all. Task B-12, landed M3. Also where the lazy default-install provisioning mechanism `CONFIG_AND_PRODUCTS.md` §12 designed at M1 (and item 4, pre-M3, laid the groundwork for) actually gets consumed for the first time.

## Files / functions
- `services/ecosystem/config_service.py` — `get_effective_config(org_id, user_id, requested_product)`, `_resolve_product()` (CONTRACTS.md §4's three-step resolution), `ensure_provisioned()` (the lazy-provisioning sweep), `_provisioning_targets()`.
- `db/models.py` — `EcosystemSurface`, `EcosystemProductProfile`, `EcosystemOrgProduct` — the first ORM models for these three tables (schema existed since M1, `db/migrate.py`'s Part AD1; no model until this task first needed to query them, per `LLD/data-model.md`'s own pairing convention).
- `routers/ecosystem_router.py`'s `GET /ecosystem/config` — thin glue; `ConfigResponse` (task B-17's response model, `LLD/external-import.md`'s sibling doc for the OpenAPI generator that reads it).

## API and DB changes
No new tables. First real ORM-level queries against `ecosystem_surfaces`/`ecosystem_product_profiles`/`ecosystem_org_products`.

## Sequence diagrams
```
GET /ecosystem/config  [x-ainxt-product header optional]
    → _resolve_product(org_id, requested_product)
        → header absent:
            → org has an is_primary=true row in ecosystem_org_products? → that product_key
            → org has NO entitlement rows at all? → "enterprise" (pre-entitlement-system fallback,
              so a deployment that predates this header keeps working unchanged)
        → header present:
            → no ecosystem_product_profiles row for that key at all → NotFoundError
            → a profile exists but no (org_id, product_key) row in ecosystem_org_products → PolicyForbiddenError
            → both exist → that product_key
    → load the resolved product's EcosystemProductProfile row
    → ensure_provisioned(user_id, org_id, profile.enabled_surfaces)   [see below]
    → build CONTRACTS.md §8's exact response shape from the profile + ecosystem_surfaces rows

ensure_provisioned(user_id, org_id, surfaces):
    → targets = every scope='builtin' item (org-independent)
               UNION any item with an existing origin IN ('provisioned','required')
                     install row for this org_id (an admin-provisioned org-wide item,
                     CONFIG_AND_PRODUCTS.md §12 point 4)
    → for each target:
        → policy_service.is_org_default_excluded(item_id, org_id)? → skip (item 4a's admin
          org-level removal, consumed here for the first time)
        → this org already has a 'required' install of this item for ANY user?
            → yes: install(..., scope="required", origin="required")   [new user gets it required
                    from their very first call, matching B-12's own definition of done]
            → no:  install(..., scope="provisioned", origin="provisioned")
        → installs_service.install()'s own UNIQUE-constraint-backed ConflictError IS the
          "INSERT ... ON CONFLICT DO NOTHING" semantics §12 point 2 specifies -- caught and
          ignored, no special-casing needed here
```

## Edge cases and errors
- **The three-way product-resolution split, each independently tested**: (1) header absent → org's primary product, or `enterprise` if the org has no entitlement rows at all (`test_resolve_product_defaults_to_org_primary_when_header_absent`, `test_resolve_product_falls_back_to_enterprise_for_an_org_with_no_entitlement_row`); (2) header names a product with no profile row → `NotFoundError`/404 (`test_requested_product_with_no_profile_row_is_not_found`); (3) header names a real product this org has no entitlement row for → `PolicyForbiddenError`/403, distinct from case 2 — a product that *exists* but isn't *entitled* is a different failure than a product that doesn't exist at all (`test_requested_product_without_entitlement_is_policy_forbidden`).
- **Lazy provisioning is genuinely idempotent, not just "probably fine on a race"**: `test_second_config_call_creates_no_additional_rows` calls `get_effective_config()` twice in a row and confirms exactly one install row exists after both — the same `UNIQUE NULLS NOT DISTINCT (item_id, org_id, installed_for)` constraint (task B-1) that backs item 4c's concurrency test backs this too, just reached through a different call path.
- **A `required` item provisions as `required`, not `provisioned`, from a brand-new user's very first call** — if *any* other user in the org already has a `required` install of that item (meaning an admin ran `policy_service.require_item()` at some point), `ensure_provisioned()` checks for that before deciding the new row's `scope`/`origin`. Verified directly: `test_a_required_item_provisions_as_required_from_the_very_first_call` seeds an existing required row for one user, then confirms a second, brand-new user's first-ever config call provisions `required`, not `provisioned`.
- **`is_org_default_excluded()` (item 4a) is consumed here for the first time** — an admin's `admin_disable_org_default()` call permanently excludes that `(item_id, org_id)` pair from this sweep; `test_org_excluded_default_is_never_provisioned` confirms a brand-new user never gets a row for an excluded default, closing the exact gap item 4a's own design note flagged ("a brand-new org member would silently get the excluded default re-provisioned... without this").
- **No orgs table, so no background provisioning job exists or is needed** — matching `CONFIG_AND_PRODUCTS.md` §12's own reasoning: `org_id` is a free-text convention (`ECOSYSTEM_PLAN.md` §4), there is no fixed list of "all orgs" to iterate over, and a new org created after any hypothetical seed job ran would be missed anyway. `GET /ecosystem/config` — "the single call every UI makes before rendering anything marketplace-shaped" — is the only place this runs, exactly as designed.

## Flags
None — entitlement resolution and lazy provisioning are always active; `item_types[].state` is what `ECOSYSTEM_TYPE_*` (`core/config.py`) actually gates, computed fresh on every call.

## Tests
`tests/services/ecosystem/test_config_service.py` (10 tests): the three-way resolution split (5 tests), the full `ConfigResponse` shape matches `CONTRACTS.md` §8 exactly (`item_types[].state` correctly reflects which types are `available` vs `coming_soon`; `surfaces` correctly filtered to the resolved profile's own `enabled_surfaces`), first-call provisioning creates exactly one row per builtin item, a second call creates zero more, a required item provisions as required from the first call, an org-excluded default is never provisioned.

## How to extend
A third product: one new `ecosystem_product_profiles` row (`db/migrate.py`'s seed data, or a future admin-facing CRUD endpoint — none exists yet) plus `ecosystem_org_products` entitlement rows for whichever orgs get it. No code change to `config_service.py` itself — every code path here already reads the profile/entitlement rows generically, none of it hardcodes `"enterprise"`/`"workspace"` except the documented pre-entitlement-system fallback.
