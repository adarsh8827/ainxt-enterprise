# Ecosystem Marketplace — High-Level Design

Living document. Updated in the same commit as every implementation task in `docs/ecosystem/SKILLS_PHASE_PLAN.md`. Written for a new team member — if a section assumes knowledge this document hasn't given you yet, that's a bug in the document, please fix it rather than working around it.

This file gives the big picture only. Per-area implementation detail (files, functions, sequence diagrams, edge cases) lives in `docs/ecosystem/design/LLD/`, one file per area. Dated history of what changed and why lives in `docs/ecosystem/design/CHANGELOG.md`.

---

## 1. What this is

A marketplace for reusable AI-platform content — skills first, with plugins, MCP servers, and connectors as later phases sharing the same foundation. Users can browse a catalog, install items for themselves or their organization, and — for skills specifically — create new ones by hand, by uploading a bundle, or by describing what they want and having a guided pipeline draft it for them. Every item, regardless of how it was created, passes through the same automated verification gate before it becomes usable.

The design goal that shapes almost every other decision: **two products, one backend.** A full-featured product (many surfaces, admin screens, every menu) and a lighter product (fewer menus, a minimal sidebar) both consume the exact same API and the exact same UI component package — they differ only in a server-returned configuration document that tells each product's UI what to show.

## 2. Components

- **Data model** (`db/migrate.py`'s ecosystem-marketplace migration, `db/models.py`'s `Ecosystem*` ORM classes) — 20 new, additive tables, plus a repair migration (`_part_ad2_..._2026_09_27`) for environments that ran the migration before an M2 `create_all()` bug fix. See `LLD/data-model.md`.
- **Object storage** (`store/ecosystem_object_storage.py`) — content-hash-addressed put/get, local-filesystem or S3/MinIO behind one interface. Distinct from `core/storage.py` (which is UUID-path-addressed and serves chat attachments) because this store's whole purpose is that the key IS the content's hash, so a read can verify it got back exactly what it asked for.
- **Backend service layer** (`services/ecosystem/`) — framework-agnostic; routers, background jobs, and chat-facing tools all call into this layer, never into each other. As of this revision, real: `publishers_service.py`, `items_service.py`, `versions_service.py`, `gate_service.py` (full orchestrator, M2), `create_service.py` (M2), `installs_service.py` (M2), `policy_service.py` (M2), `icon_service.py` (M2), `rate_limit_service.py`/`idempotency_service.py`/`audit_service.py`, `license_policy.py`. Still stubs, pointing at the milestone that fills them in: `resolver_service.py`, `config_service.py`, `events_service.py`, `drafts_service.py` (all M3/M5).
- **API surface** (`routers/ecosystem_router.py`) — thin request/response glue only, mounted behind `ENABLE_ECOSYSTEM_MARKETPLACE` (`gateway.py`, matching the existing conditional-router-mount pattern used for other optional features). 20 endpoints as of M2: create (write/upload), icon upload, the full install lifecycle, sharing/reporting, deprecate, admin force-disable/unyank/require/unrequire, featured overrides, and a jobs-status read. Not yet mounted: list/detail/config/capabilities/drafts (M3/M5, need the resolver and config service first).
- **Verification gate** (`services/ecosystem/gate_service.py`'s orchestrator + `services/ecosystem/gate/`'s 7 stage modules, M2) — the automated pipeline every new or updated item passes through, fully implemented: manifest, license, static safety (reusing `agents/compliance_engine.py`), supply chain, a hardened Docker sandbox (`sandbox/ecosystem_gate_executor.py`), an LLM-based ethics review (`models/model_router.py`), and an inert MCP/connector placeholder. Runs synchronously in-process this phase (no real async job queue yet — a disclosed, deliberate scope limitation, not silently faked). See `LLD/gate.md`, including a critical, previously-inert-constraint bug this milestone found and fixed in `db/migrate.py` itself.
- **Legacy bridge** (`services/ecosystem/legacy_bridge.py`, read-only, + `scripts/ecosystem/backfill_legacy_items.py`, the only writer) — read-only visibility into pre-existing content, without touching the systems that own it. Its AgentStudio import path had a real, silent bug (wrong sys.path assumption, always failing regardless of whether AgentStudio was actually available) found and fixed in M2. See `LLD/legacy-bridge.md`.
- **Builtin skills** (`ecosystem/builtin/skills/`, `scripts/ecosystem/seed_builtin_skills.py`, M2) — 4 first-party starter skills, written from scratch for this platform, seeded through the exact same gate as any other item.
- **Frontend package** (`packages/ecosystem-ui/`) — one component library, consumed by both products, rendering only from server-supplied configuration. Not started yet (M4).
- **Chat runtime integration** — an additive, flag-gated code path that makes installed items usable in a live conversation. Not started yet (M5).

## 3. Data flow (summary)

**Create → gate → install (implemented in M2 — the primary end-to-end flow as of this revision)**: a caller submits a write or upload payload (`create_service.py`) → the item and its first version are created (`items_service`/`versions_service`, content-hash addressed via `store/ecosystem_object_storage.py`) → a gate run is enqueued and — this phase — executed synchronously through all 7 stages (`gate_service.py`) → on a `pass`/`warn` verdict, the creator (or, for an admin's `provision_scope` choice, every eligible org member going forward) is auto-installed (`installs_service.install()`) with no separate client action. A `fail` verdict installs nothing; an unresolvable ethics review resolves to `pending`, never an implicit pass.

**Legacy bridge / backfill (M1, now gated for real as of M2)**: `scripts/ecosystem/backfill_legacy_items.py` reads behavioral-type `skills_pg` rows and AgentStudio's `skills_catalog` (via its own `workflow_repo.list_skills()`, read-only) → resolves/auto-provisions a publisher slug per org (`publishers_service`) → upserts a pointer-only `ecosystem_items` row, matched by `(legacy_source, legacy_ref)` so re-running is a no-op (`items_service`) → writes a content-hash-addressed version row so the gate has something stable to scan (`versions_service`) → enqueues a gate run that, as of M2, actually executes rather than sitting at `pending` forever. Nothing in this path ever writes to `skills_pg` or `skills_catalog`.

**Request-time authorization (not implemented yet — this is the target shape, filled in by M3)**: A request → resolves the caller's product/entitlements → resolves org policy → resolves the caller's role permissions → resolves per-item allowed actions. Each stage only narrows what the previous stage allowed; nothing is ever added back. `compute_allowed_actions()` (`items_service.py`, M2) already implements the last of these four stages as a pure, tested function — the first three (product/policy/RBAC narrowing) land with M3's resolver. See `LLD/resolver.md` for how a request turns into "what can this caller actually see and do."

## 4. Key decisions

_(one line each; full reasoning lives in the referenced LLD file)_

- Two products share one backend and one UI package; product identity is a request header, not a build-time fork. See `LLD/config-products.md`.
- Every catalog item — regardless of how it was created — passes through the same automated gate. No creation path is trusted more than another. See `LLD/gate.md`.
- Legacy, pre-existing content is surfaced read-only; nothing new ever writes back to the systems that already own that content. See `LLD/legacy-bridge.md`.
- Chat integration is fully inert until an explicit flag is on, and even then only touches one specific, non-default conversation path — never the parts of chat that existed before this work began. See `LLD/chat-runtime.md`.

## 5. Open-source hygiene note

This document, and every file under `docs/ecosystem/design/`, deliberately avoids naming any specific external AI assistant, vendor, or tool — this is a public repository. Where a design choice is informed by a pattern documented elsewhere, this document says so in neutral terms ("a reference design," "an established pattern") rather than naming the source.
