// SPDX-License-Identifier: MIT
// Task F-5: driven by ItemSummary.is_featured (server-computed, already
// folding in ecosystem_featured_overrides for the caller's org -- see
// items_service._is_featured()) -- never re-derived client-side.
import type { ItemSummary } from "../types";
import { ItemIcon } from "./ItemIcon";

export function FeaturedBanner({ items, onOpen }: { items: ItemSummary[]; onOpen: (item: ItemSummary) => void }) {
  const featured = items.filter((i) => i.is_featured);
  if (featured.length === 0) return null;

  return (
    <div data-testid="featured-banner-section" style={{ marginBottom: "var(--eco-space-lg)" }}>
      {/* Real bug found live: this banner rendered with no heading at all --
          visually the first thing on the page, so the true first titled
          section (the first CategorySection below it) looked like it was
          missing its own title. Every section gets a heading now. */}
      <h3 data-testid="featured-banner-heading" style={{ margin: "0 0 var(--eco-space-sm)", fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>
        Featured
      </h3>
      <div data-testid="featured-banner" style={{ display: "flex", gap: "var(--eco-space-md)", overflowX: "auto", paddingBottom: "var(--eco-space-sm)" }}>
      {featured.map((item) => (
        <button
          key={item.id}
          type="button"
          data-testid="featured-item"
          onClick={() => onOpen(item)}
          style={{
            display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", minWidth: "260px",
            padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
            border: `1px solid var(--eco-color-accentSkill)`, background: "var(--eco-color-surface)",
            textAlign: "left", cursor: "pointer",
          }}
        >
          <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={32} />
          <div>
            <div style={{ fontWeight: 600, color: "var(--eco-color-textPrimary)" }}>{item.display_name}</div>
            <div style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textSecondary)" }}>{item.description}</div>
          </div>
        </button>
      ))}
      </div>
    </div>
  );
}
