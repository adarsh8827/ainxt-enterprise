# LLD — Install lifecycle

**Purpose**: install/uninstall/enable/disable/update/rollback/deprecate/delete-draft, plus sharing, reporting, and admin-side force-disable and featured overrides. Landed in tasks B-10, B-19 (M2).

## Files / functions
- `services/ecosystem/installs_service.py` (task B-10) — `install()`, `uninstall()`, `set_enabled()`, `update_to_version()`, `rollback()` (an alias for `update_to_version` — rollback is "update to an older, still-immutable version," not a distinct mechanism), `get_install()`, `get_install_for_caller()`, `list_installs()`.
- `services/ecosystem/policy_service.py` (task B-19) — `share()`/`unshare()`, `report()` (with the N-report auto-hide threshold), `force_disable()`/`unyank()` (map to `ecosystem_items.status='yanked'`/`'active'`), `set_featured_override()`/`delete_featured_override()`, and `require_item()`/`unrequire_item()` (Review round following M1, item F — promotes/demotes existing `provisioned` installs to/from `required`).
- `services/ecosystem/items_service.py`'s `compute_allowed_actions()` — the single source of truth for CONTRACTS.md §6's per-caller action array, a pure function taking the item/install/caller context as plain arguments (no DB access) so it's trivially unit-testable and so every call site (router, future admin screens) derives the same answer the same way.
- `routers/ecosystem_router.py` — thin HTTP glue for all of the above; `_handle_ecosystem_error()` maps each typed service exception to its documented wire error code.

## API and DB changes
Uses `ecosystem_installs`/`ecosystem_shares`/`ecosystem_reports`/`ecosystem_featured_overrides` from task B-1 as-is. `ecosystem_items.status`'s `'yanked'` value is used for both its original meaning (upstream-source-initiated removal) and admin-initiated `force_disable` — a single value covers both cases; there's no field distinguishing which caused it, since `allowed_actions`'s `unyank` action correctly applies to either origin, and no other current behavior needs to tell them apart.

## Sequence diagrams
```
Auto-install (task E's hook, triggered by the gate — see LLD/gate.md):
    gate verdict resolves pass/warn, trigger ∈ {ui_add, chat_create}
        → installs_service.install(scope/origin per provision_scope mapping)

Require / unrequire (Review round following M1, item F):
    admin calls POST /ecosystem/items/{id}/require
        → policy_service.require_item(item_id, org_id)
        → UPDATE ecosystem_installs SET scope='required', origin='required'
          WHERE item_id=... AND org_id=... AND origin='provisioned'
        → future lazy-provisioning calls (task B-12) for not-yet-provisioned
          users in that org read this same origin='required' state
```

## Edge cases and errors
- **`uninstall` never touches `ecosystem_items`; `deprecate` never touches any other org's `ecosystem_installs` rows.** Verified directly: `uninstall()` operates only on the single install row by id; `deprecate` (in the router, since it needs a schema column `ecosystem_items` doesn't have — see below) only ever updates the one item row.
- **A second install of the same `(item_id, org_id, installed_for)` raises a typed `ConflictError`, not a silent duplicate** — enforced by the real `UNIQUE NULLS NOT DISTINCT` DB constraint from task B-1 (see `LLD/gate.md`'s Edge cases for the critical bug that made this constraint inert until this milestone found and fixed it), caught and re-raised as `installs_service.ConflictError` so the router never leaks a raw `IntegrityError`.
- **`scope='required'` installs can never be disabled** — `set_enabled(install_id, False)` raises rather than silently no-op'ing or succeeding, so a caller can't accidentally "disable" something the required-flag is supposed to prevent.
- **No `created_by`/owner column exists on `ecosystem_items`** — a real, disclosed schema gap found while implementing `deprecate` and `compute_allowed_actions`'s ownership checks. This milestone's `deprecate` endpoint enforces admin-only (`marketplace:admin_sources`) rather than "owner or admin," since there is currently no column to check ownership against. `compute_allowed_actions()` itself accepts `is_owner` as a caller-supplied boolean specifically so this gap doesn't block testing the function's own logic — whoever eventually adds the ownership column only needs to change how that one boolean is computed, not the action-computation logic itself.
- **Org policy CRUD (`GET`/`PUT /ecosystem/policy`) has no backing table.** `CONFIG_AND_PRODUCTS.md`'s `policy_summary` read shape was speced, but no `ecosystem_org_policy`-shaped write table was ever added to task B-1's DDL. Disclosed as a real gap for whichever future task needs this to actually persist anything — not built here.

## Flags
None — every action here is always available (gated by permissions/`allowed_actions`, not a feature flag).

## Tests
`tests/services/ecosystem/test_installs_service_lifecycle.py` (9 tests: install/conflict/uninstall/enable-disable/required-lock/update/rollback/list+has_any), `tests/services/ecosystem/test_policy_service.py` (9 tests: share/unshare/report+auto-hide-threshold/force-disable/unyank/featured-overrides/require/unrequire), `tests/services/ecosystem/test_compute_allowed_actions.py` (14 pure-function tests covering every action's gating condition, including the "forged permission" expectation — the router always recomputes server-side, never trusts a client-supplied array). All passing against a real Postgres instance.

## How to extend
**Plugins/Connectors/MCP servers reuse this exact path, unchanged** (Review round following M1, item E): upload → object storage (`store/ecosystem_object_storage.py`) → gate (`services/ecosystem/gate_service.py`'s orchestrator, stages per `ECOSYSTEM_PLAN.md` §6) → auto-install on `pass`/`warn` for `trigger ∈ {ui_add, chat_create}` (`installs_service.install()`, this file's own subject) → `ecosystem.changed` event (task B-13) → resolved into the caller's available surfaces (`resolver_service.get_effective_capabilities`, task B-11). Nothing about this pipeline is skill-specific — the type-specific parts are entirely upstream of it (manifest parsing differs per type in gate stage 1, and `mcp_connector_stage`/sandbox-stage specifics differ per type in stages 5-7) and downstream of it (how each type surfaces in chat/Agent Studio/desktop). When Plugins/MCP/Connectors flip from `coming_soon` to `available` (a config-only change, `CONTRACTS.md` §8), this install-lifecycle path requires no code change to accommodate them — it was built type-agnostic from the start via `ecosystem_items.item_type` and `ecosystem_installs`, not a skill-only table.
