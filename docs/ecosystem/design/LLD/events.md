# LLD — Change events

**Purpose**: how a mutation (install, uninstall, enable, disable, update, block) reaches every connected client live, so a change one person makes is visible to a teammate without a manual refresh. Task B-13, landed M3.

## Files / functions
- `services/ecosystem/events_service.py` — `publish_ecosystem_changed(org_id, *, item_type, item_id, scope, change, version)`. Fire-and-forget: never raises, even on a Redis outage (logs and returns).
- `routers/ecosystem_events_router.py` — `GET /ecosystem/events/stream`, an SSE endpoint delivering the caller's own org's events live.
- `services/ecosystem/installs_service.py`'s `_publish_change()` — the one place every B-10 install-lifecycle action calls through, so each of `install()`/`uninstall()`/`set_enabled()`/`update_to_version()` (and `rollback()`, which is `update_to_version()` under a different name) emits exactly one event, correctly typed, with no per-call-site duplication of the item_type/version lookup.

## API and DB changes
No new tables — pure Redis pub/sub, no persistence of past events (a client that was disconnected when an event fired must re-fetch the relevant list on reconnect, not expect replay — see Edge cases).

## Transport: real Redis PUBLISH/SUBSCRIBE + SSE, not WebSocket
The task's own file header cited "the WebSocket relay pattern already implemented for `routers/cowork_mcp_router.py`/`routers/cowork_dispatch_router.py`." Checked both directly before writing any code — **neither implements a WebSocket relay**: `cowork_mcp_router.py` serves **Server-Sent Events** backed by a per-session Redis `LIST` (`BLPOP`/`RPUSH` — point-to-point, one queue per connected client, "any worker's POST reaches this stream"); `cowork_dispatch_router.py` polls a Redis value directly. Grepping the entire Python tree for `WebSocket`/`websocket` turns up exactly two hits: this module's own docstring, and an unrelated regex string literal in `services/feedback_processor.py`. **There is no WebSocket endpoint anywhere in this codebase to reuse.**

`ecosystem.changed` genuinely needs *broadcast* semantics — every currently-connected client for an org must see every event, not one queue's worth split across competing consumers — which a per-session `LIST` cannot give (multiple readers on the same list compete for entries, they don't each see all of them). CONTRACTS.md §13 itself already specifies the correct primitive for this ("Redis pub/sub channel `ecosystem.changed.{org_id}`") — implemented here as genuine `PUBLISH`/`SUBSCRIBE`, with `cowork_mcp_router.py`'s real, existing pattern reused for the **delivery half** only: `StreamingResponse`, `text/event-stream`, 15s keep-alive pings, the same `redis.asyncio` client construction (`core.config.REDIS_HOST`/`REDIS_PORT`, db=5 — the same database the queues and `cowork_mcp_router.py`'s own session-routing keys already use for real-time coordination).

`core.kv`'s `KVClient` abstraction (`core.kv.get_kv`) has no `publish()`/`pubsub()` method — the same situation `core/job_queue.py`'s `_get_redis_connection()` (Lua scripts) and `cowork_mcp_router.py`'s `_get_async_redis()` (SSE session routing) are already in for other Redis-specific primitives the abstraction doesn't cover; both bypass it and construct a raw redis client directly, and `events_service.py` does the same.

## Sequence diagrams
```
[any of installs_service.py's install()/uninstall()/set_enabled()/update_to_version()]
    → mutation commits to Postgres
    → _publish_change(item_id, org_id, version_id, scope, change, installed_for)
        → resolver_service.invalidate_capabilities_cache(org_id, installed_for)   [direct call, see LLD/resolver.md]
        → look up item_type (EcosystemItem) + version string (EcosystemItemVersion)
        → events_service.publish_ecosystem_changed(org_id, item_type=..., item_id=..., scope=..., change=..., version=...)
            → raw redis.Redis(db=5).publish("ecosystem.changed.{org_id}", json.dumps(event))
    (never raises regardless of outcome -- the mutation's own response is already decided)

[connected client]
GET /ecosystem/events/stream  (SSE, same session auth as every other /ecosystem/* call)
    → subscribes to ecosystem.changed.{caller's own org_id} via redis.asyncio's pubsub()
    → yields ": connected\n\n", then "data: <event json>\n\n" per message, ": ping\n\n" every 15s idle
    → unsubscribes + closes on client disconnect (request.is_disconnected())
```

## Edge cases and errors
- **Delivery guarantee: fire-and-forget, at-most-once, no replay.** A client disconnected when an event fires (network blip, tab backgrounded and the browser suspended the connection, etc.) simply never receives that event — there is no queue, no replay buffer, no "catch up on reconnect" mechanism. This is a deliberate scope limitation, not an oversight: CONTRACTS.md §13's own invalidation table describes each `change` as "re-fetch and re-render from current fields," meaning the correct client behavior on reconnect is to re-fetch the relevant list(s) unconditionally (matching whatever `GET /ecosystem/installs`/`GET /ecosystem/capabilities` return right now), not to depend on having seen every individual event since disconnecting.
- **B-13's own definition of done scopes to B-10's install-lifecycle actions only** ("every mutating B-10 action emits exactly one correctly-typed event") — `install`/`uninstall`/`enable`/`disable`/`update`/`rollback`, all wired. B-19's other mutating actions (`share`/`unshare`/`report`/`force_disable`/`unyank`/`deprecate`/`require`/`unrequire`) are **not** wired by this task and are disclosed, not silently incomplete: `force_disable`/`unyank`/`deprecate` operate on the *item* directly rather than a specific install row, and CONTRACTS.md §13's channel is scoped per-org (`ecosystem.changed.{org_id}`) — for a globally-scoped item (`central_index`/`builtin`/`optional`), there is no single "the org" to notify, and every org with an install of that item would need to hear about it. That's a real, unresolved design question (a fan-out to every affected org's channel? a separate platform-wide channel?) that this task does not attempt to guess at.
- **A lookup or publish failure never turns a successful mutation into a request-handler error** — `_publish_change()`'s two blocks (cache invalidation, event publish) each wrap their own work in a bare `try/except: pass`; the mutation itself already committed before either runs.
- **`publish_ecosystem_changed()` itself validates `change` against CONTRACTS.md §13's fixed `ChangeKind` enum and raises `ValueError` on an unrecognized value** — this is the one place in the publish path that *does* raise, deliberately: an unrecognized change value is a bug on the calling side (the enum is fixed, not something a caller should ever get wrong), and a malformed event no client could parse is worse than a loud failure at the call site that produced it.

## Flags
None.

## Tests
`tests/services/ecosystem/test_events_service.py` (4 tests, real Redis): a real subscriber receives a published event with the right shape; a different org's channel does not receive it; an unknown `change` value raises; a Redis outage never raises out of `publish_ecosystem_changed()`. `tests/services/ecosystem/test_installs_service_lifecycle.py` (+4): `install`/`uninstall`/`set_enabled`(both directions)/`update_to_version` each publish exactly one, correctly-typed event (mocked at the `publish_ecosystem_changed` call site, since the wiring being tested is "did the right call happen with the right arguments," not the transport itself, which is `test_events_service.py`'s job).

## How to extend
Wiring B-19's remaining actions in, once the org-fan-out question above is resolved: add a `_publish_change`-equivalent call at each site, following the exact pattern already established in `installs_service.py`. The SSE endpoint itself needs no change for additional `ChangeKind` values — it relays whatever JSON was published, verbatim.
