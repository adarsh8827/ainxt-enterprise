# Pattern 2 — CI pipelines that build and guard the catalogs

## Problem

A marketplace's catalog needs to be (a) kept fresh, (b) protected from bad/malicious pointer
entries, and (c) published somewhere clients can cheaply fetch it — all without a human manually
re-crawling anything.

## How Hermes does it

**Skills index build** (`scripts/build_skills_index.py` + `.github/workflows/skills-index.yml`):
runs on a schedule (twice daily, 6am/6pm UTC) plus on-demand, crawls every skill source
(skills.sh, GitHub taps, official, ClawHub, LobeHub) with a GitHub App token, writes one JSON file
(`website/static/api/skills-index.json`), and triggers a docs-site redeploy so the new file goes
live. A **separate freshness watchdog** (`skills-index-freshness.yml`) runs every 4 hours,
independently `curl`s the *live* published URL (not the build job's own output) and checks:

```
if index.generated_at older than 26h: FAIL
for each source in [skills.sh:100, lobehub:100, clawhub:50, official:50, github:30, browse-sh:50]:
    if source.count < floor: FAIL   # "a whole marketplace silently returned empty"
if index.total < 1500: FAIL
on FAIL: open/update a GitHub issue tagged [skills-index-watchdog]
```

This two-job split (builder + independent watchdog hitting the *public* URL) catches failures the
builder itself can't see — e.g. a successful build that never actually got deployed.

**Plugin catalog validation** (`scripts/validate_plugin_catalog.py` +
`.github/workflows/plugin-catalog-ci.yml`, triggered only on PRs touching `plugin-catalog/**`):
two jobs, escalating in cost:

1. **Structural** (fast, whole-directory, every PR): required keys present
   (`name, repo, sha, description, maintainer`), `name` matches `^[a-z0-9_-]{1,64}$`, `sha` is
   exactly 40 lowercase hex chars, `tier`/`category`/`platforms` are from fixed enums, `repo` must
   be `https://`, image/screenshot URLs restricted to GitHub's own CDN hosts. Unknown top-level
   keys are a **warning, not an error** (forward-compat: newer catalogs stay valid under older
   validators).
2. **Pinned-source validation** (slow, ~30 min, only changed/added entries): actually clones the
   linked repo, `git checkout --detach <sha>` to prove the pin is real (fails if unreachable),
   confirms a manifest file exists at the declared path, then runs the real plugin
   validator/loader against the cloned code at that exact commit. A **self-updater gate**
   specifically greps for "fetches from GitHub" + "writes/renames its own files" appearing
   together in the same plugin — either alone is fine, both together fails the PR, because that
   combination is exactly how a catalog entry could quietly bypass the pinned-commit model after
   merge.

**Kill list enforcement is live, not just a docs-build concern**: every plugin install checks the
identifier and repo URL (normalized) against a `removed.yaml`-backed list before proceeding, unless
the caller explicitly passes an override flag — and even the override is logged into the install
record, never silent.

## Key design decisions and trade-offs

- **Validate structure on every PR, but only deep-verify (clone + checkout + run) the *changed*
  entries.** Re-cloning and re-running all ~300 entries on every PR would make the catalog
  effectively unmaintainable; scoping the expensive job to the diff keeps review time bounded
  regardless of catalog size.
- **A pin's existence is checked once, at merge time — not re-checked at install time.** This is a
  trust boundary decision: once a human-reviewed PR proves "this commit exists and passes the
  loader," Hermes trusts that pin going forward rather than re-validating on every install (which
  would also make installs dependent on that repo staying reachable).
- **A separate, independently-scheduled freshness watchdog** exists specifically because "the build
  job succeeded" and "the published artifact is actually fresh and non-empty" are different
  guarantees — checking the deployed URL, not the build's own logs, catches deploy-pipeline bugs
  the build job structurally cannot see.

## Failure modes and guards

- A silently-empty upstream source (one marketplace's API breaking) is caught by the per-source
  floor check, not by the structural validator (which only ever sees the *local* catalog).
- A malicious PR pointing `sha` at a real-but-wrong commit (e.g. an old, since-patched version) is
  **not** caught by "does the SHA exist" — only human review + the loader/manifest check catches a
  functionally different payload at a technically-valid pin.
- A self-updating plugin that tries to route around the pinned-commit model is specifically
  pattern-matched and blocked at review time.

## Verdict: ADOPT

This is one of the strongest patterns in the whole codebase and should be adopted close to as-is:
tiered CI cost (cheap structural check on every PR, expensive proof-of-pin only on the diff),
pin-existence proof by literally checking it out, and an independent freshness watchdog hitting the
*public* endpoint rather than trusting the builder's own exit code.

## Server-side translation

- Same two-tier CI shape works whether the destination is a static file or a database row — run
  structural validation in your PR/admin-approval pipeline, and the pin-proof job as a
  merge-gate before a catalog entry is marked "approved" in your DB.
- Replace "trigger a docs redeploy" with "invalidate/refresh your catalog read-cache" (e.g. a Redis
  key or CDN purge) as the publish step.
- Keep the freshness watchdog as a genuinely separate scheduled job hitting your **public read
  API**, not your ingestion job's internal state — that's the whole point of the pattern.
- If you accept community-submitted MCP servers/plugins at real scale, keep the self-updater
  detection idea: statically scan submitted code for "fetches from a remote host" + "writes to its
  own install directory" co-occurring, and hold those for manual review.
