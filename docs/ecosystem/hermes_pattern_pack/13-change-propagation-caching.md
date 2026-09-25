# Pattern 13 — Change propagation and caching

## Problem

When something changes (a skill is installed, a tool is disabled, config is edited), how does that
change reach an already-running conversation — and how do you avoid paying an expensive
recomputation (rebuilding the system prompt) on every trivial change?

## How Hermes does it

**The one invariant that shapes everything else: the system prompt must stay byte-identical for
the life of a conversation, because providers charge less (and respond faster) for a cached
prefix.** Every caching/reload decision in the codebase is downstream of protecting that invariant.

**Cache inventory and what invalidates each one:**

| Cache | Invalidated by | Effect timing |
|---|---|---|
| System prompt (content-addressed, stored once, restored verbatim across turns) | Only two things: an explicit `--now`/cache-clear call, or the agent's own context-compression pass | Next turn |
| Slash-command / capability index | Nothing automatically — always re-scanned fresh on demand (a "pull," not a cache at all) | Immediate, on next query |
| `check_fn` tool-visibility results | A short TTL, or an explicit "config changed" invalidation call | Within the TTL window, or immediate if explicitly cleared |
| Marketplace catalog (skills index, live plugin catalog) | A TTL, with stale-serve-on-failure as a fallback | Background-refreshed, not tied to any user action |
| Discovered MCP tool schemas | An explicit reload call for that server | Immediate for that server only |

**No filesystem watcher for extensions.** A real background watcher does exist in the codebase, but
it's scoped narrowly to a handful of live-status signals (session activity, gateway connection
state, a couple of small JSON files) — it deliberately does **not** watch skills, plugins, or MCP
config directories. Picking up a new extension is always one of: an explicit reload command, an
explicit "apply now" flag, or the natural rebuild that happens anyway at the start of a brand-new
conversation.

**Deferred-by-default, explicit-escape-hatch is the consistent shape across every extension type**:
install/enable/disable something → by default it takes effect "next session" → an explicit flag or
command makes it immediate at the cost of one deliberate cache invalidation. The naming differs
slightly per surface (`--now`, `/reset`, an explicit reload RPC) but the shape is identical
everywhere.

**Distributed propagation across surfaces (CLI, TUI, Desktop, messaging gateway) is pull, not
push**, for anything catalog/capability-shaped: every surface independently re-queries the same
underlying source of truth (the local filesystem/config state) rather than one surface pushing a
"something changed" event to the others. Live conversational events (streamed tokens, tool-call
progress) *are* pushed, over the JSON-RPC channel — the distinction is: turn-scoped events push,
catalog-scoped state pulls.

## Key design decisions and trade-offs

- **Treating cache-prefix stability as sacred, and building every other feature's reload behavior
  around not violating it**, is the single most load-bearing architectural decision in this whole
  area. It trades "instant feedback after every change" for materially lower per-turn cost across
  every conversation, indefinitely — a good trade for almost any production LLM deployment.
- **No live filesystem watcher for extensions is a deliberate simplicity choice**, not an oversight
  — a watcher would need to coordinate with the cache-stability invariant anyway (a detected change
  still can't be applied mid-conversation), so the marginal value of "changes appear a few seconds
  faster" doesn't justify the added complexity of running and debugging a watcher process.
- **Pull-based cross-surface sync** avoids needing any kind of pub/sub or shared event bus purely
  for catalog freshness — every surface just asks the same local source of truth again. This only
  works because that source of truth is cheap to query (a directory scan or a config read); it
  would not work if catalog state were expensive to fetch on every query.

## Failure modes and guards

- A user who installs something and doesn't pass the "apply now" flag, then wonders why it's not
  showing up, is a real, accepted UX cost of this design — mitigated by consistent messaging
  ("takes effect next session, or pass `--now`") rather than eliminated.
- Context compression is the **one** sanctioned exception to "never touch the cached prompt
  mid-conversation" — because it rewrites conversation history for a different reason entirely
  (staying under a context-length limit), and as a side effect it's allowed to also refresh the
  system prompt in the same moment, rather than requiring two separate cache breaks.

## Verdict: ADOPT

The cache-stability-as-sacred-invariant principle, the deferred-by-default-with-explicit-escape-
hatch pattern, and pull-based cross-surface catalog sync are all strong and portable, provided your
own backend also benefits from provider-side prompt caching (increasingly the default across major
LLM providers).

## Server-side translation

- The invariant applies **per conversation**, which in a multi-tenant server means **per session
  row**, same as Hermes — this doesn't change shape at scale, it just means you're managing many
  more independent cached prefixes concurrently. Make sure your session/conversation storage model
  supports "the system prompt for this specific session was built once and is being reused,"
  exactly like Hermes's content-addressed prompt table.
- Pull-based sync remains fine at server scale as long as the underlying catalog read stays cheap
  (an indexed DB query, not a network re-crawl) — this is one more reason pattern 1's "own DB table,
  not a live per-request crawl" recommendation matters.
- Consider whether a lightweight **push notification for capability changes** (e.g. a workspace
  admin disables a plugin org-wide) is worth adding on top of pull-based sync in a multi-user
  setting, where "another user changed something that affects my session" is a real scenario Hermes
  never has to handle (a single local user never has someone else changing their own extensions out
  from under them mid-conversation).
