// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the sort icon button + its popover,
// matching the reference mock's own sortPop() -- same 4 options in the same
// order, same "never uses raw install count" note (CONTRACTS.md §7's
// closed-off ItemSummary schema has no install_count field to sort by in
// the first place -- ranking is trust-tier/featured/recency-based only).
import { useRef, useState } from "react";
import { ArrowsUpDownIcon, CheckIcon } from "@heroicons/react/24/outline";
import { PopoverAnchor } from "./PopoverAnchor";
const OPTIONS = [{
  value: "featured",
  label: "Featured"
}, {
  value: "newest",
  label: "Newest"
}, {
  value: "updated",
  label: "Recently updated"
}, {
  value: "name",
  label: "Name"
}];
export function SortButton({
  sort,
  onSortChange
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  return <div className="relative">
      {/* Toolbar icon-consistency pass (2026-10-05) -- see
          FilterPopover.jsx's own comment; same classes, same size. */}
      <button ref={triggerRef} type="button" data-testid="toolbar-sort-trigger" title="Sort" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)} className="p-1.5 rounded-md inline-flex items-center justify-center text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer flex-shrink-0">
        <ArrowsUpDownIcon width={18} height={18} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="toolbar-sort-popover" className="min-w-[220px] max-h-80 overflow-y-auto py-2 rounded-md border border-gray-200 bg-white shadow-lg" onMouseLeave={() => setOpen(false)}>
          {OPTIONS.map(o => <button key={o.value} type="button" role="menuitemradio" aria-checked={sort === o.value} data-testid={`toolbar-sort-${o.value}`} className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-900 text-left border-none bg-transparent hover:bg-gray-100 cursor-pointer transition-colors" onClick={() => {
          onSortChange(o.value);
          setOpen(false);
        }}>
              <span className="inline-flex w-3.5 flex-shrink-0">{sort === o.value && <CheckIcon width={14} height={14} aria-hidden="true" />}</span>
              {o.label}
            </button>)}
          <div className="px-3 pt-1.5 pb-0.5 text-xs text-gray-400">Ranking never uses raw install counts.</div>
        </div>
      </PopoverAnchor>
    </div>;
}