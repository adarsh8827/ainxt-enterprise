# LLD — End-to-end (Playwright) testing

**Purpose**: the 7 named E2E specs from `docs/ecosystem/SKILLS_PHASE_PLAN.md`'s Tests section, exercising real user flows across the full stack (real Postgres/Redis/gate-worker, a real LLM provider, a real browser) rather than mocking any layer. A 16th LLD file — none of the 15 existing files were the right home for cross-cutting E2E infrastructure spanning `ai-ui`, `packages/ecosystem-ui`, the gateway, and the gate-worker at once, matching the precedent `desktop-local-cache.md`/`agentstudio-integration.md` already set for "doesn't fit any of the original areas."

## Files / functions

- `ai-ui/playwright.config.ts` (new) — `testDir: './e2e'`, `channel: 'chrome'` (a system-installed Chrome, not Playwright's own bundled Chromium — this environment's network egress blocks Playwright's browser-binary CDN download; `npx playwright install chromium` remains the documented zero-dependency path for an environment that *can* reach it). `fullyParallel: false`, `workers: 1` — specs share org/user fixtures and mutate shared state (installs, org policy), so parallel workers would race each other. Does **not** start either server itself (no `webServer` block) — both the gateway and `ai-ui`'s dev server need non-default flags/env this config can't safely assume; start them per this file's own Tests section, then point `PLAYWRIGHT_BASE_URL` at your own `ai-ui` dev server if it's not on the default port.
- `ai-ui/e2e/helpers.ts` (new) — `loginAs()` (real `POST /auth/login`, cookie lands in the browser context's own cookie jar automatically), `createResolvedSkill()`/`waitForGateResolved()` (polls `latest_verdict`, **not** `status` — see Edge cases below), `getInstallId()`.
- `ai-ui/e2e/*.spec.ts` (new, 7 files) — one per named scenario: `create-in-chat`, `install-org-scope`, `disable-in-chat`, `uninstall-empty-state`, `gpl-upload-blocked`, `workspace-product-profile`, `upload-to-chat`.
- `ai-ui/package.json` — new `@playwright/test` devDependency (Apache-2.0), new `test:e2e` script.
- `scripts/ecosystem/seed_e2e_test_users.py` (new) — two fixed, same-org test users (`e2e-user-a@ainxt.local`, `e2e-user-b@ainxt.local`, org `e2e-test-org`), mirroring `scripts/seed.py`'s own idempotent `INSERT ... ON CONFLICT DO UPDATE` pattern. Never touches `scripts/seed.py`'s own `admin@ainxt.local`/`dev@ainxt.local` accounts.

## API and DB changes

None from this task itself — every spec drives the real, already-existing API surface. Two real, pre-existing gaps were found *by* writing these specs against a real backend (neither introduced here, both disclosed, neither fixed here — out of this task's own delegated scope):

1. **`GET /ecosystem/installs` never embeds `item: ItemSummary`** on each install row (`services/ecosystem/installs_service.py::list_installs()`'s `_row_to_dict()` only serializes the raw `EcosystemInstall` columns — `item_id`, not a joined `item` object) — despite `docs/ecosystem/CONTRACTS.md` §9 and `packages/ecosystem-ui/src/types.ts`'s own `Install` type both documenting one as required. `Yours.tsx`'s `InstallRow` (task F-6) crashes on this for real (`Cannot read properties of undefined (reading 'allowed_actions')`) — invisible to every existing component test because they all render against `MockEcosystemClient`, whose hand-built fixtures already include the `item` field correctly. This blocks `uninstall-empty-state.spec.ts` and the tail of `upload-to-chat.spec.ts` from completing for real (both reach the point of exercising this exact code path and then hit the crash) — their own assertions are correct; the screen they exercise is not, today, against a real backend.
2. **`GET /ecosystem/items`'s `q` search param matches `display_name`/`description`/`tags`, not `namespace`** — confirmed directly against a real running instance while writing `create-in-chat.spec.ts`/`upload-to-chat.spec.ts` (searching by a namespace slug returned zero results for an item confirmed to exist with that exact namespace via a direct DB query). Not necessarily a bug — namespace search may never have been intended — but worth a deliberate decision rather than silent absence; both specs now search by `display_name` instead.

## Sequence diagrams

```
create-in-chat.spec.ts (real, passes end-to-end):
  login -> open chat -> "+" -> Create a skill with AI
  -> real SSE generation (SkillFactoryAdapter -> real multi-step LLM calls,
     ~30-90s wall clock -- test.setTimeout(180_000))
  -> preview card populated with AI-generated name/description/namespace
  -> edit namespace, verify the edit actually landed (toHaveValue) before submitting
  -> Save Skill -> real POST .../submit -> status card
  -> GET /ecosystem/items?q=<display_name> (real API) confirms the exact
     namespace landed in the catalog

gpl-upload-blocked.spec.ts (real, passes, no LLM/gate-worker dependency):
  login -> /marketplace/skills/upload -> upload a real in-memory zip
  (jszip) containing SKILL.md with license: GPL-3.0-only
  -> license_stage's synchronous pre-check rejects it before any gate job
     is even enqueued -- upload-blocked-banner shows the specific reason

workspace-product-profile.spec.ts (real, passes, zero backend dependency):
  goto the F-12 example host directly (a *different* app/port,
  packages/ecosystem-ui/examples/workspace-host) -- MockEcosystemClient +
  MOCK_CONFIG_WORKSPACE fixture -> compact layout, only "skill" available,
  admin routes real-navigate to admin-not-available, Import-from-URL
  disabled in the Add menu
```

## Edge cases and errors

- **`status` is not the same signal as `latest_verdict` for "has the gate finished."** `status` can already read `"active"` immediately after creation, before the gate-worker has even picked up the job — it isn't solely derived from the gate verdict. `latest_verdict` (`pending` → `pass`/`warn`/`fail`) is the field that actually reflects gate-worker completion. `waitForGateResolved()` polls the latter; an earlier draft of this file's own helper polled the former and produced results that looked like a real-time race when it was actually just polling the wrong field. Found the hard way, fixed once, documented so it isn't rediscovered.
- **A real, live race exists between a fast pass/warn verdict's auto-install (task B-10's `_auto_install()`) and a spec's own explicit `install()` call for the same item** — both target the identical `(item_id, org_id, installed_for)` unique key. `install-org-scope.spec.ts` avoids it by passing `provision_scope` on the *create* call itself (one install operation, already correctly scoped, instead of two racing to be first) rather than a separate `install()` call after the fact — this requires the calling user to hold `marketplace:provision`, which the seeded test users don't have by default (see Tests below for how this spec's own setup grants it).
- **A profile/role cache (Redis DB 8, 5-minute TTL, `auth/dependencies.py::enrich_user_context()`) deliberately overwrites a JWT's `role` claim with a fresher DB value on every request** — a documented, correct security fix (so a revoked admin's stale JWT can't keep working for up to 24h) that nonetheless means a role change made directly in the DB for test setup purposes does not take effect for up to 5 minutes unless `invalidate_profile_cache(user_id)` is called explicitly. Cost real time to diagnose (looked exactly like an authorization bug in the endpoint under test) — noted here so the next person doesn't re-spend it.
- **Fixed, later in M5**: the gate's ethics stage (`services/ecosystem/gate/ethics_stage.py`, task B-9, pre-dates this milestone) did not strip a markdown code-fence (` ```json ... ``` `) some real model responses wrap their JSON verdict in, so `_parse_verdict()`'s bare `json.loads()` failed and the gate resolved to `"pending"` instead of `"pass"`/`"warn"` — this was the single biggest source of E2E flakiness in this milestone's own suite: `disable-in-chat.spec.ts`, `install-org-scope.spec.ts`, and `upload-to-chat.spec.ts` all depend on a real gate resolution and were each, independently, at the mercy of this. Manual live smoke-testing later found this was far worse than "occasional E2E flakiness" — longer, more nuanced real content fenced *consistently* (5/5), meaning any real submission whose ethics review had anything substantive to say about it could never resolve at all. See `LLD/gate.md` for the fix. The three specs' own defensive handling (graceful skip / explicit-install fallback) is no longer strictly load-bearing but was left in place — it's still correct behavior for a genuinely slow or unavailable reviewer, just no longer masking this specific bug.
- **A completely unauthenticated (or wrong-org) caller can mutate any install by UUID** — see `LLD/security.md`'s own Tests section for the full writeup; this is the single most severe finding from this milestone's testing work as a whole, not specific to E2E.

## Flags

None of this task's own — every spec exercises whatever flags the backend/frontend under test already require (`ENABLE_ECOSYSTEM_MARKETPLACE`, `ECOSYSTEM_CHAT_SKILLS`, `VITE_ECOSYSTEM_CHAT_SKILLS`).

## Tests

Setup (see `docs/ecosystem/TESTING_GUIDE.md`'s own Playwright section for the full walkthrough):
```bash
# 1. A real backend with both flags on, pointed at a real Postgres/Redis,
#    with a gate-worker actually running against the same DB.
# 2. python scripts/ecosystem/seed_e2e_test_users.py
# 3. cd ai-ui && npm install && npx playwright test
```

Real results from this milestone's own run (a real gateway, real Postgres/Redis, a real gate-worker, a real LLM provider, a real Chrome browser — nothing mocked):
- `gpl-upload-blocked.spec.ts` — **pass**.
- `create-in-chat.spec.ts` — **pass** (full real LLM-backed generation, end to end, ~75s).
- `workspace-product-profile.spec.ts` (3 sub-tests) — **all pass**.
- `install-org-scope.spec.ts` — passes when the real gate resolves to pass/warn within its wait window; gracefully **skips** (not fails) when it resolves to `"pending"` instead, per the ethics-stage caveat above. Both outcomes were observed directly during this milestone's own runs.
- `disable-in-chat.spec.ts` — passes when the real gate resolves in time; **fails** on a `"pending"` verdict (same disclosed cause) since its own setup has no fallback path (it specifically needs a real install to exist to test disabling it).
- `uninstall-empty-state.spec.ts`, `upload-to-chat.spec.ts` — reach the real "Yours" screen for real and hit the disclosed `Yours.tsx`/`installs_service` contract-mismatch crash described above. Both specs' own logic and assertions are correct as written; the screen they exercise is not, today, against a real backend.

## How to extend

Once `LLD/security.md`'s disclosed auth gap and this file's disclosed `GET /ecosystem/installs` `item` gap are both fixed, re-run the full suite — `uninstall-empty-state.spec.ts` and `upload-to-chat.spec.ts` should then pass outright with no spec changes needed (they were written against the *documented* contract, not the current gap). Fixing the ethics-stage markdown-fence parsing (out of this milestone's scope, but named here since it's this suite's single biggest source of flakiness) would make `disable-in-chat.spec.ts`/`install-org-scope.spec.ts` deterministic instead of gate-verdict-dependent.
