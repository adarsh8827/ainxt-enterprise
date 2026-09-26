# LLD — Verification gate

**Purpose**: the automated pipeline every new or updated catalog item passes through before it's usable — manifest validation, license enforcement, static safety scanning, supply-chain checks, a hardened sandbox stage, and an ethics/policy review. Landed in tasks B-8/B-9 (M2).

## Files / functions
- `services/ecosystem/gate_service.py` — the orchestrator (`enqueue_gate_run()`, `run_gate()`). Called "gate_orchestrator.py" in the phase plan's prose; kept as `gate_service.py` since that's the file task B-3 already established for this role.
- `services/ecosystem/gate/manifest_stage.py` — stage 1: name/description validation, bundle file-count/size caps, path-traversal defense-in-depth.
- `services/ecosystem/gate/license_stage.py` — stage 2: pass/block only, no warn tier. Checks the item's own license plus an optional `dependencies` list (unused by skills this phase, present for forward compatibility).
- `services/ecosystem/gate/static_safety_stage.py` — stage 3: wraps `agents/compliance_engine.py`'s `analyze()`, filtered to `category ∈ {"SECRET", "KEY"}` — see Edge cases below for why this is filtered by `category`, not the more granular `type` field the original task text named.
- `services/ecosystem/gate/supply_chain_stage.py` — stage 4: pinned-version check on an optional `dependencies` list; no malicious-hash lookup exists yet (disclosed gap, no such database exists in this codebase).
- `services/ecosystem/gate/sandbox_stage.py` — stage 5: Python `ast.parse()` import-allowlist check, plus an optional test-entrypoint execution via `sandbox/ecosystem_gate_executor.py`.
- `sandbox/ecosystem_gate_executor.py` — `EcosystemGateExecutor`, extends `sandbox/docker_executor.py`'s `DockerExecutor`, overriding `_run()` entirely (the base class doesn't parameterize `read_only`/timeout/mem, so subclassing and overriding is the only way to change them) for `network_disabled=True` unconditionally, `read_only=True` rootfs, a tmpfs-backed `/sandbox` (code enters the container via its command line, base64-encoded, never a host bind mount), and a longer timeout/lower memory profile than the base class's short-snippet defaults.
- `services/ecosystem/gate/ethics_stage.py` — stage 6: a fresh-context call via `models/model_router.py`'s `model_router.generate()`. Never raises (per that module's own contract); failure is signaled by the returned text starting with `"Error"`, treated identically to an unparseable response — both resolve to `pending` with a retry, never `pass`.
- `services/ecosystem/gate/mcp_connector_stage.py` — stage 7: always-pass no-op for `item_type=skill`.
- `services/ecosystem/gate/types.py` — the shared `Finding`/`StageResult` dataclasses every stage returns.

## API and DB changes
No new tables (uses `ecosystem_gate_runs`/`ecosystem_gate_findings` from task B-1). `ecosystem_item_versions.gate_verdict` is updated in place once a run resolves.

## Sequence diagrams
```
enqueue_gate_run(version_id, trigger, [installed_by, installed_for, org_id, surfaces, provision_scope])
    → creates ecosystem_gate_runs row (verdict='pending')
    → run_gate(gate_run_id, ...)   [see module docstring: SYNCHRONOUS this phase, not a real job queue]
        → decode version's object-storage content (manifest + files)
        → manifest_stage, license_stage, static_safety_stage, supply_chain_stage (always run)
        → if license/manifest already failed: stages 5-7 short-circuit to 'fail', sandbox never invoked
        → elif a resolved (content_hash, scanner_version) gate run already exists: reuse its verdict
          for stages 5-7 collectively, sandbox/ethics/mcp_connector never invoked
        → else: sandbox_stage, ethics_stage, mcp_connector_stage run for real
        → aggregate all stage verdicts (license=fail wins unconditionally; else pending > fail > warn > pass)
        → write gate_runs.verdict, gate_findings rows, item_versions.gate_verdict
        → if trigger ∈ {ui_add, chat_create} and verdict ∈ {pass, warn}: auto-install the creator
          (task E's post-verdict hook, calls installs_service.install())
```

