// SPDX-License-Identifier: MIT
// Task F-5: grouped by config's taxonomy.categories (never a hardcoded
// list -- see scripts/ecosystem/check_no_hardcoded_config.py) with a
// "Show all" link that expands the section in place.
import { useState } from "react";
import { ArrowRightIcon } from "@heroicons/react/24/outline";
import { Card } from "./Card";
import { ConnectorCard } from "./Connectors/ConnectorCard";
const COLLAPSED_COUNT = 4;
export function CategorySection({
  category,
  items,
  onOpen,
  onInstalled
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);
  return <section data-testid="category-section" data-category={category} className="mb-6">
      {/* Reference-layout parity (Connectors+Plugins UI redesign,
          2026-09-30): section header now carries the item count as its
          own small pill next to the title (reference: "Top connectors
          3588"), and "Show all" reads as a real link with a trailing
          arrow rather than a plain "(count)" suffix on the toggle itself. */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <h3 className="m-0 text-lg text-gray-900 capitalize">
            {category.replace(/-/g, " ")}
          </h3>
          <span data-testid="category-count" className="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-50 text-gray-500 text-xs">
            {items.length}
          </span>
        </div>
        {items.length > COLLAPSED_COUNT && <button type="button" data-testid="show-all-link" onClick={() => setExpanded(e => !e)} className="inline-flex items-center gap-1 bg-none border-none text-gray-900 hover:opacity-70 cursor-pointer text-sm transition-colors">
            {expanded ? "Show less" : "Show all"}
            {!expanded && <ArrowRightIcon width={14} height={14} aria-hidden="true" />}
          </button>}
      </div>
      {/* User-flow QA round 4 (2026-10-03): this 480px/1fr grid was wrong on
          two counts the user directly caught live -- (1) 480px minmax only
          ever allowed 2 columns, not the requested maximum of 3, and (2) a
          category with exactly 1 item (e.g. "Dev tools", "Communication")
          had that single card stretch across the FULL row width, because
          auto-fit collapses the other, empty tracks and 1fr then
          redistributes their freed space onto the one occupied track.
          Unified with Discover.tsx/Yours.tsx's own grids: minmax(240px,
          320px) is a FIXED upper bound, not 1fr, so one card never stretches
          past a normal card width regardless of how many siblings its
          category has; maxWidth caps the row at 3 columns when there ARE
          enough items (3 * 320px + 2 * 16px gaps = 992px, under the cap --
          a 4th 240px-minimum column would need 1008px, which doesn't fit). */}
      <div className="grid gap-4 max-w-[1000px]" style={{
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 320px))"
    }}>
        {visible.map(item =>
      // Real gap found and fixed (Connectors+Plugins UI redesign,
      // 2026-09-30): this section is what actually renders on the
      // DEFAULT (no search/filter) Discover view -- Discover.tsx's own
      // ConnectorCard-vs-Card branch only ever ran on the flat
      // filtered-results grid (query/category/trust active), so a
      // connector/mcp_server item browsed by category showed the
      // wrong (install-state "+Add") card instead of the real
      // connection-state ("Connect") one. Same condition as
      // Discover.tsx's own filtered branch, so both paths agree.
      item.item_type === "connector" || item.item_type === "mcp_server" ? <ConnectorCard key={item.id} item={item} onOpen={onOpen} /> : <Card key={item.id} item={item} onOpen={onOpen} onInstalled={onInstalled} />)}
      </div>
    </section>;
}