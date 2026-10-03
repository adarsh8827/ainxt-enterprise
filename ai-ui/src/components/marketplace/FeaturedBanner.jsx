// SPDX-License-Identifier: MIT
// Task F-5: driven by ItemSummary.is_featured (server-computed, already
// folding in ecosystem_featured_overrides for the caller's org -- see
// items_service._is_featured()) -- never re-derived client-side.

import { ItemIcon } from "./ItemIcon";
export function FeaturedBanner({
  items,
  onOpen
}) {
  const featured = items.filter(i => i.is_featured);
  if (featured.length === 0) return null;
  return <div data-testid="featured-banner-section" className="mb-6">
      {/* Real bug found live: this banner rendered with no heading at all --
          visually the first thing on the page, so the true first titled
          section (the first CategorySection below it) looked like it was
          missing its own title. Every section gets a heading now. */}
      <h3 data-testid="featured-banner-heading" className="mt-0 mb-2 text-lg text-gray-900">
        Featured
      </h3>
      <div data-testid="featured-banner" className="flex gap-4 overflow-x-auto pb-2">
      {featured.map(item => <button key={item.id} type="button" data-testid="featured-item" onClick={() => onOpen(item)} className="flex items-center gap-2 min-w-[260px] p-4 rounded-xl border border-indigo-600 bg-gray-50 text-left cursor-pointer hover:bg-gray-100 transition-colors">
          <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={32} />
          <div>
            <div className="font-semibold text-gray-900">{item.display_name}</div>
            <div className="text-xs text-gray-500">{item.description}</div>
          </div>
        </button>)}
      </div>
    </div>;
}