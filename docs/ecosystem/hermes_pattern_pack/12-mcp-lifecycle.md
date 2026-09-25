# Pattern 12 — MCP server lifecycle

## Problem

An MCP server is an external process or endpoint that can crash, hang, be slow to start, or need
credentials — the platform needs to manage its lifecycle without letting a bad server degrade the
whole agent, while still letting a user filter which of its tools are actually exposed.

## How Hermes does it

**Three transports**, one lifecycle model: stdio (spawn a subprocess, talk over its stdin/stdout),
streamable HTTP, and SSE (falls back automatically from HTTP when the server responds in an
SSE-shaped way). Each server is one long-lived background task on a dedicated event loop.

**Eager vs. lazy start**: eager (default) connects at discovery time so tools are available
immediately; `lazy: true` registers a server's tools from a cached schema with **zero process
spawn**, and only actually connects on the first real call — a good default for rarely-used servers
where paying a subprocess-spawn cost at every startup isn't worth it.

**Resilience state machine** (conceptually, not exact field names):

```
state: closed -> half_open -> open (circuit breaker)
on 3 consecutive failures: open the circuit, cooldown (fixed window)
on cooldown expiry: half_open, allow one probe call
on probe success: closed again
separately: exponential backoff on reconnect attempts (base delay, capped max, per-server)
stdio processes additionally self-recycle after an idle timeout or a max lifetime
```

The circuit breaker answers *"is this server currently reachable at all,"* separately from
per-call timeout/retry logic that answers *"did this specific call fail."* A stdio child dying
**before** a call was dispatched is safely retried once; a child dying **mid-call** is reported as
"outcome uncertain" rather than blindly retried — silently replaying a call that might have already
had a side effect (e.g. a write) is treated as worse than surfacing ambiguity to the model.

**Tool filtering, per server**: an `include`/`exclude` list (exact names or glob patterns), with
include taking precedence — an empty include list means "register nothing from this server,"
letting an operator connect a server purely for future/manual use without exposing any of its tools
yet.

**Untrusted-server call gating**: a server can be marked `trust: untrusted` in config. At call time
(not discovery time), a write-shaped tool call (one lacking a "this is read-only" annotation, or
explicitly annotated as writing) from an untrusted server requires an explicit
elicit-consent step before it runs — reads proceed freely, writes don't, and a missing/ambiguous
annotation is treated as write-shaped (fails safe, not open).

**Shutdown**: a supervisor process independent of the main app tracks spawned stdio child PIDs
specifically so they get reaped even if the main process itself dies uncleanly (crash, OOM-kill) —
covering the case where the normal parent-death signal a subprocess would rely on isn't reliably
delivered on every OS.

