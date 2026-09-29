// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the catalog list page's header row --
// title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add" --
// matching docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's own
// header(). Rendered only by CatalogScreen (the list page); Detail/
// CreateForm/UploadFlow/ImportFlow are drill-in screens with their own
// back/cancel affordance instead, matching the mock's renderDetail() (no
// header() call there either -- see Marketplace.tsx's RouteSwitch).
import { MagnifyingGlassIcon, Squares2X2Icon, ListBulletIcon } from "@heroicons/react/24/outline";
import type { ListItemsParams, TrustTier } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { TypeTabs } from "./TypeTabs";
import { AddMenu } from "./AddMenu";
import { FilterButton } from "./FilterPopover";
import { SortButton } from "./SortPopover";
import { closeAny } from "./popoverCoordinator";
import type { CreateAction } from "../routing";
import "./Toolbar.css";

/** Search box placeholder text per active type tab -- the mock's own
 * per-tab copy ("Search skills"), not one generic string truncated at
 * narrow widths. Falls back to a generic phrase for an unknown/future
 * type slug rather than guessing a plural. */
const SEARCH_PLACEHOLDER: Record<string, string> = {
  skills: "Search skills", plugins: "Search plugins",
  connectors: "Search connectors", mcp: "Search MCP servers",
};

export interface ToolbarProps {
  activeSlug: string;
  onSelectType: (slug: string) => void;
  view: "discover" | "yours";
  onSelectView: (view: "discover" | "yours") => void;
  query: string;
  onQueryChange: (query: string) => void;
  categories: Set<string>;
  onCategoriesChange: (categories: Set<string>) => void;
  trust: Set<TrustTier>;
  onTrustChange: (trust: Set<TrustTier>) => void;
  sort: NonNullable<ListItemsParams["sort"]>;
  onSortChange: (sort: NonNullable<ListItemsParams["sort"]>) => void;
  onSelectCreateAction: (action: CreateAction) => void;
  onCreateWithAi?: () => void;
  /** Coming-soon tabs (UI-polish round): the SAME header/toolbar row as
   * every other tab, per the user's own ask ("keep the same page header/
   * toolbar on every tab") -- search disabled (there's a real list, just
   * nothing to search yet), filter/sort hidden entirely (nothing to
   * filter/sort). Type tabs, Yours/Discover switch, and Add stay exactly
   * where they always are. */
  searchDisabled?: boolean;
  hideFilterSort?: boolean;
  /** Grid/List toggle (item 2, M5 UI-polish review) -- only ever shown
   * when `view === "yours"`; Discover has no grid/list choice. */
  yoursLayout?: "grid" | "list";
  onYoursLayoutChange?: (layout: "grid" | "list") => void;
  /** Connectors phase item 5 (collapse "connector"+"mcp_server" into one
   * "Connectors" tab + "Advanced: MCP servers" sub-view) -- threaded
   * straight through to TypeTabs, see its own header comment. Omitted
   * (the default everywhere below) is byte-identical to today's
   * behavior -- no existing Toolbar caller regresses just by picking up
   * this change. */
  collapseConnectorsAdvanced?: boolean;
  advancedActive?: boolean;
  onSelectAdvanced?: (advanced: boolean) => void;
}

