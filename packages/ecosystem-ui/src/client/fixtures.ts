// SPDX-License-Identifier: MIT
// Fixture catalog backing MockEcosystemClient -- deliberately covers every
// badge/verdict/trust-tier combination Card.tsx's component tests need
// (task F-5's own test requirement: "a component test per badge state
// (verified/org/community/agent_created x pass/warn/fail/pending)").
import type { AdminSourcesInfo, EcosystemConfig, ItemDetail, ItemSummary, LiveSearchResult } from "../types";

export const MOCK_CONFIG: EcosystemConfig = {
  product: "enterprise",
  layout: "full",
  default_view: "discover",
  item_types: [
    { type: "skill", state: "available", slug: "skills" },
    { type: "plugin", state: "coming_soon", slug: "plugins" },
    { type: "connector", state: "coming_soon", slug: "connectors" },
    { type: "mcp_server", state: "coming_soon", slug: "mcp" },
  ],
  route_slugs: { skill: "skills", plugin: "plugins", connector: "connectors", mcp_server: "mcp" },
  surfaces: [
    { key: "chat", label: "Chat" },
    { key: "agent_studio", label: "Agent Studio" },
    { key: "desktop", label: "Desktop" },
  ],
  features: {
    discover: true, yours: true, create_with_ai: true, write: true, upload: true,
    import_url: false, share: true, provisioning: true, admin_policies: true, gate_dashboard: true,
  },
  caller_permissions: { can_share: true, can_provision: true, can_admin_surfaces: true },
  policy_summary: { who_can_add: "all_users", allowed_sources: ["central_index"], auto_update_default: false },
  taxonomy: {
    categories: [
      "productivity", "dev-tools", "communication", "data-analytics", "design", "finance",
      "crm", "marketing", "automation", "documents", "research", "hr-people",
      "security-compliance", "travel", "legal", "sales", "support", "general",
      // Kept in sync with services/ecosystem/config_service.py's real
      // taxonomy -- "engineering"/"security" are real crawled-catalog
      // categories (docs/ecosystem/catalog/sources.yaml) this list
      // originally never accounted for.
      "engineering", "security",
    ],
    trust_tiers: ["builtin", "verified", "org", "community", "agent_created"],
  },
  new_badge_days: 14,
  enums_version: "2026.09.1",
  caller_default_namespace_prefix: "mock-user-a1b2c3d4e5",
  // Discover "From the web" section: on by default in this base fixture
  // so Storybook/most component tests exercise it -- a test/story
  // specifically covering the disabled case overrides this to false.
  live_search_enabled: true,
};

// Task F-12: the `workspace` product profile's real shape (CONFIG_AND_PRODUCTS.md
// §3's table row) -- compact layout, only the `skill` item type, only the
// `workspace_chat` surface, and admin/provisioning/sharing features off (a
// deliberate ceiling, not a bug -- workspace is single-user/small-team
// leaning per the phase brief). Backs the F-12 example host and any
// Storybook story/component test that needs to render a *workspace-shaped*
// config, as opposed to just toggling Storybook's own light/dark/full/compact
// globals (.storybook/preview.tsx), which vary presentation only, not
// entitlements.
export const MOCK_CONFIG_WORKSPACE: EcosystemConfig = {
  product: "workspace",
  layout: "compact",
  default_view: "discover",
  item_types: [
    { type: "skill", state: "available", slug: "skills" },
    { type: "plugin", state: "coming_soon", slug: "plugins" },
    { type: "connector", state: "coming_soon", slug: "connectors" },
    { type: "mcp_server", state: "coming_soon", slug: "mcp" },
  ],
  route_slugs: { skill: "skills", plugin: "plugins", connector: "connectors", mcp_server: "mcp" },
  surfaces: [
    { key: "workspace_chat", label: "Chat" },
  ],
  features: {
    discover: true, yours: true, create_with_ai: true, write: true, upload: true,
    import_url: false, share: false, provisioning: false, admin_policies: false, gate_dashboard: false,
  },
  caller_permissions: { can_share: false, can_provision: false, can_admin_surfaces: false },
  policy_summary: { who_can_add: "all_users", allowed_sources: ["central_index"], auto_update_default: false },
  taxonomy: MOCK_CONFIG.taxonomy,
  new_badge_days: 14,
  enums_version: "2026.09.1",
  caller_default_namespace_prefix: "mock-workspace-user-f6a7b8c9d0",
  // Workspace's own org policy has never turned this on -- off by
  // default here (a deliberate ceiling, same rationale as every other
  // false feature flag on this fixture, not an oversight).
  live_search_enabled: false,
};

