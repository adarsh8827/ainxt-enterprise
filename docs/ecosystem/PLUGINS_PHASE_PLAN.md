# Plugins — phase plan

Stage 0 plan, per `CLAUDE.md` conventions. Same branch/tag as `CONNECTORS_PHASE_PLAN.md`; read that doc's §0 first (shared credential broker / tool-calling core / gate stage 7 apply here too).

## 0. What already exists (don't rebuild)

- `EcosystemItem.item_type` already includes `plugin`; `legacy_source` already anticipates `cowork_roles` for read-through (confirmed enum comment at `db/models.py:~2924`).
- **`services/cowork_roles.py`'s `CoworkRole`** is the closest existing precedent for a plugin manifest: already bundles `allowed_connectors` + `skill_names` + `subagent_allowlist` (no commands/hooks, no versioning/content-hash). `materialize_role()` (`:732-780`) is the existing "install"-equivalent (writes agent `.md` + scoped `managed-mcp.json`) — the read-through adapter wraps `list_marketplace()`/`list_published_roles()`/`get_role()`, does not migrate the `cowork_roles` table.
- `store/ecosystem_object_storage.py` — content-hash-addressed storage already exists in exactly the scheme a plugin manifest needs; reuse directly, don't reinvent.
- `services/ecosystem/gate/manifest_stage.py` (gate stage 1) is single-item only today (name/description/file-count/path-traversal) — needs a plugin-bundle variant that validates each bundled part with ITS OWN stage rules (a bundled connector still runs stage 7's real connector checks, a bundled skill still runs the skill path), not a bypass.
- `services/ecosystem/resolver_service.py`'s `get_effective_capabilities()` already has the `plugins: []` seam in `CONTRACTS.md` §9's `Capabilities` schema — populate it, no new resolver.
- `TypeTabs.tsx`'s `plugin` tab currently renders `ComingSoonTab.tsx` — this phase makes it live (`ItemTypeState: available`), no tab restructuring needed (unlike Connectors).

## 1. New/extended pieces

1. **Plugin manifest model** — new `services/ecosystem/plugin_manifest.py`: versioned, content-hashed (reuse `ecosystem_object_storage.py`) bundle of `{skills: [], commands: [], agents: [], connectors: [], mcp_servers: [], hooks: []}` refs (by namespace, not inline content — a plugin's skill entry points at a real, independently-gated `EcosystemItem`). Each part keeps its own `EcosystemItemVersion`/gate history; the plugin's own gate run (stage 1's new bundle-variant) validates composition (no duplicate namespaces, no missing refs, license compatibility across parts) rather than re-scanning each part's content.
2. **Install semantics** — extend `services/ecosystem/installs_service.py`: installing a plugin creates/attaches installs for every bundled part, each tagged `origin: "added"` + a new `managed_by_plugin_install_id` column so parts can't be individually uninstalled while plugin-managed (mirrors `InstallScope: "required"`'s existing lock pattern in `installs_service.uninstall()` — reuse that refusal path, don't add a second one). Update = new plugin version through the gate, diffed part-by-part; unused-by-new-version parts get freed (individually uninstallable again) on update, not silently orphaned. Rollback reuses the existing version-pointer-swap pattern from `POST /ecosystem/items/{id}/new-version`'s sibling endpoints.
3. **Sources** (Stage 5, catalog-side): (a) Cowork-roles-as-plugins — read-through only, `legacy_bridge.py`-style adapter, no crawl; (b) org-created bundles — new admin UI screen to compose a plugin from already-installed items (no new backend beyond the manifest model + a compose endpoint); (c) generic "plugin marketplace manifest" source type — new `SourceKind` addition to `sources_config.py` (currently only `github_repos`/`well_known_sites` lists exist — confirmed live, the `mcp_registry` kind named in `pointer_schema.py:51`'s comment is NOT yet a wired loader, verify before assuming), org-added only, full gate, per-item license.
4. **UI**: `packages/ecosystem-ui/src/components/Plugins/` — Discover (icon/name/New badge/description/by-publisher/+), Detail tabs (Overview · Contents(n) · Skills(n) · Commands(n) · Agents(n) · Versions · Verification · License) reusing existing `Detail.tsx` tab-shell patterns, Contents tab = version selector + file tree/preview (reuse whatever `Card.tsx`/`AddDialog` already has for skill file preview rather than building new). Side panel "Connectors & tools" risk summary — plain-language rollup of the bundled parts' read/write/destructive tool annotations (depends on Connectors phase's tool-annotation work landing first).

## 2. Flags (default OFF)

`ECOSYSTEM_TYPE_PLUGINS`. Depends on `ECOSYSTEM_CREDENTIAL_BROKER`/`ECOSYSTEM_TOOL_CALLING` being at least buildable (a plugin can bundle a connector/MCP server) but does not require Connectors' UI to be live — a plugin's bundled connector can gate/install headless before Connectors' own Discover UI ships, matching the additive-only rule.

## 3. Migrations

New tables: `ecosystem_plugin_manifests` (item_version_id FK, parts as JSONB refs), `ecosystem_installs.managed_by_plugin_install_id` (nullable FK, new column not new table). No changes to `cowork_roles`.

## 4. API contracts

Extends `CONTRACTS.md` §9 (`Capabilities.plugins[]`) and adds new endpoint section §20 (after Connectors' §19): `POST /ecosystem/items/{id}/plugin-compose` (org-bundle authoring), plugin-shaped `ItemDetail.manifest` (parts list). No changes to any existing skill/install endpoint shape — plugin installs reuse `POST /ecosystem/installs` with `item_type: "plugin"`, fanning out server-side.

## 5. Tests

Targeted per task while building; Stage 5 full pass covers: install→parts-appear-tagged→uninstall-blocked-individually→plugin-uninstall-frees-parts, Cowork-role-visible-as-plugin (read-through, zero writes to `cowork_roles`), update diffing, license-compatibility-across-parts rejection case.

## 6. Risks

- Install/uninstall fan-out touches `installs_service.py`'s existing, already-subtle scope/origin logic (§9 `Install` schema notes an already-fixed regression there) — high care needed not to reintroduce a similar bug for the new `managed_by_plugin_install_id` path.
- Plugin composing a connector/MCP server inherits ALL of that item type's own risk (SSRF, credential handling) — plugin gate must not create a shortcut around stage 7's real checks.
- Contents-tab file preview reuse depends on Detail.tsx's existing tab-shell being generic enough — if not, flag as a real design deviation rather than forcing a bad fit.
