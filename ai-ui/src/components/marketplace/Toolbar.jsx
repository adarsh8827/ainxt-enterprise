// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the catalog list page's header row --
// title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add" --
// matching docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's own
// header(). Rendered only by CatalogScreen (the list page); Detail/
// CreateForm/UploadFlow/ImportFlow are drill-in screens with their own
// back/cancel affordance instead, matching the mock's renderDetail() (no
// header() call there either -- see Marketplace.tsx's RouteSwitch).
import { MagnifyingGlassIcon, Squares2X2Icon, ListBulletIcon } from "@heroicons/react/24/outline";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
import { TypeTabs } from "./TypeTabs";
import { AddMenu } from "./AddMenu";
import { FilterButton } from "./FilterPopover";
import { SortButton } from "./SortPopover";
import { closeAny } from "./popoverCoordinator";

/** Search box placeholder text per active type tab -- the mock's own
 * per-tab copy ("Search skills"), not one generic string truncated at
 * narrow widths. Falls back to a generic phrase for an unknown/future
 * type slug rather than guessing a plural. */
const SEARCH_PLACEHOLDER = {
  skills: "Search skills",
  plugins: "Search plugins",
  connectors: "Search connectors",
  mcp: "Search MCP servers"
};
export function Toolbar({
  activeSlug,
  onSelectType,
  view,
  onSelectView,
  query,
  onQueryChange,
  categories,
  onCategoriesChange,
  trust,
  onTrustChange,
  sort,
  onSortChange,
  onSelectCreateAction,
  onCreateWithAi,
  searchDisabled = false,
  hideFilterSort = false,
  yoursLayout,
  onYoursLayoutChange,
  discoverLayout,
  onDiscoverLayoutChange,
  showAdvancedToggle = false,
  advancedActive = false,
  onSelectAdvanced
}) {
  const config = useConfig();
  const activeFilterCount = categories.size + trust.size;
  // Real bug found live: the "+ Add" dropdown stayed open after switching
  // Yours <-> Discover or type tabs -- both are local component state
  // (CatalogScreen's `view`), not a route change PopoverAnchor's own
  // router.path watcher would ever see, so it's closed explicitly here,
  // the one place both actions flow through.
  const handleSelectType = slug => {
    closeAny();
    onSelectType(slug);
  };
  const handleSelectView = v => {
    closeAny();
    onSelectView(v);
  };
  return <div data-testid="marketplace-toolbar">
      {/* Theme-alignment pass (2026-10-05): same missing-font-weight gap as
          every section heading in this package (see CategorySection.jsx's
          comment) -- `text-xl` with no weight class renders as
          regular-weight 20px, lighter than ProductManager.jsx's own
          page-title convention (`text-xl font-bold text-gray-900` for a
          selected item's name). font-semibold here, not font-bold --
          "Marketplace" is this package's own persistent page title, not a
          per-record detail heading, so a touch lighter reads correctly
          without looking under-styled. */}
      <h1 className="text-xl font-semibold text-gray-900 m-0 mb-4">
        Marketplace
      </h1>
      <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="marketplace-toolbar-bar">
        <TypeTabs activeSlug={activeSlug} onSelect={handleSelectType} showAdvancedToggle={showAdvancedToggle} advancedActive={advancedActive} onSelectAdvanced={onSelectAdvanced} />
        {/* Real bug found live (2026-09-28, screenshot at 1920px): a stray
            vertical divider (`.eco-toolbar-vsep`) used to render right
            after the last type tab, unconditionally -- with TypeTabs'
            own underline only spanning the tabs' own width (not the full
            bar), that short vertical line read as a floating, disconnected
            dash rather than a deliberate separator. Removed outright;
            `.eco-toolbar-controls`' own `margin-left: auto` already
            provides all the visual separation from the tabs this row
            needs. */}
        {/* UI alignment spec (M5 UI-parity review, 2026-09-28): everything
            right of the tabs is one group now (.eco-toolbar-controls),
            not loose flex children -- two real bugs found live fixing
            this: (1) ViewSwitch used to render on the TABS side of the
            old standalone grow-spacer, visually grouping "Yours/
            Discover" with the type tabs instead of leading the
            right-aligned cluster the spec calls for ("left: type tabs;
            right cluster: Yours/Discover switch, search, filter, sort,
            Grid/List, + Add"); (2) plain flex-wrap on mixed loose
            children has no concept of "wrap as one clean group" -- at
            in-between widths it could wrap ONE control (e.g. just Sort)
            onto its own line while the rest stayed put, a partial wrap
            the spec explicitly forbids ("no partial wrap"). Grouping
            these into one wrapper lets Toolbar.css force the whole
            group onto its own full-width row below 1280px as a single
            unit, and margin-left:auto (not a separate spacer div) push
            it right on the shared row above that. */}
        <div className="flex flex-wrap items-center gap-2 ml-auto min-w-0 max-[1280px]:basis-full max-[1280px]:ml-0">
          <ViewSwitch view={view} onSelect={handleSelectView} />
          <label className={["inline-flex items-center gap-2 min-w-[140px] flex-1 max-w-[340px] px-3 py-1.5 rounded-md border border-gray-200 bg-white shadow-sm text-gray-400 transition-colors focus-within:border-indigo-300 max-[720px]:min-w-0 max-[720px]:basis-full max-[720px]:order-1", searchDisabled ? "opacity-50" : ""].join(" ")} data-testid="toolbar-search" aria-disabled={searchDisabled}>
            <MagnifyingGlassIcon width={16} height={16} aria-hidden="true" />
            <input type="text" className="border-none bg-none outline-none focus-visible:outline-none! flex-1 min-w-0 text-sm text-gray-900" value={query} onChange={e => onQueryChange(e.target.value)} placeholder={SEARCH_PLACEHOLDER[activeSlug] ?? "Search the catalog"} aria-label="Search" disabled={searchDisabled} />
          </label>
          {!hideFilterSort && <>
              <FilterButton categories={categories} onCategoriesChange={next => {
            onCategoriesChange(next);
            onSelectView("discover");
          }} trust={trust} onTrustChange={next => {
            onTrustChange(next);
            onSelectView("discover");
          }} taxonomy={config.taxonomy} activeCount={activeFilterCount} />
              <SortButton sort={sort} onSortChange={onSortChange} />
            </>}
          {/* Discover list-view pass (2026-10-05, explicit product ask:
              "why we dont have list/grid toggle icons views in discover
              page"): same LayoutToggle control, now shared by both views --
              whichever is active owns it, each with its own persisted
              preference (yoursLayout/discoverLayout are two separate
              localStorage keys in CatalogScreen.tsx, not one shared value)
              so switching Yours <-> Discover never clobbers the other
              view's own remembered layout. */}
          {view === "yours" && onYoursLayoutChange && <LayoutToggle layout={yoursLayout ?? "grid"} onChange={onYoursLayoutChange} />}
          {view === "discover" && onDiscoverLayoutChange && <LayoutToggle layout={discoverLayout ?? "grid"} onChange={onDiscoverLayoutChange} />}
          <AddMenu activeSlug={activeSlug} onSelect={onSelectCreateAction} onCreateWithAi={onCreateWithAi} />
        </div>
      </div>
    </div>;
}

