# LLD — Legacy bridge

**Purpose**: surfaces pre-existing, already-governed content in the new marketplace catalog as read-only entries, without ever writing back to (or otherwise affecting the behavior of) the systems that actually own that content. Backfill job landed in task B-4 (M1); the rest of the marketplace (create/install/gate) that would make these entries actually installable lands in later milestones.

## Files / functions
- `services/ecosystem/legacy_bridge.py` — **read-only**. `list_behavioral_skills_pg_items()` queries `SkillRecord` directly (behavioral-type only — see Edge cases below). `list_agentstudio_skills()` (`async`) calls AgentStudio's own `AgentStudio/backend/app/core/workflow_repo.py::list_skills()`, never a direct query against AgentStudio's tables, and returns `[]` rather than raising if AgentStudio isn't importable/configured in this deployment. `slugify()` turns an arbitrary name/org_id into a namespace-segment-safe slug.
- `scripts/ecosystem/backfill_legacy_items.py` — the only writer. `main()` reads the two `ECOSYSTEM_LEGACY_BRIDGE_*` flags and runs `_backfill_skills_pg()` / `_backfill_agentstudio()` independently (either can be skipped without affecting the other). Re-runnable: matched by `(legacy_source, legacy_ref)`, so running it again is a no-op for already-mirrored items and only mirrors what's new.
- Calls into `services/ecosystem/publishers_service.py` (namespace resolution), `items_service.py` (`get_or_create_local_source`, `upsert_legacy_pointer_item`), `versions_service.py` (`create_or_refresh_legacy_version`), and `gate_service.py` (`enqueue_gate_run`) — the backfill job itself contains no direct DB writes; every write goes through the service layer.

## API and DB changes
No new tables (uses the ones task B-1 already created). Every backfilled item gets:
- An `ecosystem_items` row: `scope='org_private'`, `trust_tier='org'`, `license='MIT'` (the platform default for platform-created/mirrored content — `skills_pg` and `skills_catalog` have no license concept of their own to read), `legacy_source`/`legacy_ref` set, `source_id` pointing at **that item's own org's** `local` `ecosystem_sources` row (auto-provisioned if it doesn't exist yet — never a shared platform-wide row; see the M0-review fix in `CHANGELOG.md`).
- An `ecosystem_item_versions` row, `gate_verdict='pending'`. Its `content_hash`/`object_key` are real — the legacy content's current text is hashed and written into `store/ecosystem_object_storage.py` — but this is a scan target for the (not-yet-built) gate, not the item's source of truth: a live read of a legacy item's content still goes to the legacy table, per the read-through design. If the legacy owner edits the content, the next backfill run computes a different hash and writes a *new* version row rather than updating the old one (versions are immutable, matching every other item's version history) — so a content change is never silently absorbed into an already-gated version.
- An `ecosystem_gate_runs` row, `verdict='pending'`, `trigger='admin_provision'`. Nothing runs against it yet — `gate_service.enqueue_gate_run()` is real, but the actual verification stages don't exist until task B-8/B-9 (M2).

## Sequence diagrams
```
backfill_legacy_items.py
    │
    ├─ list_behavioral_skills_pg_items() ──► SkillRecord (skill_type='behavioral' only)
    ├─ list_agentstudio_skills() ──► AgentStudio.workflow_repo.list_skills() (read-only, graceful no-op if unavailable)
    │
    for each legacy skill:
    ├─ publishers_service.resolve_publisher(org_slug/name_slug, owner_type='org', owner_ref=org_id)
    ├─ items_service.upsert_legacy_pointer_item(...) ──► ecosystem_items (matched by legacy_source+legacy_ref)
    ├─ versions_service.create_or_refresh_legacy_version(...) ──► ecosystem_item_versions (+ object storage put)
    └─ gate_service.enqueue_gate_run(...) ──► ecosystem_gate_runs (verdict='pending')
```

## Edge cases and errors
- **A gate-failed legacy item is hidden by its latest `gate_verdict`, not by overloading `ecosystem_items.status`** (M0-review fix — see `CHANGELOG.md`). `status` stays `'active'` regardless of the gate's outcome; `'source_unavailable'` is reserved for its actual meaning (the *upstream source* becoming unreachable), a different axis from a content verdict. Once B-8/B-9 land and can produce a real `'fail'` verdict, Discover/Yours filtering joins to each item's latest version's `gate_verdict` and excludes `'fail'` rows — not implemented in this milestone (no stage can produce anything but `'pending'` yet), but the schema and the item/version rows created here are already shaped for it.
- **No fabricated install rows.** A legacy item never gets a synthesized `ecosystem_installs` row — that would misrepresent an install action nobody took. Its "Yours" representation is the `LegacyItem` shape now specified in `CONTRACTS.md` §9 (`GET /ecosystem/installs`'s `legacy_items` array, a sibling to `installs`, never merged into it) — a 6th group, "Available from existing skills," covering both sources, with `allowed_actions` always `["open"]`. Task F-6 (M4) is the UI task that renders it; the wire contract itself is settled as of this review round.
- **AgentStudio's `skills_catalog` has no `org_id` column** — it's a single shared catalog, not multi-tenant. Every item bridged from it is attributed to `org_id='default'`, the platform's existing single-org-deployment sentinel, not a per-org value this source simply doesn't have. `skills_pg`'s `SkillRecord.org_id` is real and multi-tenant, so those items keep their own org's attribution.
- **AgentStudio not configured/reachable**: `list_agentstudio_skills()` catches the import and the runtime call separately and returns `[]` either way — a deployment without AgentStudio is a valid state, not a backfill failure. Covered by `tests/services/ecosystem/test_legacy_bridge.py::test_list_agentstudio_skills_degrades_gracefully_when_unavailable`.
- **Execution-type `SkillRecord`s are never bridged** (`docs/ecosystem/ECOSYSTEM_PLAN.md` §15 decision 1) — they have no confirmed live execution path, and importing them as installable items would let a user install something that silently does nothing.

## Flags
`ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG` / `ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO` (both default on, task B-0) — independently disable either half of the backfill job without touching the other. Disabling does not delete already-backfilled pointer rows.

## Tests
`tests/services/ecosystem/test_legacy_bridge.py` (slug generation, behavioral-vs-execution filtering, org_id passthrough, AgentStudio-unavailable graceful degradation) and `tests/scripts/ecosystem/test_backfill_legacy_items.py` (end-to-end: a real `SkillRecord` row gets mirrored correctly, a second run is idempotent with zero duplicate rows, and the original `skills_pg` row is provably untouched). All run against a real Postgres instance; 12 tests, all passing as of this milestone.

## How to extend
This is the file to update if a future phase decides to bridge a write path in addition to the read path (a decision explicitly deferred, not assumed, as of this writing). To bridge a third legacy source (e.g. `cowork_roles`/`connector_definitions`, both still just `legacy_source` values reserved in the schema but not yet implemented): add a `list_*()` read function to `legacy_bridge.py` following the same read-only, exception-safe pattern, a `_backfill_*()` function to the script, and its own `ECOSYSTEM_LEGACY_BRIDGE_*` flag.
