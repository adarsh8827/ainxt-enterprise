# Pattern 8 — Chat integration: how extensions actually reach the model

## Problem

Once something is installed, how does it get in front of the model without either (a) bloating
every single request with content that's rarely needed, or (b) requiring a system restart every
time something changes?

## How Hermes does it

**Progressive disclosure, not full injection.** The default assumption — dump every installed
skill's full content into the system prompt — is explicitly rejected. Instead:

```
system_prompt += for each visible skill: "- {name}: {one_line_description}"   # index only
# model decides a skill is relevant, then:
model calls: skill_view(name)          # a tool call, not prompt content
tool result = full SKILL.md content    # returned into the conversation, not the system prompt
```

Visibility in that index is filtered by the conditional-activation fields from pattern 3
(`requires_toolsets`, `platforms`, etc.) — but note the asymmetry: those conditions only control
whether a skill is *advertised*; an explicit `skill_view(name)` call can still load a skill whose
conditions aren't currently met (the OS-level `platforms:` gate is the one exception — that's
enforced everywhere, including on-demand loading, not just the index).

**Direct invocation bypasses the tool call entirely**: typing `/skill-name` injects the skill's full
content as a **regular user message** (not a system-prompt mutation, not a tool result) — this
matters because mutating the system prompt mid-conversation would invalidate prompt caching, while
appending a new user message is the conversation's normal, expected shape.

**Slash-command discovery is a pure scan, always answered fresh**: every installed skill's `name`
becomes a `/name` command by scanning the skills directories; the same scan (plus config for
built-ins) backs "what commands exist" for autocomplete. There is no separate registration step —
a file existing in the right place *is* the registration.

**Plugin tools, MCP tools, and connector actions are indistinguishable to the model** once
registered — they all land in the same tool-call schema via one shared registry (full detail in
pattern 11); the model has no idea whether a given tool is a built-in, a plugin's, or a remote MCP
server's.

**Reload commands and their actual scope**:

| Command | What it rebuilds | Prompt cache touched? |
|---|---|---|
| `--now` flag on install | The system-prompt skills index | Yes — one deliberate invalidation |
| `/reload-skills` | The slash-command map only | No |
| `/reset` (new session) | Everything, fresh | N/A — it's a new prompt entirely |
| (no flag) | Nothing until next new session | No |

## Key design decisions and trade-offs

- **Index-then-load-on-demand is the single most important pattern for keeping a marketplace with
  thousands of items usable inside a token-budgeted context window.** It generalizes directly:
  any "catalog of instructions/capabilities" problem in an LLM system should default to summary +
  on-demand fetch, never full inclusion.
- **Two different invocation shapes (tool call vs. injected user message) for the same underlying
  content** exist because they serve different intents: model-initiated relevance discovery
  (tool call, cacheable prefix) vs. user-initiated explicit invocation (a fresh message, since the
  user is actively asking for this exact behavior right now).
- **Deferred-by-default reload is a deliberate cost trade** — it protects an expensive, load-bearing
  cache at the price of "just installed, why doesn't it show up yet" confusion, mitigated by making
  the escape hatch (`--now`, `/reset`) simple and consistently named across every extension type.

## Failure modes and guards

- A skill that's disabled is blocked even from explicit `skill_view()` calls — disable is a hard
  gate, not just an advertising filter, closing the obvious loophole ("just call it directly since
  it's not in the index anyway").
- A model could in principle over-fetch full skill bodies across many tool calls in one turn and
  blow its own context — this isn't specially guarded against; it's the same budget pressure any
  tool result applies, mitigated only by good skill authoring (short, focused documents).

## Verdict: ADOPT

Progressive disclosure via index + on-demand tool, the tool-call/injected-message split by intent,
and pure-scan-based slash discovery are all strong, directly portable patterns for any
multi-extension chat surface.

## Server-side translation

- The index-then-fetch pattern is even more important server-side, since you're now paying that
  context-budget cost **per active conversation across potentially many tenants simultaneously** —
  keep the index tiny and cacheable per-tenant.
- **Prompt-cache-safety concerns translate directly** if your backend uses any form of provider-side
  prompt caching (as most production LLM deployments now do) — treat "don't mutate the cached
  prefix mid-conversation" as a hard constraint in your own turn loop, with the same
  deferred-reload-plus-explicit-escape-hatch pattern.
- Slash-command / capability discovery should be a **per-tenant, per-session query against your own
  extensions table** (pattern 6/7), not a filesystem scan — same logical shape (always answer fresh
  from source-of-truth, no separate stale registry to keep in sync), different substrate.
- Decide explicitly whether "invoke via /command" should inject a user-role message (Hermes's
  choice, works well with strict role-alternation constraints many providers enforce) or a
  tool-result-shaped message — match whatever your own provider's caching/role rules require.
