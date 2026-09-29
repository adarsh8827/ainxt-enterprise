// SPDX-License-Identifier: MIT
// Task F-5 + item 1 (M5 UI-parity review): full Discover screen --
// GET /ecosystem/items, grouped by category (config-driven order, never
// hardcoded), with a featured banner. When CatalogScreen's Toolbar has an
// active search/filter, this instead renders a flat "N results" grid +
// "Clear filters" link, matching the reference mock's own discover()/
// filtered() (a search or filter always means "show me a flat result set",
// never the browse-by-category layout).
import { useEffect, useRef, useState } from "react";
import type { ItemSummary, ItemType, ListItemsParams, TrustTier } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { FeaturedBanner } from "./FeaturedBanner";
import { CategorySection } from "./CategorySection";
import { Card } from "./Card";

// Item 7 (tab-switch report): a just-added catalog item can still be
// mid-gate when this list is first refetched (the async gate path --
// materialize_from_catalog()'s own "about a second" fast path is already
// resolved by the time the response comes back, this only matters for the
// slower, worker-resolved case). Without this, the grid never looked
// again and a resolved item stayed stuck on "Verifying" until a manual
// reload -- same POLL_INTERVAL_MS convention as detail/Verification.tsx.
const POLL_INTERVAL_MS = 2000;

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
  // install_id/"Added" state without a full page reload, AND by the
  // poll-while-verifying effect below. isBackgroundRefresh distinguishes
  // the two: a background poll must never re-null `items` (that would
  // flash the loading state on every tick for no reason) the way an
  // explicit filter change or quick-add correctly still does.
  const [refreshKey, setRefreshKey] = useState(0);
  const isBackgroundRefresh = useRef(false);
  const onInstalled = () => setRefreshKey((k) => k + 1);

  const categoryList = categories ? [...categories] : [];
  const trustList = trust ? [...trust] : [];
  const categoryKey = categoryList.join(",");
  const trustKey = trustList.join(",");
  const hasFilters = Boolean(query.trim()) || categoryList.length > 0 || trustList.length > 0;

  useEffect(() => {
    let cancelled = false;
    let pollTimeout: ReturnType<typeof setTimeout> | null = null;
    if (!isBackgroundRefresh.current) {
      setItems(null);
      setError(null);
    }
    isBackgroundRefresh.current = false;
    client.listItems({
      item_type: itemType,
      limit: 200,
      sort,
      q: query.trim() || undefined,
      category: categoryList.length ? categoryList : undefined,
      trust: trustList.length ? trustList : undefined,
    })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setError(null);
        // Only ever an item this caller has actually installed (install_id
        // set) -- a not-yet-added catalog item's own "pending"-looking
        // state is a different thing entirely (catalogState.ts's
        // isNotYetAddedCatalogItem(), never mistaken for "verifying" by
        // Card.tsx already) and must never keep this poll alive.
        const stillVerifying = res.items.some((item) => item.install_id && item.latest_verdict === "pending");
        if (stillVerifying) {
          pollTimeout = setTimeout(() => {
            if (cancelled) return;
            isBackgroundRefresh.current = true;
            setRefreshKey((k) => k + 1);
          }, POLL_INTERVAL_MS);
        }
      })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => {
      cancelled = true;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, itemType, query, sort, categoryKey, trustKey, refreshKey]);

  if (error) {
    return <div data-testid="discover-error" role="alert">Couldn't load the catalog. Please try again.</div>;
  }
  if (items === null) {
    // Real bug found live: this used to render `strings.verifying`
    // ("Verifying…") as the generic "list hasn't loaded yet" indicator --
    // a page-level loading state must never read as a claim about any
    // item's own gate status. See HostContext.tsx's own DEFAULT_STRINGS
    // comment for the full account.
    return <div data-testid="discover-loading">{strings.loading}</div>;
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
