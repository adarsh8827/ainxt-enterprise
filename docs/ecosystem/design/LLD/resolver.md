# LLD — Capability resolver

**Purpose**: turns "this user, in this org, on this surface" into the exact set of installed, enabled, currently-available items they can see and use right now. The single function every runtime consumer (chat, later: other surfaces) calls — never a bespoke per-surface query. Task B-11, landed M3.

## Files / functions
- `services/ecosystem/resolver_service.py` — `get_effective_capabilities(org_id, user_id, surface)`, `invalidate_capabilities_cache(org_id, user_id)`.
- `routers/ecosystem_router.py`'s `GET /ecosystem/capabilities?surface=...` — thin glue, wraps the resolver's flat skill list into CONTRACTS.md §9's `Capabilities` envelope (`plugins`/`connectors`/`mcp_tools` always `[]` this phase — no live content for any of those types yet).

## API and DB changes
No new tables. Queries `ecosystem_installs` joined to `ecosystem_items` directly — see Edge cases below for why this needs no separate merge with `services/ecosystem/legacy_bridge.py` despite the task's own "merges the legacy bridge" phrasing.

## Sequence diagrams
```
GET /ecosystem/capabilities?surface=chat
    → resolver_service.get_effective_capabilities(org_id, user_id, "chat")
        → cache hit (Redis, 60s TTL, keyed by sha256(org_id:user_id:surface))? return it
        → else: SELECT ecosystem_installs JOIN ecosystem_items
                 WHERE org_id=... AND installed_for=... AND enabled=true AND items.status='active'
          → filter: item_type in {types with their ECOSYSTEM_TYPE_* flag on} (this phase: skill only)
          → filter: surface ∈ install.surfaces
          → cache the result, return it

[any installs_service mutation: install/uninstall/set_enabled/update_to_version/rollback]
    → _publish_change(...) calls resolver_service.invalidate_capabilities_cache(org_id, installed_for)
      DIRECTLY, in-process, in the same call — not as a reaction to the ecosystem.changed
      publish that happens in the same function right after
```

## Edge cases and errors
- **"Merges task B-4's legacy bridge with native ecosystem_installs rows" needs no separate query at runtime.** `scripts/ecosystem/backfill_legacy_items.py` (B-4) upserts a real `ecosystem_items` row per legacy skill and enqueues a gate run, but its trigger is `"admin_provision"` — not one of `gate_service.py`'s own `_AUTO_INSTALL_TRIGGERS = ("ui_add", "chat_create")` — so a backfilled item never gets an `ecosystem_installs` row automatically. It becomes an effective capability only once something actually installs it, exactly like any other item; there is no special-casing for legacy-sourced rows in this resolver, and no separate `legacy_bridge.py` call. Verified directly: `test_never_installed_item_is_not_resolved_even_if_gate_passed` creates a backfilled-shaped item with a passing gate verdict and confirms it does **not** appear.
- **Cache invalidation is a direct, synchronous, in-process call, not a reaction to the `ecosystem.changed` pub/sub event** (task B-13) — despite the original task text saying "invalidated by ecosystem.changed." A pub/sub-driven invalidation would require a persistent subscriber process reacting asynchronously, which introduces a real window where the cache could still be stale if that subscriber isn't running or hasn't processed the message yet. Calling `invalidate_capabilities_cache()` directly from the same function that performs the mutation (`installs_service.py`'s `_publish_change()`) guarantees "no stale-cache window beyond the explicit invalidation" unconditionally — the same functional guarantee the task asked for, achieved more directly. `ecosystem.changed` is still published (for connected UI clients to react to), just not relied upon for this cache's own correctness.
- **What happens to an in-flight resolution when an item is disabled mid-request**: nothing — the DB query and the disable both run inside their own separate, already-committed transactions; a resolution reads whatever `enabled` value was true at the instant of its own query. No stale-read protection beyond that is needed, since the request/response cycle for a single resolution is short and the very next resolution (or a cache invalidation from a concurrent disable) sees the current state.
- **A cache/Redis outage degrades to "always resolve fresh," never an error** — `_get_cache()` returns `None` on any construction/ping failure, and every call site checks for `None` before touching it.

## Flags
`ECOSYSTEM_TYPE_SKILL`/`_PLUGIN`/`_MCP`/`_CONNECTOR` (`core/config.py`) gate which `item_type` values are ever resolved — this phase, only `skill` (the others default off). Flipping one of these on later requires no resolver code change, per `_ITEM_TYPE_FLAGS`'s own mapping.

## Tests
`tests/services/ecosystem/test_resolver_service.py` (7 tests): installed+enabled+matching-surface resolves; a disabled install does not; the wrong surface does not; a never-installed (but gated) legacy-shaped item does not; a different user's install does not leak across users; disabling an item type's flag excludes it; the result is genuinely cached (proven by poisoning the cache key with an impossible value and observing it come back) and correctly invalidated on the very next mutation.

## How to extend
A future item type (`plugin`/`mcp_server`/`connector`) needs no resolver change to start being included once its `ECOSYSTEM_TYPE_*` flag flips and it starts appearing in real installs — `_available_item_types()` already re-reads the flags on every call. `GET /ecosystem/capabilities`'s `plugins`/`connectors`/`mcp_tools` arrays are the router's own job to populate from a similarly-shaped resolver query once that phase adds real content for those types; this file's `get_effective_capabilities()` intentionally only returns the `skills` shape today.
