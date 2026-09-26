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
- **M5's own consolidated security suite, `tests/services/ecosystem/test_ecosystem_security.py`** — finally fills this file's own long-standing "How to extend" item (the cross-org isolation and forged-`allowed_actions` tests named as the two most important gaps since the M0 milestone report). Covers cross-org isolation, permission/`allowed_actions` forgery, sandbox escape resistance, no skill content ever executing outside the sandbox, and license enforcement at every creation boundary (write/upload over real HTTP). 8 of 10 tests pass. **The other 2 document a real, severe, previously-undetected vulnerability rather than a test-authoring mistake**: `POST /ecosystem/installs/{id}/uninstall`, `.../set-enabled`, `.../update`, and `.../rollback` (`routers/ecosystem_router.py`, task B-10, M2 — pre-dates this milestone) declare no `current_user: dict = Depends(get_current_user)` parameter at all, unlike every other mutating endpoint in this router. A completely unauthenticated caller — or one authenticated as an unrelated org — can uninstall, disable, re-version, or roll back **any** install in **any** org, given only its UUID (returned in ordinary API responses, not a secret). Confirmed against a real running gateway process during this milestone's own verification before being reproduced as a permanent (currently failing, by design) regression test. **Disclosed here, not fixed** — out of this milestone's own delegated scope (writing tests), and a change this security-sensitive needs its own reviewed commit. This is now the single most urgent open item in this file.

## How to extend
The next task to pick this up should (1) add `current_user: dict = Depends(get_current_user)` to the four install-lifecycle endpoints named above, (2) add an ownership check — `installed_by`/`installed_for`'s org must match the caller's org, mirroring every other mutating endpoint in this router — since auth alone would fix the unauthenticated case but not the wrong-org case, and (3) flip `test_ecosystem_security.py`'s two currently-failing tests to confirm the fix (they're written to assert the *correct* behavior already, so a correct fix makes them pass with no test changes needed).
