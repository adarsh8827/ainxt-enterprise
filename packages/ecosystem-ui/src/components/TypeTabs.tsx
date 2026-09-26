// SPDX-License-Identifier: MIT
// Task F-8: the 4-tab bar, entirely driven by GET /ecosystem/config's
// item_types[] -- available types render normally, coming_soon types get
// the ComingSoonBadge inline but are still clickable (they render
// ComingSoonTab, not a disabled tab -- CONTRACTS.md §8's "all 4 tabs are
// visible" decision).
import { useConfig } from "../hooks/useEcosystemConfig";
import { ComingSoonBadge } from "./Badges";

export function TypeTabs({ activeSlug, onSelect }: { activeSlug: string; onSelect: (slug: string) => void }) {
  const config = useConfig();
  return (
    <div role="tablist" data-testid="type-tabs" style={{ display: "flex", gap: "var(--eco-space-md)", borderBottom: "1px solid var(--eco-color-border)", marginBottom: "var(--eco-space-md)" }}>
      {config.item_types.map((t) => (
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
            padding: "8px 0", fontSize: "var(--eco-font-sizeMd)", textTransform: "capitalize",
            color: activeSlug === t.slug ? "var(--eco-color-accentSkill)" : "var(--eco-color-textSecondary)",
            borderBottom: activeSlug === t.slug ? "2px solid var(--eco-color-accentSkill)" : "2px solid transparent",
            fontWeight: activeSlug === t.slug ? 600 : 400,
          }}
        >
          {t.slug}
          {t.state === "coming_soon" && <ComingSoonBadge />}
        </button>
      ))}
    </div>
  );
}
