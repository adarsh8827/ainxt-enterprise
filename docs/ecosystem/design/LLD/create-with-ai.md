# LLD — Guided creation ("Create with AI")

**Purpose**: a staged, conversational flow for drafting a new skill — the user describes what they want, a generation pipeline proposes a full draft, the user reviews/edits it, and only an explicit confirmation turns it into a real catalog item (which then goes through the same verification gate as anything else). Landed in M5, task B-14.

## Files / functions

- **Process-model verification (completed as part of this task's design, not deferred)**: production serves AgentStudio in-process with the main gateway — `gateway.py` inserts AgentStudio's packages onto `sys.path` and mounts its routers directly; `AgentStudio/backend/Dockerfile`'s own comment states this explicitly and notes the standalone `:8002` service is dev-only. **Decision**: integrate via a direct in-process call, behind a thin adapter interface, exactly as originally planned — confirmed correct, not revisited.
- `services/ecosystem/skill_factory_adapter.py` (new) — `SkillFactoryAdapter.generate(intent: str) -> AsyncIterator[DraftTurn]`, the *only* implementation `drafts_service.py` ever calls. `DraftTurn` is `{stage, text, data}` — `stage` values: `intent`, `blueprint`, `bundle` (only when the blueprint's own `needs_bundle` is true), `content`, `critique`, `assembled` (terminal, carries the final draft payload in `data["assembled"]`).
- `services/ecosystem/drafts_service.py` (B-3's stub, filled in) — `create_draft()`, `stream_draft_generation()`, `get_draft()`, `patch_draft()`, `submit_draft()`, `purge_abandoned_drafts()`.
- `routers/ecosystem_router.py` — `POST /ecosystem/drafts` (SSE), `GET`/`PATCH /ecosystem/drafts/{id}`, `POST /ecosystem/drafts/{id}/submit`.
- `db/models.py` — `EcosystemDraft` ORM model (the `ecosystem_drafts` table existed since M1's migration; no ORM model until this task first needed to query it, per this file's own pairing convention, `LLD/data-model.md`).

## API and DB changes

No new tables — `ecosystem_drafts` (M1) gets its first real reader/writer and its first ORM model. `submit_draft()` calls `create_service.create_via_write()` — the *exact same* creation path (and gate) as a manual write, never a fast path.

## Sequence diagrams

```
POST /ecosystem/drafts {item_type, intent}, Idempotency-Key required
  → cache hit (same key already used)? stream the existing draft's current
    state as a single "assembled" frame, create nothing new
  → else: drafts_service.create_draft() (status="drafting", draft_content={})
    → cache (user_id, Idempotency-Key) -> draft_id
    → drafts_service.stream_draft_generation(draft_id, intent):
        SkillFactoryAdapter().generate(intent):
          SkillIntentParser().parse(intent)                    -> "intent" turn
          SkillBlueprintGenerator().generate(minimal requirements) -> "blueprint" turn
          _draft_and_bundle(blueprint)  [AgentStudio/backend/app/api/factories.py,
                                          reused directly -- bundle decider only
                                          runs if blueprint.needs_bundle]
                                                                 -> "bundle"/"content" turns
          _lint_summary(content)                                -> "critique" turn
          SkillAssembler().assemble(...)                        -> "assembled" turn (terminal)
        on "assembled": merge the result into draft_content (namespace defaulted to
          "<org_id>/<blueprint-name>", license defaulted to MIT), set status="ready"
    → each DraftTurn relayed to the client as one SSE frame

GET /ecosystem/drafts/{id}        -> current draft_content + status
PATCH /ecosystem/drafts/{id}      -> user edits merge into draft_content
                                      (namespace/display_name/description/category/
                                      tags/license/instructions/files/surfaces)
                                      rejected once status is submitted/abandoned

POST /ecosystem/drafts/{id}/submit, Idempotency-Key required
  → cache hit? return the original response verbatim (no second item)
  → else: create_service.create_via_write(...) from draft_content
      (fails if draft_content has no namespace -- PATCH one first)
    → stamps ecosystem_drafts.submitted_item_id, status="submitted"
    → cache the response under (user_id, Idempotency-Key)
```

## Edge cases and errors

- **The interactive clarification stage is deliberately skipped, not reproduced.** AgentStudio's own `/skill-factory/chat` endpoint has a full back-and-forth (`SkillClarificationEngine`'s "ask a follow-up question" loop) before it ever generates a blueprint. `CONTRACTS.md` §10's draft endpoint set has no "reply to a clarifying question" route at all — the next interaction point after generation is `PATCH` (direct edit), not more chat turns. `SkillFactoryAdapter.generate()` instead builds a minimal `requirements` dict straight from the caller's `intent` string (`{"purpose": intent, "triggers": intent}`), mirroring the exact fallback shape `factories.py`'s own `plan_card`/`suggest_existing` branches already use when no interactive answers exist yet — not an invented shortcut, a reuse of an existing fallback path.
- **Reused, not reinvented: `_draft_and_bundle()` and `_lint_summary()`** (both private, module-level functions in `AgentStudio/backend/app/api/factories.py`) are imported and called directly, exactly like that file's own `/skill-factory/chat` "confirm" stage already reaches into `skill_factory/pipeline.py`'s private `_call_llm`/`_parse_json` — an established precedent in this codebase for reusing tested private helpers across a module boundary rather than duplicating ~15 lines of non-trivial logic (bundle-decision + content generation + lint) a second time.
- **Never touches AgentStudio's own session store or legacy tables.** The adapter constructs its own throwaway `SkillFactorySession` instance and never calls `get_or_restore_skill_session()`/`persist_skill_session()` (both read/write AgentStudio's own `workflow_repo`-backed factory-session table) — confirmed by `test_drafts_service_never_imports_anything_under_agentstudio_directly` (a source-grep test) plus a functional test asserting zero writes to `skills_catalog`/`skill_files` reach AgentStudio's own tables via this path.
- **Default namespace assumes `org_id` is already slug-shaped.** `stream_draft_generation()` defaults a fresh draft's namespace to `f"{slugify(org_id)}/{slugify(blueprint_name)}"` — reasonable for this codebase's existing `org_id` convention (a free-text `VARCHAR(255)`, per `LLD/data-model.md`, and the platform's existing `'default'` single-org sentinel is already slug-shaped), but a caller is always free to `PATCH` a different namespace before submitting; `submit_draft()` fails clearly (`"has no namespace set"`) rather than guessing if it's ever missing.
- **Idempotency is real, not cosmetic — and applied only to this task's own two endpoints, not retrofitted onto the pre-existing `POST /ecosystem/items`.** `CONTRACTS.md` §4 requires `Idempotency-Key` on both `POST /ecosystem/items` and `POST /ecosystem/drafts`/`.../submit` — a direct inspection of `routers/ecosystem_router.py` before this task found the *existing* `POST /ecosystem/items` endpoint (task B-6) never actually enforces or reads that header at all. Fixing that pre-existing gap is out of this task's own scope (a different task's endpoint); disclosed here rather than silently left unmentioned. This task's own two endpoints correctly return `400` for a missing header and use `idempotency_service.get_cached_response()`/`store_response()` (task B-20's existing Redis-backed cache) so a retry with the same key never creates a second draft/item.
- **SSE idempotency is draft-creation-only, not stream-replay.** A retried `POST /ecosystem/drafts` with an already-used key does not re-run generation or replay the original turn-by-turn stream verbatim (streams aren't cacheable the way a plain JSON response is) — it streams the already-generated draft's *current* state as a single `"assembled"` frame instead. This satisfies `CONTRACTS.md` §4's actual requirement ("rather than creating a second draft") without overclaiming byte-for-byte stream replay, which was never asked for.

## Flags

`Idempotency-Key` is a *required-header validation*, not a feature flag (`CONTRACTS.md` §4) — matching task B-14's own definition of done, which deliberately frames it this way rather than as an `ECOSYSTEM_*` toggle.

## Tests

- `tests/services/ecosystem/test_drafts_service.py` (10 tests) — every test mocks `SkillFactoryAdapter.generate()` itself (never the underlying AgentStudio pipeline, which needs a real LLM call and the full AgentStudio import chain) per this task's own stated test requirement. Covers: the source-level AgentStudio-isolation guarantee; draft creation starts empty/`drafting`; generation populates `draft_content` and sets `ready`; cross-org isolation on generation; `PATCH` merges without clobbering other fields and is rejected once `submitted`/`abandoned`; `submit` creates a real item through the normal gate and stamps `submitted_item_id`; submitting without a namespace fails clearly; submitting twice raises rather than creating a second item; the abandoned-draft purge job's dry-run doesn't delete.
- `tests/services/ecosystem/test_ecosystem_router_http.py` (+3 tests, real HTTP via `TestClient`) — both draft-mutating endpoints reject a missing `Idempotency-Key` with `400`; a full `POST /ecosystem/drafts` (SSE, mocked adapter) → `GET` → `PATCH` → `POST .../submit` round trip over real HTTP, including the submit-retry-returns-the-same-item idempotency guarantee.
- Full regression (`tests/db tests/services/ecosystem`, real Postgres/Redis): 293 passed, 0 regressions.

## How to extend

If AgentStudio's process model ever changes (e.g. it stops running in-process with the gateway), only `skill_factory_adapter.py`'s implementation needs to change — no caller in `drafts_service.py` (or the router) should need to change, since they only ever see `DraftTurn` objects from `SkillFactoryAdapter.generate()`. A future task wiring `Idempotency-Key` onto the pre-existing `POST /ecosystem/items` (the disclosed gap above) should reuse the exact same `idempotency_service.get_cached_response()`/`store_response()` pattern this task established for the two draft endpoints.
