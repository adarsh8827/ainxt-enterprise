# Ecosystem Marketplace — High-Level Design

Living document. Updated in the same commit as every implementation task in `docs/ecosystem/SKILLS_PHASE_PLAN.md`. Written for a new team member — if a section assumes knowledge this document hasn't given you yet, that's a bug in the document, please fix it rather than working around it.

This file gives the big picture only. Per-area implementation detail (files, functions, sequence diagrams, edge cases) lives in `docs/ecosystem/design/LLD/`, one file per area. Dated history of what changed and why lives in `docs/ecosystem/design/CHANGELOG.md`.

---

## 1. What this is

A marketplace for reusable AI-platform content — skills first, with plugins, MCP servers, and connectors as later phases sharing the same foundation. Users can browse a catalog, install items for themselves or their organization, and — for skills specifically — create new ones by hand, by uploading a bundle, or by describing what they want and having a guided pipeline draft it for them. Every item, regardless of how it was created, passes through the same automated verification gate before it becomes usable.

The design goal that shapes almost every other decision: **two products, one backend.** A full-featured product (many surfaces, admin screens, every menu) and a lighter product (fewer menus, a minimal sidebar) both consume the exact same API and the exact same UI component package — they differ only in a server-returned configuration document that tells each product's UI what to show.

## 2. Components

- **Data model** (`db/migrate.py`'s ecosystem-marketplace migration, `db/models.py`'s `Ecosystem*` ORM classes) — 20 new, additive tables. See `LLD/data-model.md`.
- **Object storage** (`store/ecosystem_object_storage.py`) — content-hash-addressed put/get, local-filesystem or S3/MinIO behind one interface. Distinct from `core/storage.py` (which is UUID-path-addressed and serves chat attachments) because this store's whole purpose is that the key IS the content's hash, so a read can verify it got back exactly what it asked for.
- **Backend service layer** (`services/ecosystem/`) — framework-agnostic; routers, background jobs, and chat-facing tools all call into this layer, never into each other. As of this revision: `publishers_service.py` (namespace resolution, real), `items_service.py`/`versions_service.py`/`gate_service.py` (skeletons, with the specific functions the legacy-bridge backfill job needs pulled forward and implemented for real), `rate_limit_service.py`/`idempotency_service.py`/`audit_service.py` (shared cross-cutting infrastructure, real), everything else (`installs_service.py`, `resolver_service.py`, `config_service.py`, `events_service.py`, `drafts_service.py`, `icon_service.py`) still a stub pointing at the milestone that fills it in.
- **API surface** (`routers/ecosystem_router.py`) — thin request/response glue only. Not created yet — lands with the first endpoint task (M2).
- **Verification gate** (`services/ecosystem/gate_service.py`'s orchestrator, stages land in `services/ecosystem/gate/` in M2) — the automated pipeline every new or updated item passes through. This revision can enqueue a gate run (always `pending`, since no stage executes yet); it cannot yet actually gate anything.
- **Legacy bridge** (`services/ecosystem/legacy_bridge.py`, read-only, + `scripts/ecosystem/backfill_legacy_items.py`, the only writer) — read-only visibility into pre-existing content, without touching the systems that own it. See `LLD/legacy-bridge.md`.
- **Frontend package** (`packages/ecosystem-ui/`) — one component library, consumed by both products, rendering only from server-supplied configuration. Not started yet (M4).
- **Chat runtime integration** — an additive, flag-gated code path that makes installed items usable in a live conversation. Not started yet (M5).

## 3. Data flow (summary)

**Legacy bridge / backfill (implemented this revision — the only end-to-end flow that exists so far)**: `scripts/ecosystem/backfill_legacy_items.py` reads behavioral-type `skills_pg` rows and AgentStudio's `skills_catalog` (via its own `workflow_repo.list_skills()`, read-only) → resolves/auto-provisions a publisher slug per org (`publishers_service`) → upserts a pointer-only `ecosystem_items` row, matched by `(legacy_source, legacy_ref)` so re-running is a no-op (`items_service`) → writes a content-hash-addressed version row so the gate has something stable to scan later (`versions_service`, `store/ecosystem_object_storage.py`) → enqueues a gate run that sits at `pending` until a real gate stage exists (`gate_service`). Nothing in this path ever writes to `skills_pg` or `skills_catalog`.

**Request-time authorization (not implemented yet — this is the target shape, filled in by M2/M3)**: A request → resolves the caller's product/entitlements → resolves org policy → resolves the caller's role permissions → resolves per-item allowed actions. Each stage only narrows what the previous stage allowed; nothing is ever added back. See `LLD/resolver.md` for how a request turns into "what can this caller actually see and do."

## 4. Key decisions

_(one line each; full reasoning lives in the referenced LLD file)_

- Two products share one backend and one UI package; product identity is a request header, not a build-time fork. See `LLD/config-products.md`.
- Every catalog item — regardless of how it was created — passes through the same automated gate. No creation path is trusted more than another. See `LLD/gate.md`.
- Legacy, pre-existing content is surfaced read-only; nothing new ever writes back to the systems that already own that content. See `LLD/legacy-bridge.md`.
- Chat integration is fully inert until an explicit flag is on, and even then only touches one specific, non-default conversation path — never the parts of chat that existed before this work began. See `LLD/chat-runtime.md`.

## 5. Open-source hygiene note

This document, and every file under `docs/ecosystem/design/`, deliberately avoids naming any specific external AI assistant, vendor, or tool — this is a public repository. Where a design choice is informed by a pattern documented elsewhere, this document says so in neutral terms ("a reference design," "an established pattern") rather than naming the source.
