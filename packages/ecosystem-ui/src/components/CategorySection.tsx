// SPDX-License-Identifier: MIT
// Task F-5: grouped by config's taxonomy.categories (never a hardcoded
// list -- see scripts/ecosystem/check_no_hardcoded_config.py) with a
// "Show all" link that expands the section in place.
import { useState } from "react";
import { ArrowRightIcon } from "@heroicons/react/24/outline";
import type { ItemSummary } from "../types";
import { Card } from "./Card";
import { ConnectorCard } from "./Connectors/ConnectorCard";

const COLLAPSED_COUNT = 4;

export function CategorySection({ category, items, onOpen, onInstalled }: {
  category: string; items: ItemSummary[]; onOpen: (item: ItemSummary) => void; onInstalled?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);

  return (
    <section data-testid="category-section" data-category={category} style={{ marginBottom: "var(--eco-space-lg)" }}>
      {/* Reference-layout parity (Connectors+Plugins UI redesign,
          2026-09-30): section header now carries the item count as its
          own small pill next to the title (reference: "Top connectors
          3588"), and "Show all" reads as a real link with a trailing
          arrow rather than a plain "(count)" suffix on the toggle itself. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--eco-space-sm)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <h3 style={{ margin: 0, fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)", textTransform: "capitalize" }}>
            {category.replace(/-/g, " ")}
          </h3>
          <span
            data-testid="category-count"
            style={{
              display: "inline-flex", alignItems: "center", padding: "1px 8px", borderRadius: "var(--eco-radius-full)",
              background: "var(--eco-color-surface)", color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeXs)",
            }}
          >
            {items.length}
          </span>
        </div>
        {items.length > COLLAPSED_COUNT && (
          <button
            type="button"
            data-testid="show-all-link"
            onClick={() => setExpanded((e) => !e)}
            style={{
              display: "inline-flex", alignItems: "center", gap: "4px",
              background: "none", border: "none", color: "var(--eco-color-textPrimary)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)",
            }}
          >
            {expanded ? "Show less" : "Show all"}
            {!expanded && <ArrowRightIcon width={14} height={14} aria-hidden="true" />}
          </button>
        )}
      </div>
      {/* Reference grid reads as a fixed 2-column layout (wide cards),
          not an auto-fill of as-many-240px-columns-as-fit -- a 480px
          minmax naturally caps at 2 columns on a typical desktop content
          width and collapses to 1 on a narrow viewport, matching the
          reference's own Discover screenshots at every width shown. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(480px, 1fr))", gap: "var(--eco-space-md)" }}>
        {visible.map((item) => (
          // Real gap found and fixed (Connectors+Plugins UI redesign,
          // 2026-09-30): this section is what actually renders on the
          // DEFAULT (no search/filter) Discover view -- Discover.tsx's own
          // ConnectorCard-vs-Card branch only ever ran on the flat
          // filtered-results grid (query/category/trust active), so a
          // connector/mcp_server item browsed by category showed the
          // wrong (install-state "+Add") card instead of the real
          // connection-state ("Connect") one. Same condition as
          // Discover.tsx's own filtered branch, so both paths agree.
          item.item_type === "connector" || item.item_type === "mcp_server"
            ? <ConnectorCard key={item.id} item={item} onOpen={onOpen} />
            : <Card key={item.id} item={item} onOpen={onOpen} onInstalled={onInstalled} />
        ))}
      </div>
    </section>
  );
}
