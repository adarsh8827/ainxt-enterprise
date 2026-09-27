# External Sources — Next-Phase Plan (Central Catalog, Sync, Sources Admin)

**Status: PROPOSAL — for review. Not implemented. Implementation starts only after the current Skills phase is signed off.** Nothing here changes any behavior in this phase; the starter catalog delivered alongside this document uses only the already-shipped, single-shot import path (`create_via_import`, `github_repo.py`/`well_known.py` adapters, manual/admin-triggered). This document plans the *next* phase: a real central catalog + a recurring instance-side sync worker + an admin Sources screen.

---

## 1. Why this is a separate phase

The current import path is intentionally minimal: one admin action, one repo or one well-known domain, one gate run, done. It has no concept of "keep this in sync," no signed index, no crawl, and no admin screen to manage sources — all deliberately deferred. This phase is that deferred work.

---

## 2. Central catalog repo (design)

A separate repo (not this one) that curates and publishes a signed index of importable items:

- **Crawl workflow**: periodically (GitHub Actions cron) walks a maintained allowlist of source repos/well-known domains, fetches each candidate's `SKILL.md` (or well-known index entry), extracts frontmatter.
- **Verify workflow**: re-runs the exact same Tier-1 license check this repo already has (`services/ecosystem/license_policy.py`'s `is_allowed_license()` — reused as a library or reimplemented identically, never diverged) against both the repo-level SPDX and the SKILL.md's own `license:` field. Anything not MIT/Apache-2.0 is rejected before it ever reaches the published index — the crawler must never publish a candidate it hasn't independently re-verified, even if the source claims a compatible license.
- **Version-bump workflow**: on a source's content changing (new commit, new digest), bumps that entry's pinned SHA/digest in the index. Never silently replaces content under an unchanged version pointer.
- **Build workflow**: assembles the final index JSON (schema versioned, e.g. `catalog-index/1.0.0`) and signs it (a detached signature over the index bytes — Ed25519 or similar, key held only by the catalog repo's own release process, never by any instance).
- **Output**: one signed, versioned index file, published to a stable URL (e.g. a GitHub Pages/Release asset), analogous in spirit to `well_known.py`'s existing index shape but at *ecosystem* scale rather than one domain's own skills.

## 3. Instance-side sync worker

A new worker (`workers/ecosystem_sync_worker.py`, matching this repo's existing `workers/` naming convention) that:

- **ETags the index fetch** — conditional `GET` with `If-None-Match`, no full re-download when nothing changed.
- **Verifies the index's signature** against a pinned public key (shipped in this repo, rotatable via a documented, deliberate process — never auto-trusted from the fetched response itself) before trusting anything in it.
- **Content-hash idempotency** — every entry already carries a pinned SHA/digest; the sync worker only imports an entry whose digest differs from what's already recorded for that item (mirrors `fetch_cache.py`'s existing content-addressed caching, extended to a recurring job rather than a one-shot import).
- **Runs the identical import path** this phase already built (`create_via_import`, same license pre-check, same full gate) — the sync worker is a *scheduler* for the existing importer, not a second import mechanism with different rules.
- **Air-gapped import**: for a self-hosted deployment with no outbound internet, an offline mode that accepts a pre-fetched, still-signed index bundle (a tarball an operator copies in manually) and imports from local files instead of live HTTP — same signature check, same digest check, same gate.
- **Rate limits**: a minimum interval between sync runs (configurable, sane default e.g. daily), and per-source backoff on repeated fetch failures — never a tight retry loop against an external host.

## 4. Sources

| Source kind | Mechanism | Notes |
|---|---|---|
| GitHub repos | `github_repo.py`'s existing adapter | Root-level `SKILL.md` only today — **a real gap found while assembling this phase's starter catalog**: the large majority of real-world skill publishers use one repo per *collection* (many skills in subdirectories), which the current root-only adapter cannot consume at all. This phase should decide whether to extend the adapter to accept an optional subdirectory path (fetching `<path>/SKILL.md` instead of the repo root) — a real, scoped code change, not a design change to the license/gate rules — or to require the central catalog's crawler to be the only thing that ever reaches into a subdirectory (keeping the instance-facing adapter root-only for simplicity, with the catalog crawler doing the "which subdirectory" resolution once, centrally, and publishing a per-skill pinned pointer). Recommendation: the latter — keeps the instance-side adapter simple and auditable, and puts subdirectory-walking logic in one place (the catalog crawler) instead of every self-hosted instance.
| Well-known indexes | `well_known.py`'s existing adapter | **A second real gap found live**: the one real-world implementation found during this phase's research (`agentskills.io`'s `/.well-known/agent-skills/index.json`) uses a *different* schema than this adapter currently expects — no `license` field, `url`/`digest` instead of `download_url`/`sha256`. This phase should either (a) update the adapter to match the schema real publishers actually use, treating our own earlier schema as a first-pass guess now superseded by observed reality, or (b) confirm with a second and third real-world example before committing to a schema change (one data point is not yet a standard). Either way, don't ship a next-phase sync worker against a schema no real site actually serves.
| skills.sh-listed repos | Via GitHub only | Never skills.sh's own API/endpoint — skills.sh is used only as a *discovery* aid (a human or the catalog's own crawler notes "skills.sh lists this GitHub repo"), the actual fetch is always a direct GitHub API call through `github_repo.py`, identical to any other GitHub source. |
| Official MCP Registry | Not yet — MCP item type is `coming_soon` | Design the adapter shape now (a new `import_adapters/mcp_registry.py`, same license-precheck-then-gate pattern) but don't build it until the MCP item type itself moves to `available`. |
| ToS-gated sources | Requires a recorded review | Mirrors the existing `ecosystem_sources.tos_checked_at` mechanism (already in the schema, unused this phase) — a source requiring a ToS click-through or registration must have a human-recorded review timestamp before the crawler is allowed to touch it, enforced by the crawl workflow refusing to run against any source lacking that field. |

**Explicit, standing exclusions** (same as this phase's own starter-catalog work, restated here as policy for every future source too): **ClawHub**, in full, and **anything copied from or bundled with the reference-design project** this repo's own UI mock (`docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html`) was inspired by — including that project's own official skills repositories. This applies to the central catalog's own crawl allowlist, not just to manual imports.

## 5. Admin "Sources" screen

A new admin surface (`packages/ecosystem-ui/src/components/admin/AdminSources.tsx`, alongside the existing `AdminPolicies.tsx`/`AdminGateFindings.tsx`):

- List configured sources (kind, URL/domain, last sync time, last sync status, item count contributed).
- Add / remove / enable / disable a source.
- Manual "sync now" trigger per source (for testing/urgency, outside the normal schedule).
- Surface the last sync's own findings if any items were rejected (license failure, signature failure, digest mismatch) — an admin should be able to see *why* a candidate never made it in, not just silence.

## 6. Curation, takedown, and rate limits

- **Curation**: the central catalog's crawl allowlist is a reviewed, version-controlled file in the catalog repo itself (mirrors this repo's own `ecosystem/catalog/starter.yaml` convention, one level up) — adding a source to the crawl is a reviewed PR, not an open crawl of "anything on GitHub with a SKILL.md."
- **Takedown/yank**: reuses the existing `unyank_item`/`force_disable_item` mechanism already built this phase (`policy_service.py`) — a source found to be problematic after the fact gets its already-imported items yanked the same way any other bad item does, and the source itself is disabled in the admin Sources screen so nothing further syncs from it.
- **Rate limits**: per-source minimum sync interval (§3) plus this repo's existing idempotency-key/rate-limit conventions (`test_rate_limit_and_idempotency.py`'s existing pattern) applied to the sync worker's own outbound calls, not just inbound API traffic.

## 7. License tiers for this pipeline specifically

**Tier 1 (strict, no exceptions) applies to every item this pipeline ever touches — full stop.** The tiered license policy shipped this phase (`ECOSYSTEM_PLAN.md` §11.2) introduced Tier 2 (org-policy-driven sharing) and Tier 3 (private-space, self-authored/acknowledged) exceptions — **neither applies here**. Everything crawled, synced, or externally sourced is, by definition, not the caller's own private content, so it is always subject to the original, unconditional MIT/Apache-2.0-only rule, at both the repo/index level and the individual item level, with no admin override anywhere in this pipeline. If a future requirement genuinely needs an exception for an external source, that is a new decision requiring the same explicit sign-off Tier 2/3 themselves required — never an implicit extension of this pipeline's own code.

## 8. Test strategy

Matching this project's own established discipline (real HTTP/real-service round trips over mocks, wherever practical):

- **Real integration tests**: the sync worker's ETag/signature/digest logic against a real (test-fixture) signed index served by a local test HTTP server — not mocked at the HTTP layer, since the exact bytes-on-the-wire signature verification is the thing most worth proving for real.
- **Unit/fixture tests**: the crawl/verify/build workflow's own logic (license re-check, version-bump detection) can reasonably be fixture-based unit tests, since they don't cross a real network boundary in the way the instance-side sync worker does.
- **A deliberate negative-path suite**: a tampered index (bad signature), a stale digest (content changed but the index still points at the old digest), a source that's been disabled mid-sync, and a rate-limit violation — each must fail closed, with a clear, admin-visible reason, never a silent skip.
- **E2E**: one spec proving a full sync cycle (fresh instance, no items) actually populates Discover with the expected items via the real worker, not a direct DB seed.

---

*This document is a proposal for the user's review — nothing here should be treated as approved or scheduled until reviewed.*
