# LLD — Chat runtime integration

**Purpose**: makes installed, enabled skills actually usable inside a live conversation — a short index entry always present, full content fetched on demand, invocable by name. Entirely inert until an explicit flag is on, and even then scoped to one specific conversation path only. Tasks B-15 (tool contracts) and B-16 (the actual `agents/orchestrator.py`/`agents/tools.py`/`gateway.py` wiring) both landed in this milestone (M5).

## Files / functions

- **Task B-15 — tool contracts**: `mcp/ecosystem_skill_tools.py` — a new, isolated module (deliberately **not** added to `mcp/skill_registry.py`, a different concept entirely: in-memory composed tool-*sequences*, unrelated to the Ecosystem catalog; and deliberately not reusing `AgentStudio/backend/app/tools/platform_tools.py`'s own `read_skill_file`, which queries AgentStudio's own `skill_files`/`skills_catalog` tables via a sandboxed subprocess — a different system, a different storage layer). Implements:
  - `resolve_pinned_version_id(name, *, org_id, user_id, surface) -> str | None` — the one lookup a session-scoped caller (task B-16) calls **exactly once**, when it builds the skill index for a new conversation. Returns the caller's currently installed+enabled version for that surface, or `None` if no such install exists.
  - `skill_view(name, *, org_id, user_id, surface, pinned_version_id=None) -> str` / `read_skill_file(name, path, *, org_id, user_id, surface, pinned_version_id=None) -> str` — both re-check *authorization* against the install's *current* state on every call (a caller whose install was disabled/uninstalled/surface-removed since the pin was taken must not keep reading through a stale pin) but read *content* from `pinned_version_id` when supplied. Both raise `SkillNotFoundError` — the only error shape (`CONTRACTS.md` §12) — never leaking whether a skill exists if the caller can't see it.
  - `ECOSYSTEM_SKILL_TOOLS` — a tool-schema list (name/description/input_schema), shaped like `platform_tools.py`'s own `PLATFORM_TOOLS` convention for consistency, without importing or depending on that file.
  - `render_skill_index(skills) -> str` / `build_slash_command_lookup(skills) -> dict[str, str]` (task B-16) — pure rendering/lookup helpers over `resolver_service.get_effective_capabilities()`'s own `Capabilities.skills` shape.
  - `apply_chat_skill_integration(state, *, org_id, user_id, surface) -> None` (task B-16) — the actual integration logic, deliberately kept here rather than inline in `agents/orchestrator.py`, so it has a directly-testable surface that doesn't require mocking `run()`'s entire pipeline (compliance scanning, model routing, real LLM calls). Mutates an `AgentState` in place: always sets `state.metadata["ecosystem_skill_index"]` (possibly `""`); rewrites `state.question`/`state.raw_question` **only** when the current question is a recognized `"/name ..."` invocation of an installed+enabled+surface-matching skill. Never raises.
