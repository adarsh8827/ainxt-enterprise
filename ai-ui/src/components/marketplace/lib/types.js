// SPDX-License-Identifier: MIT
// ============================================================
// Wire types mirroring docs/ecosystem/CONTRACTS.md exactly (task B-17's
// codegen script generates the Python-side enums from the same document;
// this file is the hand-written TypeScript counterpart until a shared
// generator produces both sides from one source -- see CONTRACTS.md's own
// header note on that being a future step, not this phase's job).
//
// Surface and Product are deliberately NOT closed unions here (CONTRACTS.md
// §1) -- they are runtime strings validated only against a live
// GET /ecosystem/config response. KnownSurface/KnownProduct below exist for
// editor autocomplete convenience only; never use them to validate anything
// at runtime.
// ============================================================

/** CONTRACTS.md §2 -- fixed, small, 1:1 with ItemType; never data-driven. */
export const ROUTE_SLUGS = {
  skill: "skills",
  plugin: "plugins",
  connector: "connectors",
  mcp_server: "mcp"
};

/** Editor-autocomplete convenience only -- see the file header note. */

/** Caller-specific, distinct from FeatureFlags: `features` is per-product
 * (every caller under the same product sees the same value); this is
 * per-caller (computed from the caller's own resolved permissions --
 * marketplace:share / marketplace:provision). Any scope-selection UI
 * that exists before an item is even installed (no allowed_actions array
 * to consult yet) must gate on this, never on `features` alone. */

/** Admin-only (real incident, 2026-09-27: a full day of testing against a
 * 15-hour-stale image, no way to tell from the running app) -- undefined
 * for a non-admin caller, never sent, not just hidden client-side. */

/** Item 6: one stage's live/resolved state within a GateRun.stage_timings. */

/** GET /ecosystem/items/{id}/gate-runs' full response shape (item 6). */

/** GET /ecosystem/search/live's own pointer-shaped result (Discover "From
 * the web" section) -- deliberately NOT an ItemSummary: nothing here
 * exists in the DB yet (no `id`/`item_id`, no gate verdict, no installed
 * state) until a caller actually adds it, which materializes a real item
 * through the exact same POST /ecosystem/items import path a manual
 * "Import from URL" already uses (`ref` below is that call's own `ref`
 * verbatim). `license_spdx` is always MIT/Apache-2.0-compatible already
 * (server-side pre-filter, services/ecosystem/live_search_service.py) --
 * shown as an informational badge, never a gate the caller has to clear. */

/** CONTRACTS.md §10.1 -- POST /ecosystem/items/{id}/new-version(/upload)
 * response. No `provision_scope`: a new version of an existing item never
 * re-decides where that item is provisioned. */

/** Same shape as CreateWritePayload.content -- shared between "create a
 * new item" and "add a version to an existing one." */

// ── Admin Sources screen (Task 3a) ───────────────────────────────────────

/** A single ecosystem-related process's own self-reported startup state
 * (services/ecosystem/service_health.py) -- null when that service has
 * never reported a startup at all (not running, or running code from
 * before this feature existed). */

/** Item 8: admin-visible gate-worker health signal, GET
 * /ecosystem/admin/gate-health -- services/ecosystem/gate_health_service.py's
 * get_health(). `message` is non-null exactly when there's something an
 * admin should look at (no recent heartbeat, or a stuck-verifying backlog). */

/** CONTRACTS.md §13 -- the live-update event shape. */

// ── Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md) ──────────

/** Mirrors mcp/tool_annotations.py's Classification -- conservative default
 * "write" when a tool carries no explicit hint, never "read". */

/** Plugins phase (docs/ecosystem/PLUGINS_PHASE_PLAN.md §1/§4) -- one
 * reference to an existing, independently-gated EcosystemItem bundled into
 * a plugin. Never inline content -- a plugin manifest points at real items
 * by namespace, it doesn't embed their files. */

/** ItemDetail.manifest.parts shape for an item_type: "plugin". */

/** POST /ecosystem/items/{id}/plugin-compose's success response -- the
 * same async-creation envelope every other creation path already returns
 * (CONTRACTS.md §5), reused rather than inventing a new shape. */

/** GET /ecosystem/connections list entry -- one row per (caller, connector
 * or mcp_server ref), whether or not that connector has ever been
 * installed as a catalog item (item_id is null for a native connector with
 * no ecosystem_items row of its own yet). */

/** GET /ecosystem/tool-calls/pending entry -- a model-issued tool call
 * awaiting the approval flow (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1
 * item 3). "read" classified calls never reach this list -- the backend
 * only ever queues write/destructive calls for approval. */
/** GET /ecosystem/admin/mcp-runtime entry (Stage 3) -- admin-only. */