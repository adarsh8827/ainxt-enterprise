# Plan — Agent Studio: Marketplace-only skill creation

**Status: PROPOSED — not yet implemented. Implement only after this plan is approved**, matching `docs/ecosystem/SKILLS_PHASE_PLAN.md`'s own convention. This file is a forward-looking plan, not an as-built record — contrast with `LLD/agentstudio-integration.md` (tasks B-23/B-24), which documents what's *already shipped* in this direction and is the foundation this plan builds on. Read that file first; this one assumes it.

**Product decision this plan implements**: skills must be created in the Marketplace only, always. Agent Studio's own skill-creation UI (the AI generation wizard and manual upload) is to be hidden, not deleted — no router, table, or pipeline file is removed, per the standing additive-only instruction this whole initiative follows. Agent Studio's runtime must actually be able to *use* a Marketplace skill once attached (today it cannot — see B-24's own disclosed gap below). Existing built-in skills already in `skills_catalog` must keep working unchanged.

## Where this picks up (already shipped, per `agentstudio-integration.md`)

- `CatalogPicker.jsx` already merges Ecosystem skills into the skill picker (`GET /ecosystem/capabilities?surface=agent_studio`), tagged `_ecosystemSourced: true`, badged "Marketplace" in the UI. Flag: `VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS` (frontend build-time, read via `isEcosystemAgentStudioSkillsEnabled()`).
- **Disclosed, not built**: runtime execution of a picked Ecosystem-sourced skill. `native_engine.py`'s `_resolve_catalog_skills()` only ever reads `skills_catalog`; a skill not found there is silently dropped with a log warning, regardless of whether `CatalogPicker` found it in Ecosystem. B-24's own notes flag `_CatalogTool`'s dispatch as "too deep/unfamiliar to safely modify" in that pass.
- Agent Studio is **not** a separate backend/DB in production, despite a stale docker-compose.yml comment claiming otherwise: `gateway.py` imports its routers into the same FastAPI app and runs its DB init in-process; its tables live in the same `ainxt` Postgres schema as `ecosystem_items` (`gateway.py:2276-2281`). The standalone `AgentStudio/backend/Dockerfile` (`:8002`) is dev-only, unused by any compose service.
- `skills_catalog` has a `source` column (`builtin` / `ai` / `upload`) — confirmed existing built-in default skills to preserve.

## Tasks

- **Task B-25 — Hide skill-creation UI entry points**
  - Files: `AgentStudio/frontend/src/features/skills/index.jsx` (comment out the "Generate with AI" and "Upload" buttons and their handlers — do not delete); the entry point that launches `AgentStudio/frontend/src/features/skills/SkillFactoryChat.jsx` (comment out, component file itself untouched).
  - Backend: no changes. `POST /skills-catalog/generate`, `POST /skills-catalog/upload`, `POST /skills-catalog` (upsert), and all of `AgentStudio/backend/skill_factory/pipeline.py` stay exactly as-is — reachable by direct API call, just not from this UI. Accepted tradeoff, not a security boundary.
  - Tests: update/add a frontend test asserting these actions are not rendered (mirrors the pattern `EcosystemPlusMenu.test.jsx` already uses for "never shows X").
  - Flag: none — raw comment-out, per explicit instruction (a flag wrap was considered and declined: the ask is simplicity and easy reversibility via uncomment, not a runtime toggle).
  - Definition of done: no path in the Agent Studio UI can create a new skill; existing skills (native or Marketplace-sourced) remain fully visible/attachable.

- **Task B-26 — Repurpose the "Skills" dashboard tab to read-only + Browse Marketplace**
  - Files: `AgentStudio/frontend/src/features/skills/index.jsx` — strip to a read-only list (reuse the existing native `GET /skills-catalog` fetch plus the Ecosystem-merge pattern `CatalogPicker.jsx` already established); add a "Browse Marketplace" button.
  - Open decision (deferred by product owner, default below unless told otherwise): does this button open `EcosystemBrowseSkillsModal` as-is (same component Chat uses), or a workflow-filtered variant? **Default: reuse as-is** — lower effort, nothing else in this plan depends on the answer.
  - Tests: component test confirming the list renders both sources and the button opens the chosen modal.
  - Flag: none.
  - Definition of done: the tab is browse/attach-only; creating a skill is only possible via the Marketplace.

- **Task B-27 — Runtime fallback: Ecosystem lookup in `_resolve_catalog_skills()`**
  - Files: `AgentStudio/backend/app/engine/native_engine.py`, `_resolve_catalog_skills()`. When `workflow_repo.get_skill(name)` misses, fall back to an Ecosystem lookup via `services.ecosystem.resolver_service` / `versions_service` (the same calls `mcp/ecosystem_skill_tools.py` already uses to pull `manifest["instructions"]` by namespace) before giving up and logging the drop.
  - **Lookup order — explicit product decision**: Ecosystem first is tempting ("marketplace only going forward") but **native `skills_catalog` first, Ecosystem as fallback** is the safer order for this task — it guarantees zero behavior change for every graph referencing an existing built-in skill by name, with no migration or name-collision handling required. Ecosystem skills are only reached for names `skills_catalog` doesn't have. Revisit only if a name collision between a native and Marketplace skill ever becomes a real scenario.
  - Existing default/builtin rows in `skills_catalog`: **no migration, no data change, no deletion.** They keep resolving exactly as today via the unchanged first branch.
  - Tests: new backend test(s) extending `test_missing_dependency_signal.py`'s convention — a name present only in Ecosystem resolves to real instructions; a name present only in `skills_catalog` is unaffected; a name in neither still drops with the existing warning, unchanged.
  - Flag: reuse `ECOSYSTEM_AGENTSTUDIO_SKILLS` (or register a dedicated backend flag and close the frontend/backend flag-split gap `agentstudio-integration.md` already disclosed — see B-29).
  - Definition of done: an agent run referencing a Marketplace-only skill name resolves real instructions instead of silently dropping it; all existing agents referencing native skills are provably unaffected (regression test, not just inspection).

- **Task B-28 — `_CatalogTool` dispatch: route Ecosystem-sourced skill execution correctly**
  - **Spike first, size the rest of this task after.** This is the one piece prior passes (B-23/B-24) explicitly flagged as too deep/unfamiliar to modify safely without first understanding it — do not commit to an estimate here beyond "investigate before promising a date."
  - Files: wherever `_CatalogTool`'s dispatch decides how to fetch a tool/skill's content at execution time (not yet located as of this plan — B-27 depends on this being findable; if `_resolve_catalog_skills()` alone is sufficient to carry real instructions through to the agent's prompt without a separate dispatch-time fetch, this task may collapse into B-27 — confirm during the spike, don't assume).
  - Tests: an actual end-to-end agent run using a Marketplace-only skill, asserting the real skill content reached the model (not just that resolution returned a non-null object).
  - Flag: same as B-27.
  - Definition of done: a Marketplace skill attached to an agent node actually influences that agent's behavior at run time, verified by a real execution, not just by resolution-layer unit tests.

- **Task B-29 — Unify the Ecosystem-AgentStudio flag (optional, cleanup)**
  - Files: `core/config.py` (backend), `AgentStudio/frontend`'s env reading. Close the disclosed gap: today `VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS` (frontend-only) has no backend equivalent; harmless today only because `GET /ecosystem/capabilities` is unconditionally available regardless of any AgentStudio-specific flag.
  - Tests: existing flag-coverage test pattern (`core/config.py` import + assert-default, matching B-0's convention).
  - Flag: this task *is* the flag unification.
  - Definition of done: one flag (or one clearly-documented pair with an explicit relationship) gates both the picker merge and the runtime fallback — no deployment can have one half on and the other off without it being a deliberate, visible choice.

## Milestones

- **Phase 1 (ships independently, low risk)**: B-25, B-26. Fully satisfies "skills are created in the Marketplace only" on its own. No backend behavior change, no runtime risk.
- **Phase 2 (separate change, real behavior change)**: B-27, B-28 (spike first), B-29. This is what makes a Marketplace skill actually *work* inside Agent Studio, not just visible in the picker. Ship and verify independently of Phase 1 rather than bundling — matches this project's own stated reason for not rushing B-24's runtime half in the first pass.

## Explicitly out of scope for this plan

- Deleting any Agent Studio skill-creation code, table, or route.
- Migrating existing `skills_catalog` rows into `ecosystem_items`.
- Reworking the skill-approval/governance workflow (`draft`/`pending_approval`/`approved`/`rejected` states on `skills_catalog`) — it simply stops being exercised once B-25 ships, with no code change required.
- Org-scoping semantics for Marketplace skills used inside Agent Studio (Ecosystem installs are `org_id`-scoped; native Agent Studio skills are not) — flagged here as a real open question for whoever picks up B-27, not resolved by this plan.
