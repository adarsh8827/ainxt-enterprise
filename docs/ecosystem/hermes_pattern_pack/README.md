# Hermes Pattern Pack

Architecture-level extraction of how Hermes Agent (Nous Research) builds its Skills/Plugins/MCP/
Connectors marketplace and multi-surface (CLI, TUI, Desktop, web dashboard, messaging-gateway)
architecture — written for a team building an equivalent **multi-user, self-hosted** platform
(ainxt) with its own marketplace consumed by web Chat, an Agent Studio, and Cowork, who will not
copy Hermes code.

No Hermes source code is reproduced anywhere in this pack — only schemas, flow steps, decision
tables, and short pseudocode. Every claim in the individual pattern files is cited to a Hermes file
path/function name (see `HERMES_ARCHITECTURE_REPORT.md` in the repo root for the full citation
trail this pack was distilled from); anything not directly verified in code is marked INFERRED at
its point of use.

Read time: roughly an hour for all 14 files plus this index.

## How to read this pack

Each numbered file covers one pattern with the same five sections: **Problem**, **How Hermes does
it**, **Key design decisions and trade-offs**, **Failure modes and guards**, **Verdict**, and
**Server-side translation**. Read them in order if you want the full architecture story (1–5 build
the marketplace, 6–10 cover storage/scoping/chat/UI, 11–14 cover the runtime/security substrate);
jump to any single file if you only need one piece.

| # | Pattern | Verdict | One-line server-side translation |
|---|---|---|---|
| 01 | Catalog sources per item type | ADOPT (curated-PR model) | Replace live per-query crawling with a backend ingestion job writing to your own DB table |
| 02 | CI pipelines (build + validate + freshness) | ADOPT | Same tiered structural→pin-proof→freshness-watchdog shape, targeting your own DB/API instead of static files |
| 03 | Package formats (SKILL.md, plugin.yaml, MCP manifest, connector wire schema) | ADOPT | Store as validated JSON/JSONB; add a license field everywhere from day one |
| 04 | Install pipelines (quarantine → scan → policy → activate) | ADOPT | Staging row/bucket with `status: pending_scan` in place of a local quarantine dir |
| 05 | Security scanning, trust tiers, policy matrix | ADOPT | Same trust×verdict decision table; isolate plugin dependency resolution per tenant, not shared |
| 06 | Storage model (no DB for extensions) | ADOPT principle, AVOID literal model | Give extensions real per-tenant DB rows; keep content in object storage, not local files |
| 07 | Installed vs. enabled, scoping | ADOPT | Profile → tenant/workspace; keep total isolation, no implicit config inheritance |
| 08 | Chat integration (progressive disclosure) | ADOPT | Index-then-fetch is even more important at multi-tenant scale for context-budget reasons |
| 09 | Agent-created skills (`skill_manage`) | ADOPT | Ledger → a real versioned table; staged approval → a real reviewer workflow |
| 10 | Desktop UI screen inventory | ADAPT | Own your catalog UI natively with typed API results; don't iframe a doc site or scrape subprocess stderr |
| 11 | Unified tool registry | ADOPT | Same registry design; overlay by tenant instead of by profile |
| 12 | MCP server lifecycle | ADOPT | Same circuit-breaker/backoff/trust-gating; decide explicit per-tenant vs. shared server pooling |
| 13 | Change propagation and caching | ADOPT | Cache-prefix stability matters even more under provider-side caching at scale |
| 14 | Secret scoping and redaction | ADOPT (scoping/redaction); ADAPT (storage) | Keep context-scoping; replace plaintext-per-credential-type storage with a real per-tenant secrets manager, and prefer delegating third-party OAuth tokens to a broker service over holding them yourself |

## Top 10 decisions to carry over

1. **Separate "browse" from "install" completely** — browsing a catalog should never require
   trusting or executing anything; only install does (patterns 1, 4).
2. **Trust tier (who published it) and scan verdict (what it contains) are two independent axes**,
   combined through a small explicit policy table — never conflate source reputation with content
   inspection (pattern 5).
3. **One hard floor even a "force" flag cannot cross** — a dangerous verdict from a low-trust source
   should never be installable, full stop (pattern 5).
4. **Progressive disclosure for anything catalog-shaped in an LLM context window**: an index (name +
   one-line description) in the always-sent context, full content fetched on demand via a tool call
   (pattern 8).
5. **Protect prompt-cache-prefix stability as a hard invariant**, and make every reload/change
   mechanism deferred-by-default with an explicit "apply now" escape hatch (pattern 13).