- **Task B-16 — the actual chat-path wiring**:
  - `agents/state.py` — **no change**. Uses the dataclass's existing generic `metadata: Dict[str, Any]` field rather than adding a new one — the narrowest possible touch to a class used across the whole orchestrator/tools/retriever/generator pipeline.
  - `agents/orchestrator.py` — `run()` gains one new optional keyword parameter, `ecosystem_surface: Optional[str] = None`. Immediately after `AgentState(...)` is constructed (before any other branch reads `state.question`/`raw_question` — the PCI compliance scan, the trivial-query fast-skip, `plan()`'s own complexity/domain classification), one additive block: `if core_config.ECOSYSTEM_CHAT_SKILLS and mode != "office" and ecosystem_surface: apply_chat_skill_integration(state, org_id=..., user_id=..., surface=ecosystem_surface)`. Every existing caller (which never passes `ecosystem_surface`) sees `ecosystem_surface=None`, so the condition is always false and this line never executes for them — provably byte-identical.
  - `agents/tools.py` — `generate_answer_tool()` gains one additive block, placed after every `prompt = <TEMPLATE>.format(...)` branch (including the office-mode `OFFICE_PROMPT` branch, though the append is itself gated `if mode != "office"` a second, redundant time) and before the "IN-HOUSE MODEL ESCALATION SUPPORT" section: if `state.metadata.get("ecosystem_skill_index")` is truthy, append it to `prompt`. With the flag off (or mode="office", or no surface supplied), that key is never set, `.get()` returns `None`, and `prompt` is unchanged.
  - `gateway.py` — `ask_ai()` gains one additive block immediately before its `agent.run(...)` call: computes `_ecosystem_surface` (only when `ECOSYSTEM_CHAT_SKILLS` is on and `q.mode != "office"`) per the surface-derivation rule below, and passes it as the new `ecosystem_surface=` keyword argument. With the flag off, `_ecosystem_surface` stays `None` and `agent.run()` receives exactly what every pre-existing call already sent it.
  - `services/ecosystem/config_service.py` — new `get_org_product_key(org_id) -> str`, a thin public wrapper around the existing `_resolve_product(org_id, None)` (task B-12's own entitlement-resolution read) — exposed so surface derivation can ask "which product is this org on" on *every chat turn* without paying `get_effective_config()`'s lazy-provisioning side effects (DB writes) that many times.

## API and DB changes

None — reads existing `ecosystem_items`/`ecosystem_installs`/`ecosystem_item_versions` tables and the existing content-hash-addressed object storage (`store/ecosystem_object_storage.py`).

## Sequence diagrams

```
Normal chat turn, non-office, ECOSYSTEM_CHAT_SKILLS on:

gateway.py ask_ai()
  → computes _ecosystem_surface (desktop | workspace_chat | chat, see below)
  → agent.run(..., ecosystem_surface=_ecosystem_surface)

agents/orchestrator.py OrchestratorAgent.run()
  → AgentState(...) constructed
  → apply_chat_skill_integration(state, org_id, user_id, surface)
      → get_effective_capabilities(org_id, user_id, surface)
      → state.metadata["ecosystem_skill_index"] = render_skill_index(skills)
      → if state.question/raw_question matches "/name ...":
          resolve namespace via build_slash_command_lookup(skills)
          skill_view(namespace, ...) -> body
          state.question = state.raw_question = f"{body}\n\n---\n\nUser request: {rest}"
  → (existing pipeline continues UNCHANGED: compliance scan, trivial-check,
     plan(), the plan-step iteration loop, PRE-GENERATION PCI check --
     all now operating on the possibly-rewritten state.question)
  → generate_answer_tool(state, llm)

agents/tools.py generate_answer_tool()
  → prompt = <TEMPLATE>.format(..., question=_raw_q)   # unchanged branches
  → if mode != "office" and state.metadata.get("ecosystem_skill_index"):
        prompt = f"{prompt}\n\n{skill_index}"
  → model_router.stream(prompt or [*_prior, {"role":"user","content":prompt}])
```

**Surface derivation** (`gateway.py`, task B-16's own instruction): `"desktop"` if `request.state.client_source == "desktop"`; else `"workspace_chat"` if `config_service.get_org_product_key(org_id) == "workspace"`; else `"chat"`. One hook covering both `chat` and `workspace_chat` — no separate code path for either, just a different string value flowing through the same `apply_chat_skill_integration()` call.

**Session-level pinning** (the mechanism `mcp/ecosystem_skill_tools.py`'s own docs describe, task B-15):
```
New conversation session starts
  → resolve_pinned_version_id(name, org_id, user_id, surface) for every
    installed+enabled+surface-matching skill -- ONCE, building the index
  → session stores {name: pinned_version_id} for the rest of the conversation

Mid-conversation: model calls skill_view("acme/foo") or read_skill_file("acme/foo", "path")
  → session passes its own stored pinned_version_id for "acme/foo" back in
  → skill_view()/read_skill_file() re-check CURRENT install state (still
    installed? still enabled? still surface-matched?) -- reject if not,
    even though a version is pinned
  → if authorized, read CONTENT from pinned_version_id, not whatever
    ecosystem_installs.version_id says right now
```
**Disclosed, not yet wired**: `apply_chat_skill_integration()` itself does not yet call `resolve_pinned_version_id()` up front and hold it across turns — each chat turn's slash-command handling resolves fresh (`skill_view(..., pinned_version_id=None)`), which is correct for a single-turn invocation but does not yet give a *multi-turn* conversation the "resolve once per session, reuse for the rest of it" guarantee CONTRACTS.md §12 describes. Wiring real session-level persistence (where would the pin actually live across a stateless request/response cycle — `state.user_ctx["session_id"]` keyed into some cache) is a real remaining increment, disclosed here rather than left silently unbuilt.

## Usage proof (item 7, 2026-09-27): structured logs + a chat UI chip

Before this, `apply_chat_skill_integration()` had zero logging on its success path (only a `logger.warning` if it raised, which it's designed to swallow) — live-diagnosing whether a real `/name ...` invocation actually worked was impossible from logs alone. Now, `core.logger.logger.info(...)` fires at exactly 3 points, each **name/version/surface/path only — never the skill's own instructions body or any bundled-file content**:
- `ECOSYSTEM_SKILL_RESOLVED → name=... version=... surface=...` — right after a slash token resolves to a real installed+enabled skill, before `skill_view()` is even called.
- `ECOSYSTEM_SKILL_INJECTED_AS_USER_MESSAGE → name=...` — right after `state.question`/`raw_question` are actually rewritten.
- `ECOSYSTEM_SKILL_VIEW`/`ECOSYSTEM_READ_SKILL_FILE → name=... version=... [path=...] surface=...` — inside `skill_view()`/`read_skill_file()` themselves, so ANY caller of either (not just the slash-command path — a future direct tool-call path gets this for free) is covered.

`apply_chat_skill_integration()` also now sets `state.metadata["ecosystem_skill_used"] = {"name": namespace, "display_name": ...}` when it rewrites the question. `agents/orchestrator.py`'s `run()` checks this immediately after calling it and, if set, `yield`s a new typed sentinel — `pipeline.stream_events.SkillUsedMarker` — following the exact existing `ToolMarker`/`ReasoningMarker` pattern (str-safe `__str__` returning `""`, a `to_event()` building `{"skill_used": {"name", "display_name"}}`). `gateway.py`'s Phase-5 SSE loop translates it to a real `data: {"skill_used": {...}}\n\n` frame — **unconditionally, not gated behind `_PIPELINE_V2_STREAM`** like tool/reasoning events, since this is a simple, always-relevant signal rather than v2 streaming detail. `ai-ui/src/components/Chat.jsx`'s SSE parser stores it on the message (`msg.skillUsed`), and `MessageMeta.jsx` renders a small "Using skill: `<display name>`" chip (`SkillUsedChip`, emerald, `Sparkles` icon — this file predates the Ecosystem initiative and stays on `lucide-react` rather than `@heroicons/react`, matching its own existing icon convention) whenever `msg.skillUsed` is present.

**Tests**: `test_ecosystem_skill_tools.py` gained `test_apply_chat_skill_integration_logs_resolution_and_injection_without_leaking_content` and `test_skill_view_logs_resolution_without_leaking_the_returned_body` — both patch `core.logger.logger.info` directly (structlog, not a plain stdlib logger — `caplog` has no established convention for it in this suite) and assert the real skill body/a distinctive marker string is present in the actual return value/question but absent from every captured log call. `ai-ui/src/components/MessageMeta.test.jsx` (new file) covers the chip's render/no-render conditions.

## Safety scoping + two live bugs (2026-09-27)

`mcp/ecosystem_skill_tools.py`'s `matches_installed_skill_slash_command(question, *, org_id, user_id, surface)` is the real membership check gating both `gateway.py`'s CIL ambiguity-clarification bypass and its `PIPELINE_V2` fast-path skill injection (`gateway.py:9397-9422`, `9452-9534`) — replacing an earlier, too-broad `^/\S+` syntax check. Fail-closed to `False` on any lookup error, so a broken check degrades to "treat it as an ordinary message," never to "treat everything as a skill invocation."

Two real bugs were found and fixed while live-verifying this, both now guarded by regression tests (`tests/test_gateway_ecosystem_chat_gate_safety.py`):
- A self-referencing closure in the fast-path's `_general_stream_with_skill_chip()` wrapper hung every skill-invoking chat request forever after the chip frame (Python late-binding: the closure's free-variable lookup resolved to the wrapper itself after the enclosing name was reassigned). Fixed by capturing the source generator under a name that's never reassigned.
- `ai-ui/src/components/Chat.jsx`'s final `__meta__`-triggered message update rebuilt the message from a stale pre-stream snapshot and never carried `skillUsed` forward, silently dropping the chip on every request regardless of lane. Fixed by tracking it as a local accumulator variable, same as `modelLabel`/`toolEvents`.

## Edge cases and errors

- **Pinning is split between two responsibilities, deliberately**: `mcp/ecosystem_skill_tools.py` has no notion of "session" at all — it only provides the pinning *mechanism* (`pinned_version_id` as an explicit parameter). The actual pinning *decision* (call `resolve_pinned_version_id()` once, hold onto the result for the conversation's lifetime) is task B-16's job, since only the chat runtime has a session concept. A test suite for this module alone can (and does) prove the mechanism works — `tests/services/ecosystem/test_ecosystem_skill_tools.py::test_pinned_version_id_keeps_returning_old_content_after_the_install_is_updated_to_a_new_version` simulates what a session would do (resolve once, then read again after an update lands) — but the *guarantee that a real running conversation actually does this* is only real once B-16 exists.
- **A stale pin never bypasses authorization** — `test_pinned_version_id_still_re_checks_current_authorization` confirms a disabled install rejects a previously-pinned `skill_view()` call. Only the *version* is allowed to stay pinned; whether the caller can read *anything* for that skill at all is always re-checked fresh.
- **CONTRACTS.md §12's "FILE_TOO_LARGE-shaped error for binary files" branch of `read_skill_file` is currently unreachable and not implemented against it**: every bundled file in this platform's actual creation pipeline (`create_service.py`'s write/upload/import payloads, `versions_service.py`'s `encode_envelope`) is stored as text — there is no binary-file creation path yet. Disclosed in the module's own docstring rather than built against a scenario that can't occur.
- **A real, disclosed interaction between two independently-designed limits**: the gate's `manifest_stage.py` rejects any bundled file over 64KB (task B-8) — strictly smaller than `read_skill_file`'s own 256KB read limit (`CONTRACTS.md` §12). This means no file that ever actually *passes the gate* can be large enough to exercise `read_skill_file`'s truncation branch through the real `create_via_write` → gate → install pipeline. The corresponding test writes the version/object-storage rows directly (bypassing `create_service`/the gate) to still exercise the code path for real, rather than fabricate a scenario the real pipeline could never produce — see the test file's own comment for the full reasoning.

## Flags

`ECOSYSTEM_CHAT_SKILLS` (`core/config.py`, default off) gates the entire integration: `mcp/ecosystem_skill_tools.py`'s tools (meaningless with nothing calling them), task B-11's resolver, and now `agents/orchestrator.py`'s `run()`/`agents/tools.py`'s `generate_answer_tool()` additive blocks. With it off, `agents/orchestrator.py`'s guard condition is always false and `gateway.py` never even computes `_ecosystem_surface` (stays `None`) — the live chat path is provably unreached by any of this task's code.

## Tests

- `tests/services/ecosystem/test_ecosystem_skill_tools.py` (11 tests, task B-15): basic `skill_view`/`read_skill_file` reads; 8,000-character truncation; 256KB truncation (via the direct-DB-setup workaround above); `NOT_FOUND` for never-installed, disabled, wrong-surface, cross-org, and undeclared-path cases; the two pinning-mechanism tests.
- `tests/services/ecosystem/test_orchestrator_ecosystem_chat_skills.py` (6 tests, task B-16) — **the single most safety-critical test in this whole phase**, since `agents/orchestrator.py`'s `run()` is the live production chat path (`gateway.py:ask_ai()` → `agent.run()`, reached on every non-office message). Drives the real `OrchestratorAgent.run()` control flow (classifier mocked to avoid a real LLM slow-path call; `generate_answer_tool` mocked to capture the `state` it receives, rather than making a real model call) and proves:
  1. Flag off, with a slash-command-shaped message → `state.question`/`raw_question` untouched, `state.metadata` has no `ecosystem_skill_index` key.
  2. `ecosystem_surface=None` (every caller before this task existed never passes it) → same, even with the flag on.
  3. `mode="office"` → same, regardless of flag or surface.
  4. Flag on + surface + a non-slash message → the index gets attached, but the question is untouched.
  5. Flag on + surface + a real installed skill's slash command → the question is rewritten to the skill body + the rest of the message.
  6. Flag on + surface + an unrecognized slash command → question untouched (no crash, no false match).
- **Full regression, run against a real Postgres 16 + Redis 7 instance**: `pytest tests/auth tests/config tests/core tests/agents tests/store tests/cil tests/db tests/services/ecosystem` → 24 failed / 692 passed. `scripts/ci/compare_test_failures.py` flagged one as new: `tests/config/test_validate_prod_config.py::test_fails_when_jwt_missing_in_prod`. **Confirmed via `git stash` to the prior commit (before any B-16 code existed) that this exact failure is already present there too** — genuinely pre-existing, not a B-16 regression, and not previously in `scripts/ci/known_failures.txt`'s baseline (plausibly a Windows-local-only flake, given the test's own fixture surfaces a `WindowsPath`; not independently verified against Linux). Disclosed, not fixed — out of scope for this task, and the real CI baseline (which runs on Ubuntu) is the authoritative source of truth for whether it needs adding to `known_failures.txt`, not this local Windows run.
- `agents/orchestrator.py`/`agents/tools.py`/`gateway.py` full syntax validity confirmed (`python -m py_compile`); a full `gateway.py` process boot was not performed in this environment (requires production-shaped infra -- Kafka, full LLM provider config -- beyond what this milestone's throwaway Postgres/Redis verification setup provides) -- the new code paths were instead verified via the direct-call regression suite above, which exercises the exact `agent.run(..., ecosystem_surface=...)` signature `gateway.py` now calls.

## Item 6 — adding skills from chat

**Purpose**: six named chat-initiated ways to get a skill into the catalog, all going through the exact same `create_service`/`gate_service`/`installs_service` paths every other creation method already uses — no chat-specific fast path, license check, or permission model.

- **Design rule for every chat-recognized flow**: explicit, button-triggered actions, never guessed intent from free text. "Update my &lt;skill&gt;," "attach a file + add as skill," "save this message as a skill," and "import from a URL" are all reachable only via a real UI affordance (a menu button, a per-message action, a modal) — none of them parse a chat message's own text for an intent phrase. This keeps the mechanism honest and testable; a future task adding real free-text intent recognition on top of these same explicit actions is a separate, larger undertaking, not bundled here.
- **New backend capability**: `services/ecosystem/create_service.py`'s `add_version_to_existing_item()` / `add_version_to_existing_item_from_upload()` — an immutable new version of an **existing** item (never a new `EcosystemItem` row), gated by `_require_owner_or_admin()` (owner or `marketplace:provision`, mirroring `compute_allowed_actions()`'s own is-owner-or-admin rule for `deprecate`) and the same `is_allowed_license()` check every other creation path uses. New router endpoints `POST /ecosystem/items/{id}/new-version` (JSON) and `.../new-version/upload` (multipart). A new gate trigger, `chat_update_version` (`gate_service.py`'s `_UPDATE_VERSION_TRIGGERS`), makes a passing/warn-ing re-gate call `_bump_own_install_on_pass()` — moves the caller's own existing install onto the new version automatically, the same effect `POST /ecosystem/installs/{id}/update` already has, just triggered by the gate resolving instead of a second manual call.
- **`ai-ui/src/components/EcosystemBrowseSkillsPanel.jsx`** — superseded 2026-09-27, deleted. The chat "+" menu's "Browse skills" entry now opens **`ai-ui/src/components/EcosystemBrowseSkillsModal.jsx`**, a thin wrapper around `packages/ecosystem-ui`'s real `<Marketplace>` (`layout="compact"`, a self-contained fake router — local `useState`, not `react-router` — so Marketplace's own Detail-page drill-down works inside a modal overlay without touching the app's URL bar) rather than a second, bespoke browse UI. The old panel's search/Add/enable-toggle/"Manage in Marketplace" all become the real Marketplace's own Discover/Yours/`AddDialog`/kebab-toggle UI; upload and GitHub-URL import go through `AddMenu`'s existing "Upload"/"Import from GitHub / URL" entries (`UploadFlow.tsx`/`ImportFlow.tsx`) instead of the panel's own bespoke `UploadAsSkillButton`/`ImportSkillModal`. **Disclosed gap, not carried forward**: the old panel's file-upload-based "Update" button (`POST /ecosystem/items/{id}/new-version/upload`, still a real, working backend endpoint) has no UI equivalent inside the embedded Marketplace — only Detail's "Edit" tab (manual text editing) does; a real, known simplification, not an oversight.
- **"Save this as a skill"** — `CreateWithAiModal.jsx` gained an optional `initialIntent` prop; a new button in `Chat.jsx`'s user-message hover action bar (heroicons `SparklesIcon` — this initiative's own icon-set rule; every other icon in `Chat.jsx` predates it and correctly stays on `lucide-react`) opens Create-with-AI pre-seeded with that message's text.
- **Live "/" menu updates without a reload**: `ai-ui/src/hooks/useEcosystemChatSkills.js` now also subscribes to `GET /ecosystem/events/stream` (task B-13) and refetches capabilities on any `ecosystem.changed` event, rather than only on mount. Before this, `disable-in-chat.spec.ts` (task B-16/F-11) needed an explicit `page.reload()` to observe a state change — that spec is unchanged (still correct, since a reload also works), but a new E2E spec proves the no-reload path now works too.
- **Scope enforcement, reusing the same-day `caller_permissions` fix (`LLD/config-products.md`)**: `add_version_to_existing_item*()` never takes a scope at all (a version update, not a re-install); `submit_draft()` (Create-with-AI) never threads a `provision_scope` through regardless of who's calling, so every chat-created item's install is always `scope="private"`; the Browse-skills panel's Add button always installs `scope: "private"`. A normal user has no path to an org-wide/Required install from chat — structurally (no such UI exists anywhere in this flow) and server-side (the underlying `install_item` endpoint's own scope check, commit `300d3a5`, rejects a forged attempt regardless of which UI — or lack of one — made the call).
- **Disclosed, not built in this pass**: "attach a .zip/.skill + add as skill" is its own standalone button in the Browse-skills panel, not wired into `Chat.jsx`'s existing message-attachment pipeline (a different, RAG/doc-QA-purposed upload system) — reusing that pipeline for an unrelated purpose risked a much larger change to a live, unfamiliar part of the chat surface for no functional difference in the real backend behavior. "Import from a URL" only supports `github_repo` (a `github.com/<owner>/<repo>` URL) — `well_known` (the other real import kind, task I) needs only a second form field to reach from the same modal, not built here.

## How to extend

A new tool needing the same pinning mechanism: add it to `mcp/ecosystem_skill_tools.py`, take `pinned_version_id` as an optional parameter exactly like the existing two, and re-check current authorization state before reading pinned content — never skip that re-check, even for a low-risk-seeming addition. A new surface: add it to `ecosystem_surfaces` (already a registry, not an enum — `LLD/config-products.md`) and extend `gateway.py`'s surface-derivation `if`/`else` chain; nothing in `agents/orchestrator.py`/`agents/tools.py` needs to change, since both already treat `surface` as an opaque string. A new chat-initiated creation flow: reuse `_require_owner_or_admin()`/the existing `create_service` functions rather than a new permission check, and keep the action explicit (a button, not parsed free text), per item 6's own design rule above.
