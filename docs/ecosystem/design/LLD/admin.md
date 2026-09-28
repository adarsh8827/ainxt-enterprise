# LLD — Admin UI

**Purpose**: the enterprise-only admin screens (policies, provisioning, force-disable, gate findings, featured overrides) — task F-13, landed M4. Every screen fails closed twice: hidden client-side when the product profile's feature flags say so, and independently permission-checked server-side regardless of what the UI rendered (the UI hiding is a convenience, never the enforcement, matching `CONTRACTS.md`'s `allowed_actions` philosophy extended to whole screens).

## Files / functions

- `packages/ecosystem-ui/src/components/admin/AdminScreen.tsx` — the nav shell. Filters its own screen list by the live `GET /ecosystem/config`'s `features` flags (`admin_policies`, `provisioning`, `gate_dashboard`); if none are on for the caller's product (e.g. `workspace`), renders `admin-not-available` and nothing else — never a screen with every button disabled.
- `AdminPolicies.tsx` — `GET`/`PUT /ecosystem/policy` (task M4 backend prerequisites — this table/endpoint pair didn't exist before this milestone; `policy_service.py`'s own module docstring disclosed the gap since task B-19).
- `AdminProvisioning.tsx` — `POST /ecosystem/items/{id}/require`/`unrequire`. **Disclosed, deliberate scope limitation**: this screen promotes/demotes an *already org-provisioned* item's install rows to/from `required` — it does not (and cannot, given the real backend surface) target an arbitrary published item for org-wide default-on provisioning from scratch; that provisioning happens only at creation time via `provision_scope` (`CreateForm.tsx`'s own picker, `CONFIG_AND_PRODUCTS.md` §12 point 4). There is no "group targeting" concept anywhere in this backend (`CONTRACTS.md`'s full endpoint list has no such primitive) — the original task text's "group targeting" phrase is not implemented, because nothing exists server-side for it to call.
- `AdminForceDisable.tsx` — `POST /ecosystem/items/{id}/force-disable`/`unyank` (task B-19).
- `AdminGateFindings.tsx` — `GET /ecosystem/gate-findings` (task M4 backend prerequisite; `gate_service.list_recent_findings()`, org-scoped — an admin can never see another org's private items' findings, plus platform `builtin` items' findings, which every org's admin may legitimately see).
- `AdminFeatured.tsx` — `PUT`/`DELETE /ecosystem/featured/{item_id}` (task B-19/§11). `PUT {featured:false}` (explicit "not featured" override) and `DELETE` (remove the override, revert to the platform default) are genuinely different actions — an early draft of this screen conflated them; see `LLD/ui-package.md`'s Edge cases for the fix.

## API and DB changes

None beyond what `LLD/data-model.md`'s 2026-09-26 entry (`ecosystem_org_policy` table) and the M4 backend-prerequisite router endpoints already cover.

## Sequence diagrams

```
AdminScreen mounts
  → useConfig() (already resolved by the time this renders, per Marketplace.tsx's loading gate)
  → filter SCREENS by config.features[screen.feature]
  → 0 screens available → render "admin-not-available", stop
  → >=1 available → render nav + the active screen's own component,
    each of which independently calls its own GET/POST/PUT/DELETE endpoint
    (no shared admin-specific service layer beyond the EcosystemClient interface)
```

## Edge cases and errors

- **A `workspace`-profile caller with every admin feature off never even sees the nav, let alone a screen** — verified by `AdminScreen.test.tsx`'s own component test (not just code review): a `workspace`-shaped config fixture renders `admin-not-available` and nothing with `data-testid="admin-nav-*"` or `data-testid="admin-policies"` exists in the DOM at all.
- **UI hiding is never the real enforcement** — every one of these five screens' backend calls (`PUT /ecosystem/policy`, `.../require`, `.../force-disable`, `GET /ecosystem/gate-findings`, `PUT /ecosystem/featured/...`) is independently gated server-side by a `require_permission(...)` FastAPI dependency (`routers/ecosystem_router.py`) — a caller who somehow reached one of these components without the right permission (e.g. a modified client bypassing this UI's own hiding) still gets a real `403 POLICY_FORBIDDEN` from the server, per the standing "never trust client-side gating" rule already established for `allowed_actions`.

## Flags

None of these screens are gated by a separate `ECOSYSTEM_*` flag — visibility is entirely a function of the product profile's `features` object (`CONFIG_AND_PRODUCTS.md` §3), per task F-13's own instruction.

## Tests

`packages/ecosystem-ui/src/components/admin/AdminScreen.test.tsx` (2 tests): renders nothing for a `workspace`-profile fixture; renders the requested screen for an `enterprise`-profile fixture with admin features on. Per-screen component tests for `AdminPolicies`/`AdminProvisioning`/`AdminForceDisable`/`AdminGateFindings`/`AdminFeatured`'s own request/response wiring are not yet written — each screen is thin enough (a form calling one `EcosystemClient` method, per `LLD/ui-package.md`'s "no business logic in components" rule) that the coverage gap is disclosed here rather than padded with low-value tests; a future pass verifying each screen's specific request payload shape against a real backend response would be the natural next increment.

## How to extend

A new admin screen: add its component under `components/admin/`, add one entry to `AdminScreen.tsx`'s `SCREENS` array naming which `config.features` key gates it, and call the corresponding `EcosystemClient` method — never add a new client-side permission check of its own, since the feature-flag filter here is a convenience and the server's own `require_permission` dependency is the actual gate.
