// SPDX-License-Identifier: MIT
// Task F-5 + item 1 (M5 UI-parity review): full Discover screen --
// GET /ecosystem/items, grouped by category (config-driven order, never
// hardcoded), with a featured banner. When CatalogScreen's Toolbar has an
// active search/filter, this instead renders a flat "N results" grid +
// "Clear filters" link, matching the reference mock's own discover()/
// filtered() (a search or filter always means "show me a flat result set",
// never the browse-by-category layout).
import { useEffect, useState } from "react";
import type { ItemSummary, ItemType, ListItemsParams, TrustTier } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { FeaturedBanner } from "./FeaturedBanner";
import { CategorySection } from "./CategorySection";
import { Card } from "./Card";

export function Discover({ itemType, onOpen, query = "", categories, trust, sort = "featured", onClearFilters }: {
  itemType: ItemType;
  onOpen: (item: ItemSummary) => void;
  query?: string;
  categories?: Set<string>;
  trust?: Set<TrustTier>;
  sort?: NonNullable<ListItemsParams["sort"]>;
  onClearFilters?: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const strings = useI18n();
  const [items, setItems] = useState<ItemSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  // Bumped by a card's own quick-add so the grid picks up its new
  // install_id/"Added" state without a full page reload.
  const [refreshKey, setRefreshKey] = useState(0);
  const onInstalled = () => setRefreshKey((k) => k + 1);

  const categoryList = categories ? [...categories] : [];
  const trustList = trust ? [...trust] : [];
  const categoryKey = categoryList.join(",");
  const trustKey = trustList.join(",");
  const hasFilters = Boolean(query.trim()) || categoryList.length > 0 || trustList.length > 0;

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    client.listItems({
      item_type: itemType,
      limit: 200,
      sort,
      q: query.trim() || undefined,
      category: categoryList.length ? categoryList : undefined,
      trust: trustList.length ? trustList : undefined,
    })
      .then((res) => { if (!cancelled) setItems(res.items); })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, itemType, query, sort, categoryKey, trustKey, refreshKey]);

  if (error) {
    return <div data-testid="discover-error" role="alert">Couldn't load the catalog. Please try again.</div>;
  }
  if (items === null) {
    return <div data-testid="discover-loading">{strings.verifying}</div>;
  }

  if (hasFilters) {
    return (
      <div data-testid="discover-screen" data-discover-mode="filtered">
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "var(--eco-space-sm)" }}>
          <h3 data-testid="discover-results-count" style={{ margin: 0, fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>
            {items.length} result{items.length === 1 ? "" : "s"}
          </h3>
          {onClearFilters && (
            <button
              type="button"
              data-testid="discover-clear-filters"
              onClick={onClearFilters}
              style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)" }}
            >
              Clear filters
            </button>
          )}
        </div>
        {items.length === 0 ? (
          <p style={{ color: "var(--eco-color-textMuted)" }}>No {itemType}s match. Try another search or category.</p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
            {items.map((item) => <Card key={item.id} item={item} onOpen={onOpen} onInstalled={onInstalled} />)}
          </div>
        )}
      </div>
    );
  }

  if (items.length === 0) {
    return <div data-testid="discover-empty-state">{strings.empty_discover}</div>;
  }

  const byCategory = new Map<string, ItemSummary[]>();
  for (const item of items) {
    const bucket = byCategory.get(item.category) ?? [];
    bucket.push(item);
    byCategory.set(item.category, bucket);
  }

  return (
    <div data-testid="discover-screen" data-discover-mode="browse">
      <FeaturedBanner items={items} onOpen={onOpen} />
      {config.taxonomy.categories
        .filter((category) => byCategory.has(category))
        .map((category) => (
          <CategorySection key={category} category={category} items={byCategory.get(category) ?? []} onOpen={onOpen} onInstalled={onInstalled} />
        ))}
    </div>
  );
}