## Edge cases and errors
- **Ethics reviewer unavailable, or its response can't be parsed into a verdict → `pending` + implicit retry-on-next-call, never `pass`.** This is the M0-review correction, and it applies identically whether the caller is a normal creation (B-6), the legacy backfill (B-4), or builtin seeding (B-22) — verified by a dedicated test for each. There is no separate "retry job" yet (no async queue exists, see the module's own scope-limitation note) — a "retry" concretely means re-running `enqueue_gate_run`/`run_gate` again later, which produces a fresh attempt against the same content.
- **License stage failing is unconditional and independent of everything else** — even a cache hit or an otherwise-clean sandbox/ethics result never overrides a license `fail`. Enforced by `_aggregate()` checking `license` first, before even looking at `pending`.
- **`static_safety_stage` filters by `category`, not the exact `type` strings the original task text named** (SECRET/API_KEY/ACCESS_TOKEN/PRIVATE_KEY_LEAK/CERTIFICATE_LEAK/SSH_KEY_LEAK/KEY_ASSIGNMENT_LEAK). Verified directly against `agents/compliance_engine.py`'s actual output: `detect_secrets()` tags findings `AWS_KEY`/`JWT_TOKEN`/`API_KEY`/`BEARER_TOKEN`/`STRIPE_KEY`/`PRIVATE_KEY` under `category="SECRET"`; `detect_key_leaks()` tags `PRIVATE_KEY_LEAK`/`CERTIFICATE_LEAK`/`SSH_KEY_LEAK`/`KEY_ASSIGNMENT_LEAK` under `category="KEY"`. Filtering on category (`{"SECRET", "KEY"}`) captures the full, correct set the task actually intends without depending on exact "type" spellings that don't all match what the detectors currently emit.
- **This gate stage's efficacy depends on a pre-existing, unrelated flag: `COMPLIANCE_SERVICE_ENABLED` (`core/config.py`, default `false`).** `agents/compliance_engine.py`'s `analyze()` returns `[]` unconditionally when this flag is off — meaning `static_safety_stage` silently finds nothing and always passes in any deployment that hasn't separately turned this flag on. This task does **not** flip that flag (doing so would be an out-of-scope side effect on an unrelated, pre-existing feature this initiative doesn't own) — a deployment that wants the marketplace's static-safety stage to actually catch anything must set `COMPLIANCE_SERVICE_ENABLED=true` independently. Flagged prominently here and in the M2 milestone report rather than silently left for someone to discover later.
- **Pre-existing, unrelated bug found while testing this stage**: `agents/secret_detector.py`'s `detect_secrets()` never calls its own `iter_env_secret_values()` helper, despite that file's comments describing exactly this fix for SNAKE_CASE env-var-assignment secrets (e.g. `AWS_SECRET_ACCESS_KEY = "..."`) — such a value is silently never caught by `detect_secrets()` today. Out of scope to fix here (existing, unrelated code); this gate stage's own tests use a pattern the detector does catch (a bare `AKIA...` access-key-ID shape) instead of depending on the broken path.
- **A critical, previously-undetected bug in `db/migrate.py` was found and fixed while testing this task**: `Base.metadata.create_all()` (an early step in `run_migrations()`, pre-existing code) creates a bare version of every ORM-modeled table — including every `Ecosystem*` model added in this initiative — **before** task B-1's own raw-DDL `_part_ad1_...` runs. Since that raw DDL uses `CREATE TABLE IF NOT EXISTS`, `create_all()` winning the race made several of B-1's own constraints (`ecosystem_installs`' `UNIQUE NULLS NOT DISTINCT`, most notably) permanently inert on any database this ran against — the constraint text existed in the migration file but was **never actually applied**. Fixed by excluding every `ecosystem_*`/`oauth_*`/`credential_audit`/`desktop_devices` table from `create_all()`'s table list, mirroring the exact precedent already in that code for `document_embeddings`/`workspace_messages` (tables with their own raw-DDL migrations that `create_all()` must not preempt). See `docs/ecosystem/design/CHANGELOG.md`'s M2 entry for the full account, and `LLD/data-model.md` for what this means going forward (every future `Ecosystem*` ORM model must have its own corresponding raw DDL run **before** it can safely be exercised — `create_all()` alone is not sufficient and must never be relied on for these tables).

## Flags
None — the gate always runs in full; no per-stage disable switch exists anywhere (a built-in bypass would defeat the point).

## Tests
38 pure/near-pure unit tests across `tests/services/ecosystem/gate/` (one file per stage) plus 6 integration tests in `tests/services/ecosystem/test_gate_service_orchestrator.py` (real Postgres, ethics mocked for determinism) covering: a clean item passes; a secret-containing item warns/fails; ethics-unavailable resolves to pending; findings are recorded; a disallowed license short-circuits before ever invoking ethics; a content-hash cache hit skips re-invoking ethics entirely. `sandbox_stage`'s test-entrypoint-execution tests run against a real Docker container (network isolation, exit-code propagation, and a genuine failure case all verified against the actual sandboxed process, not mocked) — see the M2 milestone report for the exact command and pass/fail counts.

## How to extend
This is the file to update when a later phase adds real content to the currently-inert MCP/connector check stage (flip `ECOSYSTEM_TYPE_MCP`/`ECOSYSTEM_TYPE_CONNECTOR`, per `SKILLS_PHASE_PLAN.md`'s "Next phases"). Building the real async job queue this stage's own module docstring flags as missing is the other significant piece of future work — at that point `enqueue_gate_run()`'s synchronous `run_gate()` call becomes a queue publish instead, and a new worker process consumes it; the wire contract (`job_id`/`GET /ecosystem/jobs/{id}`) does not need to change.
