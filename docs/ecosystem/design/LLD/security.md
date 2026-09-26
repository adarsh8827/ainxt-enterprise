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
- `tests/services/ecosystem/test_audit_service.py` — a written event round-trips with its exact fields; an unknown action is rejected. The cross-organization isolation test and the forged-`allowed_actions` test (this file's other two flagged priorities) can't be written until there are real endpoints and real org-scoped queries to test against (task B-10/B-19, M2) — tracked there, not silently dropped here.
- `tests/db/test_ecosystem_migration.py::test_one_local_source_per_org_unique_index_enforced` — the closest thing to a cross-org isolation test this milestone can exercise: verifies the schema-level guarantee two orgs can't collide on the same `local` source row.

## How to extend
When task B-10/B-19 land, this file's Tests section should gain the actual cross-organization isolation test (an integration test asserting no query in `installs_service`/`items_service` can return another org's row) and the forged-`allowed_actions` test (a client-supplied `allowed_actions` array is never trusted — the server independently recomputes it). Both are named explicitly in the M0 milestone report as the two most important entries still missing.
