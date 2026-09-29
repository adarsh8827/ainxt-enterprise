# Connectors + Advanced/MCP servers — phase plan

Stage 0 plan, per `CLAUDE.md` conventions. Branch `feature/ecosystem-connectors-plugins` off `feature/ecosystem-external-sources` (tag `skills-port-v1`). Companion doc: `PLUGINS_PHASE_PLAN.md`. Extends `CONTRACTS.md` (already anticipates this phase — see §0 below) rather than re-deriving it.

## 0. What already exists (don't rebuild)

- `db/models.py:2896` `EcosystemItem.item_type` already has `connector`/`mcp_server`; `legacy_source` already anticipates `connector_definitions` for read-through.
- `services/ecosystem/gate/mcp_connector_stage.py` — gate stage 7, already wired at `gate_service.py:589`, currently a no-op for `item_type=skill`. Fill in `run()` for `connector`/`mcp_server`: HTTPS-only + SSRF guard, OAuth protected-resource metadata check, tool-annotation (read/write/destructive) presence check.
- `packages/ecosystem-ui/src/components/TypeTabs.tsx` already renders 4 tabs; `connector`/`mcp_server` currently render `ComingSoonTab.tsx`. This phase restructures to ONE "Connectors" tab (default view) + "Advanced: MCP servers" sub-view (policy-gated), not a 4→4 fill-in.
- `connectors/oauth2.py`'s `OAuth2Handler` (PKCE S256, auth-URL, exchange, refresh, revoke, Redis flow-state) and `core/ckms/key_service.py`'s `KeyService` (envelope encryption) — reuse both wholesale, do not reimplement.
- `connectors/registry.py`'s `get_user_status()`/`list_connected_tools()`/`_get_connected_connectors()` — the read-through adapter wraps these; existing `ainxt.user_oauth_tokens`/`ainxt.connector_definitions` tables are untouched.
- `services/ecosystem/resolver_service.py`'s `get_effective_capabilities()` already gates per item_type on `ECOSYSTEM_TYPE_CONNECTOR`/`_MCP` flags and returns hardcoded `[]` for both today — this phase populates those arrays, no new resolver.
- `CONTRACTS.md` §1 already has `ConnectionStatus`/`SecretClass`/`SecretBackend`/`GateStage(mcp_connector)`/`ItemTypeState` enums seamed in. §9's `Capabilities` schema already has `connectors: []`/`mcp_tools: []` placeholders to fill.
- Known gap to NOT inherit: the existing `/connectors/execute`/`/connectors/status-for-user` impersonation gap noted in `ECOSYSTEM_PLAN.md` (~line 873) — the new broker's own endpoints must authorize per-caller, not trust a passed user_id.

## 1. New/extended pieces

