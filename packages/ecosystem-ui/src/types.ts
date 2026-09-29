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

export type ItemType = "skill" | "plugin" | "mcp_server" | "connector";
export type ItemScope = "builtin" | "optional" | "central_index" | "org_private";
export type ItemStatus = "active" | "source_unavailable" | "yanked" | "deprecated";
export type TrustTier = "builtin" | "verified" | "org" | "community" | "agent_created";
export type GateVerdict = "pass" | "warn" | "fail" | "pending";
export type GateStage = "manifest" | "license" | "static_safety" | "supply_chain" | "sandbox" | "ethics" | "mcp_connector";
export type GateSeverity = "info" | "warn" | "block";
export type InstallScope = "private" | "shared" | "org" | "provisioned" | "required";
export type InstallOrigin = "created" | "shared" | "provisioned" | "required" | "added";
export type DraftStatus = "drafting" | "ready" | "submitted" | "abandoned";
export type Execution = "server" | "local";
export type ConnectionStatus =
  | "connected" | "needs_reauth" | "expired" | "revoked" | "insufficient_scope"
  | "not_connected" | "connecting" | "error";
export type SecretClass = "platform" | "per_user" | "org_shared" | "device_local";
export type SecretBackend = "builtin" | "aws_kms" | "gcp_kms" | "azure_kv" | "vault";
export type JobStatus = "verifying" | "active" | "warn" | "blocked" | "failed";
export type ChangeKind = "installed" | "uninstalled" | "enabled" | "disabled" | "updated" | "blocked" | "connection_changed";
export type SourceKind = "github_repo" | "mcp_registry" | "well_known" | "private_git" | "skills_sh_indirect" | "local";
export type GateTrigger = "ui_add" | "chat_create" | "cli" | "index_ci" | "admin_provision" | "desktop" | "new_version";
export type ItemTypeState = "available" | "coming_soon";

export type AllowedAction =
  | "install" | "uninstall" | "enable" | "disable" | "update" | "rollback"
  | "share" | "unshare" | "report" | "deprecate" | "edit_content" | "delete_draft"
  | "force_disable" | "unyank" | "edit_policy";

/** CONTRACTS.md §2 -- fixed, small, 1:1 with ItemType; never data-driven. */
export const ROUTE_SLUGS: Record<ItemType, string> = {
  skill: "skills",
  plugin: "plugins",
  connector: "connectors",
  mcp_server: "mcp",
};

/** Editor-autocomplete convenience only -- see the file header note. */
export type KnownSurface = "chat" | "agent_studio" | "cowork" | "desktop" | "workspace_chat";
export type KnownProduct = "enterprise" | "workspace";

export interface ErrorShape {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  retryable: boolean;
}

export interface ItemTypeConfig {
  type: ItemType;
  state: ItemTypeState;
  slug: string;
}

export interface SurfaceRef {
  key: string;
  label: string;
}

export interface FeatureFlags {
  discover: boolean;
  yours: boolean;
  create_with_ai: boolean;
  write: boolean;
  upload: boolean;
  import_url: boolean;
  share: boolean;
  provisioning: boolean;
  admin_policies: boolean;
  gate_dashboard: boolean;
}

export interface PolicySummary {
  who_can_add: "all_users" | "admins_only";
  allowed_sources: string[];
  auto_update_default: boolean;
}

export interface Taxonomy {
  categories: string[];
  trust_tiers: TrustTier[];
}

/** Caller-specific, distinct from FeatureFlags: `features` is per-product
 * (every caller under the same product sees the same value); this is
 * per-caller (computed from the caller's own resolved permissions --
 * marketplace:share / marketplace:provision). Any scope-selection UI
 * that exists before an item is even installed (no allowed_actions array
 * to consult yet) must gate on this, never on `features` alone. */
