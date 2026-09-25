# Ecosystem — Integration Contracts

Single source of truth for the Ecosystem marketplace's backend/UI/desktop integration surface. Code (OpenAPI spec, generated TS client, generated enums) is generated **from** this document — never hand-write the same types twice. This document defines the *shape* of the contract; the generation tooling (OpenAPI-to-TypeScript, Python enum ↔ TS enum codegen) is an implementation detail left to `ECOSYSTEM_PLAN.md`'s week-by-week plan (§13, Week 1: `CONTRACTS.md` first draft; ongoing: contract tests in CI, §16 below).

This is additive: it defines a **new** `/ainxt/v1/api/ecosystem/*` surface and does not alter the request/response shape of any existing endpoint (`marketplace_router.py`, `skills_router.py`, `connectors_router.py`, `mcp_server_router.py`, `mcp_governance_router.py`, `cowork_admin_router.py`), per `ECOSYSTEM_PLAN.md`'s additive-migration constraint.

See `CONFIG_AND_PRODUCTS.md` for the behavior behind §8's `GET /ecosystem/config`, the product-profile/RBAC/policy layering, and the full text of every decision referenced below. **Every fix in this revision implements `DECISIONS_AND_PROMPTS.md` §9C** (that file is referenced but does not exist anywhere in this checkout — see `CONFIG_AND_PRODUCTS.md`'s header note; this document implements the 18 fixes exactly as enumerated inline in the approving instruction, cited below as "§9C fix N").

---

## 1. Shared enums (generate into Python `enum.Enum` and TypeScript `union type`/`enum`)

```
ItemType        = "skill" | "plugin" | "mcp_server" | "connector"
ItemScope       = "builtin" | "optional" | "central_index" | "org_private"
ItemStatus      = "active" | "source_unavailable" | "yanked" | "deprecated"
TrustTier       = "builtin" | "verified" | "org" | "community" | "agent_created"
GateVerdict     = "pass" | "warn" | "fail" | "pending"
GateStage       = "manifest" | "license" | "static_safety" | "supply_chain" | "sandbox" | "ethics" | "mcp_connector"
GateSeverity    = "info" | "warn" | "block"
InstallScope    = "private" | "shared" | "org" | "provisioned" | "required"
InstallOrigin   = "created" | "shared" | "provisioned" | "required" | "added"
DraftStatus     = "drafting" | "ready" | "submitted" | "abandoned"
Execution       = "server" | "local"
ConnectionStatus = "connected" | "needs_reauth" | "expired" | "revoked" | "insufficient_scope" | "not_connected" | "connecting" | "error"
SecretClass     = "platform" | "per_user" | "org_shared" | "device_local"
SecretBackend   = "builtin" | "aws_kms" | "gcp_kms" | "azure_kv" | "vault"
JobStatus       = "verifying" | "active" | "warn" | "blocked" | "failed"
ChangeKind      = "installed" | "uninstalled" | "enabled" | "disabled" | "updated" | "blocked" | "connection_changed"
SourceKind      = "github_repo" | "mcp_registry" | "well_known" | "private_git" | "skills_sh_indirect" | "local"
GateTrigger     = "ui_add" | "chat_create" | "cli" | "index_ci" | "admin_provision" | "desktop" | "new_version"
ItemTypeState   = "available" | "coming_soon"
```

**`InstallOrigin` is new** (§9C fix 9) — powers the "Yours" page's 5-group scheme (`SKILLS_UI_AUDIT.md`'s option map) directly, one enum value per group: `created` (Created by me), `shared` (Shared with me), `provisioned`/`required` (Org provisioned/Required), `added` (Added from Discover). Stored on `ecosystem_installs.origin` (`ECOSYSTEM_PLAN.md` §4).

**`DraftStatus` is new** (§9C fix 10) — see §10's draft endpoints.

**`SourceKind` gained `local`** (§9C fix 3) — one per org, representing items that org created directly (write/upload/Create-with-AI), so `ecosystem_items.source_id` can stay `NOT NULL` for every item without an upstream repo (see `ECOSYSTEM_PLAN.md` §4 for the full reasoning and the "why not make `source_id` nullable instead" justification).

**`ItemTypeState` is new** (§9C fix 18) — `available` (installable/browsable, real API calls) vs `coming_soon` (visible as a read-only placeholder tab, no install/add actions, no API calls for that type). Carried per-type in `GET /ecosystem/config`'s `item_types` array (§8).

