# Ecosystem Marketplace — Changelog

One dated entry per implementation task, in the order tasks land. Each entry: what changed, why, files touched, and a pointer to the relevant `HLD.md`/`LLD/` section. Newest entries at the top.

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
- `CONFIG_AND_PRODUCTS.md`: removed the header note explaining `DECISIONS_AND_PROMPTS.md`'s absence (no longer useful now that the implementation phase is past that discussion); §5's `GET /ecosystem/config` example now matches `CONTRACTS.md` §8 verbatim (was still showing the superseded flat `enabled_item_types` array and a 16-category taxonomy missing `sales`/`support`); §7 item 3's category count corrected from "16" to "18" (it had stopped counting after the `legal` addition and never accounted for §9C fix 15's later `sales`/`support` addition); §7 item 1's route list gained the `/marketplace/:typeSlug/import` route (§9C fix 11) it was missing; §6 item 6 got the same 77→78 lucide-count correction as `ECOSYSTEM_PLAN.md` (see below).
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
Finding on (b), disclosed rather than silently fixed: the M0 commit's message text (not this commit's) still contains both banned terms in this branch's local, unpushed history, since standing git-safety rules default to a new corrective commit rather than rewriting an existing one absent an explicit instruction to do so. If the branch is rebased/squashed before merging, or if history rewriting is otherwise acceptable, that commit's message should be edited to remove the two literal directory names at that point.
Files: `.gitignore` (2 new entries), `docs/ecosystem/hermes_pattern_pack/*` and `docs/ecosystem/claude_ui_refs/*` (removed from git's index only — not deleted from disk).
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
