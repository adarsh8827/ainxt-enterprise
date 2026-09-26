# LLD — Security

**Purpose**: cross-cutting security properties of the marketplace — organization-scoping on every query, server-side enforcement of every action regardless of client-supplied hints, the hardened sandbox's isolation guarantees, and rate-limiting/idempotency/audit coverage. Filled in incrementally by every backend task; this file is the consolidated view.

## Files / functions
- `services/ecosystem/rate_limit_service.py` (task B-20, M1) — per-`(user_id, action_class)` sliding-window counters, `action_class ∈ {add, install, connect, report}`. Reuses the sliding-window-via-Redis-sorted-set *technique* already established in `core/rate_limiter.py`'s `_check_rate_limit_redis()` (cited, not imported — that module is FastAPI-`Request`-coupled by design, since every one of its call sites is a route handler; this service is framework-agnostic per task B-3's rule, so it reimplements the same algorithm and returns a plain `RateLimitResult`, leaving the HTTP-429-with-headers translation to the router layer once one exists). Falls back to an in-process counter if Redis is unreachable, same resilience posture as the module it's modeled on.
- `services/ecosystem/idempotency_service.py` (task B-20, M1) — Redis-backed `(caller, Idempotency-Key) → response` cache, 24h TTL, per `docs/ecosystem/CONTRACTS.md` §4.
- `services/ecosystem/audit_service.py` (task B-20, M1) — `write_audit_event()`, the shared infrastructure every mutating endpoint (task B-6 through B-19, M2) is responsible for calling from its own code path. This milestone verifies the function itself, not endpoint coverage — see Tests below.
- Both rate-limit and idempotency use a dedicated Redis DB (10) — DBs 0-9 are already allocated elsewhere in this codebase (`core/rate_limiter.py`, `auth/session_manager.py`, `auth/dependencies.py`, others); claimed the next free slot rather than colliding.
- `db/migrate.py`'s `_part_ad1_...` (task B-1, M1) — every new table with an `org_id` column uses it consistently (`VARCHAR(255)`, matching the platform-wide convention); see `LLD/data-model.md` for the full schema and its edge cases (the one-local-source-per-org and namespace-uniqueness partial indexes).
- Sandbox isolation (task B-9) and server-side action enforcement (task B-10) land in M2 — not yet implemented.

## API and DB changes
_n/a — this file references changes made elsewhere; it does not introduce its own._

## Sequence diagrams
_TBD — lands with task B-9/B-10 (M2), where there's an actual request path to diagram._

