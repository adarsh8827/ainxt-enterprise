// SPDX-License-Identifier: MIT
// Task F-5: grouped by config's taxonomy.categories (never a hardcoded
// list -- see scripts/ecosystem/check_no_hardcoded_config.py) with a
// "Show all" link that expands the section in place.
import { useState } from "react";
import type { ItemSummary } from "../types";
import { Card } from "./Card";

const COLLAPSED_COUNT = 4;

export function CategorySection({ category, items, onOpen }: {
  category: string; items: ItemSummary[]; onOpen: (item: ItemSummary) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);

  return (
    <section data-testid="category-section" data-category={category} style={{ marginBottom: "var(--eco-space-lg)" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "var(--eco-space-sm)" }}>
        <h3 style={{ margin: 0, fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)", textTransform: "capitalize" }}>
          {category.replace(/-/g, " ")}
        </h3>
        {items.length > COLLAPSED_COUNT && (
          <button
            type="button"
            data-testid="show-all-link"
            onClick={() => setExpanded((e) => !e)}
            style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)" }}
          >
            {expanded ? "Show less" : `Show all (${items.length})`}
          </button>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
        {visible.map((item) => <Card key={item.id} item={item} onOpen={onOpen} />)}
      </div>
    </section>
  );
}