export function Toolbar({
  activeSlug, onSelectType, view, onSelectView,
  query, onQueryChange, categories, onCategoriesChange, trust, onTrustChange,
  sort, onSortChange, onSelectCreateAction, onCreateWithAi,
  searchDisabled = false, hideFilterSort = false,
  yoursLayout, onYoursLayoutChange,
  collapseConnectorsAdvanced = false, advancedActive = false, onSelectAdvanced,
}: ToolbarProps) {
  const config = useConfig();
  const activeFilterCount = categories.size + trust.size;
  // Real bug found live: the "+ Add" dropdown stayed open after switching
  // Yours <-> Discover or type tabs -- both are local component state
  // (CatalogScreen's `view`), not a route change PopoverAnchor's own
  // router.path watcher would ever see, so it's closed explicitly here,
  // the one place both actions flow through.
  const handleSelectType = (slug: string) => { closeAny(); onSelectType(slug); };
  const handleSelectView = (v: "discover" | "yours") => { closeAny(); onSelectView(v); };

  return (
    <div data-testid="marketplace-toolbar">
      <h1 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)", margin: "0 0 var(--eco-space-md)" }}>
        Marketplace
      </h1>
      <div className="eco-toolbar-bar" data-testid="marketplace-toolbar-bar">
        <TypeTabs
          activeSlug={activeSlug}
          onSelect={handleSelectType}
          collapseConnectorsAdvanced={collapseConnectorsAdvanced}
          advancedActive={advancedActive}
          onSelectAdvanced={onSelectAdvanced}
        />
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
        <div className="eco-toolbar-controls">
          <ViewSwitch view={view} onSelect={handleSelectView} />
          <label className="eco-toolbar-search" data-testid="toolbar-search" aria-disabled={searchDisabled} style={searchDisabled ? { opacity: 0.5 } : undefined}>
            <MagnifyingGlassIcon width={16} height={16} aria-hidden="true" />
            <input
              type="text"
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder={SEARCH_PLACEHOLDER[activeSlug] ?? "Search the catalog"}
              aria-label="Search"
              disabled={searchDisabled}
            />
          </label>
          {!hideFilterSort && (
            <>
              <FilterButton
                categories={categories}
                onCategoriesChange={(next) => { onCategoriesChange(next); onSelectView("discover"); }}
                trust={trust}
                onTrustChange={(next) => { onTrustChange(next); onSelectView("discover"); }}
                taxonomy={config.taxonomy}
                activeCount={activeFilterCount}
              />
              <SortButton sort={sort} onSortChange={onSortChange} />
            </>
          )}
          {view === "yours" && onYoursLayoutChange && (
            <LayoutToggle layout={yoursLayout ?? "grid"} onChange={onYoursLayoutChange} />
          )}
          <AddMenu activeSlug={activeSlug} onSelect={onSelectCreateAction} onCreateWithAi={onCreateWithAi} />
        </div>
      </div>
    </div>
  );
}

/** Grid/List toggle for Yours (item 2, M5 UI-polish review) -- same
 * segmented-control pattern as ViewSwitch above, keyboard-accessible
 * (real <button>s, aria-pressed) and legible at the compact layout's
 * narrower toolbar (icon-only, no label text to wrap/clip). */
function LayoutToggle({ layout, onChange }: { layout: "grid" | "list"; onChange: (layout: "grid" | "list") => void }) {
  return (
    <div className="eco-toolbar-seg" role="group" aria-label="Layout" data-testid="yours-layout-toggle">
      <button
        type="button"
        data-testid="yours-layout-grid"
        aria-pressed={layout === "grid"}
        aria-label="Grid view"
        title="Grid view"
        className={layout === "grid" ? "on" : ""}
        onClick={() => onChange("grid")}
      >
        <Squares2X2Icon width={16} height={16} aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid="yours-layout-list"
        aria-pressed={layout === "list"}
        aria-label="List view"
        title="List view"
        className={layout === "list" ? "on" : ""}
        onClick={() => onChange("list")}
      >
        <ListBulletIcon width={16} height={16} aria-hidden="true" />
      </button>
    </div>
  );
}

function ViewSwitch({ view, onSelect }: { view: "discover" | "yours"; onSelect: (view: "discover" | "yours") => void }) {
  return (
    <div className="eco-toolbar-seg" role="tablist" data-testid="view-switch">
      <button
        type="button" role="tab" aria-selected={view === "yours"} data-testid="view-toggle-yours"
        className={view === "yours" ? "on" : ""} onClick={() => onSelect("yours")}
      >
        Yours
      </button>
      <button
        type="button" role="tab" aria-selected={view === "discover"} data-testid="view-toggle-discover"
        className={view === "discover" ? "on" : ""} onClick={() => onSelect("discover")}
      >
        Discover
      </button>
    </div>
  );
}
