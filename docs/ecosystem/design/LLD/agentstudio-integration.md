# LLD — AgentStudio integration (Ecosystem → AgentStudio direction)

**Purpose**: the opposite direction from `LLD/legacy-bridge.md` (which surfaces AgentStudio's own content *into* the Ecosystem catalog, read-only). This file covers the reverse: making Ecosystem-installed capabilities usable *from inside* AgentStudio's own UI and runtime. A 15th LLD file, added in M5 when tasks B-23/B-24 needed a home — none of D-0's original 13 areas fit (matching the precedent `desktop-local-cache.md` set as a 14th, added later for a new area).

## Files / functions

- **Task B-23 — "missing dependency" surfacing**: `AgentStudio/backend/app/engine/native_engine.py`'s `NativeEngine._resolve_catalog_tools()` gains one new optional parameter, `missing_dependencies: Optional[list] = None`. The method's own two existing tool-drop sites (a catalog lookup that raised, or one that returned nothing) each gain one additive line: `if ECOSYSTEM_AGENTSTUDIO_MISSING_DEP and missing_dependencies is not None: missing_dependencies.append(tool_name)`. The flag itself is read defensively — `from core.config import ECOSYSTEM_AGENTSTUDIO_MISSING_DEP` wrapped in `try/except ImportError` (falls back to `False`) — since `AgentStudio/backend/app/core/config.py` is a *separate* config module from the main repo's `core/config.py`, and AgentStudio's standalone dev-mode service (`:8002`, not used by any compose service, per `AgentStudio/backend/Dockerfile`'s own comment) has no path back to the main repo's module at all.
- **Task B-24 — skill picker merges Ecosystem skills**: `_TBD_` (not yet built — see the Skills Phase plan's own task list for the exact scope: `AgentStudio/frontend/src/components/common/CatalogPicker.jsx` additionally calling `GET /ecosystem/capabilities?surface=agent_studio` when `ECOSYSTEM_AGENTSTUDIO_SKILLS` is on, merging the result into the picker's existing list with a distinguishing badge).

## API and DB changes

None. `_resolve_catalog_tools()`'s own DB reads (`workflow_repo.get_tool()`, AgentStudio's `tools_catalog`) are completely unchanged — this task never writes anywhere, and never touches the Ecosystem catalog's own tables either (that's task B-24's job, via a read-only `GET /ecosystem/capabilities` call, not a DB read from AgentStudio's backend directly).

## Sequence diagrams

```
NativeEngine._resolve_catalog_tools(requested, ..., missing_dependencies=None)
  → for each requested tool name:
      lookup in tools_catalog (async, concurrent via asyncio.gather)
      → found: wrap as _CatalogTool, append to the returned tools list (unchanged)
      → not found / lookup raised:
          log a warning (unchanged, always happens)
          IF ECOSYSTEM_AGENTSTUDIO_MISSING_DEP and a caller passed a list:
            append tool_name to that list  <- the only new behavior
  → return tools  (the SAME list shape as before this task -- never changed)
```

## Edge cases and errors

- **`NativeEngine` is a shared singleton across concurrent requests** (its own docstring cites `self._singleton_tool_cache` — "Singleton tool cache for platform utilities that never change at runtime"). This ruled out the obvious-looking design of recording missing dependencies as instance state (`self.missing_dependencies = [...]`) — that would leak one request's missing-dependency list into a completely unrelated concurrent request's response. The out-parameter design (`missing_dependencies: Optional[list] = None`, populated per-call, never stored on `self`) avoids this entirely — enforced by `test_missing_dependencies_is_never_stored_on_self`, a real regression test for exactly this failure mode, not just a design note.
- **Seven existing call sites, only one signature change, zero behavior change for six of them.** `_resolve_catalog_tools()` has 7 call sites across `native_engine.py`, each in a different execution context (top-level agent run, sub-agent construction, workflow node re-entry, etc.). None of them pass `missing_dependencies` — the parameter's default (`None`) means every one of the drop-site checks (`missing_dependencies is not None`) is false regardless of the flag, so this task changed the *signature* (additive-only, a new optional kwarg) without changing *behavior* at any of the 7 sites.
- **Disclosed, deliberately not implemented in this pass: wiring the signal all the way to a specific user-visible UI surface.** `_resolve_catalog_tools()` now has a real, tested mechanism for a caller to *ask* for the missing-dependency list — but no call site yet actually passes one and threads it into a response the AgentStudio frontend renders. Confidently identifying *which* of the 7 call sites is "the one the calling UI reads from," and what response shape that UI already expects, requires deeper context on `native_engine.py`'s ~8,000-line control flow and its frontend counterpart than this pass could safely acquire without risking a mistake in unfamiliar, live, production code (`native_engine.py` could not even be imported standalone for testing in this environment — see Tests below — underscoring how deep and load-bearing this file's own dependency chain is). This is the resolver-side half of B-23, fully correct and independently useful (any future caller can opt in immediately); the UI-wiring half is a real, named follow-up, not silently dropped.

## Flags

`ECOSYSTEM_AGENTSTUDIO_MISSING_DEP` (`core/config.py`, default off) — task B-23. `ECOSYSTEM_AGENTSTUDIO_SKILLS` (`core/config.py`, default off) — task B-24, not yet built.

## Tests

`AgentStudio/backend/tests/test_missing_dependency_signal.py` (5 tests) — source-string style, matching the existing convention `test_sample_doc.py`'s own native-engine plumbing checks already established in this file (importing `native_engine.py` directly pulls in the main repo's `core.*` stack; confirmed directly — a standalone import attempt from this environment hung rather than completing, even with both the repo root and `AgentStudio/backend` on `PYTHONPATH`). Covers: the flag is read defensively with a fail-closed fallback; the new parameter is optional with a `None` default; both drop sites record when the flag is on and a list was supplied; the original warning logs are untouched; the missing-dependency state is never stored on `self`. `AgentStudio/backend/tests/test_sample_doc.py`'s own 11 pre-existing tests re-run after this change: unaffected.

## How to extend

Task B-24 (not yet built): a new `GET /ecosystem/capabilities?surface=agent_studio` call from `CatalogPicker.jsx`, merged client-side — the existing `GET /skills-catalog` endpoint and its response shape must stay untouched (per the Skills Phase plan's own "why additive, not a modification" reasoning). Wiring B-23's missing-dependency signal to an actual UI surface: identify the specific call site among the 7 that corresponds to "a user is looking at this agent's configuration/run in the UI" (most likely the top-level agent-run entry point, not a sub-agent/workflow-node re-entry path), pass it a list, and thread the result into whatever response schema that endpoint already returns — a scoped follow-up task, not a blind guess.
