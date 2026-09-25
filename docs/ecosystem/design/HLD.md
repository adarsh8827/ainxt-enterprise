# Ecosystem Marketplace — High-Level Design

Living document. Updated in the same commit as every implementation task in `docs/ecosystem/SKILLS_PHASE_PLAN.md`. Written for a new team member — if a section assumes knowledge this document hasn't given you yet, that's a bug in the document, please fix it rather than working around it.

This file gives the big picture only. Per-area implementation detail (files, functions, sequence diagrams, edge cases) lives in `docs/ecosystem/design/LLD/`, one file per area. Dated history of what changed and why lives in `docs/ecosystem/design/CHANGELOG.md`.

---

## 1. What this is

A marketplace for reusable AI-platform content — skills first, with plugins, MCP servers, and connectors as later phases sharing the same foundation. Users can browse a catalog, install items for themselves or their organization, and — for skills specifically — create new ones by hand, by uploading a bundle, or by describing what they want and having a guided pipeline draft it for them. Every item, regardless of how it was created, passes through the same automated verification gate before it becomes usable.

The design goal that shapes almost every other decision: **two products, one backend.** A full-featured product (many surfaces, admin screens, every menu) and a lighter product (fewer menus, a minimal sidebar) both consume the exact same API and the exact same UI component package — they differ only in a server-returned configuration document that tells each product's UI what to show.

## 2. Components

_(filled in as each task lands — this is a stub as of the design-docs-skeleton task)_

- **Backend service layer** (`services/ecosystem/`) — framework-agnostic; routers, background jobs, and chat-facing tools all call into this layer, never into each other.
- **API surface** (`routers/ecosystem_router.py`) — thin request/response glue only.
- **Verification gate** (`services/ecosystem/gate/`, `sandbox/ecosystem_gate_executor.py`) — the automated pipeline every new or updated item passes through.
- **Legacy bridge** (`services/ecosystem/legacy_bridge.py` + a backfill job) — read-only visibility into pre-existing content, without touching the systems that own it.
- **Frontend package** (`packages/ecosystem-ui/`) — one component library, consumed by both products, rendering only from server-supplied configuration.
- **Chat runtime integration** — an additive, flag-gated code path that makes installed items usable in a live conversation.

## 3. Data flow (summary)

_(stub — filled in by task B-3 onward; see `LLD/data-model.md` for the full schema and `LLD/resolver.md` for how a request turns into "what can this caller actually see and do")_

A request → resolves the caller's product/entitlements → resolves org policy → resolves the caller's role permissions → resolves per-item allowed actions. Each stage only narrows what the previous stage allowed; nothing is ever added back.

## 4. Key decisions

_(one line each; full reasoning lives in the referenced LLD file)_

- Two products share one backend and one UI package; product identity is a request header, not a build-time fork. See `LLD/config-products.md`.
- Every catalog item — regardless of how it was created — passes through the same automated gate. No creation path is trusted more than another. See `LLD/gate.md`.
- Legacy, pre-existing content is surfaced read-only; nothing new ever writes back to the systems that already own that content. See `LLD/legacy-bridge.md`.
- Chat integration is fully inert until an explicit flag is on, and even then only touches one specific, non-default conversation path — never the parts of chat that existed before this work began. See `LLD/chat-runtime.md`.

## 5. Open-source hygiene note

This document, and every file under `docs/ecosystem/design/`, deliberately avoids naming any specific external AI assistant, vendor, or tool — this is a public repository. Where a design choice is informed by a pattern documented elsewhere, this document says so in neutral terms ("a reference design," "an established pattern") rather than naming the source.
