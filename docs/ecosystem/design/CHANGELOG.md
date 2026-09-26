# Ecosystem Marketplace — Changelog

One dated entry per implementation task, in the order tasks land. Each entry: what changed, why, files touched, and a pointer to the relevant `HLD.md`/`LLD/` section. Newest entries at the top.

---

## 2026-09-26 — M2: create / gate / install

**Task B-6 — Creation service: write / upload / import.**
Why: the single entry point for getting a new item into the catalog, all three payload shapes going through the identical gate — no fast path for any method.
Files: `services/ecosystem/create_service.py` (write/upload real; import's license pre-check real, the fetcher itself not wired up — no external source exists to fetch from yet, disclosed not silently faked), `services/ecosystem/license_policy.py` (shared MIT/Apache-2.0-inclusive check, reused by the gate's own license stage), `services/ecosystem/_agentstudio_interop.py` (see the AgentStudio-import bug fix below), `tests/services/ecosystem/test_create_service.py` (13 tests).
Design docs: `LLD/gate.md`, `LLD/install-lifecycle.md`.

**Task B-7 — Icon upload.**
Why: `icon_url`'s `url:` form must only ever be produced by a server-side upload that sanitizes SVG content — never a client-constructed value.
Files: `services/ecosystem/icon_service.py` — SVG sanitization via `defusedxml` (already a repo dependency, not newly added) for XXE-safe parsing plus a manual allowlist rewrite stripping `<script>`, `on*` handlers, and external `href`/`xlink:href` (verified directly: a malicious SVG round-trips sanitized, not rejected); raster formats stored as-is with a size cap. `tests/services/ecosystem/test_icon_service.py` (10 tests).
Design docs: none dedicated — icon handling is referenced from `CONTRACTS.md` §7/§10, already up to date.
Known gap, disclosed: `CONTRACTS.md`'s `url:<same-origin object-storage path>` form has no actual `GET` endpoint to serve a stored icon back over HTTP in the current endpoint list — this task stores content and returns `url:<content-hash key>`; resolving that into a real servable path is for whichever future task adds the missing route.

**Task B-8 — Gate stages 1-4 (manifest, license, static safety, supply chain).**
Why: every item, regardless of creation path, passes the same structural/legal/security checks before anything else happens to it.
Files: `services/ecosystem/gate/manifest_stage.py`, `license_stage.py` (pass/block only, no warn, unconditional), `static_safety_stage.py` (wraps `agents/compliance_engine.py`'s `analyze()`), `supply_chain_stage.py`, `services/ecosystem/gate/types.py` (shared `Finding`/`StageResult`).
Design docs: `LLD/gate.md`.

**Task B-9 — Gate stages 5-7 (hardened sandbox, ethics, MCP/connector no-op) + verdict cache + post-verdict auto-install hook.**
Why: the safety-critical stages, plus the mechanism (Review round following M1, item E) that makes a passed item immediately usable with no separate manual step.
Files: `sandbox/ecosystem_gate_executor.py` (`EcosystemGateExecutor`, extends `sandbox/docker_executor.py`'s `DockerExecutor`, hardened profile: network always off, read-only rootfs, tmpfs-backed `/sandbox`, no host bind mount for code), `services/ecosystem/gate/sandbox_stage.py` (Python import-allowlist check + optional test-entrypoint execution), `services/ecosystem/gate/ethics_stage.py` (fresh-context `models/model_router.py` call; unavailable/unparseable response → `pending`, never `pass`), `services/ecosystem/gate/mcp_connector_stage.py` (inert no-op for skills), `services/ecosystem/gate_service.py` (full orchestrator: runs all 7 stages, aggregates verdicts, `(content_hash, scanner_version)` cache short-circuit before the expensive stages, records `ecosystem_gate_runs`/`ecosystem_gate_findings`, triggers the auto-install hook).
Design docs: `LLD/gate.md` (fully filled in), `LLD/install-lifecycle.md`.
Tests: 38 tests across `tests/services/ecosystem/gate/` (one file per stage) plus 6 integration tests in `tests/services/ecosystem/test_gate_service_orchestrator.py`. The sandbox's test-entrypoint execution tests run against a **real Docker container** — network isolation, exit-code propagation, and a genuine execution failure are all verified against the actual sandboxed process (`python:3.11-slim`, pulled fresh for this milestone's testing), not mocked.

**Task B-10 — Install lifecycle.**
Why: install/uninstall/enable/disable/update/rollback, plus the single, server-side-only, per-caller `allowed_actions` computation every other action-gating decision in this initiative depends on.
Files: `services/ecosystem/installs_service.py`, `services/ecosystem/items_service.py`'s new `compute_allowed_actions()` (a pure function — no DB access — implementing all 14 of `CONTRACTS.md` §6's documented actions).
Design docs: `LLD/install-lifecycle.md`.
Tests: `tests/services/ecosystem/test_installs_service_lifecycle.py` (9), `tests/services/ecosystem/test_compute_allowed_actions.py` (14).