1. **`store/ecosystem_secret_store.py`** (new) — per-org envelope-encrypted secret store, modeled on `store/credential_vault.py`'s CRUD shape (`create/get/get_value/update/delete/list/rotate`) but backed by `KeyService.decrypt`/`.instance()` for the encryption key instead of a flat env var. Adds the missing `needs_reauth`/`expired` states `registry.get_user_status()` doesn't have today (`ConnectionStatus` enum already ships these — §1 CONTRACTS.md).
2. **`services/ecosystem/credential_broker_service.py`** (new) — OAuth 2.1 flows (wraps `OAuth2Handler`), admin OAuth-app registration (client id/secret via the new secret store), remote-MCP protected-resource metadata discovery + SSRF guard (genuinely new — confirmed nothing today covers this), connection status queries. Read-through: for existing native connectors, delegates status/list calls straight to `connectors/registry.py` — never duplicates state.
3. **Tool-calling core** (shared with Plugins phase, tracked separately — see task list): additive `tools: Optional[list] = None` param added explicitly to `gateway_claude.py`, `gateway_openai.py`, `gateway_gemini.py`, `gateway_local_llm.py` (no `**kwargs` catch-all in these 4 today — confirmed live); `gateway_generic_openai.py`/`gateway_ollama.py` need smaller changes. `models/model_router.py:2985 generate()`/`:1596 route()` get an additive `tools=None` passthrough. Tool registry: new `mcp/tool_annotations.py` (read/write/destructive classification — doesn't exist anywhere today, confirmed by grep). Approval: new chat UI card (no existing pattern to match — confirmed via grep, genuinely new UX).
4. **`routers/ecosystem_connectors_router.py`** (new, mounted under `/ecosystem`) — connect/disconnect/reconnect, admin OAuth-app CRUD, connection status list. Extends `CONTRACTS.md` §17's endpoint list (new section §19, since §12/§18 taken by tool contracts/license policy — see companion doc for §19/§20 split).
5. **Gate**: fill in `mcp_connector_stage.py`'s real checks (item 0 above); extend `sandbox_stage.py`'s network-off assumption — remote MCP connectors need an explicit exception path (outbound HTTPS to the declared connector URL only, still no arbitrary network) rather than reusing the AST-only skill path unchanged.
6. **UI**: `packages/ecosystem-ui/src/components/Connectors/` (Discover cards, Detail w/ Tools list + side panel, Yours status chips + Reconnect/Disconnect) + `Advanced/McpServers/` (custom URL add, local/stdio list, admin runtime status+logs). `TypeTabs.tsx` restructured to collapse `connector`+`mcp_server` into one tab with an internal "Advanced" sub-view gated by a policy flag (not a 5th top-level tab). Chat: inline Connect card + "Using `<connector>`" indicator + approval card (new component, no existing pattern). Agent Studio: `NativeEngine._resolve_catalog_tools()` extended once resolver flags flip.
7. **Local/stdio MCP runtime** (Stage 3 only): new lifecycle worker (`workers/start_workers.py --mcp-runtime` flag, following the existing `--doc`/`--chat` pattern) — confirmed neither `sandbox/ecosystem_gate_executor.py` (gate-time, one-shot, network off) nor `sandbox/docker_executor.py` (60s timeout, one-shot) supports long-running managed processes; this is genuinely new code reusing `docker_executor.py`'s resource-limit/no-priv-escalation Docker patterns but adding health-check/restart-backoff/idle-shutdown lifecycle on top. Explicitly evaluated against the gate/gate-sweeper fork-safety incident (`CLAUDE.md`) before deciding process topology — default to its own dedicated process, never shared with `--gate`/`--gate-sweeper`.

## 2. Flags (all default OFF)

`ECOSYSTEM_CREDENTIAL_BROKER`, `ECOSYSTEM_TOOL_CALLING`, `ECOSYSTEM_TYPE_CONNECTORS`, `ECOSYSTEM_TYPE_MCP` (already referenced in `resolver_service.py` per fork research — confirm current default is off), `ECOSYSTEM_MCP_ADVANCED_POLICY` (gates the Advanced sub-view to admins/developers per org policy).

## 3. Migrations

New tables: `ecosystem_secrets` (per-org envelope-encrypted blobs, org_id/user_id/kind/ciphertext/key_version), `ecosystem_oauth_apps` (admin-registered provider client id/secret via secret store, per-org), `ecosystem_connections` (connection status per user×connector/mcp_server, supersedes nothing — additive to `user_oauth_tokens`), `ecosystem_mcp_runtime` (local server instance lifecycle state: status, container_id, last_health_check, restart_count). No changes to existing `connector_definitions`/`user_oauth_tokens`.

## 4. Tests

Targeted per task while building (regression proof for the model-router change is mandatory before Stage 2+ per the standing rule); security tests deferred to the Stage 5 full pass (token isolation, SSRF, approval enforcement, cross-org 404s, route-enumeration auth).

## 5. Risks

- Adding `tools=` to 4 fixed-signature gateway adapters touches non-ecosystem files — every call site of each `generate()` must be re-verified unaffected (default `None`, no behavior change when absent).
- Remote MCP OAuth + SSRF guard is genuinely new attack surface — most security-sensitive piece of this phase.
- UI tab restructuring changes existing (if `coming_soon`) user-visible surface — must stay behind `ItemTypeState` so an org without the flags on still sees today's 4-tab/coming-soon behavior unchanged.
- Local MCP runtime process topology mistake could recreate the fork+lock deadlock class already hit once (2026-09-28) — treat as a hard constraint, not a nice-to-have.
