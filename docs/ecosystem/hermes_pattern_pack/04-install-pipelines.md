# Pattern 4 — Install pipelines

## Problem

Turning a catalog entry into something actually usable requires a safe, auditable sequence:
fetch untrusted content, inspect it, decide whether to trust it, and only then let it touch the
real system — while still allowing rollback and detecting drift from what was originally
installed.

## How Hermes does it (skills — the fullest example; plugins/MCP follow the same shape minus the
content-quarantine step, since they install via a pinned git ref rather than an arbitrary bundle)

```
resolve(identifier)                    # which catalog source answered, what's the canonical id
  -> fetch(source, identifier)         # download into memory as a bundle, not to disk yet
  -> validate_paths(bundle)            # reject absolute paths, "..", symlinks, drive letters
  -> write_to_quarantine(bundle)       # staging dir, NOT the real install location
  -> verdict = scan(quarantine_path)   # safe | caution | dangerous
  -> allowed = policy(trust_tier, verdict, force_flag)
  -> if not allowed: log("BLOCKED"), delete quarantine copy, stop
  -> confirm_with_user() unless force/skip_confirm
  -> move(quarantine_path -> real_install_path)   # atomic on the same filesystem
  -> record_provenance(lock_file, source, hash, verdict, trust_tier, timestamp)
```

**`lock.json` schema** (one entry per installed item):
```json
{
  "installed": {
    "<name>": {
      "source": "github", "identifier": "owner/repo/path",
      "trust_level": "community", "scan_verdict": "safe",
      "content_hash": "<sha256-16hex>", "install_path": "...",
      "installed_at": "...", "updated_at": "..."
    }
  }
}
```

**Audit log** — one append-only line per action: `<timestamp> <INSTALL|UNINSTALL|BLOCKED> <name>
<source>:<trust_level> <verdict> [extra]`.

**Update / drift detection**: on `check`/`update`, recompute the content hash of the currently
installed copy and compare to the lock file's recorded hash *before* touching anything — if they
differ, the user edited it locally, and the update is **skipped by default** (not overwritten)
unless forced. Upstream-change detection tries a cheap "current revision" probe first (e.g. a
repo's latest commit SHA) before falling back to a full content-hash comparison, to avoid
re-downloading everything just to check for updates.

**Plugins/MCP** skip content-quarantine (there's no arbitrary bundle — the "fetch" step is a
`git checkout` at a pinned commit that was already proven to exist during catalog CI, per
pattern 2) but keep the same trust/provenance/lock-file shape.

## Key design decisions and trade-offs

- **Quarantine-then-scan-then-move, never scan-in-place.** Scanning a bundle sitting in its final
  location risks a race where the model or another process reads it mid-scan; a dedicated staging
  directory makes "not yet approved" a filesystem-visible state.
- **Path validation happens before any file write**, not after — untrusted archive contents can
  contain `../../etc/passwd`-shaped paths, and the fix has to happen at the "what am I about to
  write" step, not as cleanup afterward.
- **Local edits are a first-class signal, not an error condition.** Treating "the installed copy no
  longer matches what we recorded" as "the user customized this on purpose" (skip, don't clobber)
  is the correct default for a single-user tool; a multi-tenant version needs an explicit policy
  decision here (see translation below).
- **`--force` has a hard ceiling.** Even the override flag cannot install something the scanner
  called dangerous from a community/untrusted source — this specific carve-out (`--force` cannot
  override a `dangerous` verdict at low trust) is the one place Hermes refuses to let the user shoot
  themselves in the foot.

## Failure modes and guards

- A crash mid-install between "moved to real location" and "wrote the lock entry" would leave an
  active-but-unrecorded item — mitigated by doing the lock-file write immediately after the move,
  same function, no intervening I/O.
- A scan that itself crashes fails closed in the install path (treated as "could not verify," not
  "assume safe").
- Re-installing over an existing entry requires an explicit force flag — protects against a
  silent, unintended overwrite from a routine "let me try that again" retry.

## Verdict: ADOPT

The whole pipeline shape — quarantine → scan → trust×verdict policy → confirm → atomic move →
provenance record — is directly portable and doesn't assume single-user anything except the "skip
local edits" default (which needs adaptation, see below).

## Server-side translation

- **No local filesystem quarantine — use a staging table/object-storage prefix.** Fetch into a
  private bucket/row with `status: pending_scan`, run the scanner as a backend job, and only flip
  `status: active` (making it visible/servable to that tenant) after policy passes. This is the
  direct server-side equivalent of "quarantine dir, then move."
- **Content hash + lock-file record → a versioned row per (tenant, item) install**, with the same
  fields (source, pinned identifier, trust tier, verdict, hash, timestamps) — this is your audit
  trail and your update-diffing mechanism, unchanged in shape.
- **"Skip update if locally edited" needs a real per-tenant policy**, because "local edit" now means
  "this specific user customized their copy" — decide explicitly whether per-tenant customization
  of a marketplace item is supported at all; if yes, keep Hermes's default (never silently
  overwrite); if no, simplify by disallowing edits to installed-from-catalog items entirely.
- **Audit log → a real audit table**, queryable per tenant/per admin, not an append-only text file —
  same content, better queryability at scale.
