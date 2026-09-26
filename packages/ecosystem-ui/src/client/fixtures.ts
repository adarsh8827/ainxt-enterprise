// SPDX-License-Identifier: MIT
// Fixture catalog backing MockEcosystemClient -- deliberately covers every
// badge/verdict/trust-tier combination Card.tsx's component tests need
// (task F-5's own test requirement: "a component test per badge state
// (verified/org/community/agent_created x pass/warn/fail/pending)").
import type { EcosystemConfig, ItemDetail, ItemSummary } from "../types";

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
  caller_permissions: { can_share: true, can_provision: true },
  policy_summary: { who_can_add: "all_users", allowed_sources: ["central_index"], auto_update_default: false },
  taxonomy: {
    categories: [
      "productivity", "dev-tools", "communication", "data-analytics", "design", "finance",
      "crm", "marketing", "automation", "documents", "research", "hr-people",
      "security-compliance", "travel", "legal", "sales", "support", "general",
    ],
    trust_tiers: ["builtin", "verified", "org", "community", "agent_created"],
  },
  new_badge_days: 14,
  enums_version: "2026.09.1",
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
  caller_permissions: { can_share: false, can_provision: false },
  policy_summary: { who_can_add: "all_users", allowed_sources: ["central_index"], auto_update_default: false },
  taxonomy: MOCK_CONFIG.taxonomy,
  new_badge_days: 14,
  enums_version: "2026.09.1",
};

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
    is_featured: false,
    is_new: false,
    latest_version: "1.0.0",
    latest_verdict: "pass",
    allowed_actions: ["install", "report"],
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
