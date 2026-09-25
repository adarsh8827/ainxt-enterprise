# LLD — Security

**Purpose**: cross-cutting security properties of the marketplace — organization-scoping on every query, server-side enforcement of every action regardless of client-supplied hints, the hardened sandbox's isolation guarantees, and rate-limiting/idempotency/audit coverage. Filled in incrementally by every backend task; this file is the consolidated view.

## Files / functions
_TBD — see B-1 (org-scoping in the schema), B-9 (sandbox isolation), B-10 (server-side action enforcement), B-20 (rate limiting, idempotency, audit)._

## API and DB changes
_n/a — this file references changes made elsewhere; it does not introduce its own._

## Sequence diagrams
_TBD._

## Edge cases and errors
_TBD — the specific, previously-identified gap this design deliberately does not repeat: an internal service-to-service call must never authenticate by a shared secret plus a caller-supplied identity claim. Document here how this design avoids that pattern once the relevant task lands._

## Flags
_n/a._

## Tests
_TBD — the cross-organization isolation test and the forged-permissions test are the two most important entries here._

## How to extend
_TBD._
