// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the filter icon button + its popover --
// category checkboxes (config.taxonomy.categories) and publisher/trust-tier
// checkboxes (config.taxonomy.trust_tiers), matching the reference mock's
// own filterPop(). Categories/trust tiers come from the global taxonomy
// (CONTRACTS.md's config schema has no per-type category list), a disclosed,
// deliberate simplification vs. the mock's own per-type-derived list.
// Toggling either always switches the catalog to Discover -- Yours has no
// category/trust concept to filter by, matching the mock's own tog().
import { useRef, useState } from "react";
import { FunnelIcon } from "@heroicons/react/24/outline";
import type { Taxonomy, TrustTier } from "../types";
import { PopoverAnchor } from "./PopoverAnchor";

const TRUST_LABEL: Record<TrustTier, string> = {
  builtin: "Built-in", verified: "Verified", org: "Org", community: "Community", agent_created: "Agent-created",
};

export function FilterButton({ categories, onCategoriesChange, trust, onTrustChange, taxonomy, activeCount }: {
  categories: Set<string>; onCategoriesChange: (next: Set<string>) => void;
  trust: Set<TrustTier>; onTrustChange: (next: Set<TrustTier>) => void;
  taxonomy: Taxonomy; activeCount: number;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const toggleCategory = (c: string) => {
    const next = new Set(categories);
    if (next.has(c)) next.delete(c); else next.add(c);
    onCategoriesChange(next);
  };
  const toggleTrust = (t: TrustTier) => {
    const next = new Set(trust);
    if (next.has(t)) next.delete(t); else next.add(t);
    onTrustChange(next);
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        data-testid="toolbar-filter-trigger"
        title="Filter"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="eco-toolbar-ib"
      >
        <FunnelIcon width={18} height={18} aria-hidden="true" />
        {activeCount > 0 && <span className="eco-toolbar-dot" data-testid="toolbar-filter-dot" />}
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right">
        <div role="menu" data-testid="toolbar-filter-popover" className="eco-toolbar-pop" onMouseLeave={() => setOpen(false)}>
          <div className="eco-toolbar-pop-heading">Category</div>
          {taxonomy.categories.map((c) => (
            <label key={c} className="eco-toolbar-pop-item">
              <input type="checkbox" checked={categories.has(c)} onChange={() => toggleCategory(c)} /> {c.replace(/-/g, " ")}
            </label>
          ))}
          <hr />
          <div className="eco-toolbar-pop-heading">Publisher</div>
          {taxonomy.trust_tiers.map((t) => (
            <label key={t} className="eco-toolbar-pop-item">
              <input type="checkbox" checked={trust.has(t)} onChange={() => toggleTrust(t)} /> {TRUST_LABEL[t]}
            </label>
          ))}
        </div>
      </PopoverAnchor>
    </div>
  );
}
