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
  | "share" | "unshare" | "report" | "deprecate" | "delete_draft"
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

export interface EcosystemConfig {
  product: string;
  layout: "full" | "compact";
  default_view: "discover" | "yours";
  item_types: ItemTypeConfig[];
  route_slugs: Record<string, string>;
  surfaces: SurfaceRef[];
  features: FeatureFlags;
  policy_summary: PolicySummary;
  taxonomy: Taxonomy;
  new_badge_days: number;
  enums_version: string;
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
  is_featured: boolean;
  is_new: boolean;
  latest_version: string | null;
  latest_verdict: GateVerdict;
  allowed_actions: AllowedAction[];
}

export interface ItemDetail extends ItemSummary {
  publisher: { slug: string; type: "org" | "user" };
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

export interface GateRun {
  id: string;
  version_id: string;
  trigger: GateTrigger;
  verdict: GateVerdict;
  scanner_version: string;
  started_at: string | null;
  finished_at: string | null;
  findings: GateFinding[];
}

export interface Install {
  install_id: string;
  item: ItemSummary;
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

export interface OrgPolicy {
  org_id: string;
  who_can_add: "all_users" | "admins_only";
  allowed_sources: string[];
  auto_update_default: boolean;
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

/** CONTRACTS.md §13 -- the live-update event shape. */
export interface EcosystemChangedEvent {
  v: 1;
  type: ItemType;
  item_id: string;
  scope: string;
  change: ChangeKind;
  version: string | null;
}
