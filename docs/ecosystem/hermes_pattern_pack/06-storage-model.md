# Pattern 6 — Storage model: no DB for extensions, one DB for conversations

## Problem

Where does extension state (what's installed, its config, its provenance) live, versus where does
conversation state live — and should they share a database at all?

## How Hermes does it

They are **completely separate storage systems**, and the split is total, not partial:

- **`state.db`** (one SQLite file, WAL mode + FTS5) holds *only* conversation-shaped state:
  sessions, messages, per-model usage/billing, turn leases, async delegation bookkeeping, and a
  content-addressed system-prompt cache. There is no `skills`, `plugins`, `mcp_servers`, or
  `connectors` table anywhere in this schema.
- **Skills** live as real files on disk (`skills/<name>/SKILL.md`), with a small flat **JSON**
  sidecar (`lock.json`) for provenance metadata (source, trust tier, verdict, content hash,
  timestamps) — never SQL rows.
- **Plugins** live as real Python packages on disk; their enabled/disabled state and any per-plugin
  settings live in `config.yaml`, not a database.
- **MCP servers** are entirely config-defined — a block in `config.yaml`; there is no separate store
  at all beyond that config plus a small on-disk cache of each server's discovered tool schema (so a
  lazy server doesn't need to be spawned just to know what tools it has). **One real exception**: an
  MCP server that uses its own OAuth (e.g. a vendor-hosted remote server like Atlassian's) does get a
  genuine per-server on-disk store — three small JSON files (tokens, dynamically-registered client
  info, server metadata) under one directory, keyed by server name. Full detail in pattern 14.
- **Connectors** split further: messaging-gateway platform credentials live in `.env`; Nous Portal
  connector *accounts* (which OAuth connections exist) are **not stored locally at all** — they live
  on the Portal's own hosted backend, fetched live via an authenticated API call each time the UI
  needs them. A third model exists for a *directly*-OAuth'd MCP server (not brokered through Portal)
  — see pattern 14 for why this is a materially different trust model than either of the other two.

The unifying idea: **the database is reserved for things that change every turn** (messages,
token counts, turn state) — genuinely relational, high-write-frequency data. **Everything about
"what extensions exist" is either a file (cheap, versionable, diffable, works with `git`/backup
tools out of the box) or, for connector accounts, deliberately not-local at all** (single source of
truth lives with whoever owns the OAuth relationship).

## Key design decisions and trade-offs

- **Files-not-rows for skills means the filesystem is the source of truth**; the JSON lock file is
  metadata *about* that truth, not the truth itself — you can always recover from "what files
  actually exist on disk," even if the lock file is corrupted or stale.
- **No cross-extension-type join is possible** in this model (you can't SQL-query "give me every
  skill that depends on plugin X") — an accepted trade-off for a single-user tool where that kind of
  query is rare and a full directory/config scan is cheap enough.
- **Not storing connector accounts locally at all** removes an entire class of local-secret-leak
  risk for that one item type, at the cost of an unconditional network dependency for even listing
  what's connected.

## Failure modes and guards

- A lock-file/filesystem mismatch (e.g. `lock.json` says installed, folder was manually deleted) is
  detected by an explicit `_find_all_skills()`-style directory scan cross-referenced against the
  lock file — the folder scan wins as ground truth.
- Because MCP server state is just config, there's no "MCP is out of sync with its config" failure
  mode possible by construction — the running connection is always derived fresh from the config at
  connect time.

## Verdict: ADOPT (with a real caveat for scale)

The "files for extensions, DB only for conversation-shaped data" split is a clean, low-complexity
design that's genuinely appropriate for a single local user. It does **not** scale as-is to a
multi-tenant server, and this is the pattern most in need of deliberate re-architecture rather than
direct adoption.

## Server-side translation

- **Extension state (installed items, provenance, config) needs real per-tenant rows in your
  database** — "files on a shared server's disk, one lock.json per tenant" doesn't give you
  queryability, doesn't survive horizontal scaling across replicas, and doesn't give you an audit
  trail comparable to a real table with row versioning.
- Recommended shape: an `installed_extensions` table keyed by `(tenant_id, extension_type,
  extension_id)` carrying exactly the fields Hermes's lock file already has (source, pinned
  identifier, trust tier, verdict, content hash, installed_at/updated_at) — same schema, different
  substrate.
- **The actual extension *content*** (a skill's markdown, a plugin's code) still doesn't belong in
  your primary relational DB — put it in object storage (S3-shaped), with the DB row pointing at it
  by content hash, mirroring Hermes's own hash-addressed approach just backed by blob storage
  instead of a local folder.
- **Keep connector accounts out of your own DB if you can** — proxy through the OAuth provider (or
  your own connector-broker service) the same way Hermes defers to Nous Portal, rather than storing
  refresh tokens directly in your primary application database; if you must store them, isolate
  them in a dedicated secrets store, not a general-purpose table.
