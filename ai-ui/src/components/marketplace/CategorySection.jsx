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
  onInstalled,
  layout = "grid"
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);
  return <section data-testid="category-section" data-category={category} className="mb-8">
      {/* Reference-layout parity (Connectors+Plugins UI redesign,
          2026-09-30): section header now carries the item count as its
          own small pill next to the title (reference: "Top connectors
          3588"), and "Show all" reads as a real link with a trailing
          arrow rather than a plain "(count)" suffix on the toggle itself.
          Theme-alignment pass (2026-10-05, explicit product ask: "font
          color and style match with existing application theme... your
          section category heading style, color, margin, padding should
          be fixed"): was `text-lg text-gray-900` with no font-weight class
          at all (Tailwind preflight resets the h-tag's default bold, so
          this rendered as REGULAR-weight 18px text) -- simultaneously
          larger AND lighter than every other screen's own section-heading
          convention (confirmed directly against ProductManager.jsx/
          KnowledgeBase.jsx's own content-section headings: always
          `font-semibold` + `text-gray-800`, sized `text-sm`/`text-base`,
          never a bare `text-lg`). Matched here; mb-2 -> mb-3 and the
          section's own mb-6 -> mb-8 for a bit more breathing room between
          groups, per the same "premium... spacing between sections" ask. */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="m-0 text-sm font-semibold text-gray-800 capitalize">
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
          category has -- that fix is independent of the container's own
          width and still holds below.
          Layout-density pass (2026-10-05, explicit product ask: "showing 3
          card per row... is that right approach, or we can have to
          dynamically utilize the pages"): the extra `max-w-[1000px]` this
          grid used to carry on top of the above had nothing to do with the
          single-card-stretch fix -- it was a separate, deliberate choice to
          always cap the row at 3 columns regardless of how wide the actual
          content area was, which is exactly what produced the complaint
          (cards pinned to the left, 3-per-row even on a wide monitor, a
          dead strip of whitespace on the right). Dropped: auto-fit now
          fits as many columns as the real available width allows, so this
          scales with the viewport instead of a hardcoded column count.
          Follow-up found live on a laptop-width screen (1536px, explicit
          report: "kind of stuck layout"): auto-fit's own repeat-count math
          uses the track sizing function's MAX (not its min) to decide how
          many tracks fit (CSS Grid spec 12.2.3.1) -- at 320px that math
          landed on exactly 3 columns at 1536px with ~260px (21%) left
          unused on the right, because a 4th 320px column plus its gap
          didn't quite fit, and the auto-fit algorithm never partially
          grows a column short of fitting a whole extra one. Lowering the
          max to 280px lets a 4th column fit in that same 1536px case
          (leftover drops to ~86px, 7%) and a 5th at 1920px (up from 4) --
          still a comfortable card width, just tuned to pack common laptop
          widths better instead of leaving a visibly large idle strip. */}
      {/* Discover list-view pass (2026-10-05): list mode drops the grid
          entirely for a flat flex column -- Card.tsx's own list row already
          carries its own border-b divider per item, so this wrapper needs
          no gap/border of its own (matching InstallRow's identical list
          container in Yours.tsx). ConnectorCard has no list variant (out
          of scope for this round -- its own card shape wasn't part of the
          "skill cards" ask), so a connector/mcp_server item still always
          renders its existing grid card regardless of the toggle, same as
          it always has. */}
      {layout === "list" ? <div className="flex flex-col">
          {visible.map(item => item.item_type === "connector" || item.item_type === "mcp_server" ? <ConnectorCard key={item.id} item={item} onOpen={onOpen} /> : <Card key={item.id} item={item} onOpen={onOpen} onInstalled={onInstalled} layout="list" />)}
        </div> : <div className="grid gap-4" style={{
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 280px))"
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
      </div>}
    </section>;
}