// Discover "From the web" section fixture results -- deliberately
// pointer-shaped only (no id/gate-verdict/installed state, matching what
// GET /ecosystem/search/live genuinely returns for a not-yet-materialized
// external repo). Covers both real allowed licenses (MIT/Apache-2.0) since
// live_search_service.py's own server-side pre-filter never lets anything
// else through.
export const MOCK_LIVE_SEARCH_RESULTS: LiveSearchResult[] = [
  {
    namespace: "acme/web-scraper-skill",
    display_name: "web-scraper-skill",
    description: "A skill for scraping and summarizing web pages.",
    license_spdx: "MIT",
    source_kind: "github_repo",
    source_url: "https://github.com/acme/web-scraper-skill",
    ref: "acme/web-scraper-skill",
  },
  {
    namespace: "example-org/pdf-tools",
    display_name: "pdf-tools",
    description: "Extracts and summarizes text from PDF documents.",
    license_spdx: "Apache-2.0",
    source_kind: "github_repo",
    source_url: "https://github.com/example-org/pdf-tools",
    ref: "example-org/pdf-tools",
  },
];

function item(overrides: Partial<ItemSummary>): ItemSummary {
  return {
    id: overrides.id ?? "item-0",
    namespace: "acme/example",
    item_type: "skill",
    display_name: "Example Skill",
    description: "An example skill for the catalog.",
    category: "productivity",
    tags: [],
    icon_url: "emoji:✨",
    trust_tier: "community",
    license: "MIT",
    status: "active",
    // Ordinary fixture items represent a normal published/created skill,
    // never a not-yet-added catalog pointer -- "optional" (a regular,
    // fully-materialized Discover item), never "central_index" by
    // default. Tests that specifically need the not-yet-added-catalog-
    // item state override this explicitly alongside latest_version: null.
    item_scope: "optional",
    is_featured: false,
    is_new: false,
    latest_version: "1.0.0",
    latest_verdict: "pass",
    allowed_actions: ["install", "report"],
    install_id: null,
    enabled: null,
    install_scope: null,
    install_surfaces: null, has_other_installs: false, share_id: null,
    compatibility: "chat",
    ...overrides,
  };
}