**`TrustTier` changed** from `builtin|trusted|community|agent_created` to `builtin|verified|org|community|agent_created` — `trusted` is gone (it never had a precise meaning distinct from `verified`); `org` is new (an org-authored/org-published item, ranked above generic `community` but below platform-vetted `verified`, matching the mock's own 4-tier badge set: Built-in/Verified/Org/Community). `agent_created` stays as a 5th tier, orthogonal to the badge-display 4 (an agent-authored item is never shown as "Verified" or "Org" regardless of who owns it, until a human explicitly re-tiers it).

**`ItemStatus` gained `deprecated`** (owner/admin-initiated soft retirement, distinct from `yanked` which is upstream-source-initiated) — see §6's `deprecate` action.

**`ConnectionStatus` gained `not_connected` and `connecting`** (seam only — no item type in this phase has connections at all, but the enum ships complete now so a later Connectors/MCP phase never needs a breaking enum change).

**`Surface` and `Product` are intentionally NOT in this enum block.** Both are data-driven registries (`ainxt.ecosystem_surfaces`, `ainxt.ecosystem_product_profiles`) rather than closed unions — see `CONFIG_AND_PRODUCTS.md` §1/§3/§4 for the full rationale and the current seed rows. Generate a `KnownSurface`/`KnownProduct` TypeScript type from the current seed for editor-autocomplete convenience only; runtime code must always validate against the live `GET /ecosystem/config` response (§8), never against the generated type.

---

## 2. Route slug mapping

`ItemType`'s wire value and its URL/query-param slug diverge for exactly one type. Full table (also documented in `CONFIG_AND_PRODUCTS.md` §2 with the reasoning for why this is a fixed table, not a registry):

| `ItemType` | Route/query slug |
|---|---|
| `skill` | `skills` |
| `plugin` | `plugins` |
| `connector` | `connectors` |
| `mcp_server` | `mcp` |

`GET /ecosystem/config` echoes this table verbatim as `route_slugs` (§8) so a client never hardcodes it either, even though it changes rarely. Nested routes (`CONFIG_AND_PRODUCTS.md` §7.1): `/marketplace/:typeSlug`, `/marketplace/:typeSlug/new`, `/marketplace/:typeSlug/upload`, `/marketplace/:typeSlug/import` (new, §9C fix 11), `/marketplace/:typeSlug/:namespace`.

---

## 3. Error format

Every non-2xx response from `/ecosystem/*` uses one shape:

```json
{
  "code": "GATE_BLOCKED",
  "message": "human-readable summary, safe to show in UI",
  "details": { "gate_run_id": "...", "findings": [ { "stage": "license", "code": "LICENSE_NOT_ALLOWED", "message": "..." } ] },
  "retryable": false
}
```

Documented `code` values (extend this list in place, never repurpose an existing code for a new meaning):

| code | meaning | retryable |
|---|---|---|
| `LICENSE_NOT_ALLOWED` | item or a dependency isn't MIT/Apache-2.0 | false |
| `GATE_BLOCKED` | verification gate returned `fail` | false (until a new version is submitted) |
| `GATE_PENDING` | verdict not yet available | true (poll job) |
| `POLICY_FORBIDDEN` | org policy disallows this action for this caller — **including a syntactically valid `x-ainxt-product` value the org is not entitled to** (§9C fix 1; §4 below) | false |
| `NEEDS_CONNECTION` | the tool call needs a connector connection the user lacks | true (after connecting) |
| `NOT_FOUND` | item/install/job/draft/product-profile id doesn't exist, isn't visible to caller, or (§4 below) `x-ainxt-product` names a product with no profile row at all (distinct from `POLICY_FORBIDDEN`'s "exists but you're not entitled") | false |
| `CONFLICT` | e.g. installing an already-installed item without `force` | false |
| `RATE_LIMITED` | too many add/install/connect/report calls | true (after backoff, see §5's `Retry-After`) |
| `SOURCE_UNAVAILABLE` | upstream commit disappeared; item hidden, existing installs unaffected | false |
| `SANDBOX_ESCAPE_SUSPECTED` | sandbox run behaved anomalously; treated as `fail` | false |
| `CONNECTION_EXPIRED` | credential needs reauth | true (after reconnect) |
| `NAMESPACE_INVALID` | the publisher segment of a requested namespace doesn't resolve in `ecosystem_publishers`, or the caller isn't that publisher (§9C fix 2) | false |
| `ICON_SOURCE_NOT_ALLOWED` | an `icon_url` value uses an external URL instead of the same-origin upload endpoint (§9C fix 7) | false |

---

## 4. Headers

**`x-ainxt-product: enterprise|workspace`** (§9C fix 1, supersedes the earlier draft's simpler "default enterprise" rule): every request to `/ecosystem/*` carries this header. Resolution:
1. If absent, default to the caller's **org's primary product** (`ainxt.ecosystem_org_products.is_primary = true` for that org, `ECOSYSTEM_PLAN.md` §4) — **not** a hardcoded global default of `enterprise`. An org with no entitlement row at all falls back to `enterprise` (the pre-entitlement-system behavior), so existing callers from before this header existed keep working unchanged.
2. If present, it must name a product the org is entitled to (a row in `ecosystem_org_products` for that `(org_id, product_key)`) — **not just** a product that exists in `ecosystem_product_profiles`. A product key with no profile row at all → `NOT_FOUND`. A product key with a profile but no entitlement row for this org → `POLICY_FORBIDDEN` (§3).
3. The header selects a *view* over one backend and one auth domain — it never changes session/auth behavior (§13).

Full layering behavior (entitlement → profile → org policy → RBAC → `allowed_actions`) is specified in `CONFIG_AND_PRODUCTS.md` §3-4.

**`Idempotency-Key`** (§9C fix 14, request header, client-generated UUID): required on `POST /ecosystem/items`, `POST /ecosystem/items/{id}/install`, `POST /ecosystem/drafts`, `POST /ecosystem/drafts/{id}/submit`. The server deduplicates by `(caller, Idempotency-Key)` for 24h — a retried request with the same key returns the original response verbatim (including the original `job_id`) rather than creating a second draft/item/job. Missing the header on these endpoints is itself a client bug worth surfacing, not silently tolerated — return `400` if absent on a required endpoint.

**Rate-limit response headers** (§9C fix 14, on every `/ecosystem/*` response, not just `429`s): `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix seconds). A `429 RATE_LIMITED` additionally sets `Retry-After` (seconds). Rate limits apply per `(user_id, action_class)` where `action_class ∈ {add, install, connect, report}` (matches `ECOSYSTEM_PLAN.md` §12's existing rate-limit mention).

---

## 5. Async operations

`install`/`update`/`uninstall` (uninstall is synchronous in practice but kept in the same envelope for UI simplicity) return immediately:

```json
{ "job_id": "uuid", "status": "verifying" }
```

Final state arrives via (a) the `ecosystem.changed` event (§13) and (b) `GET /ecosystem/jobs/{job_id}` → a `Job` object (§9).

**Content-hash verdict cache**: before enqueuing a fresh gate run, the install handler checks for an existing `ecosystem_gate_runs` row keyed on the exact `(content_hash, scanner_version)` pair. If found, the cached verdict is reused and the job resolves near-instantly instead of re-running the sandbox stage — this is why quick-add on an already-vetted item (e.g. a second org installing the same public skill unchanged) feels instant even though the wire contract is still async end-to-end. A client must not assume synchronous completion just because it observed fast resolution in practice — always poll/listen for the real terminal state.

---

## 6. `allowed_actions` — backend-computed, UI-enforced-and-backend-enforced

Every item detail/list response includes a per-caller-computed array; the UI only renders actions present in this array, and **the backend independently re-checks policy on every action regardless of what the UI sent** (never trust the array as authorization, only as a rendering hint):

```json
"allowed_actions": ["install", "share", "report"]
```
Possible values: `install, uninstall, enable, disable, update, rollback, share, unshare, report, deprecate, delete_draft, force_disable, unyank, edit_policy`.

- **`deprecate`** — owner/admin-only, soft-retires the *item* (`ecosystem_items.status → 'deprecated'`, stamps `deprecated_at`/`deprecated_by`), distinct from `uninstall` which only ever removes the caller's own `ecosystem_installs` row and never touches the item itself.
- **`delete_draft`** — **new, replaces the earlier draft's "implicit hidden hard-purge inside uninstall"** (§9C fix 6, closing the vagueness `SKILLS_UI_AUDIT.md` M10 flagged): a real, explicit, owner-only action, present in `allowed_actions` **only** when the item is `scope='private'` (or a not-yet-submitted `ecosystem_drafts` row, §10) **and** has zero rows in `ecosystem_installs` other than the owner's own. Calls `POST /ecosystem/items/{id}/delete-draft` (§16), which hard-deletes the item, its versions, and their object-storage content — genuinely destructive, unlike `deprecate`. There is still no plain "Delete" action for a published item with any other install — `deprecate` is the only retirement path once anyone else depends on it.

---

## 7. List-query format (one shape for all 4 item types)

```
GET /ecosystem/items?cursor=<opaque>&limit=50&q=<text>&category[]=productivity&trust[]=community&trust[]=verified&status[]=active&verdict[]=pass&verdict[]=warn&surface[]=chat&sort=featured|newest|updated|name
```

`verdict[]` filters on each item's latest `ecosystem_item_versions.gate_verdict` (`pass|warn|fail|pending`), a different axis from `status[]` (`ItemStatus`, the catalog-entry lifecycle) — a "show me items with a warning" filter is a verdict filter, not a status filter, and the two must be independently combinable (e.g. `status[]=active&verdict[]=warn`).

Response: `{ "items": [ItemSummary, ...], "next_cursor": "opaque-or-null", "total_hint": 1234 }` — `ItemSummary` schema in §9.

**Item summary shape never includes an install-count field** — not omitted-but-present-as-null, genuinely absent from the schema, so no future UI can accidentally start rendering it. Internal install metrics for ranking/ops purposes are computed server-side (`ECOSYSTEM_PLAN.md` §12) and never serialized into this response.

**Icon field, restricted** (§9C fix 7, tightens the earlier draft): `icon_url` is a single string with a mandatory prefix — `emoji:🧠` (a Unicode emoji), or `url:<same-origin object-storage path>`. **The `url:` form only ever points at content this instance's own object storage served same-origin** — raster (PNG/JPG/WebP) or SVG that has been sanitized server-side (stripped of `<script>`, `on*` event-handler attributes, and any external `href`/`xlink:href` reference) at upload time via `POST /ecosystem/uploads/icon` (§10). An `icon_url` value pointing at an external URL is rejected at write time with `ICON_SOURCE_NOT_ALLOWED` (§3) — this is a deliberate SSRF/tracking-pixel/mixed-content guard, not an oversight. Absent/empty → the client renders a monogram fallback (first character of `display_name`, deterministic per-namespace background color) — never a broken image, never a generic placeholder icon, never `lucide-react`.

**UI default view** (§9C fix 8): a type tab defaults to **Yours** if `GET /ecosystem/installs?item_type=X` would return at least one row for the caller, else the product profile's `default_view` (`CONFIG_AND_PRODUCTS.md` §3). The client determines this from `GET /ecosystem/installs`'s `has_any` field (§9's `Capabilities`/installs summary) rather than a separate call — no new endpoint needed, just a documented field.

---

## 8. `GET /ecosystem/config`

The single call every UI makes before rendering anything marketplace-shaped — **UIs render only from this response**, never from a hardcoded list of item types, surfaces, features, or categories.

```json
{
  "product": "enterprise",
  "layout": "full",
  "default_view": "discover",
  "item_types": [
    { "type": "skill",       "state": "available",    "slug": "skills" },
    { "type": "plugin",      "state": "coming_soon",  "slug": "plugins" },
    { "type": "connector",   "state": "coming_soon",  "slug": "connectors" },
    { "type": "mcp_server",  "state": "coming_soon",  "slug": "mcp" }
  ],
  "route_slugs": { "skill": "skills", "plugin": "plugins", "connector": "connectors", "mcp_server": "mcp" },
  "surfaces": [ { "key": "chat", "label": "Chat" }, { "key": "agent_studio", "label": "Agent Studio" }, { "key": "cowork", "label": "Cowork" }, { "key": "desktop", "label": "Desktop" } ],
  "features": { "discover": true, "yours": true, "create_with_ai": true, "write": true, "upload": true, "import_url": false, "share": true, "provisioning": true, "admin_policies": true, "gate_dashboard": true },
  "policy_summary": { "who_can_add": "all_users", "allowed_sources": ["central_index"], "auto_update_default": false },
  "taxonomy": { "categories": ["productivity","dev-tools","communication","data-analytics","design","finance","crm","marketing","automation","documents","research","hr-people","security-compliance","travel","legal","sales","support","general"], "trust_tiers": ["builtin","verified","org","community","agent_created"] },
  "new_badge_days": 14,
  "enums_version": "2026.09.1"
}
```

**`item_types` replaces the old flat `enabled_item_types` array** (§9C fix 18): every response lists **all 4** item types (superseding the earlier "hide Connectors/Plugins/MCP" decision — see `CONFIG_AND_PRODUCTS.md` §7.14, now itself superseded), each tagged `state: available|coming_soon`. `available` types render their real tab (search/filter/install, real API calls). `coming_soon` types render a **read-only placeholder tab** — a short static description of what the type does, a "Coming soon" badge, optionally a preview of what will appear — with **zero API calls for that type** and **no** install/add actions rendered anywhere for it, including the "+ Add" menu (whose corresponding entries — "Add MCP server," "Add connector," a plugin-creation entry — render **disabled** with a "Coming soon" label rather than being omitted, so users learn the capability exists without being able to trigger it) and the chat "+" menu (Skills active; other type sections shown disabled/"Coming soon," or omitted entirely if the product profile excludes that surface). Flipping a type from `coming_soon` to `available` later is purely a backend config change — the corresponding `ECOSYSTEM_TYPE_*` flag flips on and the type is added to the product profile's `enabled_item_types` (still tracked internally alongside `visible_item_types`, `ECOSYSTEM_PLAN.md` §4) — **no UI code changes**, because the tab/placeholder components for every type are already built as dormant seams in `packages/ecosystem-ui`, wired to the same shared data-fetching hooks from day one.

Which types are merely *visible-as-coming-soon* vs not shown as a tab at all is still a per-product-profile decision (`visible_item_types`, `ECOSYSTEM_PLAN.md` §4) — this phase, both `enterprise` and `workspace` set `visible_item_types` to all 4, so every product shows all 4 tabs, differing only in which are `available` (`skill` only, both products, this phase) vs `coming_soon` (the other 3, both products, this phase). A product could in principle hide a type's tab entirely by omitting it from `visible_item_types`; neither seeded profile does this yet.

`new_badge_days` (default `14`) drives the "New" badge threshold — never hardcoded client-side. `enums_version` is a seam for a future stale-codegen-bundle warning; not surfaced as a UI banner this phase.

---

## 9. JSON schemas (§9C fix 9)

**`ItemSummary`** (list responses, §7):
```json
{
  "id": "uuid", "namespace": "acme/exec-assistant", "item_type": "skill",
  "display_name": "Exec Assistant", "description": "...", "category": "productivity", "tags": ["office"],
  "icon_url": "emoji:🧠", "trust_tier": "org", "license": "MIT", "status": "active",
  "is_featured": false, "is_new": true,
  "latest_version": "1.2.0", "latest_verdict": "pass",
  "allowed_actions": ["install", "share", "report"]
}
```
No install-count field (§7). `is_new` is server-computed from `new_badge_days` (§8) — the client never computes this itself.

**`ItemDetail`** (`GET /ecosystem/items/{id}`) — `ItemSummary` plus:
```json
{
  "...ItemSummary": "...",
  "publisher": { "slug": "acme", "type": "org" },
  "attribution": "MIT License\n\nCopyright (c) 2026 Acme Corp\n...",
  "source": { "kind": "local", "url": null },
  "manifest": { "...": "parsed SKILL.md frontmatter or plugin/MCP/connector schema" },
  "deprecated_at": null, "deprecated_by": null
}
```

**`Version`** (`GET /ecosystem/items/{id}/versions` list entries):
```json
{ "id": "uuid", "version": "1.2.0", "pinned_sha": null, "content_hash": "sha256:...", "license": "MIT", "gate_verdict": "pass", "created_at": "2026-09-01T00:00:00Z", "is_current": true }
```

**`GateRun` + `Finding`** (`GET /ecosystem/items/{id}/gate-runs` list entries):
```json
{
  "id": "uuid", "version_id": "uuid", "trigger": "chat_create", "verdict": "warn",
  "scanner_version": "2026.09.1", "started_at": "...", "finished_at": "...",
  "findings": [ { "stage": "static_safety", "severity": "warn", "code": "EXTERNAL_URL_REFERENCE", "message": "...", "details": {} } ]
}
```

**`Install`** (`GET /ecosystem/installs` list entries — the "Yours" page's core data):
```json
{
  "install_id": "uuid", "item": { "...": "ItemSummary" }, "scope": "org", "origin": "created",
  "installed_by": "user_id", "installed_for": null, "enabled": true,
  "surfaces": ["chat", "agent_studio"], "auto_update": false, "installed_at": "..."
}
```
`origin` is the `InstallOrigin` value (§1) driving the 5-group "Yours" layout directly — the client groups client-side by this one field rather than re-deriving group membership from `scope`/`installed_by` heuristics.

**`GET /ecosystem/installs` response envelope** (carries the §7 default-view signal):
```json
{ "installs": [ "...Install" ], "has_any": true, "next_cursor": null }
```
`has_any` is scoped to whatever `item_type` filter was passed (or overall, if none) — the client uses it per §7's default-view rule.

**`Job`** (`GET /ecosystem/jobs/{id}`):
```json
{ "job_id": "uuid", "status": "verifying", "item_id": "uuid", "version_id": "uuid", "gate_run_id": "uuid|null", "error": null }
```

**`Capabilities`** (`GET /ecosystem/capabilities` — per-surface, this is what Chat/Agent Studio/Cowork actually consume at runtime):
```json
{
  "surface": "chat",
  "skills": [ { "namespace": "acme/exec-assistant", "display_name": "Exec Assistant", "description": "one-line index text", "slash_command": "/exec-assistant" } ],
  "plugins": [], "connectors": [], "mcp_tools": []
}
```
Only `enabled=true` installs whose `surfaces` array includes the requested `surface`, and only for `item_types` currently `state:"available"` (§8) — `coming_soon` types never appear here regardless of any stray install row, closing off any path for a not-yet-shipped type to leak into a live capability list.

**`Config`**: see §8 in full — that response body *is* the `Config` schema, not reproduced twice here.

---

## 10. Create-with-AI drafts, create payloads, and icon upload (§9C fixes 10, 11)

**Drafts** (backed by the AgentStudio Skill Factory pipeline, `ECOSYSTEM_PLAN.md` §1.1/§9):
```
POST   /ecosystem/drafts                 SSE stream — {item_type} in, server streams Skill-Factory conversational turns (intent/clarify/blueprint/content/bundle/critique) back
GET    /ecosystem/drafts/{id}            current draft_content + status
PATCH  /ecosystem/drafts/{id}            user edits to draft_content (the "preview/edit card")
POST   /ecosystem/drafts/{id}/submit     finalize — requires draft_content.license (MIT default); creates the ecosystem_items + first ecosystem_item_versions row, enqueues a gate job (§5), stamps ecosystem_drafts.submitted_item_id
```
A draft (`ainxt.ecosystem_drafts`, `ECOSYSTEM_PLAN.md` §4) is never itself browsable/installable — it only becomes a real catalog entry on `submit`. `DraftStatus` transitions: `drafting → ready` (Skill Factory pipeline finished, awaiting user review) `→ submitted` (terminal, success) or `→ abandoned` (terminal, user cancels or TTL-expires without submission — a housekeeping job purges `abandoned` drafts older than 30 days).

**Create payloads** (`POST /ecosystem/items`, one endpoint, three payload shapes distinguished by `Content-Type`/a `create_via` field):
- **write**: `application/json` — `{ create_via: "write", item_type, namespace, display_name, description, category, tags, license, content: { instructions, files: [{name, content}] } }`.
- **upload**: `multipart/form-data` — a single `.zip`/`.skill` file field plus the same metadata fields as form fields; server-side unzip/validation mirrors the existing `.zip` path-traversal/zip-bomb guards already used by `AgentStudio/backend/app/api/catalog.py`'s upload handler (`ECOSYSTEM_PLAN.md` §1.1).
- **import**: `application/json` — `{ create_via: "import", kind: "url" | "github", ref: "https://..." | "owner/repo/path", item_type, namespace, license }` — fetched, validated, and gated exactly like any other creation path; no special trust conferred by having come from a URL.

All three require `license` (MIT default when the client omits it for `write`/`import`; `upload` must find a `license:` frontmatter field or the request is rejected with `LICENSE_NOT_ALLOWED`) and all three go through the full gate (§5, `ECOSYSTEM_PLAN.md` §6) identically — there is no fast path for any creation method.

**Icon upload**: `POST /ecosystem/uploads/icon` (`multipart/form-data`, one image file) → `{ "icon_url": "url:<same-origin path>" }`. Server-side: raster files are stored as-is (with size/dimension caps); SVG files are sanitized (§7) before storage. This is the **only** way an `icon_url` `url:` value is produced — a client may never construct one itself.

---

## 11. Admin: featured overrides (§9C fix 12)

```
PUT    /ecosystem/featured/{item_id}     body: {} — sets ecosystem_featured_overrides(org_id=caller's org, item_id, featured=true)
DELETE /ecosystem/featured/{item_id}     removes the org's override row (reverts to the platform-level ecosystem_items.is_featured value for that org)
```
Admin-only (`marketplace:admin_policies` or equivalent RBAC permission, `ECOSYSTEM_PLAN.md` §1.5/§13).

---

## 12. Tool contracts: `skill_view` and `read_skill_file` (§9C fix 13)

Extends AgentStudio's existing progressive-disclosure pattern (`AgentStudio/backend/app/core/skill_manifest.py:131`, `read_skill_file` at `AgentStudio/backend/app/tools/platform_tools.py:604`, `ECOSYSTEM_PLAN.md` §1.1/§9) platform-wide rather than reinventing it.

**`skill_view(name: str) -> string`** — called by the model when a skill is relevant beyond its one-line index entry.
- **Pinned version**: resolves against the caller's *currently installed and enabled* version for that surface at the time of the call (`ecosystem_installs.version_id` at call time) — **not** necessarily the item's latest version, and **not** re-resolved mid-conversation if an update lands during the same session (matching the cache-prefix-stability principle, `ECOSYSTEM_PLAN.md` §2/Hermes pattern 13). A mid-conversation update is picked up on the next new session, same as any other `ecosystem.changed`-driven capability refresh.
- **Size limit**: returns up to 8,000 characters of the skill's instructions body; longer content is truncated with a trailing `"...(truncated, N characters omitted)"` marker rather than silently cut.
- **Errors**: `NOT_FOUND` if the named skill isn't currently installed+enabled for the caller's surface (never leaks the existence of a skill the caller can't see); no other error shape — a skill_view call either returns text or a not-found signal, nothing else can go wrong at this layer (upstream object-storage failures degrade to `NOT_FOUND` from the model's perspective too, logged server-side for ops visibility).

**`read_skill_file(name: str, path: str) -> string | bytes`** — called to fetch a specific bundled file (`references/`, `scripts/`, etc.) by relative path.
- **Pinned version**: same pinning rule as `skill_view`.
- **Size limit**: 256 KB per file; larger files return a truncation marker for text files, or a `FILE_TOO_LARGE`-shaped error for binary files (binary truncation isn't meaningful).
- **Path safety**: `path` is resolved relative to the pinned version's manifest file list only — no path traversal, no access to any file not explicitly declared in that version's `ecosystem_item_versions.manifest`. A `path` not present in the manifest is `NOT_FOUND`, not a generic 403 (avoids confirming/denying the existence of paths outside the declared set).
- **Errors**: `NOT_FOUND` (skill not installed+enabled, or path not in the pinned version's manifest).

---

## 13. `ecosystem.changed` event schema (versioned)

```json
{
  "v": 1,
  "type": "skill" ,
  "item_id": "uuid",
  "scope": "org",
  "change": "installed",
  "version": "1.2.0"
}
```
Transport: Redis pub/sub channel `ecosystem.changed.{org_id}` → WebSocket relay → connected web/desktop clients for that org (reuses the Redis-pub/sub-to-WebSocket pattern already implemented for `routers/cowork_mcp_router.py`/`routers/cowork_dispatch_router.py`, per `ECOSYSTEM_PLAN.md` §3.3/§13).

**UI-query invalidation table** — which cached queries a client must re-fetch per `change` value:

| `change` | Invalidate |
|---|---|
| `installed` | `GET /ecosystem/installs`, `GET /ecosystem/capabilities`, item detail (`allowed_actions`) |
| `uninstalled` | same as `installed` |
| `enabled` / `disabled` | `GET /ecosystem/installs`, `GET /ecosystem/capabilities`, chat slash-command/tool index |
| `updated` | item detail (Versions tab), `GET /ecosystem/capabilities` if the update changed enabled surfaces |
| `blocked` | item detail (Verification tab), admin gate-findings dashboard |
| `connection_changed` | `GET /ecosystem/connections`, connector-gated tool visibility in `GET /ecosystem/capabilities` |

`deprecate` and `delete_draft` do not get their own `change` value — both are carried as `change: "updated"` (or `"uninstalled"` for `delete_draft`, since the item ceases to exist) with the item's new state visible in the re-fetched response, since a client's only correct reaction is the same "re-fetch and re-render from current fields" behavior as any other update.

---

## 14. Session/auth parity

Same session (HttpOnly/Secure/SameSite cookie or `Authorization: Bearer` JWT — matches the existing `auth/dependencies.py:get_current_user()` dual-path, `ECOSYSTEM_PLAN.md` §1.5) for both REST and WebSocket, identical on web and desktop, identical regardless of `x-ainxt-product` (§4). No separate auth scheme introduced for the ecosystem surface.

---

## 15. Namespaced IDs

`publisher/name` everywhere an item is referenced — in API paths (`GET /ecosystem/items/{namespace}` accepts either the UUID `id` or the `namespace` string), CLI arguments, and `ecosystem.changed` events (`item_id` is always the stable UUID in events; `namespace` is resolved client-side for display via the item summary already cached from the list query).

**Publisher verification** (§9C fix 2): the `publisher` segment of a namespace must resolve to a row in `ainxt.ecosystem_publishers` (`ECOSYSTEM_PLAN.md` §4) — a verified org or user slug — before an item can be created under it. Creating an item auto-provisions the caller's own publisher-slug row on first use if one doesn't exist (an org's slug, or a user's own slug for personal/private items), rather than requiring a separate manual "register your publisher slug" step. A namespace whose publisher segment doesn't resolve, or resolves to a slug the caller doesn't own, is rejected with `NAMESPACE_INVALID` (§3).

---

## 16. Contract tests in CI

Two independent conformance checks, both required to pass, both new CI jobs (Tier 1, per `ECOSYSTEM_PLAN.md` §12):
1. Backend response schemas validated against the generated OpenAPI spec on every PR touching `routers/ecosystem_router.py` or the service layer.
2. The frontend's mock adapter (used in `ecosystem-ui`'s component tests) validated against the same OpenAPI spec — CI fails the build if backend and frontend drift, exactly the guarantee this document exists to provide.

---

## 17. Full endpoint list (consolidated, supersedes any partial list in `ECOSYSTEM_PLAN.md` §5)

```
GET    /ecosystem/config
GET    /ecosystem/items
GET    /ecosystem/items/{id}
GET    /ecosystem/items/{id}/versions
GET    /ecosystem/items/{id}/gate-runs
POST   /ecosystem/items                       -- create (write/upload/import payloads, §10)
POST   /ecosystem/items/{id}/install
POST   /ecosystem/items/{id}/uninstall
POST   /ecosystem/items/{id}/enable | /disable
POST   /ecosystem/items/{id}/update
POST   /ecosystem/items/{id}/rollback
POST   /ecosystem/items/{id}/share
POST   /ecosystem/items/{id}/report
POST   /ecosystem/items/{id}/deprecate
POST   /ecosystem/items/{id}/delete-draft     -- §6, §9C fix 6
POST   /ecosystem/uploads/icon                -- §10, §9C fix 7
POST   /ecosystem/drafts                      -- §10, §9C fix 10 (SSE)
GET    /ecosystem/drafts/{id}
PATCH  /ecosystem/drafts/{id}
POST   /ecosystem/drafts/{id}/submit
GET    /ecosystem/jobs/{job_id}
GET    /ecosystem/installs
GET    /ecosystem/capabilities
-- admin --
GET/POST/DELETE /ecosystem/sources
GET/PUT         /ecosystem/policy
GET             /ecosystem/gate-findings
POST            /ecosystem/items/{id}/force-disable | /unyank
PUT/DELETE      /ecosystem/featured/{item_id}  -- §11, §9C fix 12
-- credentials (seam only, not implemented this phase) --
GET    /ecosystem/oauth/providers
POST   /ecosystem/oauth/providers/{provider}
GET    /ecosystem/oauth/start/{item_id}
GET    /ecosystem/oauth/callback
GET    /ecosystem/connections
DELETE /ecosystem/connections/{id}
```