export interface CallerPermissions {
  can_share: boolean;
  can_provision: boolean;
  /** Per-surface toggles round (2026-09-29): real, caller-specific RBAC
   * signal (marketplace:admin_surfaces) -- gates the admin-only "Advanced"
   * per-surface override on Yours/AddDialog/Detail. Not a product feature
   * flag: every caller under the same product sees a different value here
   * depending on their own role. Optional (rather than required) so every
   * existing test/story literal that predates this field keeps compiling
   * -- an absent value is treated as `false` (fail closed: no admin
   * surface-override powers unless the backend explicitly says so). */
  can_admin_surfaces?: boolean;
}

/** Admin-only (real incident, 2026-09-27: a full day of testing against a
 * 15-hour-stale image, no way to tell from the running app) -- undefined
 * for a non-admin caller, never sent, not just hidden client-side. */
export interface BuildInfo {
  commit: string;
  built_at: string;
}

export interface EcosystemConfig {
  product: string;
  layout: "full" | "compact";
  default_view: "discover" | "yours";
  item_types: ItemTypeConfig[];
  route_slugs: Record<string, string>;
  surfaces: SurfaceRef[];
  features: FeatureFlags;
  caller_permissions: CallerPermissions;
  policy_summary: PolicySummary;
  taxonomy: Taxonomy;
  new_badge_days: number;
  enums_version: string;
  /** The caller's own default publisher-namespace prefix (CONTRACTS.md's
   * new field) -- lets "Copy to my skills" install a forked item under
   * `${caller_default_namespace_prefix}/${originalName}` with no form. */
  caller_default_namespace_prefix: string;
  /** Discover "From the web" section (2026-09-29): the real, EFFECTIVE
   * "both the instance-wide ECOSYSTEM_LIVE_SOURCES flag AND this org's own
   * live_sources_enabled policy toggle are true" signal --
   * services/ecosystem/config_service.py's get_effective_config() computes
   * it via the exact same live_search_service.live_search_enabled() GET
   * /ecosystem/search/live itself calls, so it can never disagree with
   * that endpoint's own behavior. Distinct from policy_summary's raw
   * live_sources_enabled (the org toggle alone, real gap: that alone isn't
   * enough to know whether a search would ever return anything). Gates
   * whether the section renders at all -- never a disabled/greyed-out
   * state, per the backend's own "off unless both gates are true" design. */
  live_search_enabled: boolean;
  build_info?: BuildInfo | null;
}

export interface ItemSummary {
  id: string;
  namespace: string;
  item_type: ItemType;
  display_name: string;
  description: string;
  category: string;
  tags: string[];
  icon_url: string | null;
  trust_tier: TrustTier;
  license: string;
  status: ItemStatus;
  /** The item's own scope (builtin|optional|central_index|org_private) --
   * distinct from Install.scope below (private|shared|org|provisioned|
   * required), a different concept entirely. Real bug found live: this
   * type existed (ItemScope, above) but was never actually wired onto
   * ItemSummary, so the frontend had no way to tell a not-yet-added
   * catalog item (item_scope === "central_index", latest_version === null
   * -- no gate run exists yet) apart from one genuinely mid-verification;
   * both fell back to the same "Verifying..." badge. See
   * docs/ecosystem/design/LLD/gate.md's "Item-state model". */
  item_scope: ItemScope;
  is_featured: boolean;
  is_new: boolean;
  latest_version: string | null;
  latest_verdict: GateVerdict;
  allowed_actions: AllowedAction[];
  /** The caller's own install for this item, if any -- null/null when
   * never installed by this caller. Detail.tsx's header shows a kebab
   * menu + enable/disable toggle instead of Add/Copy once install_id is
   * non-null. */
  install_id: string | null;
  enabled: boolean | null;
  /** The caller's own install's scope, if installed -- null when never
   * installed. Needed to lock Uninstall (and explain why) for a
   * scope === "required" install in the "Installed ▾" popover, matching
   * the real server-side refusal installs_service.uninstall() already
   * enforces. */
  install_scope: InstallScope | null;
  /** The caller's own install's surfaces list, if installed -- null when
   * never installed. Detail.tsx's Overview tab ("enabled surfaces"). */
  install_surfaces: string[] | null;
  /** "chat" (usable purely through a chat conversation) or
   * "tool_dependent" (the instructions assume shell/git/file-edit access
   * -- Cowork/Desktop/Agent Studio only, never chat). null only for a
   * version created before this field existed. */
  compatibility: "chat" | "tool_dependent" | null;
  /** True when some install other than the caller's own exists (a share,
   * an org-wide provision, another user who separately installed it).
   * Distinguishes, when "delete_draft" is absent from allowed_actions,
   * "absent because this is shared/installed elsewhere" (show Retire +
   * Unshare instead) from "absent because I'm not the owner or this is
   * built-in/required" (show nothing). */
  has_other_installs: boolean;
  /** The RECIPIENT's own relevant EcosystemShare.id, when this caller's own
   * install has scope === "shared" (i.e. "unshare" is in allowed_actions).
   * Real gap this fixes: POST /ecosystem/shares/{share_id}/unshare needs
   * the SHARER's own EcosystemShare.id, which a recipient had no way to
   * look up before this field existed -- "unshare" showed up in
   * allowed_actions with nothing in the client able to act on it. null
   * whenever "unshare" isn't offered, or (rare) no matching share row
   * could be resolved for this caller. */
  share_id: string | null;
}