export const MOCK_ITEMS: ItemSummary[] = [
  item({
    id: "item-exec-assistant", namespace: "acme/exec-assistant", display_name: "Exec Assistant",
    description: "Drafts executive summaries from meeting notes.", category: "productivity",
    trust_tier: "verified", is_featured: true, latest_verdict: "pass",
    allowed_actions: ["install", "share", "report"],
  }),
  item({
    id: "item-invoice-parser", namespace: "acme/invoice-parser", display_name: "Invoice Parser",
    description: "Extracts line items from PDF invoices.", category: "finance",
    trust_tier: "org", is_new: true, latest_verdict: "warn",
    allowed_actions: ["install", "share", "report"],
  }),
  item({
    id: "item-quick-scraper", namespace: "acme/quick-scraper", display_name: "Quick Scraper",
    description: "Scrapes a web page into structured JSON.", category: "dev-tools",
    trust_tier: "community", latest_verdict: "fail", status: "active",
    allowed_actions: ["report"],
  }),
  item({
    id: "item-contract-reviewer", namespace: "acme/contract-clause-reviewer", display_name: "Contract Clause Reviewer",
    description: "Flags nonstandard clauses in a contract draft.", category: "legal",
    trust_tier: "verified", latest_verdict: "pending",
    allowed_actions: ["report"],
  }),
  item({
    id: "item-standup-notes", namespace: "acme/standup-notes", display_name: "Standup Notes",
    description: "Turns raw standup bullets into a clean summary.", category: "communication",
    trust_tier: "agent_created", latest_verdict: "pass",
    allowed_actions: ["install", "report"],
  }),
  item({
    id: "item-onboarding-buddy", namespace: "platform/onboarding-buddy", display_name: "Onboarding Buddy",
    description: "Built-in starter skill for new-hire onboarding questions.", category: "hr-people",
    trust_tier: "builtin", latest_verdict: "pass",
    allowed_actions: ["uninstall", "disable", "report"],
  }),
];

// Task 3a: admin Sources screen fixture -- one of each real state (a
// clean last sync, an approved well-known site, an org's own local
// source, no GitHub credential configured) so Storybook/component tests
// exercise every row this screen actually renders.
export const MOCK_ADMIN_SOURCES: AdminSourcesInfo = {
  catalog_url: "https://raw.githubusercontent.com/acme/ainxt-enterprise/ecosystem-index/index",
  catalog_signer_configured: true,
  last_sync: {
    ok: true,
    synced_at: "2026-09-28T18:00:00Z",
    shards: [
      { shard: "skill", fetched: true, verified: true, error: null, created: 12, updated: 3, yanked: 0 },
      { shard: "mcp_server", fetched: true, verified: true, error: null, created: 40, updated: 0, yanked: 1 },
    ],
  },
  well_known_sites: [
    { domain: "docs.example.com", category: "dev-tools", tags: ["code-review"], needs_product: null, account_required: false, tos_note: "reviewed 2026-09-01", enabled: true },
  ],
  sources_yaml_error: null,
  org_sources: [
    { id: "source-local-mock-org", kind: "local", url: null, enabled: true, tos_checked_at: null, tos_notes: null, created_by: "mock-user", created_at: "2026-08-01T00:00:00Z", credential_configured: false },
  ],
  github_credential_configured: false,
  github_credential_hint: "No GITHUB_IMPORT_TOKEN is configured -- GitHub imports are running anonymously, limited to 60 requests/hour.",
  live_sources_flag_enabled: true,
  service_health: {
    gateway_commit: "abc1234",
    warnings: [],
    services: {
      gateway: { service: "gateway", commit: "abc1234", started_at: "2026-09-29T10:00:00Z", pid: 1, commit_mismatch: false },
      gate_worker: { service: "gate_worker", commit: "abc1234", started_at: "2026-09-29T10:00:00Z", pid: 2, commit_mismatch: false, queue_names: ["ecosystem_gate_queue_high", "ecosystem_gate_queue", "ecosystem_gate_queue_low"], missing_lanes: [] },
      gate_sweeper: { service: "gate_sweeper", commit: "abc1234", started_at: "2026-09-29T10:00:00Z", pid: 3, commit_mismatch: false },
    },
  },
};

export const MOCK_DETAILS: Record<string, ItemDetail> = Object.fromEntries(
  MOCK_ITEMS.map((summary) => [
    summary.id,
    {
      ...summary,
      publisher: { slug: summary.namespace.split("/")[0] ?? "acme", type: "org" },
      attribution: `${summary.license} License\n\nCopyright (c) 2026 Acme Corp`,
      source: { kind: "local", url: null },
      manifest: { name: summary.display_name, description: summary.description, instructions: "..." },
      deprecated_at: null,
      deprecated_by: null,
    } satisfies ItemDetail,
  ]),
);
