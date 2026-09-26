# LLD — Chat runtime integration

**Purpose**: makes installed, enabled skills actually usable inside a live conversation — a short index entry always present, full content fetched on demand, invocable by name. Entirely inert until an explicit flag is on, and even then scoped to one specific conversation path only. Task B-15 (tool contracts) landed in this milestone (M5); task B-16 (the actual `agents/orchestrator.py` wiring) is still `_TBD_` below.

## Files / functions

- **Task B-15 — tool contracts**: `mcp/ecosystem_skill_tools.py` — a new, isolated module (deliberately **not** added to `mcp/skill_registry.py`, a different concept entirely: in-memory composed tool-*sequences*, unrelated to the Ecosystem catalog; and deliberately not reusing `AgentStudio/backend/app/tools/platform_tools.py`'s own `read_skill_file`, which queries AgentStudio's own `skill_files`/`skills_catalog` tables via a sandboxed subprocess — a different system, a different storage layer). Implements:
  - `resolve_pinned_version_id(name, *, org_id, user_id, surface) -> str | None` — the one lookup a session-scoped caller (task B-16) calls **exactly once**, when it builds the skill index for a new conversation. Returns the caller's currently installed+enabled version for that surface, or `None` if no such install exists.
  - `skill_view(name, *, org_id, user_id, surface, pinned_version_id=None) -> str` / `read_skill_file(name, path, *, org_id, user_id, surface, pinned_version_id=None) -> str` — both re-check *authorization* against the install's *current* state on every call (a caller whose install was disabled/uninstalled/surface-removed since the pin was taken must not keep reading through a stale pin) but read *content* from `pinned_version_id` when supplied. Both raise `SkillNotFoundError` — the only error shape (`CONTRACTS.md` §12) — never leaking whether a skill exists if the caller can't see it.
  - `ECOSYSTEM_SKILL_TOOLS` — a tool-schema list (name/description/input_schema), shaped like `platform_tools.py`'s own `PLATFORM_TOOLS` convention for consistency, without importing or depending on that file.
- **Task B-16 — the actual chat-path wiring**: `_TBD_`.

## API and DB changes

None — reads existing `ecosystem_items`/`ecosystem_installs`/`ecosystem_item_versions` tables and the existing content-hash-addressed object storage (`store/ecosystem_object_storage.py`).

## Sequence diagrams

```
New conversation session starts (task B-16, not yet built)
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

## Edge cases and errors

- **Pinning is split between two responsibilities, deliberately**: `mcp/ecosystem_skill_tools.py` has no notion of "session" at all — it only provides the pinning *mechanism* (`pinned_version_id` as an explicit parameter). The actual pinning *decision* (call `resolve_pinned_version_id()` once, hold onto the result for the conversation's lifetime) is task B-16's job, since only the chat runtime has a session concept. A test suite for this module alone can (and does) prove the mechanism works — `tests/services/ecosystem/test_ecosystem_skill_tools.py::test_pinned_version_id_keeps_returning_old_content_after_the_install_is_updated_to_a_new_version` simulates what a session would do (resolve once, then read again after an update lands) — but the *guarantee that a real running conversation actually does this* is only real once B-16 exists.
- **A stale pin never bypasses authorization** — `test_pinned_version_id_still_re_checks_current_authorization` confirms a disabled install rejects a previously-pinned `skill_view()` call. Only the *version* is allowed to stay pinned; whether the caller can read *anything* for that skill at all is always re-checked fresh.
- **CONTRACTS.md §12's "FILE_TOO_LARGE-shaped error for binary files" branch of `read_skill_file` is currently unreachable and not implemented against it**: every bundled file in this platform's actual creation pipeline (`create_service.py`'s write/upload/import payloads, `versions_service.py`'s `encode_envelope`) is stored as text — there is no binary-file creation path yet. Disclosed in the module's own docstring rather than built against a scenario that can't occur.
- **A real, disclosed interaction between two independently-designed limits**: the gate's `manifest_stage.py` rejects any bundled file over 64KB (task B-8) — strictly smaller than `read_skill_file`'s own 256KB read limit (`CONTRACTS.md` §12). This means no file that ever actually *passes the gate* can be large enough to exercise `read_skill_file`'s truncation branch through the real `create_via_write` → gate → install pipeline. The corresponding test writes the version/object-storage rows directly (bypassing `create_service`/the gate) to still exercise the code path for real, rather than fabricate a scenario the real pipeline could never produce — see the test file's own comment for the full reasoning.

## Flags

`ECOSYSTEM_CHAT_SKILLS` gates both this module's only real caller (task B-16, not yet built) and task B-11's resolver — with the flag off, nothing calls `mcp/ecosystem_skill_tools.py` at all, so it ships dark by default (consistent with the resolver's own flag note in `LLD/resolver.md`).

## Tests

`tests/services/ecosystem/test_ecosystem_skill_tools.py` (11 tests): basic `skill_view`/`read_skill_file` reads; 8,000-character truncation; 256KB truncation (via the direct-DB-setup workaround above); `NOT_FOUND` for never-installed, disabled, wrong-surface, cross-org, and undeclared-path cases (never a different error shape, never a 403 that would confirm a path's existence); the two pinning tests described above.

_The flag-off regression suite proving zero behavior change to the live chat path is task B-16's own test, not this file's — B-15 has no integration point into `agents/orchestrator.py` at all yet, so there is nothing for a flag-off test to prove here._

## How to extend

A new tool needing the same pinning mechanism: add it to this module, take `pinned_version_id` as an optional parameter exactly like the existing two, and re-check current authorization state before reading pinned content — never skip that re-check, even for a low-risk-seeming addition.
