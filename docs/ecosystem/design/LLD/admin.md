# LLD — Admin

**Purpose**: org policy management, provisioning, force-disable, featured overrides, and the gate-findings dashboard — visible only to the full-featured product's administrators, enforced server-side regardless of what the UI shows. Backend endpoints landed in task B-19 (M2); the admin screens themselves are task F-13 (M4, not started).

## Files / functions
- `services/ecosystem/policy_service.py` — `force_disable()`/`unyank()`, `set_featured_override()`/`delete_featured_override()`, `require_item()`/`unrequire_item()` (Review round following M1, item F).
- `routers/ecosystem_router.py` — `POST /ecosystem/items/{id}/force-disable`, `POST /ecosystem/items/{id}/unyank`, `PUT`/`DELETE /ecosystem/featured/{item_id}`, `POST /ecosystem/items/{id}/require`/`unrequire` — every one gated by `Depends(require_permission("marketplace:admin_sources"))` or `"marketplace:admin_policy"`/`"marketplace:provision"` as appropriate (`auth/rbac.py`, task B-18), never left to client-side hiding alone.

## API and DB changes
Uses `ecosystem_items.status`, `ecosystem_featured_overrides`, and `ecosystem_installs.scope`/`origin` from task B-1. No new tables. **Org policy CRUD has no backing table yet** (see `LLD/install-lifecycle.md`'s Edge cases) — `GET`/`PUT /ecosystem/policy` are not implemented this pass.

## Sequence diagrams
_n/a — each admin action here is a single, direct state transition (see `LLD/install-lifecycle.md`'s sequence diagram for `require`/`unrequire`, the one multi-row admin action)._

## Edge cases and errors
- **The difference between a screen being hidden (client-side convenience) and an action being rejected (server-side enforcement) — both hold independently.** Every admin action's router handler depends on the matching RBAC permission via `Depends(require_permission(...))`, which raises `403` before the handler body ever runs for a caller lacking it — a client that somehow renders an admin control anyway still gets a real rejection, not a successful mutation.
- **`force_disable`/`unyank` reuse `ecosystem_items.status`'s existing `'yanked'`/`'active'` values** rather than introducing a new status — see `LLD/install-lifecycle.md` for why this is a deliberate, minimal reuse rather than a schema change.
- **The N-report auto-hide threshold (task B-19) only marks `ecosystem_reports.status='auto_hidden'`** — it does not itself remove the item from Discover. Actually excluding an auto-hidden item from catalog listings is the resolver's job (task B-11, M3), not implemented here; disclosed rather than assumed done.

## Flags
None.

## Tests
Covered by `tests/services/ecosystem/test_policy_service.py` (force-disable/unyank/featured-overrides/require/unrequire — 5 of its 9 tests) — all against a real Postgres instance. No test exercises the RBAC-permission-rejection path at the HTTP layer yet (would need a running FastAPI test client with a real/fake JWT, not built this pass) — the permission wiring itself (`Depends(require_permission(...))` on every admin route) is verified by direct code inspection, not an executed test; disclosed as a gap for task F-13 or a dedicated router test to close.

## How to extend
Task F-13 (admin screens, M4) is the next consumer of everything in this file — it should render nothing client-side that isn't backed by a real `allowed_actions`/permission check already enforced here, per the edge-case note above.
