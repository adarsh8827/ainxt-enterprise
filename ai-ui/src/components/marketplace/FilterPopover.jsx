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
import { PopoverAnchor } from "./PopoverAnchor";
// Item 3 (M5 UI-polish round 2, 2026-09-28): this used to keep its own
// second copy of the trust-tier label map (stale -- still said
// "Agent-created" after Badges.tsx's own copy was renamed to "Created
// with AI"). Reusing the one export now instead of a second copy that
// can drift again.
import { TRUST_LABEL } from "./Badges";
export function FilterButton({
  categories,
  onCategoriesChange,
  trust,
  onTrustChange,
  taxonomy,
  activeCount
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const toggleCategory = c => {
    const next = new Set(categories);
    if (next.has(c)) next.delete(c);else next.add(c);
    onCategoriesChange(next);
  };
  const toggleTrust = t => {
    const next = new Set(trust);
    if (next.has(t)) next.delete(t);else next.add(t);
    onTrustChange(next);
  };
  return <div className="relative">
      {/* Toolbar icon-consistency pass (2026-10-05, explicit product ask:
          "filter, sort, add button, keep all three as icons on hover it
          will has slight bg, with same size"): was a permanently-visible
          bordered/white-filled box -- the real app-wide icon-button
          convention for this exact shape (no border, no resting
          background, hover-only tint) is `p-1.5 rounded-md
          hover:bg-gray-100 text-gray-500 hover:text-gray-700` (see e.g.
          KnowledgeGraph.jsx's own toolbar icon buttons), not a bordered
          square -- matched here and in SortPopover.jsx/AddMenu.jsx so all
          three sit at the exact same size with the exact same classes. */}
      <button ref={triggerRef} type="button" data-testid="toolbar-filter-trigger" title="Filter" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)} className="relative p-1.5 rounded-md inline-flex items-center justify-center text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer flex-shrink-0">
        <FunnelIcon width={18} height={18} aria-hidden="true" />
        {activeCount > 0 && <span className="absolute top-1 right-1 w-[7px] h-[7px] rounded-full bg-indigo-600" data-testid="toolbar-filter-dot" />}
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="toolbar-filter-popover" className="min-w-[220px] max-h-80 overflow-y-auto py-2 rounded-md border border-gray-200 bg-white shadow-lg" onMouseLeave={() => setOpen(false)}>
          <div className="px-3 py-1 text-xs uppercase tracking-wide text-gray-500">Category</div>
          {taxonomy.categories.map(c => <label key={c} className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-900 hover:bg-gray-100 cursor-pointer">
              <input type="checkbox" checked={categories.has(c)} onChange={() => toggleCategory(c)} /> {c.replace(/-/g, " ")}
            </label>)}
          <hr className="border-none border-t border-gray-200 my-1" />
          <div className="px-3 py-1 text-xs uppercase tracking-wide text-gray-500">Publisher</div>
          {taxonomy.trust_tiers.map(t => <label key={t} className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-900 hover:bg-gray-100 cursor-pointer">
              <input type="checkbox" checked={trust.has(t)} onChange={() => toggleTrust(t)} /> {TRUST_LABEL[t]}
            </label>)}
        </div>
      </PopoverAnchor>
    </div>;
}