**OAuth-authenticated remote servers — a concrete example worth naming explicitly.** Some catalog
entries aren't "run this locally" at all — they're a pure HTTP connection to a vendor's own hosted
MCP server, authenticated with real OAuth 2.1. A verified real example: an Atlassian catalog entry
whose `transport.url` points straight at Atlassian's own server and whose `auth.type` is `oauth` —
Hermes never spawns anything for it. The connect flow uses **Dynamic Client Registration** (the
client registers itself with the vendor's auth server on the fly, no pre-shared client ID needed),
then the standard local-loopback-callback + PKCE dance from pattern 14. What matters for *lifecycle*
specifically: token attachment and refresh are handled by a **generic auth-provider object**, not by
hand-written per-server logic:

```
provider = build_oauth_provider(server_name, token_store)
http_client = new_client(base_url=server.url, auth=provider)   # one line — provider is now
                                                                 # responsible for every request

# on every outgoing request, transparently, before Hermes's own code runs:
if provider.access_token_expired():
    new_tokens = refresh(provider.refresh_token)     # via the vendor's token endpoint
    token_store.set_tokens(new_tokens)               # persisted immediately
request.headers["Authorization"] = f"Bearer {provider.access_token}"
```

A vendor-issued **refresh token is bound to the specific authorization server that issued it**
(`hermes_issuer` stamped alongside it): if Hermes ever detects a stored refresh token about to be
sent to a *different* issuer than the one that granted it, it strips just the refresh token (keeping
the still-valid access token usable a while longer) rather than risk sending a credential to the
wrong party.

## Key design decisions and trade-offs

- **Circuit breaker + backoff are two separate mechanisms answering two separate questions**
  ("is it worth trying at all right now" vs. "how long before the next attempt"), which is more
  robust than conflating them into one retry counter — a server that's reachable but consistently
  erroring on real calls (open circuit) is a different failure than one that's simply slow to start
  (backoff).
- **Fail-safe-to-write-shaped on ambiguous annotations** is the conservative choice at a real cost
  (some genuinely read-only tools from a server that doesn't annotate well will unnecessarily
  prompt for consent) — accepted because the alternative (assuming read-only by default) risks
  silent unwanted writes from an untrusted source.
- **A crash-recovery decision that depends on *when* the crash happened relative to dispatch** (
  before vs. mid-call) is a deliberately more nuanced policy than a blanket "always retry once" —
  worth the extra state tracking because retry-with-side-effects is a real correctness hazard, not
  just an inconvenience.
- **Delegating token attach/refresh to one generic auth-provider object, wired in once at client
  construction, rather than hand-rolling "check expiry, refresh, attach header" at every call site**,
  means every MCP server that uses OAuth gets correct, consistent refresh behavior for free — a new
  OAuth-based catalog entry needs zero new lifecycle code.

## Failure modes and guards

- A chronically-failing server is prevented from causing restart storms via the connect-cooldown +
  circuit breaker combination, rather than retrying at a fixed short interval forever.
- An OS that doesn't reliably deliver parent-death signals to child processes (a known gap on at
  least one major OS) is covered by an out-of-band supervisor process, not relied on to "just work."
- A trust-tier misconfiguration (a typo in the trust value) fails to the *safer* state
  (`untrusted`), not the more permissive one.
- A vendor deprecating/changing their hosted MCP endpoint (a real recorded incident: a vendor's
  documented MCP URL stopped working after a cutover date, breaking every existing connection with
  404s despite OAuth still succeeding) is an operational risk unique to remote-hosted MCP servers —
  worth monitoring endpoint health separately from auth health, since "OAuth succeeded" and "the
  endpoint still exists" are independent failure axes.

## Verdict: ADOPT

The eager/lazy split, the separated circuit-breaker + backoff model, the before-vs-mid-call crash
distinction, and the annotation-based write-call gating are all strong, directly portable design
choices for managing any pool of external, semi-trusted tool-providing processes.

## Server-side translation

- **Per-tenant server pooling matters here**: if multiple tenants can configure "the same" MCP
  server (e.g. two tenants both connect a Notion MCP server), decide explicitly whether that's one
  shared connection or one per tenant — Hermes's single-user model never has to answer this
  question, and getting it wrong (accidentally sharing a connection/session across tenants) is a
  serious isolation bug, not just an efficiency one.
- Keep supervisor-based orphan reaping for stdio-transport servers if your server architecture ever
  spawns subprocesses directly — in a containerized/orchestrated deployment, prefer letting the
  orchestrator (not a custom supervisor process) own process lifecycle where possible.
- The trust/annotation-based write-gating model translates directly and is *more* important in a
  multi-tenant server, where an untrusted MCP server performing an unexpected write could affect
  data belonging to a paying customer, not just one individual's own machine.
- Expose per-server, per-tenant health status (the circuit-breaker state, last error, reconnect
  countdown) through your own status API/UI rather than only a CLI/log — this is exactly the kind
  of operational visibility a shared service needs and a single local user can more easily do
  without.
- **Token storage for OAuth-based MCP servers must be per-tenant, not per-server-name.** Hermes's
  `<server_name>.json` keying is safe because there's only one user; a multi-tenant platform must key
  by `(tenant_id, server_name)` at minimum, and should keep the token itself in a real secrets
  store/KMS rather than a file — see pattern 14 for the full storage-and-encryption discussion, since
  this is really a secrets-management problem wearing an MCP-lifecycle hat.
