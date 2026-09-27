// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the sort icon button + its popover,
// matching the reference mock's own sortPop() -- same 4 options in the same
// order, same "never uses raw install count" note (CONTRACTS.md §7's
// closed-off ItemSummary schema has no install_count field to sort by in
// the first place -- ranking is trust-tier/featured/recency-based only).
import { useRef, useState } from "react";
import { ArrowsUpDownIcon, CheckIcon } from "@heroicons/react/24/outline";
import type { ListItemsParams } from "../types";
import { PopoverAnchor } from "./PopoverAnchor";

type SortValue = NonNullable<ListItemsParams["sort"]>;
const OPTIONS: Array<{ value: SortValue; label: string }> = [
  { value: "featured", label: "Featured" },
  { value: "newest", label: "Newest" },
  { value: "updated", label: "Recently updated" },
  { value: "name", label: "Name" },
];

export function SortButton({ sort, onSortChange }: { sort: SortValue; onSortChange: (sort: SortValue) => void }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        data-testid="toolbar-sort-trigger"
        title="Sort"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="eco-toolbar-ib"
      >
        <ArrowsUpDownIcon width={18} height={18} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="toolbar-sort-popover" className="eco-toolbar-pop" onMouseLeave={() => setOpen(false)}>
          {OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              role="menuitemradio"
              aria-checked={sort === o.value}
              data-testid={`toolbar-sort-${o.value}`}
              className="eco-toolbar-pop-item eco-toolbar-pop-button"
              onClick={() => { onSortChange(o.value); setOpen(false); }}
            >
              <span className="eco-toolbar-sort-check">{sort === o.value && <CheckIcon width={14} height={14} aria-hidden="true" />}</span>
              {o.label}
            </button>
          ))}
          <div className="eco-toolbar-pop-note">Ranking never uses raw install counts.</div>
        </div>
      </PopoverAnchor>
    </div>
  );
}
