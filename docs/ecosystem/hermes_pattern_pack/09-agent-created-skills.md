# Pattern 9 — Agent-created skills (the model writes its own extensions)

## Problem

If the model itself can create/edit extensions (turning a successful workflow into a reusable
skill), you need write guards that are at least as careful as the install pipeline — arguably more,
since the "publisher" here is the model acting inside a live conversation, not a reviewed catalog
entry.

## How Hermes does it

A single tool (`skill_manage`) exposes a small closed set of actions per call, batchable:

```
skill_manage({operations: [
  {action: "create", name, content, category},
  {action: "patch", name, target_content, replacement_content},   # targeted find/replace
  {action: "write_file" | "remove_file", name, path, content?},   # sub-files only
  {action: "delete", name}
]})
```

**Guards applied before any write actually lands:**
- Path/symlink escape checks (can't write or delete outside the skill's own directory).
- A pinned-name protection list that even `delete` cannot touch.
- A ledger snapshot **before** the mutation (content hash of every file about to change) so any
  write is provably reversible.
- Batch semantics: up to a fixed cap of operations per call, a "clobber guard" rejecting two
  destructive operations on the same file in one batch, and `delete` must be the sole operation in
  its batch (its semantics don't compose with an all-or-nothing rollback the way file edits do).

**Write-approval staging (opt-in, config-gated)**: when enabled, a skill write is never applied
inline — it's always written to a pending-review file and requires a separate explicit approval
step before it takes effect, with the reasoning stated plainly in the code: skill content is too
large to review as an inline yes/no prompt the way a single shell command is.

**Provenance labeling**: a created skill is tagged (in the same JSON sidecar as install provenance,
not the skill's own frontmatter) with who effectively authored it — a background
autonomous-maintenance pass gets a different tag than a normal foreground "please turn this into a
skill" request, so a later audit can distinguish "the user asked for this, live" from "the system
did this on its own during idle maintenance."

**The curator** — a separate, lower-privilege background process that can archive/consolidate/prune
skills over time based on usage, explicitly forbidden from touching pinned, catalog-installed, or
bundled skills, required to cite evidence (`absorbed_into` on any deletion), and required to
re-read a skill's current content immediately before writing to it (preventing a stale-read/write
race against a human's concurrent edit).

**Rollback**: every mutation's before/after content hashes live in an append-only ledger backed by
a content-addressed blob store — restoring a prior version is a lookup, not a recovery procedure.

## Key design decisions and trade-offs

- **A closed action set with per-action schemas**, rather than a generic "write this file"
  primitive, bounds what the model can even attempt — it can create/patch/delete a skill, not touch
  arbitrary paths.
- **Staging + explicit approval for large writes**, as opposed to Hermes's usual inline
  approve/deny for small dangerous actions (pattern in the wider approval system), is a deliberate
  UX admission that a human cannot meaningfully review a large diff inline in the middle of a chat.
- **Giving the autonomous curator strictly less authority than a foreground user request** (can't
  touch pinned/bundled/catalog items, must cite evidence, must re-read-before-write) treats
  "the model acting on its own initiative" as inherently higher-risk than "the model acting on an
  explicit request in the current turn," even though it's the same underlying tool.

## Failure modes and guards

- Two concurrent writers (a live conversation and a background curator pass) racing on the same
  skill file are guarded by per-skill file locks plus the curator's read-before-write requirement.
- A batch containing a `delete` alongside other operations is rejected outright rather than
  partially applied — avoids an ambiguous "some of the batch succeeded, the delete didn't" state.
- Content-hash-based rollback degrades gracefully if a referenced blob is missing (fails closed,
  doesn't silently restore a wrong/empty version).

## Verdict: ADOPT

The closed-action-set tool design, pre-mutation ledger snapshots for rollback, and the
staged-approval-for-large-writes pattern are all strong and transfer directly. The
lower-authority-for-autonomous-vs-requested distinction is a genuinely good idea worth generalizing
beyond skills to any "the agent can act on its own initiative" feature.

## Server-side translation

- The ledger becomes a real **versioned table** (one row per mutation, before/after content hashes
  pointing at your object store) rather than a JSON-lines file plus a local blob cache — same
  guarantee, standard multi-tenant storage.
- **Write-approval staging maps directly onto a real review/approval workflow** in a multi-user
  product — e.g., a skill an AI agent drafts inside a shared workspace could require a human
  workspace member's sign-off before it's promoted from "draft" to "active," which is a natural fit
  for a UI with real user accounts (something a single-user desktop app can only approximate with a
  local pending-file).
- **Per-tenant/per-workspace scoping of what an agent-created skill can affect** needs to be
  explicit: an agent acting inside tenant A's workspace must be structurally unable to create,
  patch, or delete anything outside that tenant's own extension rows — the local
  path/symlink-escape guard's server-side equivalent is a tenant-scoped row-level check, not a
  filesystem boundary.
- Keep the "autonomous background maintenance has less authority than an explicit in-session
  request" distinction — and enforce it the same way (a different, more restricted credential/scope
  for the background job than for a live user-initiated agent turn).
