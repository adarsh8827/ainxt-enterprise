// SPDX-License-Identifier: MIT
// Wires the catalog list page together (task F-5/F-6, item 1 of the M5
// UI-parity review): the Toolbar (title, type tabs, Yours/Discover switch,
// search, filter, sort, "+ Add") plus the Discover/Yours body -- the
// reference mock's own header() + discover()/yoursView() combined into one
// renderList(). Default view (CONTRACTS.md §7, Review fix 8): Yours if
// GET /ecosystem/installs?item_type=X has_any is true, else the product
// profile's default_view -- determined from that one field, no separate call.
import { useEffect, useState } from "react";
import type { ItemSummary, ItemType, ListItemsParams, TrustTier } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient } from "../context/HostContext";
import { Discover } from "./Discover";
import { Yours } from "./Yours";
import { Toolbar } from "./Toolbar";
import type { CreateAction } from "../routing";

export function CatalogScreen({
  itemType, typeSlug, onOpen, onCreate, onSelectType, onCreateAction, onCreateWithAi,
  collapseConnectorsAdvanced, advancedActive, onSelectAdvanced,
}: {
  itemType: ItemType;
  typeSlug: string;
  onOpen: (item: ItemSummary) => void;
  onCreate: () => void;
  onSelectType: (slug: string) => void;
  onCreateAction: (action: CreateAction) => void;
  onCreateWithAi?: () => void;
  /** Connectors phase item 5 -- see Toolbar.tsx/TypeTabs.tsx. Omitted is
   * byte-identical to today's behavior. */
  collapseConnectorsAdvanced?: boolean;
  advancedActive?: boolean;
  onSelectAdvanced?: (advanced: boolean) => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [view, setView] = useState<"discover" | "yours" | null>(null);
  const [query, setQuery] = useState("");
  const [categories, setCategories] = useState<Set<string>>(new Set());
  const [trust, setTrust] = useState<Set<TrustTier>>(new Set());
  const [sort, setSort] = useState<NonNullable<ListItemsParams["sort"]>>("featured");
  // Grid/List for Yours (item 2, M5 UI-polish review): a UI preference
  // only, never data -- localStorage, not a server call. Per-user because
  // localStorage is already per-browser-profile; default grid.
  const [yoursLayout, setYoursLayout] = useState<"grid" | "list">(() => {
    try {
      const stored = window.localStorage.getItem("ecosystem-ui:yours-layout");
      return stored === "list" ? "list" : "grid";
    } catch {
      return "grid";
    }
  });
  const handleYoursLayoutChange = (next: "grid" | "list") => {
    setYoursLayout(next);
    try {
      window.localStorage.setItem("ecosystem-ui:yours-layout", next);
    } catch {
      // Private-browsing/storage-disabled -- the toggle still works for
      // this session, it just won't be remembered next time. Not worth
      // surfacing an error for a pure UI preference.
    }
  };

  useEffect(() => {
    let cancelled = false;
    client.getInstalls(itemType).then((res) => {
      if (!cancelled) setView(res.has_any ? "yours" : config.default_view);
    });
    return () => { cancelled = true; };
  }, [client, itemType, config.default_view]);

  // Switching type tabs resets search/filter/sort -- matches the reference
  // mock's own setType() ("S.q=''; S.cats.clear(); S.trust.clear()").
  useEffect(() => {
    setQuery("");
    setCategories(new Set());
    setTrust(new Set());
    setSort("featured");
  }, [itemType]);

  const clearFilters = () => {
    setQuery("");
    setCategories(new Set());
    setTrust(new Set());
  };

  if (view === null) return <div data-testid="catalog-screen-loading">Loading…</div>;

  return (
    <div data-testid="catalog-screen">
      <Toolbar
        activeSlug={typeSlug}
        onSelectType={onSelectType}
        view={view}
        onSelectView={setView}
        query={query}
        onQueryChange={setQuery}
        categories={categories}
        onCategoriesChange={setCategories}
        trust={trust}
        onTrustChange={setTrust}
        sort={sort}
        onSortChange={setSort}
        onSelectCreateAction={onCreateAction}
        onCreateWithAi={onCreateWithAi}
        yoursLayout={yoursLayout}
        onYoursLayoutChange={handleYoursLayoutChange}
        collapseConnectorsAdvanced={collapseConnectorsAdvanced}
        advancedActive={advancedActive}
        onSelectAdvanced={onSelectAdvanced}
      />
      {view === "discover"
        ? <Discover itemType={itemType} onOpen={onOpen} query={query} categories={categories} trust={trust} sort={sort} onClearFilters={clearFilters} />
        : <Yours itemType={itemType} onOpen={onOpen} onCreate={onCreate} onDiscover={() => setView("discover")} query={query} layout={yoursLayout} />}
    </div>
  );
}
