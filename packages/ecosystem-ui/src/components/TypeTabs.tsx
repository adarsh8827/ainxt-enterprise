// SPDX-License-Identifier: MIT
// Task F-8: the tab bar, entirely driven by GET /ecosystem/config's
// item_types[] -- available types render normally, coming_soon types get
// the ComingSoonBadge inline but are still clickable (they render
// ComingSoonTab, not a disabled tab -- CONTRACTS.md §8's "all tabs are
// visible" decision).
//
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// collapses the separate "connector"/"mcp_server" tabs into one
// "Connectors" tab with an internal "Advanced: MCP servers" sub-view --
// but ONLY when the host explicitly opts in via `collapseConnectorsAdvanced`
// (default false/omitted). This is deliberately NOT driven by config state
// yet (no backend signal for "policy allows Advanced" exists as a config
// field at the time of this change) -- an omitted prop renders EXACTLY
// today's 4-separate-tabs behavior, so no existing host regresses just by
// picking up this file's changes. A host wires the real opt-in once its
// own RBAC/policy check for "show Advanced" is available.
import { useConfig } from "../hooks/useEcosystemConfig";
import { ComingSoonBadge } from "./Badges";
import type { ItemType } from "../types";

// Real bug found live: the tab rendered `{t.slug}` (a route/URL segment,
// e.g. "mcp") through `textTransform: capitalize`, which reads "Mcp" for
// anything with no space to capitalize a second word of -- slugs are
// stable URL segments, not display copy, so a real label map is needed
// instead of trying to derive one from the slug string.
const TYPE_LABEL: Record<ItemType, string> = {
  skill: "Skills", plugin: "Plugins", connector: "Connectors", mcp_server: "MCP servers",
};

export interface TypeTabsProps {
  activeSlug: string;
  onSelect: (slug: string) => void;
  /** Opt-in only (see file header) -- collapses "connector"+"mcp_server"
   * into one "Connectors" tab; selecting it while already active toggles
   * an internal "Advanced" sub-view rather than navigating away. Consumers
   * read the sub-view via `onSelectAdvanced`. */
  collapseConnectorsAdvanced?: boolean;
  advancedActive?: boolean;
  onSelectAdvanced?: (advanced: boolean) => void;
}

export function TypeTabs({ activeSlug, onSelect, collapseConnectorsAdvanced = false, advancedActive = false, onSelectAdvanced }: TypeTabsProps) {
  const config = useConfig();
  const itemTypes = collapseConnectorsAdvanced
    ? config.item_types.filter((t) => t.type !== "mcp_server")
    : config.item_types;
  // The Advanced sub-view only ever makes sense when mcp_server is actually
  // a visible type for this caller's product profile -- a profile whose
  // own visible_item_types excludes mcp_server entirely (e.g. "workspace",
  // Connectors phase item 5) already has no mcp_server entry in
  // config.item_types, so this naturally hides the button too, no separate
  // per-product special-casing needed here.
  const mcpServerType = config.item_types.find((t) => t.type === "mcp_server");
  const connectorSlug = config.item_types.find((t) => t.type === "connector")?.slug;

  return (
    <div role="tablist" data-testid="type-tabs" style={{ display: "flex", flexShrink: 0, gap: "var(--eco-space-md)", borderBottom: "1px solid var(--eco-color-border)", marginBottom: "var(--eco-space-md)" }}>
      {itemTypes.map((t) => (
        <button
          key={t.slug}
          type="button"
          role="tab"
          aria-selected={activeSlug === t.slug}
          data-testid={`type-tab-${t.slug}`}
          data-state={t.state}
          onClick={() => onSelect(t.slug)}
          style={{
            display: "flex", alignItems: "center", gap: "6px", background: "none", border: "none", cursor: "pointer",
            padding: "8px 0", fontSize: "var(--eco-font-sizeMd)", whiteSpace: "nowrap",
            color: activeSlug === t.slug ? "var(--eco-color-accentSkill)" : "var(--eco-color-textSecondary)",
            borderBottom: activeSlug === t.slug ? "2px solid var(--eco-color-accentSkill)" : "2px solid transparent",
            fontWeight: activeSlug === t.slug ? 600 : 400,
          }}
        >
          {TYPE_LABEL[t.type] ?? t.slug}
          {t.state === "coming_soon" && <ComingSoonBadge />}
        </button>
      ))}
      {collapseConnectorsAdvanced && mcpServerType && activeSlug === connectorSlug && onSelectAdvanced && (
        <button
          type="button"
          data-testid="type-tab-advanced-mcp"
          aria-selected={advancedActive}
          onClick={() => onSelectAdvanced(!advancedActive)}
          style={{
            marginLeft: "auto", background: "none", border: "none", cursor: "pointer",
            padding: "8px 0", fontSize: "var(--eco-font-sizeSm)",
            color: advancedActive ? "var(--eco-color-accentSkill)" : "var(--eco-color-textMuted)",
          }}
        >
          Advanced: MCP servers
        </button>
      )}
    </div>
  );
}