export interface ItemDetail extends ItemSummary {
  /** type is null when no real ecosystem_publishers row exists for this
   * slug (item 6.2, 2026-09-29 live-test round) -- always true for a
   * crawled catalog item (item_scope 'central_index'), since nobody in
   * this install owns that external namespace. Never guess a value for
   * this case client-side either -- RiskSidePanel.tsx falls back to
   * `source` below instead. */
  publisher: { slug: string; type: "org" | "user" | null };
  attribution: string;
  source: { kind: SourceKind; url: string | null };
  manifest: Record<string, unknown>;
  deprecated_at: string | null;
  deprecated_by: string | null;
}

export interface ItemVersion {
  id: string;
  version: string;
  pinned_sha: string | null;
  content_hash: string;
  license: string;
  gate_verdict: GateVerdict;
  created_at: string | null;
  is_current: boolean;
  sbom?: Array<{ name: string; version: string; license: string }>;
}

export interface GateFinding {
  stage: GateStage;
  severity: GateSeverity;
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/** Item 6: one stage's live/resolved state within a GateRun.stage_timings. */
export type StageTimingStatus = "queued" | "running" | "pass" | "warn" | "fail" | "pending" | "skipped";
export interface StageTiming {
  status: StageTimingStatus;
  duration_ms: number;
  started_at: string | null;
  /** Present only for a "skipped" stage (real gap found live, 2026-09-29:
   * gate_service.py has always recorded this -- e.g. "no scripts →
   * no sandbox", "signed catalog hash matched → fast scan reused" --
   * the frontend just never rendered it). Absent for every other status. */
  reason?: string;
}

export interface GateRun {
  id: string;
  version_id: string;
  trigger: GateTrigger;
  verdict: GateVerdict;
  scanner_version: string;
  started_at: string | null;
  finished_at: string | null;
  findings: GateFinding[];
  /** Per-stage status/duration, keyed by GateStage -- only the stages this
   * run's own path (fast path vs. full gate) actually ran. */
  stage_timings: Record<string, StageTiming>;
  /** True when this run took task D's synchronous fast path (private,
   * self-created, no bundled scripts) -- 3 stages, not 7. */
  is_fast_path: boolean;
  /** How many jobs are ahead of this run in its priority lane, only while
   * genuinely still queued (real gap found live, 2026-09-29 -- there was
   * previously no way to tell "next up" from "behind a deep pre-check
   * backlog"). null once the run has started or resolved, or if RQ is
   * unavailable. Only ever computed for the newest run. */
  queue_position: number | null;
}

/** GET /ecosystem/items/{id}/gate-runs' full response shape (item 6). */
export interface GateRunsResponse {
  gate_runs: GateRun[];
  /** Recent average duration per stage, for whichever path the latest run
   * took -- lets the Verification tab show a live ETA while in progress. */
  average_stage_durations_ms: Record<string, number>;
}

export interface Install {
  install_id: string;
  item: ItemSummary;
  version_id: string;
  scope: InstallScope;
  origin: InstallOrigin;
  installed_by: string;
  installed_for: string | null;
  enabled: boolean;
  surfaces: string[];
  auto_update: boolean;
  installed_at: string | null;
}

export interface LegacyItem {
  item: ItemSummary;
  legacy_source: string;
  allowed_actions: ["open"];
}

export interface InstallsResponse {
  installs: Install[];
  legacy_items: LegacyItem[];
  has_any: boolean;
  next_cursor: string | null;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  item_id: string | null;
  version_id: string | null;
  gate_run_id: string | null;
  error: string | null;
  stuck_message?: string | null;
  /** Additive (item 2, 2026-09-29 live-test round): install_item()'s own
   * response is now this same Job envelope -- this lets the caller learn
   * the install_id it just created without a separate round trip. Never
   * present on GET /ecosystem/jobs/{id}'s own response (a job has no
   * single install tied to it in general), so always optional. */
  install_id?: string | null;
}

export interface CapabilitySkill {
  namespace: string;
  display_name: string;
  description: string;
  slash_command: string;
}

export interface Capabilities {
  surface: string;
  skills: CapabilitySkill[];
  plugins: unknown[];
  connectors: unknown[];
  mcp_tools: unknown[];
}

export interface ItemListResponse {
  items: ItemSummary[];
  next_cursor: string | null;
  total_hint: number;
}

export interface ListItemsParams {
  item_type?: ItemType;
  cursor?: string;
  limit?: number;
  q?: string;
  category?: string[];
  trust?: TrustTier[];
  status?: ItemStatus[];
  verdict?: GateVerdict[];
  surface?: string[];
  sort?: "featured" | "newest" | "updated" | "name";
}

export type CreateVia = "write" | "upload" | "import";
export type ProvisionScope = "private" | "org_default_on" | "required";

export interface CreateWritePayload {
  create_via: "write";
  item_type: ItemType;
  namespace: string;
  display_name: string;
  description: string;
  category: string;
  tags?: string[];
  license?: string;
  content: { instructions: string; files: Array<{ name: string; content: string }> };
  surfaces?: string[];
  provision_scope?: ProvisionScope;
  /** Tiered license policy (ECOSYSTEM_PLAN.md §11.2) -- Tier 3 only,
   * ignored for a non-private provision_scope. Required (server-enforced)
   * when `license` is set but not MIT/Apache-2.0-compatible. */
  license_acknowledged?: boolean;
  /** Tier 3 only: when `license` is empty, defaults it to MIT server-side
   * instead of erroring -- never overrides a license that WAS declared. */
  self_authored?: boolean;
}

export interface CreateImportPayload {
  create_via: "import";
  item_type: ItemType;
  namespace: string;
  category: string;
  kind: SourceKind;
  ref: string;
  license?: string;
  surfaces?: string[];
  provision_scope?: ProvisionScope;
}

export interface CreateResult {
  item_id: string;
  version_id: string;
  gate_run_id: string;
  status: JobStatus;
  provision_scope: string;
}

/** GET /ecosystem/search/live's own pointer-shaped result (Discover "From
 * the web" section) -- deliberately NOT an ItemSummary: nothing here
 * exists in the DB yet (no `id`/`item_id`, no gate verdict, no installed
 * state) until a caller actually adds it, which materializes a real item
 * through the exact same POST /ecosystem/items import path a manual
 * "Import from URL" already uses (`ref` below is that call's own `ref`
 * verbatim). `license_spdx` is always MIT/Apache-2.0-compatible already
 * (server-side pre-filter, services/ecosystem/live_search_service.py) --
 * shown as an informational badge, never a gate the caller has to clear. */
export interface LiveSearchResult {
  namespace: string;
  display_name: string;
  description: string;
  license_spdx: string;
  source_kind: SourceKind;
  source_url: string;
  ref: string;
}

/** CONTRACTS.md §10.1 -- POST /ecosystem/items/{id}/new-version(/upload)
 * response. No `provision_scope`: a new version of an existing item never
 * re-decides where that item is provisioned. */
export interface NewVersionResult {
  item_id: string;
  version_id: string;
  gate_run_id: string;
  status: JobStatus;
}

/** Same shape as CreateWritePayload.content -- shared between "create a
 * new item" and "add a version to an existing one." */
export interface EditableContent {
  instructions: string;
  files: Array<{ name: string; content: string }>;
}

export interface OrgPolicy {
  org_id: string;
  who_can_add: "all_users" | "admins_only";
  allowed_sources: string[];
  auto_update_default: boolean;
  /** Tier 2 of the tiered license policy (ECOSYSTEM_PLAN.md §11.2) --
   * licenses this org accepts once an item is shared/provisioned/required.
   * Can only widen Tier 1's MIT/Apache-2.0 rule, never narrow it. */
  allowed_licenses_shared: string[];
  /** Who may share their own items with specific users/groups -- same
   * value set as who_can_add, default "all_users". */
  who_can_share: "all_users" | "admins_only";
  /** Catalog-checking round: when the ethics review stage runs at all. */
  ethics_review_policy: "always" | "scripts_or_noncatalog" | "never";
  /** Optional background pre-check of featured/popular catalog items --
   * off by default, never blocks a real user's own Add either way. */
  gate_precheck_enabled: boolean;
  gate_precheck_cap_per_hour: number;
  /** Admin Sources screen (Task 3a): per-org on/off for Discover's "From
   * the web" live-search section -- narrows, never widens, the separate
   * instance-wide ECOSYSTEM_LIVE_SOURCES flag (surfaced read-only as
   * AdminSourcesInfo.live_sources_flag_enabled below). */
  live_sources_enabled: boolean;
}

// ── Admin Sources screen (Task 3a) ───────────────────────────────────────

export interface ShardSyncStatus {
  shard: string;
  fetched: boolean;
  verified: boolean;
  error: string | null;
  created: number;
  updated: number;
  yanked: number;
}

export interface LastSyncStatus {
  ok: boolean;
  shards: ShardSyncStatus[];
  synced_at: string;
}

export interface WellKnownSiteInfo {
  domain: string;
  category: string;
  tags: string[];
  needs_product: string | null;
  account_required: boolean;
  tos_note: string;
  enabled: boolean;
}

export interface OrgSourceInfo {
  id: string;
  kind: string;
  url: string | null;
  enabled: boolean;
  tos_checked_at: string | null;
  tos_notes: string | null;
  created_by: string;
  created_at: string | null;
  credential_configured: boolean;
}

export interface AdminSourcesInfo {
  catalog_url: string | null;
  catalog_signer_configured: boolean;
  last_sync: LastSyncStatus | null;
  well_known_sites: WellKnownSiteInfo[];
  sources_yaml_error: string | null;
  org_sources: OrgSourceInfo[];
  github_credential_configured: boolean;
  github_credential_hint: string | null;
  live_sources_flag_enabled: boolean;
}

export interface GateFindingRow {
  gate_run_id: string;
  item_id: string;
  version_id: string;
  trigger: GateTrigger;
  verdict: GateVerdict;
  started_at: string | null;
  findings: Array<{ stage: GateStage; severity: GateSeverity; code: string; message: string }>;
}

/** Item 8: admin-visible gate-worker health signal, GET
 * /ecosystem/admin/gate-health -- services/ecosystem/gate_health_service.py's
 * get_health(). `message` is non-null exactly when there's something an
 * admin should look at (no recent heartbeat, or a stuck-verifying backlog). */
export interface GateHealth {
  gate_worker_healthy: boolean;
  last_heartbeat: string | null;
  heartbeat_stale_after_seconds: number;
  stuck_verifying_count: number;
  stuck_verifying_threshold_seconds: number;
  message: string | null;
  last_sweep: { checked: number; reenqueued: number; still_in_flight: number; swept_at: string } | null;
}

/** CONTRACTS.md §13 -- the live-update event shape. */
export interface EcosystemChangedEvent {
  v: 1;
  type: ItemType;
  item_id: string;
  scope: string;
  change: ChangeKind;
  version: string | null;
}
