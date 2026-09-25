# Pattern 1 — Catalog sources per item type

## Problem

A marketplace needs to answer "what's available?" for four different kinds of extensions, each
sourced differently, without forcing every browse action to be as expensive/risky as an install.

## How Hermes does it

Four item types, four different catalog strategies — this is the most important thing to copy
correctly, because Hermes deliberately does **not** use one mechanism for all four:

| Type | Catalog source | Governance | Browsing needs network? |
|---|---|---|---|
| Skills | Live-crawled aggregate: GitHub taps, skills.sh, ClawHub, LobeHub, browse.sh, a `.well-known` protocol, direct URL | Automated crawl, no human review of individual entries | Yes, every time (TTL-cached) |
| Plugins | `plugin-catalog/*.yaml`, one pointer file per entry (`repo`, pinned `sha`, `tier`) | Human PR review, CI-validated | No — files are local; a *live* copy is also fetched opportunistically (see below) |
| MCP servers | `optional-mcps/*/manifest.yaml`, curated | Human PR review | No — files are local |
| Connectors | (a) Nous Portal hosted catalog API, (b) plugin/MCP catalog entries shown as "connector" cards, (c) messaging-gateway platform adapters (no catalog at all — `.env` tokens) | Mixed | (a) yes, account-gated; (b)/(c) no |

**Skills — source router, priority order** (`tools/skills_hub_search.py::create_source_router`):

```
sources = [OfficialBundled, HermesIndex, SkillsSh, WellKnown, DirectUrl,
           GitHub(taps), ClawHub, LobeHub, BrowseSh]
for source in sources (in parallel, per query):
    results += source.search(query)
dedupe_by_trust(results)   # a name that exists in two sources keeps the higher-trust one
```

The `HermesIndex` entry is itself a **build artifact**, not a live per-query crawl: a scheduled job
(pattern 2) periodically re-crawls every source and republishes one aggregate JSON file, which the
client fetches instead of hitting GitHub/ClawHub/etc. on every keystroke. Direct API sources
(`GitHub`, `SkillsSh`, `ClawHub`, `WellKnown`) are *skipped* when the index already answered
non-empty, and consulted only as a fallback on an index miss — protecting an unauthenticated user's
hourly GitHub rate limit.

**Plugins/MCP — no live crawl, just checked-in pointer files**, reviewed one at a time via PR. A
plugin catalog entry doesn't contain the plugin's code — only enough to resolve and pin it:

```yaml
name: my-plugin
repo: https://github.com/someone/my-plugin
sha: <40-hex-char pinned commit>
tier: community | official
category: platform | tools | ...
```

Plugins additionally maintain a **live mirror** of that same file set
(`hermes_cli.plugin_catalog.LIVE_CATALOG_URL`), published as a side effect of the docs-site deploy,
so an already-installed client sees new entries without waiting for a new Hermes release. Merge
rule when local and live disagree on a pin: **whichever source is more recent wins** — compare the
local checkout's git-commit-time against the live doc's `generated_at`, falling back to semver,
falling back to "live wins" (a packaged release's in-tree copy is presumed frozen/stale).

## Key design decisions and trade-offs

- **Browsing is cheap and non-authoritative; installing is the only gate.** You can show a user
  100,000 skills without having vetted any of them, because nothing downloads until they click
  Install.
- **Curated vs. crawled is a deliberate split**, not an oversight: plugins/MCP run arbitrary code on
  the user's machine, so Hermes requires a human-reviewed PR per entry; skills are inert markdown,
  so Hermes accepts an automated crawl of much lower-trust sources and pushes trust-tiering to
  install time instead of catalog time.
- **A live-catalog-over-local-checkout mirror** lets already-installed users see new entries between
  releases without a forced auto-update — but it means "what the user sees" can legitimately differ
  from "what's in the git checkout at HEAD," which is exactly the discrepancy a user will notice and
  ask about.

## Failure modes and guards

- Network failure on the aggregate index → serve the stale cache regardless of age rather than an
  empty catalog.
- A single upstream source going empty (e.g. ClawHub API breaking) silently degrades browse results
  — mitigated only by a separate CI freshness watchdog (pattern 2), not at request time.
- Live-vs-local merge ambiguity is resolved by a heuristic (commit time vs. `generated_at`), which
  can be wrong in edge cases (e.g. a shallow/rebased checkout with distorted commit timestamps).

## Verdict: ADOPT (with one AVOID)

ADOPT the curated-PR-pointer model for anything that runs code (plugins, MCP). ADOPT the
"browse ≠ install, browse can be loose/cheap" separation universally. **AVOID** literally
live-crawling third-party sites per-query in a multi-tenant server — that's fine for a
single-user desktop app hitting rate limits on its own account, but a shared backend serving many
users must not multiply those crawl/rate-limit costs per tenant.

## Server-side translation

- Replace the live per-source crawl with **one backend ingestion job** (cron/worker) that crawls
  external skill sources on a schedule and writes results into your own database table — the same
  shape as Hermes's `build_skills_index.py`, just landing in Postgres instead of a static JSON file.
  Serve browse/search from that table via your own API, not by re-hitting GitHub/ClawHub per
  request.
- Keep the plugin/MCP catalog as **human-reviewed rows in your own DB** (repo + pinned commit +
  tier + category), populated via your own review workflow (PR-equivalent: an admin approval queue)
  instead of a YAML file per entry — same governance model, different storage.
- For connectors, decide up front whether you're building (a) a hosted OAuth broker like Nous
  Portal (needed for true multi-tenant "each user connects their own Gmail" flows) or (b) simple
  per-tenant credential storage behind your own connector adapters. Don't conflate the two the way
  Hermes's "Connectors tab" does (three different backends behind one UI) unless you have a good
  reason — it adds real complexity for marginal UI simplicity.
