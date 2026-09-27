// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the catalog list page's header row --
// title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add" --
// matching docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's own
// header(). Rendered only by CatalogScreen (the list page); Detail/
// CreateForm/UploadFlow/ImportFlow are drill-in screens with their own
// back/cancel affordance instead, matching the mock's renderDetail() (no
// header() call there either -- see Marketplace.tsx's RouteSwitch).
import { MagnifyingGlassIcon } from "@heroicons/react/24/outline";
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
}

export function Toolbar({
  activeSlug, onSelectType, view, onSelectView,
  query, onQueryChange, categories, onCategoriesChange, trust, onTrustChange,
  sort, onSortChange, onSelectCreateAction, onCreateWithAi,
  searchDisabled = false, hideFilterSort = false,
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
        <TypeTabs activeSlug={activeSlug} onSelect={handleSelectType} />
        <div className="eco-toolbar-vsep" aria-hidden="true" />
        <ViewSwitch view={view} onSelect={handleSelectView} />
        <div className="eco-toolbar-grow" />
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
        <AddMenu activeSlug={activeSlug} onSelect={onSelectCreateAction} onCreateWithAi={onCreateWithAi} />
      </div>
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
