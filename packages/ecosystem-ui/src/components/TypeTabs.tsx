// SPDX-License-Identifier: MIT
// Task F-8: the tab bar, entirely driven by GET /ecosystem/config's
// item_types[] -- available types render normally, coming_soon types get
// the ComingSoonBadge inline but are still clickable (they render
// ComingSoonTab, not a disabled tab -- CONTRACTS.md §8's "all tabs are
// visible" decision).
//
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// collapses the separate "connector"/"mcp_server" tabs into one
// "Connectors" tab with an internal "Advanced: MCP servers" sub-view.
//
// Real gap found and fixed (2026-09-30, live user report): the FIRST cut
// of this made the whole merge conditional on the admin-only prop
// (the admin-only signal) -- so a non-admin caller fell all the way back
// to the OLD 4-separate-tabs layout, including a bare standalone
// "MCP servers" tab. That's wrong: "MCP servers" must never be its own
// top-level tab for ANYONE (matching the reference design's fixed 3-tab
// shell: Skills · Connectors · Plugins) -- only the "Advanced" TOGGLE
// BUTTON inside Connectors is admin-gated, not the merge itself. The two
// concerns are now split: `mcp_server` is filtered out of the tab list
// unconditionally; `showAdvancedToggle` (admin permission) only controls
// whether the "Advanced: MCP servers" button itself renders.
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
  /** Admin/dev-policy gate on the "Advanced: MCP servers" TOGGLE BUTTON
   * only (default false) -- the mcp_server tab itself is ALWAYS merged
   * into Connectors regardless of this prop; a caller without this
   * permission simply has no way to reach the Advanced sub-view, not a
   * fallback to a separate top-level MCP tab. */
  showAdvancedToggle?: boolean;
  advancedActive?: boolean;
  onSelectAdvanced?: (advanced: boolean) => void;
}

export function TypeTabs({ activeSlug, onSelect, showAdvancedToggle = false, advancedActive = false, onSelectAdvanced }: TypeTabsProps) {
  const config = useConfig();
  // Unconditional -- mcp_server is never its own top-level tab, matching
  // the reference design's fixed 3-tab shell (Skills · Connectors ·
  // Plugins). A profile whose own visible_item_types already excludes
  // mcp_server (e.g. "workspace") has no mcp_server entry to begin with;
  // this filter is a no-op there and the real gate for everyone else.
  const itemTypes = config.item_types.filter((t) => t.type !== "mcp_server");
  // The Advanced sub-view only ever makes sense when mcp_server is actually
  // a visible type for this caller's product profile -- a profile whose
  // own visible_item_types excludes mcp_server entirely (e.g. "workspace",
  // Connectors phase item 5) already has no mcp_server entry in
  // config.item_types, so this naturally hides the button too, no separate
  // per-product special-casing needed here.
  const mcpServerType = config.item_types.find((t) => t.type === "mcp_server");
  const connectorSlug = config.item_types.find((t) => t.type === "connector")?.slug;

  return (
    <div role="tablist" data-testid="type-tabs" style={{ display: "flex", flexShrink: 0, alignItems: "center", gap: "var(--eco-space-xs, 4px)", marginBottom: "var(--eco-space-md)" }}>
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
            display: "flex", alignItems: "center", gap: "6px", border: "none", cursor: "pointer",
            padding: "6px 14px", borderRadius: "var(--eco-radius-full)", fontSize: "var(--eco-font-sizeMd)", whiteSpace: "nowrap",
            color: activeSlug === t.slug ? "var(--eco-color-textPrimary)" : "var(--eco-color-textSecondary)",
            background: activeSlug === t.slug ? "var(--eco-color-surface)" : "none",
            fontWeight: activeSlug === t.slug ? 600 : 400,
          }}
        >
          {TYPE_LABEL[t.type] ?? t.slug}
          {t.state === "coming_soon" && <ComingSoonBadge />}
        </button>
      ))}
      {showAdvancedToggle && mcpServerType && activeSlug === connectorSlug && onSelectAdvanced && (
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