/** Grid/List toggle for Yours (item 2, M5 UI-polish review) -- same
 * segmented-control pattern as ViewSwitch above, keyboard-accessible
 * (real <button>s, aria-pressed) and legible at the compact layout's
 * narrower toolbar (icon-only, no label text to wrap/clip). */
// Real jank found live (2026-10-05, "toggling Yours/Discover... page
// getting jumping"): toggling `font-semibold` on/off between the
// active/inactive state changes this text's own rendered width by a few
// px (bold vs. regular glyphs of the same string aren't the same width),
// so the Yours/Discover pill itself visibly shifted on every click, on
// top of the (larger, separately fixed) content-area skeleton/real-card
// height mismatch. font-semibold now applies unconditionally -- the
// active/inactive distinction is carried entirely by background + shadow,
// which cause zero layout shift.
const segButtonClass = on => ["px-3.5 py-1.5 rounded-full text-sm font-semibold transition-colors cursor-pointer border-none", on ? "bg-white text-gray-900 shadow-sm" : "bg-transparent text-gray-500 hover:text-gray-900"].join(" ");
function LayoutToggle({
  layout,
  onChange
}) {
  return <div className="inline-flex p-0.5 rounded-full bg-gray-100 flex-shrink-0" role="group" aria-label="Layout" data-testid="yours-layout-toggle">
      <button type="button" data-testid="yours-layout-grid" aria-pressed={layout === "grid"} aria-label="Grid view" title="Grid view" className={segButtonClass(layout === "grid")} onClick={() => onChange("grid")}>
        <Squares2X2Icon width={16} height={16} aria-hidden="true" />
      </button>
      <button type="button" data-testid="yours-layout-list" aria-pressed={layout === "list"} aria-label="List view" title="List view" className={segButtonClass(layout === "list")} onClick={() => onChange("list")}>
        <ListBulletIcon width={16} height={16} aria-hidden="true" />
      </button>
    </div>;
}
function ViewSwitch({
  view,
  onSelect
}) {
  return <div className="inline-flex p-0.5 rounded-full bg-gray-100 flex-shrink-0" role="tablist" data-testid="view-switch">
      <button type="button" role="tab" aria-selected={view === "yours"} data-testid="view-toggle-yours" className={segButtonClass(view === "yours")} onClick={() => onSelect("yours")}>
        Yours
      </button>
      <button type="button" role="tab" aria-selected={view === "discover"} data-testid="view-toggle-discover" className={segButtonClass(view === "discover")} onClick={() => onSelect("discover")}>
        Discover
      </button>
    </div>;
}