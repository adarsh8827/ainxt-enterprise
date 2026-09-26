# Ecosystem — Product Profiles, Surfaces Registry, and Effective Config

Companion to `CONTRACTS.md` (wire shapes) and `ECOSYSTEM_PLAN.md` §4 (canonical DDL — this document does not duplicate table definitions; it explains the *behavior* of the tables that live there: `ecosystem_surfaces`, `ecosystem_product_profiles`, and the pieces of `ecosystem_items`/`ecosystem_installs` that a UI's rendering decisions depend on). Additive, per the standing rule — no existing router, table, or screen is touched.

---

## 1. Surfaces are data-driven, not a hard-coded enum

**Decision**: `Surface` stops being a closed TypeScript/Python union. It's rows in a new table, `ainxt.ecosystem_surfaces` (DDL lives in `ECOSYSTEM_PLAN.md` §4 — columns: `key` PK, `label`, `enabled_by_default` bool, `created_at`), seeded with exactly 5 rows for this phase:

| key | label | enabled_by_default | notes |
|---|---|---|---|
| `chat` | Chat | true | ai-ui's main chat surface |
| `agent_studio` | Agent Studio | true | AgentStudio-authored agents |
| `cowork` | Cowork | true | the Buddy/Code surface |
| `desktop` | Desktop | true | the Electron app (same tool, `execution:"server"` vs `"local"` still applies per `ECOSYSTEM_PLAN.md` §3.6/§8.6) |
| `workspace_chat` | Chat | true | **new this phase** — the `ainxt-workspace` product's own chat surface, kept distinct from `chat` because it is a *different backend consumer* (different product, potentially different capability resolution), even though the two render an outwardly similar chat UI |

Why a registry instead of an enum: the whole point of this phase is that a second product (`ainxt-workspace`) exists with a different, and likely still-growing, set of surfaces — hard-coding the union type means every new product ships a breaking enum change to every client. A registry means `GET /ecosystem/config` (§3) is the only thing that needs to change, and old clients that don't recognize a new surface key simply don't render toggles for it (fail open on *display*, fail closed on *authorization* — a surface a client doesn't understand is never implicitly granted).

**Codegen note for `CONTRACTS.md`**: generate a `KnownSurface` TypeScript type from the current seed for editor autocomplete convenience, but never use it for runtime validation — runtime code must treat `Surface` as `string` and validate against the live `GET /ecosystem/config` response, exactly like `ItemType`'s route-slug mapping (§2) is handled.

---

## 2. Route slug mapping (`ItemType` ↔ URL slug)

`ItemType` itself is unchanged (`skill | plugin | mcp_server | connector`, per the original task mandate — this was never in question). What's newly documented is the **route/query slug** each type uses in URLs and the `?category[]=`-style query params, because `mcp_server` is the one type whose enum value and URL slug diverge (matches the mock's own `TYPES` object, which keys `mcp` → `"MCP servers"` while every other key is a plain pluralization):

| `ItemType` enum value | Route/query slug | Example |
|---|---|---|
| `skill` | `skills` | `/marketplace/skills/:namespace` |
| `plugin` | `plugins` | `/marketplace/plugins/:namespace` |
| `connector` | `connectors` | `/marketplace/connectors/:namespace` |
| `mcp_server` | `mcp` | `/marketplace/mcp/:namespace` |

This mapping is a fixed, small, unlikely-to-grow table (only 4 rows, tied 1:1 to `ItemType`'s own enum, which the task mandate says stays as-is) — unlike Surfaces/Products it does **not** need to be data-driven; it ships as a plain constant object in `ecosystem-ui` (and the equivalent in the backend's route registration), generated once from this table, not from a runtime API call.

---

## 3. Product profiles

**Decision**: `ainxt.ecosystem_product_profiles` (DDL in `ECOSYSTEM_PLAN.md` §4), one row per product, holding:

```sql
CREATE TABLE ainxt.ecosystem_product_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_key         TEXT NOT NULL UNIQUE,           -- 'enterprise' | 'workspace' this phase; new products = new rows, not a new enum value
    label               TEXT NOT NULL,
    layout              TEXT NOT NULL CHECK (layout IN ('full','compact')),
    default_view        TEXT NOT NULL CHECK (default_view IN ('discover','yours')) DEFAULT 'discover',
    enabled_item_types  JSONB NOT NULL DEFAULT '["skill"]',              -- this phase: only "skill" enabled for either product
    enabled_surfaces    JSONB NOT NULL,                                  -- FK-by-key into ecosystem_surfaces.key, enforced at write time not by a DB FK (JSONB array)
    features            JSONB NOT NULL DEFAULT '{}',                     -- see feature-flag shape below
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`features` shape (matches the phase brief's list exactly, all booleans):
```json
{
  "discover": true, "yours": true, "create_with_ai": true, "write": true,
  "upload": true, "import_url": false, "share": true,
  "provisioning": false, "admin_policies": false, "gate_dashboard": false
}
```

**Seed rows, this phase**:

| `product_key` | `layout` | `enabled_item_types` | `enabled_surfaces` | `features` (non-default only) |
|---|---|---|---|---|
| `enterprise` | `full` | `["skill"]` (plugin/mcp_server/connector rows exist in the DB behind their own `ECOSYSTEM_TYPE_*` flags — see `ECOSYSTEM_PLAN.md` §13 — but are excluded from `enabled_item_types` until those flags flip) | `["chat","agent_studio","desktop"]` (**`cowork` excluded, Review round following M1, item G** — Cowork is consumed only by the external `ainxt-cli` via a direct `GET /ecosystem/capabilities?surface=cowork` call, not through any product profile's UI-facing surface toggles; the `cowork` surface stays registered in `ecosystem_surfaces` for that direct-consumer use, it's just not one of `enterprise`'s enabled toggles until a UI-integrated consumer exists) | `provisioning: true, admin_policies: true, gate_dashboard: true` (enterprise admins get the full admin surface; workspace doesn't) |
| `workspace` | `compact` | `["skill"]` | `["workspace_chat"]` | `import_url: false, provisioning: false, admin_policies: false, gate_dashboard: false, share: false` (workspace is single-user/small-team leaning per the phase brief — sharing/admin features start off, can be revisited) |

**Layering, exactly as specified**: `profile → org policy → RBAC → per-item allowed_actions`. Concretely, computing what a given request can see/do is four sequential narrowing passes, never a union:

1. **Profile** (`ecosystem_product_profiles`, keyed by `x-ainxt-product`) sets the *ceiling* — e.g. workspace's profile has `admin_policies: false`, so no amount of org policy or RBAC below can turn admin screens back on for a workspace request. This is deliberately the outermost gate specifically so a compact product can never accidentally inherit a feature its UI has no chrome for.
2. **Org policy** (`GET/PUT /ecosystem/policy`, per `ECOSYSTEM_PLAN.md` §5) narrows further within what the profile allows — e.g. an enterprise org can set `who_can_add: admins_only`, which narrows `features.write`/`create_with_ai` down to admin-only even though the enterprise profile itself allows all users.
3. **RBAC** (`auth/rbac.py`'s existing role/permission system, extended with the new `marketplace:*` permissions per `ECOSYSTEM_PLAN.md` §1.5/§13) narrows to what *this specific user's role* can do within what org policy allows.
4. **`allowed_actions`** (per-item, server-computed, `CONTRACTS.md` §6) is the final, per-item narrowing — e.g. even an admin with every permission can't `rollback` an item that has only one version, or `share` an item whose org policy has sharing disabled for that category.

Worked example: a `workspace` user tries to see the admin policy screen. Profile check fails at step 1 (`admin_policies: false` on the `workspace` profile row) — the request never reaches steps 2-4, and the UI never even requests the screen because `GET /ecosystem/config`'s `features.admin_policies: false` tells it not to render the nav entry at all (§4).

---

## 4. Product entitlement and the `x-ainxt-product` header

**Superseded per Review fix 1** — the original draft treated `x-ainxt-product` as a bare, globally-defaulted selector with no notion of which orgs may use which products. That's wrong for a real deployment: an org that's only licensed for `workspace` should never be able to request `enterprise` just by sending a header. The corrected model adds a server-side entitlement table, `ainxt.ecosystem_org_products` (`ECOSYSTEM_PLAN.md` §4: `(org_id, product_key, is_primary)`), and the header now only ever *selects among* a caller's entitled products, never grants access to a new one:

1. **Header absent** → default to the caller's org's **primary** entitled product (`is_primary=true` row in `ecosystem_org_products`). An org with no entitlement rows at all (e.g. every org that existed before this table did) falls back to `enterprise` — the pre-entitlement behavior — so this is still additive and non-breaking for existing callers.
2. **Header present** → the named product must (a) exist as a row in `ecosystem_product_profiles` and (b) have a corresponding `ecosystem_org_products` row for the caller's org. Case (a) failing is `NOT_FOUND` (the product itself doesn't exist anywhere). Case (b) failing — a real product the caller's org just isn't licensed for — is `POLICY_FORBIDDEN` (`CONTRACTS.md` §3), a materially different failure a client should present differently ("your org doesn't have workspace" vs. "that's not a real product").
3. Same session/auth (`CONTRACTS.md` §14) regardless of product — the header selects a *view* over one backend, never a different auth domain.

Full wire-level spec: `CONTRACTS.md` §4.

---

## 5. `GET /ecosystem/config`

The single call every UI makes before rendering anything marketplace-shaped. `CONTRACTS.md` §8 is the authoritative wire shape — reproduced here verbatim (not re-derived) so this document doesn't drift from it a second time:

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
  "surfaces": [
    { "key": "chat", "label": "Chat" },
    { "key": "agent_studio", "label": "Agent Studio" },
    { "key": "cowork", "label": "Cowork" },
    { "key": "desktop", "label": "Desktop" }
  ],
  "features": {
    "discover": true, "yours": true, "create_with_ai": true, "write": true,
    "upload": true, "import_url": false, "share": true,
    "provisioning": true, "admin_policies": true, "gate_dashboard": true
  },
  "policy_summary": {
    "who_can_add": "all_users",
    "allowed_sources": ["central_index"],
    "auto_update_default": false
  },
  "taxonomy": {
    "categories": ["productivity","dev-tools","communication","data-analytics","design","finance","crm","marketing","automation","documents","research","hr-people","security-compliance","travel","legal","sales","support","general"],
    "trust_tiers": ["builtin","verified","org","community","agent_created"]
  },
  "new_badge_days": 14,
  "enums_version": "2026.09.1"
}
```

**`item_types` replaces the old flat `enabled_item_types` array** (Review fix 18, corrected here to match `CONTRACTS.md` §8 exactly — an earlier revision of this section still showed the superseded `enabled_item_types: ["skill"]` shape and a stale 16-category taxonomy missing `sales`/`support`). See `CONTRACTS.md` §8 for the full `available`/`coming_soon` semantics; this document doesn't duplicate that explanation.

**UIs render ONLY from this response** (task mandate) — no client ever hardcodes the item-types list, the surfaces list, a feature flag, the category list, or the trust-tier list. `enums_version` lets a client detect a stale generated-enums bundle and prompt a reload/rebuild (a seam for the contract-tests/codegen pipeline in `CONTRACTS.md` §16 — not implemented as an actual version-mismatch UI banner this phase, just present in the payload from day one so it doesn't require a breaking response-shape change later).

`policy_summary` is a **read-only projection** of the org's actual policy row (full policy CRUD stays behind `GET/PUT /ecosystem/policy`, admin-only) — it exists so a non-admin client can render conditional copy (e.g. "Ask an admin to enable uploads") without needing admin permissions just to know the org's current policy.

---

## 6. Recorded decisions — the 9 open questions from `ECOSYSTEM_PLAN.md` §15

Per your instruction, these are now decisions, not open questions. `ECOSYSTEM_PLAN.md` §15 is being edited in place to mark each one `RESOLVED` with a pointer back here; the authoritative decision text is:

1. **Execution-type `SkillRecord`s are legacy and not imported.** The read-through bridge (`ECOSYSTEM_PLAN.md` §4.2) exposes `skills_pg` rows with `legacy_source='skills_pg'` for *behavioral*-type skills only (the type Cowork actually executes, per `ECOSYSTEM_PLAN.md` §1.1). `execution`-type `SkillRecord`s are excluded from the bridge entirely — they have no confirmed live execution path in the codebase and importing them as installable Ecosystem "Skill" items would let a user install something that silently does nothing. Confirmed with PO per this instruction; if a live execution path for these is found later, revisit.
2. **`workers/external_sync_worker.py` is a design reference only.** Nothing in the Skills phase (or any phase) depends on that worker actually running; `workers/ecosystem_sync_worker.py` (new, `ECOSYSTEM_PLAN.md` §13 Week 3) is modeled on its *shape* (manifest-driven, idempotent-by-content-hash, split fetch/import) but is an independent implementation with no runtime dependency on the original worker's config files ever existing.
3. **The `connectors/registry.py` ↔ `mcp_registry` dead-wiring fix is gated behind a new flag, `ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE`, default **off**, and is explicitly **not** part of this (or any near-term) phase.** Confirmed per this instruction. This also means `ECOSYSTEM_PLAN.md` §13's Week-1 row, which previously listed this fix as a prerequisite task, is being corrected (see the diff note in `ECOSYSTEM_PLAN.md` itself) — it wasn't actually required for the Skills item type anyway, since Skills don't route through `mcp_registry`/`connectors/registry.py` at all.
4. **`routers/mcp_governance_router.py` is untouched.** No fix, no reuse, no reference implementation borrowed from it. `ECOSYSTEM_PLAN.md` §13's Week-1 row and §13's legacy-deprecation ordering are both being corrected to remove the "fix it" and "replace once trusted" language — it stays exactly as broken/dead as it is today until some future, separate decision addresses it.
5. **Legacy `org_id` gaps are out of scope; new tables enforce `org_id` from day one.** No change proposed to `user_oauth_tokens`/`CredentialVault`/`connector_definitions`'s missing `org_id` columns. Already true of every new table in `ECOSYSTEM_PLAN.md` §4 — this decision just makes it explicit that closing the legacy gap is not this initiative's job.
6. **`lucide-react` is banned in new code; existing usage goes on a CI allowlist with a cleanup ticket.** Concretely: the new license-check CI job (`ECOSYSTEM_PLAN.md` §11/§13 Week 2) ships with a static allowlist file (e.g. `.ecosystem-license-allowlist.json`) listing every currently-lucide-importing file path (the 78 files identified in `ECOSYSTEM_PLAN.md` §1.6 — corrected from an earlier count of 77, see `docs/ecosystem/design/CHANGELOG.md`'s 2026-09-25 entry); the check fails on any ISC/non-MIT-Apache dependency usage **not** on that list, and a separate, already-filed cleanup ticket (referenced by ID once filed — not this document's job to file it) tracks shrinking the allowlist to zero over time. `packages/ecosystem-ui` itself is never added to the allowlist — it's new code, held to the real rule from its first commit.
7. **The new broker never authenticates via a shared-secret header plus a body-supplied `user_id`.** The credential-broker design (`ECOSYSTEM_PLAN.md` §8.3) already only resolves identity from the authenticated request context (`auth/dependencies.py`), never from a caller-supplied field — this decision just makes explicit that the existing `/connectors/execute`/`/connectors/status-for-user` pattern (`ECOSYSTEM_PLAN.md` §1.3) is a **known gap in existing code**, reported to security as its own item, and is explicitly **not** a pattern the new broker inherits or extends, even for its own internal callers.
8. **AgentStudio and Cowork are read-through only.** Not a Phase-1.5-and-later stretch goal anymore — this is the settled, indefinite target state. `EcosystemService` never writes to `skills_catalog`/`skill_files` (AgentStudio) or `cowork_roles` (Cowork); those systems keep their own write paths forever, bridged into the Ecosystem catalog read-only via `legacy_source`/`legacy_ref` (`ECOSYSTEM_PLAN.md` §4.2). `ECOSYSTEM_PLAN.md` §13's "Stretch / explicitly Phase 1.5" paragraph is being corrected to remove the write-unification framing.
9. **Cowork's server-side role-resolution gap is out of scope.** `get_effective_capabilities()` is **not** wired into `agents/orchestrator.py`'s `_plan_office()` this phase or any near-term phase — the existing client-side (`ainxt-cli`) wiring for Cowork roles stays exactly as it is. Confirmed per this instruction.

---

## 7. UI/design decisions resolving the Skills audit's mismatches

Cross-referenced to `SKILLS_UI_AUDIT.md`'s row/mismatch labels where applicable.

1. **Marketplace naming + nested routes** (resolves M1, M6): the nav entry, route prefix, and all copy use **"Marketplace"** (not "Customize" — the FE's existing name wins, since it's already shipped and users would see it first). Routes become a real tree: `/marketplace/:typeSlug`, `/marketplace/:typeSlug/new`, `/marketplace/:typeSlug/upload`, `/marketplace/:typeSlug/import` (Review fix 11 — the third create-payload path, `create_via: import`, missing from an earlier revision of this list), `/marketplace/:typeSlug/:namespace` — using the route-slug mapping from §2 above, so `/marketplace/mcp/:namespace` is correct even though the enum value is `mcp_server`.
2. **`verdict[]` filter** (resolves M2): `CONTRACTS.md`'s list-query format gains `verdict[]=pass|warn|fail|pending` as a sibling to `status[]`, backed by a join against each item's latest `ecosystem_item_versions.gate_verdict`.
3. **18-category taxonomy, served via config** (resolves M3; count corrected — an earlier revision of this item said "16" and stopped after adding `legal`): the canonical list (`ECOSYSTEM_PLAN.md` §4.1, updated) first adds `legal` to the previous 15, landing on 16 — reconciling the merged FE's inclusion of "Legal" (present in its hardcoded taxonomy and its own seed data, e.g. the "Contract Clause Reviewer" example skill) with the original plan's list, which had omitted it — then Review fix 15 (see the fix index in §9 below) adds `sales` and `support`, landing on the final **18** shown in §5's response shape and `CONTRACTS.md` §8. No client hardcodes this list; it's served exclusively via `GET /ecosystem/config`'s `taxonomy.categories` (§5 above).
4. **Create-with-AI rebuilt on the AgentStudio Skill Factory, with a staged draft/preview/confirm flow** (resolves M4): the chat "Create with AI" path calls into the **existing** `AgentStudio/backend/skill_factory/pipeline.py` conversational pipeline (`SkillIntentParser` → `SkillClarificationEngine` → `SkillBlueprintGenerator` → `SkillContentGenerator` → `SkillBundleDecider` → `SkillCritiqueAgent` → `SkillQualityLoop` → `SkillAssembler`, per `ECOSYSTEM_PLAN.md` §1.1) rather than building a second, parallel generation pipeline — this is a genuine cross-system reuse decision, not just a read-through bridge: the *service layer* for chat-driven skill creation calls the Skill Factory's existing generation functions directly, then hands the assembled draft to `EcosystemService`'s creation path (still additive — the Skill Factory's own `skills_catalog`/`skill_files` write path is untouched; `EcosystemService` calls the Factory's generation functions and writes the *result* into `ecosystem_items`/`ecosystem_item_versions`, it does not write into `skills_catalog`). The staged flow: draft generated → full preview/edit card shown in chat (never auto-saved) → user confirms → gate runs → item lands as a private, installed draft.
5. **Mandatory license, MIT default** (resolves M5): every creation path (manual form, upload, Create-with-AI's confirm card) requires a `license` field before submission is possible; the manual form and Create-with-AI card default the field to `MIT`; upload requires the uploaded `SKILL.md`'s frontmatter to declare a license or the upload flow prompts for one before proceeding (an unset or disallowed license is caught client-side as a hard validation error, and re-validated server-side by gate stage 2 regardless — the client check is a UX convenience, never the actual enforcement point).
6. **Featured flag + org override**: `ecosystem_items` gains an `is_featured` boolean (platform-level, set by whoever curates `ecosystem/builtin`/the central index), and a new small table `ecosystem_featured_overrides (org_id, item_id, featured BOOLEAN)` lets an org admin pin or unpin a specific item as featured *for their org's Discover page* independent of the platform-level flag — an org can feature something the platform didn't, or hide the platform's featured pick, without affecting any other org.
7. **`new_badge_days = 14`**: the "New" badge (card + detail page) renders when `now() - ecosystem_item_versions.created_at < 14 days` for the item's earliest version. The value itself comes from `GET /ecosystem/config`'s `new_badge_days` field (§5) rather than being hardcoded in `ecosystem-ui`, so it can be tuned per-deployment without a client release.
8. **No install counts in the UI, anywhere**: the item-summary and item-detail response shapes in `CONTRACTS.md` do not include an `install_count`/`installs` field at all (not just "don't render it" — it isn't even sent), closing off the possibility of a future UI accidentally surfacing it. Internal metrics/telemetry may still count installs server-side for operational purposes (`ECOSYSTEM_PLAN.md` §12); this decision is about the public API surface and UI only.
9. **Icon field: `url:`/`emoji:` prefix convention + monogram fallback**: `ecosystem_items.icon_url` (existing column, `ECOSYSTEM_PLAN.md` §4) is repurposed as a single string field with a required prefix: `url:https://...` for an uploaded/hosted icon image, or `emoji:🧠` for a Unicode emoji (matching the merged FE's existing emoji-palette UX, which this decision keeps rather than discarding — see the audit's card-icon row). If the field is null/empty, `ecosystem-ui` renders a **monogram** (the item's first display-name character, on a deterministic-per-namespace background color) as the fallback — never a broken-image icon or a generic placeholder glyph, and never `lucide-react`.
10. **Async quick-add with a content-hash verdict cache** (resolves M8): `POST /ecosystem/items/{id}/install` always returns the async `{job_id, status:"verifying"}` envelope (per `CONTRACTS.md` §5, unchanged) — but the gate orchestrator first checks whether an `ecosystem_gate_runs` row already exists for the exact `(content_hash, scanner_version)` pair being installed (e.g. re-installing an already-gated version, or a second org installing the same public item). If a cached pass/warn/fail verdict exists, the job resolves near-instantly by reusing it (no sandbox re-run) rather than re-executing the full pipeline — making the common "install something already vetted" path feel fast, while a genuinely new version still pays the full gate cost.
11. **Immutable versions + rollback**: reconfirms `ECOSYSTEM_PLAN.md` §4's existing design (`ecosystem_item_versions` rows are never mutated in place; "Edit" always creates a new version row) — no design change, this decision just closes M9 by stating explicitly that the FE's in-place-mutation behavior must not be carried over.
12. **Uninstall vs. owner-only soft delete, now with an explicit `delete_draft` action** (resolves M10; **superseded/tightened per Review fix 6** — the original draft here left the private-zero-install-draft hard-delete case as an implicit, undocumented side effect of `uninstall`, which is exactly the kind of hidden behavior this whole initiative is trying to move away from): `POST /ecosystem/items/{id}/uninstall` only ever removes the caller's own `ecosystem_installs` row — it can never affect the underlying item, regardless of who published it. `POST /ecosystem/items/{id}/deprecate` (owner/admin-only) sets `ecosystem_items.status → 'deprecated'` (new columns `deprecated_at`/`deprecated_by`, `ECOSYSTEM_PLAN.md` §4) — existing installs keep working (matching the "source unavailable" behavior already designed for yanked upstream items) but the item stops appearing in Discover. **A third, separate, explicit action** — `POST /ecosystem/items/{id}/delete-draft` (`CONTRACTS.md` §6/§17) — is the only way to hard-delete an item's storage, and only appears in `allowed_actions` when the item is a private, zero-other-installs draft. There is still no plain "Delete" action for anything published/shared.
13. **Remove `ThirdPartyCheckModal`, the `SkillsHome` first-party/third-party split, and the "Third-party" badge** (resolves M7): confirmed for removal exactly as the audit recommended — superseded by the trust-tier badge system and the real Verification tab/gate mechanism, which cover the same ground with an actual backend behind it instead of 4 static always-passing checks.
14. **~~Hide Connectors/Plugins/MCP~~ — SUPERSEDED, see §9 item 18 below.** The audit's original HIDE-FOR-NOW recommendation (don't render these tabs at all) is no longer the decision as of Review fix 18: all 4 type tabs are now **visible**, with Connectors/Plugins/MCP rendering as read-only "Coming soon" placeholders rather than being omitted from the UI entirely. The underlying `ECOSYSTEM_TYPE_*` flags (all default off) are unchanged — only the FE's *visibility* treatment of the not-yet-enabled types changed, from "don't show the tab" to "show a disabled placeholder tab."
15. **`jszip` license notice**: add a `THIRD-PARTY-NOTICES.md` entry for `jszip` (dual MIT/GPL-3.0, used under the MIT option) — a one-line documentation task, no design impact; noted here so it isn't lost between this document and `ECOSYSTEM_PLAN.md` §11's licensing section, which is also being updated to reference it.
16. **Accent colors become theme tokens**: the merged FE's per-tab `ACCENT_CHIP`/`ACCENT_TEXT`/`ACCENT_BORDER_HOVER` maps (hardcoded to Tailwind's `indigo`/`sky`/`violet` classes) are replaced with references to host-injected theme tokens (per `CONTRACTS.md`'s host-injection requirement — `ecosystem-ui` receives theme tokens from whichever app embeds it, per `ECOSYSTEM_PLAN.md` §9's "no hex values" rule) — `ai-ui` and the workspace host can each supply their own token values without touching `ecosystem-ui`'s component code. Skills keeps its own accent slot in the token set (since it's the only type shipping this phase); Connectors/Plugins/MCP's accent tokens are reserved (named, unused) so adding those types later doesn't require a token-set breaking change.

---

## 9. Review — full fix index

18 fixes, applied in this revision across all three documents. Each row names where the authoritative detail now lives — most are documented in full elsewhere and only indexed here to keep one place that maps "fix N" to "where it actually is."

| # | Fix | Where it's documented |
|---|---|---|
| 1 | Product entitlement (`ecosystem_org_products`, `x-ainxt-product` only selects among entitled products, `POLICY_FORBIDDEN` for non-entitled) | §4 above; `CONTRACTS.md` §4; `ECOSYSTEM_PLAN.md` §4 (`ecosystem_org_products` DDL) |
| 2 | Namespace rules — verified publisher slug, partial unique indexes (global vs. per-org) | `ECOSYSTEM_PLAN.md` §4 (`ecosystem_publishers`, the two `ux_ecosystem_items_namespace_*` indexes); `CONTRACTS.md` §15 |
| 3 | `SourceKind = 'local'` (one per org), `ecosystem_items.source_id` stays `NOT NULL` | `ECOSYSTEM_PLAN.md` §4 (decision + DDL); `CONTRACTS.md` §1 |
| 4 | `ainxt.orgs` doesn't exist; `org_id` is `VARCHAR(255)`, not `UUID` | `ECOSYSTEM_PLAN.md` §4 header note (full citation trail: `db/models.py:78,294,348,383,437,827,1074,2124,2803`, `auth/jwt_handler.py:65,80,102`) |
| 5 | Install default surfaces come from the product profile at insert time, not a DB-level enterprise-shaped default | `ECOSYSTEM_PLAN.md` §4 (`ecosystem_installs.surfaces` comment + `DEFAULT '[]'`) |
| 6 | `delete_draft` explicit allowed_action replaces the implicit hidden hard-purge | §7 item 12 above (rewritten); `CONTRACTS.md` §6, §17 |
| 7 | `icon_url`'s `url:` form restricted to same-origin object-storage uploads (raster or sanitized SVG), no external URLs | `CONTRACTS.md` §7, §10 (`POST /ecosystem/uploads/icon`), §3 (`ICON_SOURCE_NOT_ALLOWED`) |
| 8 | UI default view = Yours if the user has items of that type, else profile `default_view` | `CONTRACTS.md` §7 (bottom), §9 (`GET /ecosystem/installs`'s `has_any` field) |
| 9 | Explicit JSON schemas: `ItemSummary`, `ItemDetail`, `Version`, `GateRun`+`Finding`, `Install` (with `origin`), `Job`, `Capabilities`, `Config` | `CONTRACTS.md` §9 (new section) |
| 10 | Create-with-AI draft endpoints (`POST /ecosystem/drafts` SSE, `GET`/`PATCH /ecosystem/drafts/{id}`, `POST .../submit`) | `CONTRACTS.md` §10; `ECOSYSTEM_PLAN.md` §4 (`ecosystem_drafts` DDL), §9 |
| 11 | Create payloads (write/upload/import) + `/marketplace/:typeSlug/import` route | `CONTRACTS.md` §10, §2 |
| 12 | Admin featured override endpoints | `CONTRACTS.md` §11, §17 |
| 13 | `skill_view`/`read_skill_file` tool contracts (pinned version, size limits, errors) | `CONTRACTS.md` §12 |
| 14 | `Idempotency-Key` header on create/install; rate-limit response headers | `CONTRACTS.md` §4 |
| 15 | Taxonomy +`sales`/+`support` (18 total) | `ECOSYSTEM_PLAN.md` §4.1; `CONTRACTS.md` §8 |
| 16 | Remove stale "FIX connector registry" text (§2 row, §3.1 diagram), soften §1.4 Cowork "must close" wording, `ecosystem_sources.credential_id`/§8.1/§8.4 → SecretStore seam | `ECOSYSTEM_PLAN.md` §2, §3.1, §1.4, §8.1, §8.4, §7 (Sources) |
| 17 | Record `marketplaceStore.js`/localStorage removal + CAPTCHA-revert prerequisite status | §11 below (new); `SKILLS_PHASE_PLAN.md` |
| 18 | **Changed decision**: all 4 type tabs visible now, Connectors/Plugins/MCP as "Coming soon" placeholders, `visible_item_types` + per-type `state` in config | §7 item 14 above (superseded note); `CONTRACTS.md` §1 (`ItemTypeState`), §8 (`item_types` array); `ECOSYSTEM_PLAN.md` §4 (`visible_item_types` column), §9 (UI spec) |

---

## 10. What changed in `CONTRACTS.md` and `ECOSYSTEM_PLAN.md` (this revision)

See those two files' own diffs for the full detail; summary of every touch point, for review convenience:

- `CONTRACTS.md`: fully restructured (17 sections, up from 13) to fit the Review's additions without cramming — see the fix index in §9 above for what moved where. Net-new: `InstallOrigin`/`DraftStatus`/`ItemTypeState` enums, `SourceKind='local'`, a combined Headers section (`x-ainxt-product` entitlement + `Idempotency-Key` + rate-limit headers), a JSON Schemas section, a Drafts/create-payloads/icon-upload section, an Admin featured-overrides section, a Tool Contracts section (`skill_view`/`read_skill_file`), two new error codes (`NAMESPACE_INVALID`, `ICON_SOURCE_NOT_ALLOWED`), `item_types`/`route_slugs` restructuring in `GET /ecosystem/config`, and a consolidated full endpoint list (§17) that supersedes the partial list in `ECOSYSTEM_PLAN.md` §5.
- `ECOSYSTEM_PLAN.md`: §4 DDL — every `org_id UUID ... REFERENCES ainxt.orgs(id)` column corrected to `VARCHAR(255)` (Review fix 4, a real bug in the earlier draft — `ainxt.orgs` never existed); new tables `ecosystem_publishers`, `ecosystem_drafts`, `ecosystem_org_products`; `ecosystem_sources` gains `kind='local'` + SecretStore-seam columns (dropping the old `credential_id → credential_vault` FK); `ecosystem_items`' single `UNIQUE(namespace, item_type)` replaced with two partial unique indexes; `ecosystem_installs` gains `origin` and loses its hardcoded 4-surface default; `ecosystem_product_profiles` gains `visible_item_types`. §4.1 taxonomy → 18 categories (`legal`/`sales`/`support` added). §3.1 diagram and §2's comparison-table row drop the "FIX connector registry" framing. §1.4's Cowork gap is reframed as explicitly out-of-scope rather than "must close." §5 API outline gains the drafts/upload-icon/delete-draft/featured endpoints. §9 UI spec rewritten for the coming-soon-tabs decision. §11/§13 unchanged from the prior revision (jszip notice, deferred fixes) except cross-reference renumbering.

---

## 11. Prerequisite/cleanup tracking (Review fix 17)

Two items to record explicitly rather than let slide between documents:

- **`ai-ui/src/marketplaceStore.js` and its `localStorage`-backed data layer are removed once the real `EcosystemClient` API adapter lands** (`SKILLS_PHASE_PLAN.md`, frontend refactor tasks) — not before, since the merged frontend's components need a working data source at every point in the refactor, and `marketplaceStore.js` is that source until the adapter is ready to swap in. This is a deletion that happens as part of the refactor task, not a separate cleanup ticket.
- **The `Login.jsx` CAPTCHA-disable is a prerequisite task, status confirmed as of this revision: still disabled.** Re-checked directly against the current working branch (`ai-ui/src/components/Login.jsx`) — the validation block is still commented out (`// TEMPORARILY DISABLED for local dev/testing... re-enable before shipping`). This has nothing to do with the Skills marketplace scope and should be reverted independently, but it's listed as a named prerequisite task in `SKILLS_PHASE_PLAN.md` (not silently assumed fixed) precisely because it's still broken at the time of this writing. **Status update**: this was in fact reverted by task P-0 in the M0 milestone, `docs/ecosystem/design/CHANGELOG.md`'s 2026-09-25 entry — the note above is left as historical context of the state at the time this document was written, not a currently-accurate status.

---

## 12. Visibility and default-install mechanism (Review round following M1, item F)

Three distinct visibility rules, identical on web and desktop (both read the same `ecosystem_installs`/`allowed_actions` shapes — desktop has no separate visibility model of its own):

**1. User-created/uploaded items are private until shared.** `create_via: write|upload|import` (task B-6) always produces `scope='private'`, `origin='created'`, `installed_for=<creator's user_id>` on auto-install (item E). Nothing about this item is visible to anyone else until the creator explicitly shares it (`POST /ecosystem/items/{id}/share`, task B-19) or an admin later re-provisions it at a wider scope (below) — sharing/re-provisioning are separate, explicit actions, never an implicit consequence of creation.

**2. Builtin items are available to everyone automatically, via lazy per-user provisioning, not a batch "seed for all orgs" job.** This platform has no real orgs table (`org_id` is a free-text convention, `ECOSYSTEM_PLAN.md` §4) — there is no fixed list of "all orgs" to iterate over at seed time, and even if there were, a new org created after the seed job ran would be missed. The mechanism instead is **on-demand, idempotent provisioning at first request**: `config_service.get_effective_config()` (task B-12 — `GET /ecosystem/config`, "the single call every UI makes before rendering anything marketplace-shaped") is the hook point. On each call, for every `scope='builtin'` item the caller's product profile has `enabled_item_types` for for, the service ensures an `ecosystem_installs` row exists for **that specific caller** (`installed_for=<user_id>`, `scope='provisioned'`, `origin='provisioned'`, `enabled=true`, `surfaces` from the caller's product profile) via `INSERT ... ON CONFLICT DO NOTHING` keyed on the existing `UNIQUE NULLS NOT DISTINCT (item_id, org_id, installed_for)` constraint (`ECOSYSTEM_PLAN.md` §4) — so calling it a thousand times is exactly as cheap as calling it once after the first. **Per-user, not per-org, deliberately**: rows are materialized per user (not one shared org-wide row with `installed_for=NULL`) specifically so "users may disable unless admin marks Required" (item F) is representable at all — an org-wide single row would mean one person's disable action turns the item off for the entire org, which is not what "users may disable" means. A user who never opens the marketplace/chat never gets a row materialized for them — provisioning is genuinely lazy, not a background sweep.

**3. Users may disable a provisioned default unless an admin has marked it Required.** Disabling is the normal `enable`/`disable` action (task B-10) on the caller's own provisioned install row — `allowed_actions` includes `disable` when `scope='provisioned'`, and never includes it when `scope='required'`. An admin promotes a specific item from provisioned to required via a new admin-only action (task B-19, alongside `force_disable`/`unyank`) that updates `scope='required'` on **existing** rows for that item and changes what future lazy-provisioning calls create for users who haven't been provisioned yet.

**4. Admin-authored items get an explicit scope picker, not just auto-install-as-private.** For a caller with `marketplace:provision` (admin tier, `auth/rbac.py`), the create payload (task B-6) accepts an optional `provision_scope: "private" | "org_default_on" | "required"` (client-facing name — do not confuse with `ecosystem_items.scope`, the *catalog* scope column; an admin-provisioned org-wide item still gets `ecosystem_items.scope='org_private'`, `org_id=<admin's org>`, same as any other org-scoped item — `provision_scope` only affects the *install* rows this creates) — shown in the UI's scope picker (task F-4/F-8, "Just me" / "Everyone in org (default-on)" / "Required") only when the caller has that permission, and only applied to the auto-install step **after** the gate passes/warns (item E) — a `fail` verdict never provisions anything at any scope, admin or not. `provision_scope` absent or `"private"` (the default for a non-admin, or an admin who didn't pick anything) behaves exactly like a normal user creation (`ecosystem_installs.scope='private'`, `origin='created'`). `"org_default_on"` (`ecosystem_installs.scope='provisioned'`, `origin='provisioned'`) and `"required"` (`scope='required'`, `origin='required'`) immediately materialize the creating admin's own install at that scope. **Extending point 2's lazy-provisioning target list**: `config_service`'s provisioning check (point 2) targets `scope='builtin'` items (org-independent) **union** any item with an existing `origin IN ('provisioned','required')` install row for the caller's `org_id` (covers exactly this admin-provisioned-org-wide case) — so a new user in that org gets their own copy on their first `GET /ecosystem/config` call, the same lazy mechanism, no separate code path for "admin-provisioned" vs. "platform-builtin."