**Task B-19 — Policy, sharing, reporting, featured overrides, force-disable + require/unrequire (Review round following M1, item F).**
Why: the admin/social actions layered on top of the install lifecycle, plus the required-promotion mechanism item F's visibility design needs.
Files: `services/ecosystem/policy_service.py` — `share`/`unshare`, `report` (with a 3-report auto-hide threshold), `force_disable`/`unyank` (reusing `ecosystem_items.status`'s existing `'yanked'`/`'active'` values), `set_featured_override`/`delete_featured_override`, `require_item`/`unrequire_item`.
Design docs: `LLD/install-lifecycle.md`, `LLD/admin.md` (filled in).
Tests: `tests/services/ecosystem/test_policy_service.py` (9).
Disclosed gap: org policy CRUD (`GET`/`PUT /ecosystem/policy`) has no backing table in task B-1's DDL — not implemented this pass, not silently faked.

**Task B-22 — Seed default builtin skills.**
Why: a fresh instance ships with real, useful, gate-passed content from day one.
Files: `ecosystem/builtin/skills/{productivity,dev-tools,communication}/*/SKILL.md` — 4 starter skills (meeting-notes-summarizer, commit-message-writer, weekly-status-report, email-tone-polish), each written from scratch for this platform, MIT-licensed. `scripts/ecosystem/seed_builtin_skills.py` — walks the folder, upserts each through `items_service`/`versions_service`/`gate_service` exactly like any other item, no bypass. `tests/scripts/ecosystem/test_seed_builtin_skills.py` (5, including a dedicated test confirming an unavailable ethics reviewer during seeding still resolves to `pending`, never an implicit pass because seeding is "trusted").

**Routing.**
`routers/ecosystem_router.py` (new, 20 endpoints) mounted in `gateway.py` behind `ENABLE_ECOSYSTEM_MARKETPLACE`, matching the exact conditional-import/conditional-`include_router` pattern already used for `ENABLE_DISCUSSIONS`/`ENABLE_TEAMS`/etc. Routers stay thin — every handler parses the request, calls one service function, serializes the result; typed service exceptions (`LicenseNotAllowedError`, `PolicyForbiddenError`, `NotFoundError`, `ConflictError`) map to their documented `CONTRACTS.md` §3 wire codes in one shared `_handle_ecosystem_error()`.

**Three significant bugs found and fixed while implementing/testing this milestone (all disclosed here, not silently patched over):**
1. **Critical — `db/migrate.py`'s pre-existing `Base.metadata.create_all()` step silently made several of task B-1's own DB constraints permanently inert**, most notably `ecosystem_installs`' `UNIQUE NULLS NOT DISTINCT (item_id, org_id, installed_for)`. `create_all()` runs early in `run_migrations()` and creates a bare version of every ORM-modeled table before `_part_ad1_...`'s own raw DDL runs; since that raw DDL is `CREATE TABLE IF NOT EXISTS`, `create_all()` winning the race meant the constraint text in the migration file was correct the entire time but never actually reached a live table. Fixed by excluding every `ecosystem_*`/`oauth_*`/`credential_audit`/`desktop_devices` table from `create_all()`'s table list, mirroring the exact existing precedent for `document_embeddings`/`workspace_messages`. Caught by a previously-passing test (`test_install_duplicate_raises_conflict_not_silent_duplicate`) that started failing the moment a real `EcosystemInstall` ORM model was added this milestone — see `LLD/gate.md` and `LLD/data-model.md` for the full account.
2. **`services/ecosystem/legacy_bridge.py`'s AgentStudio import (task B-4, M1) always failed, in every environment, regardless of whether AgentStudio was actually configured** — `AgentStudio.backend.app.core.workflow_repo`'s own internal `from app.core.config import ...` only resolves once `AgentStudio/backend` is on `sys.path` directly (the exact mechanism `gateway.py:1284-1291` already uses for AgentStudio's own routers), which the dotted-import route never set up. B-4's graceful-degradation fallback silently absorbed this as "AgentStudio not available" in every case, never actually reaching AgentStudio even when it was genuinely present. Fixed via a new shared helper, `services/ecosystem/_agentstudio_interop.py`, reused by this milestone's own AgentStudio interop (B-6's upload path, B-22's seeding) for the exact same reason.
3. **Pre-existing, unrelated, out-of-scope finding (not fixed)**: `agents/secret_detector.py`'s `detect_secrets()` never calls its own `iter_env_secret_values()` helper, despite that file's comments describing exactly that fix for SNAKE_CASE env-var-assignment secrets (e.g. `AWS_SECRET_ACCESS_KEY = "..."`) — such a value is silently never caught today. Left alone (existing, unrelated code); this milestone's own tests use a pattern the detector does catch instead of depending on the broken path.

**Also disclosed, not fixed (existing/cross-cutting, out of this milestone's scope):**
- `services/ecosystem/gate/static_safety_stage.py`'s efficacy depends on the pre-existing `COMPLIANCE_SERVICE_ENABLED` flag (`core/config.py`, default `false`) — this task does not turn it on (an unrelated feature's flag); a deployment wanting this gate stage to catch anything must set it independently.
- No real async job queue exists yet — `gate_service.py`'s `enqueue_gate_run()` runs every stage synchronously, in-process. The wire contract (`job_id`, `GET /ecosystem/jobs/{id}`) is unaffected; a real background worker is separate, disclosed future work.
- No `created_by`/owner column exists on `ecosystem_items` — `deprecate` is admin-only this pass (not "owner or admin," since there's no column to check ownership against yet).
- No RBAC-permission-rejection test exists at the HTTP layer (would need a running FastAPI test client) — the `Depends(require_permission(...))` wiring on every admin route is verified by direct code inspection, not an executed request.

**Verified (real, executed test output)**: against a real `pgvector/pgvector:pg16` instance (migration verified idempotent both before and after the `create_all()` fix) and a real Docker daemon (with `python:3.11-slim` pulled fresh) — **197 passed, 2 skipped (MinIO, same documented sandbox limitation as M1), 0 failed**, covering `tests/db/`, `tests/services/`, `tests/scripts/`, `tests/store/`, `tests/ci/`, `tests/config/`, `tests/auth/` for this initiative in full.

---

## 2026-09-26 — M1: data + core

**Task B-1 — Migration: all new tables.**
Why: every other M1 (and later) task needs the schema to exist first.
Files: `db/migrate.py` (`_part_ad1_ecosystem_marketplace_tables_2026_09_25`, 20 tables + 2 extensions + seed data for `ecosystem_surfaces`/`ecosystem_product_profiles`/`ecosystem_org_products`), `db/models.py` (6 new ORM models — only the tables M1's services actually query; the rest get a model when the milestone that queries them lands), `tests/db/test_ecosystem_migration.py`.
Design docs: `LLD/data-model.md`.

**Task B-2 — Object storage interface.**
Why: version content needs a content-hash-addressed store, distinct from the existing UUID-path-addressed `core/storage.py` (which serves chat attachments and doesn't verify what it hands back matches what was written).
Files: `store/ecosystem_object_storage.py` (local-filesystem default + S3/MinIO, same `minio` client `core/storage.py` already depends on), `tests/store/test_ecosystem_object_storage.py`.
Design docs: referenced from `LLD/data-model.md` and `LLD/legacy-bridge.md` (its first real consumer).

**Task B-3 — Service layer skeleton.**
Why: routers/CLI/chat tools/workers need one place to call into, never each other, and never containing business logic themselves.
Files: `services/ecosystem/` (new package) — `errors.py` (shared exception types, a small addition beyond B-3's literal file list, justified because B-5's `NAMESPACE_INVALID` needs somewhere to live), `items_service.py`, `versions_service.py`, `gate_service.py`, `installs_service.py`, `resolver_service.py`, `config_service.py`, `events_service.py`, `drafts_service.py`, `icon_service.py`. Most are stubs pointing at the milestone that fills them in; `items_service.get_or_create_local_source`/`upsert_legacy_pointer_item`, `versions_service.create_or_refresh_legacy_version`, and `gate_service.enqueue_gate_run` are real — task B-4 needed them now, in M1, ahead of the create/install/gate lifecycle they'll eventually be part of.
Design docs: `LLD/data-model.md`, `LLD/legacy-bridge.md`.

**Task B-5 — Publisher/namespace service.**
Why: an item's namespace's publisher segment must resolve to a verified owner before creation — this is what makes that real rather than an unenforced convention.
Files: `services/ecosystem/publishers_service.py` (real — `split_namespace`, `resolve_publisher` with auto-provision-on-first-use and ownership enforcement, `get_publisher`), `tests/services/ecosystem/test_publishers_service.py` (namespace validation, auto-provisioning, ownership rejection, cross-org isolation).
Design docs: `LLD/data-model.md`.

**Task B-20 — Rate limiting, Idempotency-Key storage, audit writes.**
Why: shared infrastructure every mutating endpoint (M2 onward) needs, built once rather than per-endpoint.
Files: `services/ecosystem/rate_limit_service.py` (per-`(user_id, action_class)` sliding-window, algorithm reused from `core/rate_limiter.py`, framework-agnostic), `services/ecosystem/idempotency_service.py` (Redis-backed 24h cache), `services/ecosystem/audit_service.py` (`write_audit_event`, infrastructure only — endpoint-coverage testing waits for M2's endpoints to exist), `db/models.py`'s `EcosystemAudit`, `tests/services/ecosystem/test_rate_limit_and_idempotency.py`, `tests/services/ecosystem/test_audit_service.py`.
Design docs: `LLD/security.md`.

**Task B-4 (backfill job only, per the M0-review-adjusted design) — Legacy bridge.**
Why: makes pre-existing `skills_pg`/AgentStudio content visible in the new catalog without migrating or touching either legacy system.
Files: `services/ecosystem/legacy_bridge.py` (read-only), `scripts/ecosystem/backfill_legacy_items.py` (the only writer, idempotent by `(legacy_source, legacy_ref)`), `tests/services/ecosystem/test_legacy_bridge.py`, `tests/scripts/ecosystem/test_backfill_legacy_items.py`.
Design docs: `LLD/legacy-bridge.md` (fully filled in, including the M0-review-adjusted gate-hiding/per-org-source/group-rename design).

**Out-of-scope items noted, not fixed (per the strict-scope rule):**
- `db/models.py:36`'s `_now_utc()` uses the now-deprecated `datetime.utcnow()` — pre-existing, used throughout the codebase, unrelated to this milestone's work.
- `SKILLS_PHASE_PLAN.md` F-6 / `CONTRACTS.md` §1/§9 still describe `Yours` as a 5-group scheme with no mention of the legacy-bridge's 6th group — a pre-existing gap (see the M0-review-fix entry for item 4), not introduced or fixed by this milestone; F-6 (M4) is where it should be closed.
- The MinIO/S3 backend's Tier-2 test (`store/ecosystem_object_storage.py`) is written and correctly skips when no MinIO endpoint is configured — this session's sandbox can't pull a MinIO image (no cached image, registry pull blocked), so it has only been exercised via the local-filesystem backend's 9 tests, not against a real S3-compatible endpoint.
- The cross-organization isolation test and the forged-`allowed_actions` test flagged in `LLD/security.md` need real endpoints (task B-10/B-19, M2) to test against — not written this milestone, tracked there instead of silently dropped.

**Verified (real, executed test output, not just written tests)**: `pytest tests/services/ tests/scripts/ tests/store/test_ecosystem_object_storage.py tests/db/test_ecosystem_migration.py tests/ci/ tests/config/test_ecosystem_flags.py tests/auth/test_rbac_marketplace_permissions.py` against a real `pgvector/pgvector:pg16` container (migrated fresh, then re-run to confirm idempotency) and a real `redis:7-alpine` container — **95 passed, 2 skipped (MinIO, documented above), 0 failed**.

---

## 2026-09-25 — M0 review fixes (item 3): dependency-manifest license check

**Fix — extend the license CI job to cover newly added dependencies, not just banned imports.**
Why: the review of M0 pointed out that the original check only scanned JS/TS source for `lucide-react` imports; a dependency could be added to `requirements.txt` or a `package.json` with a disallowed or unverified license and nothing would catch it until (if ever) something imported it.
What changed: `scripts/ci/ecosystem_license_check.py` gained a second, independent check — `find_dependency_violations()` diffs `requirements.txt`/`requirements-ldap.txt`/`requirements-ocr.txt` and the `ai-ui`/`desktop`/`AgentStudio/frontend` `package.json` files against a base git ref (default `origin/main`), and for every dependency name newly present, looks it up in `compliance/python-components.tsv`/`compliance/node-components.tsv`. Missing from the inventory fails closed (a new dependency needs a verified compliance entry, it doesn't get the benefit of the doubt); present but not MIT/Apache-2.0-compatible also fails. Both checks run in `main()`; either failing fails the job.
Fixed along the way: `_git_show()` originally decoded `git show`'s output using the platform default text encoding, which is cp1252 on Windows — this silently corrupted the base-ref comparison for any manifest with non-ASCII bytes (most of this repo's) and made nearly every pre-existing dependency look "newly added." Now decodes explicitly as UTF-8.
Also fixed: running the new check against this branch surfaced that `jszip` (added to `ai-ui/package.json` earlier on this branch, license already recorded in `THIRD-PARTY-NOTICES.md` §2.3) was missing from `compliance/node-components.tsv`, the machine-readable file this check reads — added the matching row so the check the same task introduces doesn't immediately fail on pre-existing, already-reviewed code.
Files: `scripts/ci/ecosystem_license_check.py`, `tests/ci/test_ecosystem_license_check.py` (8 new tests), `compliance/node-components.tsv` (1 row), `docs/ecosystem/SKILLS_PHASE_PLAN.md` (B-21 and the Tests & Quality CI bullet updated to describe both checks).
Design docs: no dedicated LLD file — CI/process infrastructure, same as the original B-21 entry.
Verified: `pytest tests/ci/` — 12 passed; full M0 regression set (`tests/ci/`, `tests/config/test_ecosystem_flags.py`, `tests/auth/test_rbac_marketplace_permissions.py`) — 22 passed. Ran the script standalone against this repo's actual history (`--base-ref e5d80ae` and `--base-ref HEAD`) — passes cleanly on both after the `jszip` compliance-row fix.

---

## 2026-09-25 — M0 review fixes (item 4): B-4 backfill design corrections

**Fix — three corrections to the B-4 legacy-bridge backfill design (docs only; B-4 itself lands in M1).**
Why: the M0 review caught three design mistakes before any code was written: `status='source_unavailable'` was being overloaded to mean "gate failed," conflating catalog-entry lifecycle with content-verdict — two axes `SKILLS_UI_AUDIT.md` M2 already establishes as genuinely distinct; a single "reserved platform" `local` source row for all backfilled items would violate the schema's own `ux_ecosystem_sources_one_local_per_org` per-org uniqueness and misattribute cross-org content; and the Yours group name "Available from Agent Studio" undersold its own scope, since it covers `skills_pg` as well.
What changed (docs only): `docs/ecosystem/SKILLS_PHASE_PLAN.md` task B-4 — (1) a `fail` gate verdict now hides a backfilled item from Discover/Yours via a join to its latest `ecosystem_item_versions.gate_verdict`, leaving `ecosystem_items.status` at `'active'`; (2) each backfilled item's `source_id` now points at its own org's `local` source row (auto-provisioned if that org doesn't have one yet), never a shared platform-wide row; (3) the Yours group is renamed "Available from existing skills."
Files: `docs/ecosystem/SKILLS_PHASE_PLAN.md` (B-4 task text and its tests/definition-of-done).
Design docs: `docs/ecosystem/design/LLD/legacy-bridge.md` stays a stub — filled in when B-4's code actually lands in M1, per this file's existing convention of documenting design once a task has real code.
Out-of-scope note (not fixed, flagged for a future task): `SKILLS_PHASE_PLAN.md` F-6 and `CONTRACTS.md` §1/§9 describe `Yours` as a "5-group" scheme keyed on `InstallOrigin` and don't mention this 6th, non-install-backed legacy group at all — a pre-existing gap that predates this fix, not introduced by it.

---

## 2026-09-25 — M0 review fixes (item 5): ethics-stage unavailability must not resolve to `pass`

**Fix — an unreachable ethics reviewer produces `pending` + retry, never `pass` (docs only; B-9/B-22 land in M2).**
Why: the M0 review caught that the gate design didn't explicitly state what happens when the ethics-stage model call itself fails — leaving room for an implementation to (incorrectly) treat "couldn't review it" as "nothing bad was found," which is not the same claim. This applies with equal force to builtin-skill seeding (B-22): a trusted first-party origin does not excuse skipping the same rule, since the concern is about the review actually having happened, not about who authored the content.
What changed (docs only): `docs/ecosystem/ECOSYSTEM_PLAN.md` §6 stage 6 now states the reviewer-unavailable → `pending` + retry rule explicitly. `docs/ecosystem/SKILLS_PHASE_PLAN.md` task B-9 documents the same rule against `ethics_stage.py`, adds an ethics-reviewer-unavailable test, and cross-references B-22; B-22's own test bullet gets the matching seeding-path test.
Files: `docs/ecosystem/ECOSYSTEM_PLAN.md`, `docs/ecosystem/SKILLS_PHASE_PLAN.md`.
Design docs: `docs/ecosystem/design/LLD/gate.md` stays a stub — filled in when B-8/B-9 land in M2, per this file's existing convention.

---

## 2026-09-25 — M0 review fixes (item 6): doc-drift corrections

**Fix — several small factual/cross-reference drifts across the three design docs, caught in the M0 review.**
Why: these docs are meant to be a single source of truth that later tasks can trust without re-verifying; each of these was a small but real inconsistency that would otherwise mislead whoever reads that section next.
What changed:
- `CONFIG_AND_PRODUCTS.md`: removed the header note explaining `DECISIONS_AND_PROMPTS.md`'s absence (no longer useful now that the implementation phase is past that discussion); §5's `GET /ecosystem/config` example now matches `CONTRACTS.md` §8 verbatim (was still showing the superseded flat `enabled_item_types` array and a 16-category taxonomy missing `sales`/`support`); §7 item 3's category count corrected from "16" to "18" (it had stopped counting after the `legal` addition and never accounted for Review fix 15's later `sales`/`support` addition); §7 item 1's route list gained the `/marketplace/:typeSlug/import` route (Review fix 11) it was missing; §6 item 6 got the same 77→78 lucide-count correction as `ECOSYSTEM_PLAN.md` (see below).
- `ECOSYSTEM_PLAN.md`: all remaining "77 files" lucide-count references (§1.6, two in §11, one in §15) corrected to 78, matching the direct-search-verified count already used elsewhere. §13's week-by-week table now states explicitly that `SKILLS_PHASE_PLAN.md`'s milestones supersede it as the actual execution order, kept only as historical planning context.
- `CONTRACTS.md`: §4's session/auth-behavior cross-reference corrected from "(§13)" to "(§14)" — §14 is this document's actual "Session/auth parity" section; §13 is "ecosystem.changed events," an unrelated section this reference had accidentally pointed at.
Files: `docs/ecosystem/CONFIG_AND_PRODUCTS.md`, `docs/ecosystem/ECOSYSTEM_PLAN.md`, `docs/ecosystem/CONTRACTS.md`.
Design docs: none of these are `docs/ecosystem/design/` files — this entry itself is the record, per this file's role as the changelog for the initiative as a whole.

---

## 2026-09-25 — M0 review fixes (item 7): RBAC tier decision, researched and confirmed

**Decision — `marketplace:add`/`marketplace:share` stay at the `developer` tier (no code change; B-18's existing placement was already correct).**
Why: the review asked which role a normal chat user gets by default before choosing between "all authenticated users (`viewer` and up)" and "keep at `developer` and up." Research: `chat:write` itself — the permission to actually send a chat message — is gated at `developer`, not `viewer` (`auth/rbac.py:36-54`; `viewer` is read-only platform-wide). Every path that provisions a real, chat-capable account defaults to `role="user"` (`routers/auth_router.py:461,758,1403`; `auth/sso.py:416`), which is a legacy alias for the `developer` tier (`auth/rbac.py:29`). The one exception — the Azure AD "office" OBO SSO flow (`auth/sso.py:770`) — provisions at `viewer`, but those accounts can't write a chat message either, so they aren't "normal chat users" by this codebase's own definition of the tier. Conclusion: a normal chat user already gets `developer` by default; keeping the marketplace permissions there covers the intended population without breaking `viewer`'s otherwise strictly-read-only invariant.
Files: `docs/ecosystem/SKILLS_PHASE_PLAN.md` (B-18 — research and decision recorded); no `auth/rbac.py` change (the placement from the earlier M0 commit already matches this decision).
Design docs: none — this is a decision record, not a new design.

---

## 2026-09-25 — M0 review fixes (item 8): stop tracking local reference-research material; commit-hygiene finding

**Fix — untrack two local-only reference-research directories; flag a commit-message violation found while checking.**
Why: the review asked (a) how to handle two pre-existing, untracked-before-this-session directories under `docs/ecosystem/` that hold reference research material predating this initiative's implementation phase, and (b) to verify no commit so far names an AI tool or carries a co-author trailer, per standing rule 3. Checking (b) surfaced a real violation: the prior M0 commit's own message named both directories by their literal on-disk names in its body text, which itself put a banned term into a commit message.
Decision on (a), per instruction: keep both directories on local disk for ongoing reference while this initiative's tasks are still in progress, but stop version-controlling them — they are removed from git's index (contents untouched on disk) and added to `.gitignore` under a neutral description, so no future `git add -A` re-adds them. Both directories are slated for deletion from disk once every task in this initiative is complete, not before (per instruction — they're still useful reference during the work).
Finding on (b), disclosed rather than silently fixed at the time: the M0 commit's message text (not this commit's) still contained both banned terms in this branch's local, unpushed history, since standing git-safety rules default to a new corrective commit rather than rewriting an existing one absent an explicit instruction to do so. **Resolved in the following review round** — see the dated entry below covering items A-H, which reworded that commit's message (explicitly authorized, unpushed-only) once the branch was reviewed again.
Files: `.gitignore` (2 new entries), the two reference-research directories under `docs/ecosystem/` (removed from git's index only — not deleted from disk).
Design docs: none — this is a git-tracking/process fix, not a design change.

---

## 2026-09-25 — M0: prerequisites

**Task P-0 — Revert the CAPTCHA disable.**
Why: unrelated to this initiative, but the check was left disabled on this branch for local testing and needed reverting before further work landed on top.
Files: `ai-ui/src/components/Login.jsx`.
Design docs: none (not part of the marketplace design).

**Task B-0 — Register feature flags.**
Why: every flag this phase introduces needs to exist before any task that reads it is implemented.
Files: `core/config.py` (11 new flags, matching the file's existing `ENABLE_<NAME>` convention), `tests/config/test_ecosystem_flags.py`.
Design docs: `HLD.md` §4 references the flag-gating principle generally; per-flag detail lives with the task that actually uses each flag.

**Task B-18 — RBAC permissions.**
Why: the creation/sharing/admin endpoints landing in later milestones need permission strings to gate on.
Files: `auth/rbac.py` (6 new permissions: `marketplace:add`, `marketplace:share` at the developer tier; `marketplace:provision`, `marketplace:admin_sources`, `marketplace:admin_policy`, `connectors:admin_shared` at the admin tier), `tests/auth/test_rbac_marketplace_permissions.py`.
Design docs: `LLD/admin.md` (server-side enforcement principle).

**Task B-21 — CI license check, allowlist, third-party notice.**
Why: the platform's MIT/Apache-2.0-only rule needs an automated check before any new marketplace code lands, and one pre-existing dual-licensed dependency needed its notice recorded.
Files: `scripts/ci/ecosystem_license_check.py` (new), `.ecosystem-license-allowlist.json` (new — 78 pre-existing files flagged for a banned-license icon import; re-verified by direct search rather than trusting an earlier count, which turned out to be off by one), `.github/workflows/ci.yml` (new Tier-1 step, blocking), `THIRD-PARTY-NOTICES.md` (new §2.3 entry), `tests/ci/test_ecosystem_license_check.py`.
Design docs: `HLD.md` §5 (open-source hygiene note); no dedicated LLD file — this is CI/process infrastructure, not a runtime component.

**Task D-0 — Design docs skeleton.**
Why: every subsequent task in this plan is required to update these documents in the same commit as its code; the skeleton has to exist first.
Files: `docs/ecosystem/design/HLD.md`, `docs/ecosystem/design/LLD/*.md` (12 files), `docs/ecosystem/design/CHANGELOG.md` (this file).
Design docs: this task created them.

---
