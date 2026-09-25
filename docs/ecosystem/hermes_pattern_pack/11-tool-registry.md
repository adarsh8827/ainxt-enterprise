# Pattern 11 — Unified tool registry

## Problem

The model needs to call tools without caring whether a given tool is built into the platform, added
by a plugin, or proxied from a remote MCP server — but the platform still needs collision handling,
per-session gating, and a way to hide tools that aren't currently usable.

## How Hermes does it

**One registry, three origins, one dispatch path**:

```
register(name, toolset, schema, handler, check_fn=None, scope=None, override=False)
# built-ins: called at import time, scope=None (global)
# plugins:   called from the plugin's own register(ctx), scope=<profile>
# MCP:       called after a server's tools/list response, toolset="mcp-<server_name>", scope=<profile>

dispatch(name, args):
    entry = merged_tools(current_scope)[name]   # global registry overlaid with this profile's scoped entries
    return entry.handler(args)
```

The model never sees provenance — a `ToolEntry` looks identical whether its handler is a local
Python function, a plugin's function, or a network round-trip to an MCP server.

**Collision policy** (checked at registration time, not dispatch time):
- Exact duplicate registration (same name, same toolset) → allowed, treated as a refresh (e.g. an
  MCP server reconnecting).
- Same name, **different** toolset → rejected unless the caller passes `override=True` **and** an
  explicit operator opt-in exists for that specific plugin — an MCP server or plugin can never
  silently shadow a built-in tool by accident.
- MCP tools are namespaced under `mcp-<server_name>` specifically to make same-name collisions
  across two different MCP servers structurally impossible.
- A generated "utility" tool (e.g. an auto-synthesized `list_resources` for a resource-only MCP
  server) yields to a same-named tool the server provides natively.

**`check_fn` — visibility gating, decoupled from registration.** A tool can be *registered*
unconditionally but only *shown to the model* when its `check_fn` passes (e.g. "only show this tool
if the required API key is configured"). Results are cached with a short TTL (tens of seconds), with
a grace window that treats a check that *was* passing and *just* failed as a possible transient
flake rather than immediately hiding a previously-working tool — the two failure classes (a
brand-new optional tool that's never worked vs. a core tool that just broke) are logged at
different severities on purpose.

**Per-session toolset resolution — the capstone rule**: which *toolsets* (groups of tools) are
active for a given turn is resolved from the session's own recorded properties (its platform, its
configured toolset list, its role) — **never from a process-wide environment variable**, because
one backend process can be serving many different sessions/surfaces concurrently, and "is this a
GUI session" is a fact about that specific session, not the process.

**Profile-scoped overlays**: plugin- and MCP-registered tools live in a per-profile overlay layer on
top of the global registry, so a multi-profile process never leaks one profile's plugin/MCP tools
into another profile's tool list.

## Key design decisions and trade-offs

- **Registration-time collision checks, not dispatch-time**, mean a misconfigured plugin fails
  loudly and early (at load) rather than producing confusing "which tool actually ran" behavior
  mid-conversation.
- **Decoupling "exists" from "visible"** (`check_fn`) lets the registry stay simple (a flat map) while
  visibility logic — which can be arbitrarily complex per tool — lives beside each tool's own
  definition instead of in a central conditional.
- **Session-scoped, not process-scoped, capability resolution** is the single most important
  correctness rule in this whole pattern for any platform where one backend serves multiple
  surfaces/tenants at once — getting this wrong means capability leaks across sessions that
  shouldn't share anything.

## Failure modes and guards

- A `check_fn` that itself throws is treated as "cannot verify," logged, and the tool is hidden —
  fails closed, not open.
- A plugin registering with the same name as a built-in in a different toolset is rejected outright
  unless both `override=True` and an explicit operator config flag are set — two independent
  conditions, not one, to make an accidental shadow structurally hard to trigger.

## Verdict: ADOPT

The single-registry-three-origins design, registration-time collision policy, and especially the
"capability resolution is a property of the session, never the process" rule are all
directly and fully portable — this last rule in particular should be treated as close to
non-negotiable for any multi-tenant agent backend.

## Server-side translation

- The registry itself can be process-local exactly as Hermes has it (one backend process, in-memory
  map) — the profile-scoped-overlay idea maps directly onto **tenant-scoped overlay**: plugin/MCP
  tools registered by/for tenant A must never appear in tenant B's merged tool list, enforced the
  same way (scope-keyed overlay dict, resolved fresh per request).
- `check_fn` visibility gating is even more valuable server-side, since "is this tool's prerequisite
  configured" is now a **per-tenant** question (tenant A has a Slack connector configured, tenant B
  doesn't) — key the TTL cache by `(check_fn, tenant_id)`, not just `(check_fn,)`.
- Enforce "resolve active toolsets from the request/session record, never from process env or a
  global" as a hard architectural rule from day one — retrofitting it after a process-env shortcut
  has leaked into a few call sites is exactly the kind of bug class Hermes's own AGENTS.md calls out
  as expensive to unwind later.