6. **Never mutate a shared/global environment (or process-wide state) to scope a secret or a
   capability to "the current identity"** — use request/session-scoped context, always (patterns 7,
   11, 14).
7. **One dedicated, audited function builds every child-process environment**, actively stripping
   foreign credentials rather than trusting call sites to build a clean env each time (pattern 14).
8. **A single unified tool registry, with plugin/MCP/connector tools indistinguishable from
   built-ins to the model**, backed by a strict, registration-time collision policy (pattern 11).
9. **Pin exact commit SHAs for anything that runs code from a third-party repo**, verify the pin
   actually resolves at review time (not just at parse time), and gate self-updating code
   specifically (pattern 2).
10. **Give autonomous/background agent actions strictly less authority than an explicit, in-session
    user-directed request** — same underlying tool, different privilege ceiling depending on who's
    asking (pattern 9).

## Top risks Hermes guards against

- **A malicious or careless third-party skill/plugin/MCP server compromising the user's machine or
  data** — guarded by quarantine + scan + trust tiers + a non-overridable floor (patterns 4, 5).
- **A catalog entry silently changing after review** (supply-chain drift) — guarded by mandatory
  commit-SHA pinning, verified at CI merge time, plus a self-updater detector (pattern 2).
- **Cross-identity secret/credential leakage in a process serving multiple identities** — guarded by
  context-scoped secret resolution and a single audited subprocess-env builder (pattern 14).
- **Holding a live third-party OAuth token that a compromised local machine could steal** — sidestepped
  entirely for hosted connectors by never storing that token locally at all (a broker holds it, the
  local machine only gets a scoped access token to the broker); for directly-configured OAuth MCP
  servers where a local token is unavoidable, mitigated by strict file permissions, atomic writes,
  and binding a refresh token to the specific issuer that granted it (pattern 14).
- **Runaway cost from prompt-cache invalidation** — guarded by treating the system prompt as
  byte-stable by default, with all reload paths deferred unless explicitly forced (pattern 13).
- **A hung or crashing plugin/MCP server taking down the whole agent** — guarded by load timeouts,
  per-hook exception isolation, and a circuit-breaker/backoff state machine (patterns 5 [plugin
  isolation], 12).
- **An install silently overwriting a user's own local customizations** — guarded by content-hash
  drift detection that skips (doesn't clobber) locally-edited items by default (pattern 4).
- **A background/autonomous process overreaching** (deleting or rewriting something it shouldn't) —
  guarded by a strictly lower-authority guard set for autonomous actions vs. explicit requests
  (pattern 9).

## Catalog source / browse / install / list / add-entry, all four item types side by side

| | Skills | Plugins | MCP servers | Connectors |
|---|---|---|---|---|
| **Catalog source** | Live-crawled aggregate of 5+ external marketplaces, republished as one JSON | `plugin-catalog/*.yaml` pointer files, in-repo | `optional-mcps/*/manifest.yaml`, in-repo | Nous Portal hosted API, *or* the plugin/MCP catalog shown as connector cards, *or* nothing (messaging-gateway adapters are `.env`-configured directly) |
| **Browsing needs network?** | Yes, every time (TTL-cached, stale-fallback) | No for the checked-out catalog; a live mirror is also fetched opportunistically | No — purely local files | Yes for hosted; no for local/plugin-adapter cards |
| **Install fetches from** | Wherever the matched source says (GitHub, skills.sh CDN, etc.) | The pinned commit SHA on the linked external repo | The manifest's pinned git ref, or a direct command/URL | Hosted: the Portal's own OAuth flow. Local/plugin: the underlying plugin/MCP install pipeline |
| **"List installed" reads** | A local lock file + a directory scan — never the catalog | Local plugin directories + config | The `mcp_servers` config block | Hosted accounts: a live Portal API call (not stored locally). Local: config/lock state |
| **How an entry gets added to the catalog** | An automated crawl picks it up from wherever it's publicly listed — no review gate | A human-reviewed pull request, pinned SHA verified by CI (clone + checkout) | Same PR-review + CI process as plugins | Hosted: added on Portal's side, out of this codebase's scope. Local/plugin-backed: same as plugins/MCP above |

---

*Source: distilled from a full architecture reverse-engineering pass over the `hermes-agent`
checkout, cross-referenced against `HERMES_ARCHITECTURE_REPORT.md` in the same repo. Every specific
claim traces to a file path/function name in that report or in this pack's individual pattern
files; nothing here was copied from Hermes source.*
