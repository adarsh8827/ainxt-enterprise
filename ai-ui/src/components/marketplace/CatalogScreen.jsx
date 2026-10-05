// SPDX-License-Identifier: MIT
// Wires the catalog list page together (task F-5/F-6, item 1 of the M5
// UI-parity review): the Toolbar (title, type tabs, Yours/Discover switch,
// search, filter, sort, "+ Add") plus the Discover/Yours body -- the
// reference mock's own header() + discover()/yoursView() combined into one
// renderList(). Default view (CONTRACTS.md §7, Review fix 8): Yours if
// GET /ecosystem/installs?item_type=X has_any is true, else the product
// profile's default_view -- determined from that one field, no separate call.
import { useEffect, useState } from "react";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
import { useEcosystemClient } from "./lib/context/HostContext";
import { Discover } from "./Discover";
import { Yours } from "./Yours";
import { ConnectorsYours } from "./Connectors/ConnectorsYours";
import { Toolbar } from "./Toolbar";
import { LoadingState } from "./LoadingState";
export function CatalogScreen({
  itemType,
  typeSlug,
  onOpen,
  onCreate,
  onSelectType,
  onCreateAction,
  onCreateWithAi,
  showAdvancedToggle,
  advancedActive,
  onSelectAdvanced
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [view, setView] = useState(null);
  const [query, setQuery] = useState("");
  const [categories, setCategories] = useState(new Set());
  const [trust, setTrust] = useState(new Set());
  const [sort, setSort] = useState("featured");
  // Grid/List for Yours (item 2, M5 UI-polish review): a UI preference
  // only, never data -- localStorage, not a server call. Per-user because
  // localStorage is already per-browser-profile; default grid.
  const [yoursLayout, setYoursLayout] = useState(() => {
    try {
      const stored = window.localStorage.getItem("ecosystem-ui:yours-layout");
      return stored === "list" ? "list" : "grid";
    } catch {
      return "grid";
    }
  });
  const handleYoursLayoutChange = next => {
    setYoursLayout(next);
    try {
      window.localStorage.setItem("ecosystem-ui:yours-layout", next);
    } catch {
      // Private-browsing/storage-disabled -- the toggle still works for
      // this session, it just won't be remembered next time. Not worth
      // surfacing an error for a pure UI preference.
    }
  };
  // Discover list-view pass (2026-10-05, explicit product ask: "why we
  // dont have list/grid toggle icons views in discover page"): own
  // localStorage key, own state -- deliberately NOT shared with
  // yoursLayout above, so switching Yours <-> Discover never clobbers
  // whichever one the caller set independently for the other view.
  const [discoverLayout, setDiscoverLayout] = useState(() => {
    try {
      const stored = window.localStorage.getItem("ecosystem-ui:discover-layout");
      return stored === "list" ? "list" : "grid";
    } catch {
      return "grid";
    }
  });
  const handleDiscoverLayoutChange = next => {
    setDiscoverLayout(next);
    try {
      window.localStorage.setItem("ecosystem-ui:discover-layout", next);
    } catch {
      // Same private-browsing/storage-disabled fallback as yoursLayout above.
    }
  };
  useEffect(() => {
    let cancelled = false;
    client.getInstalls(itemType).then(res => {
      if (!cancelled) setView(res.has_any ? "yours" : config.default_view);
    });
    return () => {
      cancelled = true;
    };
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
  if (view === null) return <div data-testid="catalog-screen-loading"><LoadingState /></div>;
  // Toolbar/content alignment pass (2026-10-05, explicit product ask:
  // "yours/discover toggle, search, all the subsequent icons... look more
  // right aligned need little left aligned"): Toolbar's own right-hand
  // cluster (ViewSwitch/search/filter/sort/layout/Add) sits inside a
  // `ml-auto` group, which pushes it all the way to this row's own right
  // edge -- fine when that edge tracked a capped ~1000px content width,
  // but now that the grid below genuinely fills the viewport (layout-
  // density pass, same day), that edge is the literal browser window
  // edge on a wide monitor. The grid itself never reaches that same edge
  // (auto-fit's column math always leaves SOME remainder -- see
  // CategorySection.jsx's own comment), so the toolbar's right cluster
  // visibly overshot past where the cards actually end, reading as
  // disconnected/too-far-right. A shared max-width on this root --
  // covering both the Toolbar and the Discover/Yours body below it --
  // gives both the SAME right boundary: comfortably past 5 columns
  // (5*280px cards + gaps = 1464px) so it doesn't reintroduce the old
  // "always 3 columns" cap, but stops the toolbar cluster from drifting
  // out past the content on anything wider than a ~1600px content area.
  return <div data-testid="catalog-screen" className="max-w-[1600px]">
      <Toolbar activeSlug={typeSlug} onSelectType={onSelectType} view={view} onSelectView={setView} query={query} onQueryChange={setQuery} categories={categories} onCategoriesChange={setCategories} trust={trust} onTrustChange={setTrust} sort={sort} onSortChange={setSort} onSelectCreateAction={onCreateAction} onCreateWithAi={onCreateWithAi} yoursLayout={yoursLayout} onYoursLayoutChange={handleYoursLayoutChange} discoverLayout={discoverLayout} onDiscoverLayoutChange={handleDiscoverLayoutChange} showAdvancedToggle={showAdvancedToggle} advancedActive={advancedActive} onSelectAdvanced={onSelectAdvanced} />
      {view === "discover" ? <Discover itemType={itemType} onOpen={onOpen} query={query} categories={categories} trust={trust} sort={sort} onClearFilters={clearFilters} layout={discoverLayout} /> : itemType === "connector"
    // Real gap found and fixed (2026-09-30): ConnectorsYours.tsx's
    // row renderer existed and was tested since Stage 2 but was
    // never reachable -- this always rendered the generic,
    // install-based <Yours> for every item type including
    // "connector". Connection-status-driven, not install-driven.
    ? <ConnectorsYours onDiscover={() => setView("discover")} /> : <Yours itemType={itemType} onOpen={onOpen} onCreate={onCreate} onDiscover={() => setView("discover")} query={query} layout={yoursLayout} />}
    </div>;
}