## Edge cases and errors
- The specific, previously-identified gap this design deliberately does not repeat: an internal service-to-service call must never authenticate by a shared secret plus a caller-supplied identity claim (`docs/ecosystem/ECOSYSTEM_PLAN.md` §15 decision 7 records this as a known gap in *existing*, pre-marketplace code, reported to security separately — the new credential broker, whenever it lands, does not inherit or extend this pattern). Nothing built in M1 touches credentials or service-to-service auth yet.
- **Audit action values are a closed set** (`_KNOWN_ACTIONS` in `audit_service.py`, matching `ecosystem_audit.action`'s documented value list) — an unrecognized action raises `ValueError` at the call site rather than silently accepting a typo'd string that would never be queryable later.
- **Rate-limit action classes are similarly closed** (`_ACTION_CLASSES` in `rate_limit_service.py`) — same reasoning.

## Flags
_n/a — this infrastructure has no flag; it's always active for any code path that calls it (task B-6 onward decides when that is)._

## Tests
- `tests/services/ecosystem/test_rate_limit_and_idempotency.py` — per-user, per-action-class isolation; blocking after the limit; idempotency round-trips and per-(caller, key) scoping. Backend-agnostic (passes whether Redis or the in-process fallback is active), run against a real Redis container for this milestone.
- `tests/services/ecosystem/test_audit_service.py` — a written event round-trips with its exact fields; an unknown action is rejected.
- `tests/db/test_ecosystem_migration.py::test_one_local_source_per_org_unique_index_enforced` — the closest thing to a cross-org isolation test M1 alone could exercise: verifies the schema-level guarantee two orgs can't collide on the same `local` source row.
- **M5's own consolidated security suite, `tests/services/ecosystem/test_ecosystem_security.py`** (12 tests, all passing) — fills this file's own long-standing "How to extend" item (cross-org isolation and forged-`allowed_actions` named as the two most important gaps since the M0 milestone report). Covers cross-org isolation, permission/`allowed_actions` forgery, sandbox escape resistance, no skill content ever executing outside the sandbox, and license enforcement at every creation boundary (write/upload over real HTTP). Two of its tests were written first as intentionally-failing documentation of a real vulnerability, then flipped to pass once the fix below landed in the same milestone: `test_install_lifecycle_endpoints_require_authentication` (now covers all four endpoints, not just two) and `test_install_lifecycle_endpoints_enforce_org_ownership_even_when_authenticated`. Two more were added once the fix's own design needed proving: `test_every_ecosystem_route_requires_authentication` (enumerates every registered route in `routers/ecosystem_router.py` and asserts a 401 with zero `Authorization` header — the mechanical backstop against a future endpoint shipping without auth) and `test_install_lifecycle_endpoints_allow_the_owner_and_reject_a_same_org_non_owner_non_admin` (a same-org non-owner gets 403, the actual owner succeeds).

### The vulnerability, and why B-10's own tests never caught it
`POST /ecosystem/installs/{id}/uninstall`, `.../set-enabled`, `.../update`, and `.../rollback` (`routers/ecosystem_router.py`, task B-10, M2) declared no `current_user: dict = Depends(get_current_user)` parameter at all, unlike every other mutating endpoint in this router. A completely unauthenticated caller — or one authenticated as an unrelated org — could uninstall, disable, re-version, or roll back **any** install in **any** org, given only its UUID (returned in ordinary API responses, not a secret). A live audit while fixing this found four more endpoints with the same *class* of gap, at lower severity — see the table below.

`tests/services/ecosystem/test_installs_service_lifecycle.py` (B-10's own suite) calls `installs_service.uninstall()`/`set_enabled()`/etc. **directly as Python functions**, never through the HTTP router — so it could never have caught a router-wiring gap; the service functions themselves did exactly what their (then-narrower) contract asked. `test_compute_allowed_actions.py`'s forged-permission test proves a *different* thing: that `compute_allowed_actions()` — the function that decides which actions to *advertise* in a response, purely informational, e.g. for the UI to grey out a button — never trusts a client-supplied permission set. It says nothing about whether the actual mutating endpoint enforces anything at all once a client decides to call it directly, ignoring whatever the UI advertised. This bug lived entirely in that second, unrelated gap: the real enforcement point had no check of any kind, so a correct `allowed_actions` computation upstream was irrelevant. Only a test exercising the *real HTTP route*, with a *real absent-or-wrong-org* `Authorization` header, could ever have caught this — the same lesson this milestone already learned twice before (the namespace-routing 404 bug, the missing SSE `draft_id`): a service-layer-only test suite is blind to an entire class of wiring bugs at the router boundary.

### The fix
1. **Router-level default**: `routers/ecosystem_router.py`'s `router = APIRouter(...)` now declares `dependencies=[Depends(get_current_user)]` — every route in this file requires authentication whether or not it also declares its own `current_user` parameter (FastAPI caches the dependency per request, so routes needing the actual payload aren't calling it twice). No route is exempt.
2. **Ownership + org scoping**, added to every endpoint taking an install/item/draft/job/share id that lacked it:

| Route | Auth (before → after) | Org/ownership scoping (before → after) | Permission check |
|---|---|---|---|
| `POST /ecosystem/installs/{id}/uninstall` | none → router-level + explicit | none → `_authorize_install_mutation()`: same org required, then owner or `marketplace:provision` | n/a (ownership check covers it) |
| `POST /ecosystem/installs/{id}/set-enabled` | none → router-level + explicit | same as above | same as above |
| `POST /ecosystem/installs/{id}/update` | none → router-level + explicit | same as above | same as above |
| `POST /ecosystem/installs/{id}/rollback` | none → router-level + explicit | same as above | same as above |
| `GET /ecosystem/jobs/{id}` | none → router-level + explicit | none → joins version_id→item_id, `_visible_to_caller()` | n/a |
| `GET /ecosystem/items/{id}/versions` | already had it | none → `_visible_to_caller()` on the item | n/a |
| `GET /ecosystem/items/{id}/gate-runs` | already had it | none → `_visible_to_caller()` on the item | n/a |
| `POST /ecosystem/items/{id}/share` | already had it | `install_id` (body) not verified → now must belong to caller's org | `marketplace:share` (unchanged) |
| `POST /ecosystem/shares/{id}/unshare` | already had it | none → joins to the underlying install's org | n/a (never was) |
| `POST /ecosystem/items/{id}/deprecate` | already had it | none → `_visible_to_caller()` (global items still reachable by any admin; `org_private` items only by their own org's admin) | `marketplace:admin_sources` (unchanged) |
| `POST /ecosystem/items/{id}/force-disable` | already had it | same as deprecate | `marketplace:admin_sources` (unchanged) |
| `POST /ecosystem/items/{id}/unyank` | already had it | same as deprecate | `marketplace:admin_sources` (unchanged) |
| everything else in this router (create, list/detail, drafts, install, require/unrequire, featured, config/capabilities, policy CRUD, gate-findings, gate-health) | already had it | already correctly org-scoped | unchanged |
| `GET /ecosystem/events/stream` (`routers/ecosystem_events_router.py`, a separate file) | already had it | already scoped to `ecosystem.changed.{caller's own org_id}` | n/a — audited, no change needed |

   Cross-org lookups raise `NotFoundError` (404) rather than `PolicyForbiddenError` (403) — a caller outside an install's/item's org must not learn the id refers to something real. Same-org, wrong caller (not the owner, not an admin) gets a real 403 — the caller is already inside the org boundary, so revealing existence there is not itself a leak.
3. **Deliberately not changed**: `POST /ecosystem/items/{id}/report` (reporting a suspect item is deliberately never permission- or org-gated per task B-19 — the item id is caller-supplied, not learned from the response, so there's no information disclosure to fix); `PUT`/`DELETE /ecosystem/featured/{id}` (already keyed by `(caller's org_id, item_id)` — an override on an item the caller's org can't otherwise see is an inert row with no observable effect, since that item never appears in that org's own catalog to be affected by it).
4. `_authorize_install_mutation()` reuses `marketplace:provision` — the same permission `require_item()`/`unrequire_item()` already use to act org-wide on installs — for the "org admin acting on a teammate's install" case, rather than inventing a new permission.
5. Confirmed the two originally-failing tests were **never** added to `scripts/ci/known_failures.txt` (checked directly) — a real, disclosed vulnerability is not the kind of thing that baseline exists to tolerate.
6. Full regression after the fix: `tests/services/ecosystem` 277 passed (0 failures); the broader CI-covered subset (`tests/auth tests/config tests/core tests/agents tests/store tests/cil`) shows the same 23 pre-existing failures already in `known_failures.txt` plus the same one already-disclosed-elsewhere `test_fails_when_jwt_missing_in_prod` (confirmed pre-existing via `git stash` earlier this milestone, `LLD/chat-runtime.md`) — 0 new regressions from this fix.

## How to extend
A new endpoint in this router never needs to remember to add auth — the router-level dependency already covers it — but it does need to remember org/ownership scoping if it takes an id whose underlying row has an owner or an org: reuse `_authorize_install_mutation()` (installs) or `_visible_to_caller()` (items) rather than writing a new check, and add its route to `test_every_ecosystem_route_requires_authentication`'s implicit coverage automatically (that test enumerates the router's own registered routes, so nothing further is needed there) plus a route-specific cross-org/ownership test modeled on the ones in `test_ecosystem_security.py`.
