// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the catalog list page's header row --
// title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add"
// all present in one row (docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's
// own header()), plus the filter/sort popovers' own behavior.
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, within } from "@testing-library/react";
import { renderWithHost } from "./test-utils";
import { Toolbar } from "@marketplace/Toolbar";
function renderToolbar(overrides = {}) {
  const props = {
    activeSlug: "skills",
    onSelectType: vi.fn(),
    view: "discover",
    onSelectView: vi.fn(),
    query: "",
    onQueryChange: vi.fn(),
    categories: new Set(),
    onCategoriesChange: vi.fn(),
    trust: new Set(),
    onTrustChange: vi.fn(),
    sort: "featured",
    onSortChange: vi.fn(),
    onSelectCreateAction: vi.fn(),
    ...overrides
  };
  return {
    ...renderWithHost(<Toolbar {...props} />),
    props
  };
}
describe("Toolbar", () => {
  it("renders title, type tabs, view switch, search, filter, sort and Add in one row", () => {
    renderToolbar();
    expect(screen.getByText("Marketplace")).toBeInTheDocument();
    expect(screen.getByTestId("type-tabs")).toBeInTheDocument();
    const bar = screen.getByTestId("marketplace-toolbar-bar");
    expect(within(bar).getByTestId("view-switch")).toBeInTheDocument();
    expect(within(bar).getByTestId("toolbar-search")).toBeInTheDocument();
    expect(within(bar).getByTestId("toolbar-filter-trigger")).toBeInTheDocument();
    expect(within(bar).getByTestId("toolbar-sort-trigger")).toBeInTheDocument();
    expect(within(bar).getByTestId("add-menu-trigger")).toBeInTheDocument();
  });
  it("the Yours/Discover switch reflects the active view and both segments are clickable", () => {
    const onSelectView = vi.fn();
    renderToolbar({
      view: "yours",
      onSelectView
    });
    expect(screen.getByTestId("view-toggle-yours")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("view-toggle-discover")).toHaveAttribute("aria-selected", "false");
    fireEvent.click(screen.getByTestId("view-toggle-discover"));
    expect(onSelectView).toHaveBeenCalledWith("discover");
  });
  it("typing in search calls onQueryChange", () => {
    const onQueryChange = vi.fn();
    renderToolbar({
      onQueryChange
    });
    fireEvent.change(screen.getByLabelText("Search"), {
      target: {
        value: "invoice"
      }
    });
    expect(onQueryChange).toHaveBeenCalledWith("invoice");
  });
  it("the filter popover lists categories and trust tiers from config.taxonomy, and checking one both updates state and forces Discover view", () => {
    const onCategoriesChange = vi.fn();
    const onSelectView = vi.fn();
    renderToolbar({
      onCategoriesChange,
      onSelectView,
      view: "yours"
    });
    fireEvent.click(screen.getByTestId("toolbar-filter-trigger"));
    const pop = screen.getByTestId("toolbar-filter-popover");
    expect(within(pop).getByText("productivity")).toBeInTheDocument();
    expect(within(pop).getByText("Community")).toBeInTheDocument();
    fireEvent.click(within(pop).getByText("productivity"));
    expect(onCategoriesChange).toHaveBeenCalledWith(new Set(["productivity"]));
    expect(onSelectView).toHaveBeenCalledWith("discover");
  });
  it("an active filter shows a dot on the filter button", () => {
    renderToolbar({
      categories: new Set(["productivity"])
    });
    expect(screen.getByTestId("toolbar-filter-dot")).toBeInTheDocument();
  });
  it("no active filters means no dot", () => {
    renderToolbar();
    expect(screen.queryByTestId("toolbar-filter-dot")).not.toBeInTheDocument();
  });
  it("the sort popover offers featured/newest/updated/name and reports the active one", () => {
    const onSortChange = vi.fn();
    renderToolbar({
      sort: "name",
      onSortChange
    });
    fireEvent.click(screen.getByTestId("toolbar-sort-trigger"));
    const pop = screen.getByTestId("toolbar-sort-popover");
    expect(screen.getByTestId("toolbar-sort-featured")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-newest")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-updated")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-name")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(pop).getByTestId("toolbar-sort-featured"));
    expect(onSortChange).toHaveBeenCalledWith("featured");
  });

  // Item 2 (M5 UI-polish review, 2026-09-28): Grid/List toggle, originally
  // Yours-only -- this test used to assert "only on Yours... never on
  // Discover (no grid/list choice there)" as a hard invariant. Discover
  // list-view pass (2026-10-05, explicit product ask: "why we dont have
  // list/grid toggle icons views in discover page... go ahead, build it"):
  // that's now a deliberate reversal of the 2026-09-28 decision, not an
  // oversight -- Discover gets the exact same toggle, just gated on its
  // own onDiscoverLayoutChange prop instead of onYoursLayoutChange, so
  // each view keeps its own independent preference (CatalogScreen.tsx's
  // two separate localStorage keys).
  it("hides the toggle on Discover when no onDiscoverLayoutChange is supplied at all (e.g. the coming-soon Toolbar call in MarketplaceScreen.tsx, which passes neither layout handler)", () => {
    const onYoursLayoutChange = vi.fn();
    renderToolbar({
      view: "discover",
      yoursLayout: "grid",
      onYoursLayoutChange
    });
    expect(screen.queryByTestId("yours-layout-toggle")).not.toBeInTheDocument();
  });
  it("shows the toggle on Yours when onYoursLayoutChange is supplied", () => {
    renderToolbar({
      view: "yours",
      yoursLayout: "grid",
      onYoursLayoutChange: vi.fn()
    });
    expect(screen.getByTestId("yours-layout-toggle")).toBeInTheDocument();
  });
  it("shows the toggle on Discover too, once onDiscoverLayoutChange is actually supplied", () => {
    renderToolbar({
      view: "discover",
      discoverLayout: "grid",
      onDiscoverLayoutChange: vi.fn()
    });
    expect(screen.getByTestId("yours-layout-toggle")).toBeInTheDocument();
  });
  it("clicking List/Grid calls onYoursLayoutChange with the selected value, and reflects the current one via aria-pressed", () => {
    const onYoursLayoutChange = vi.fn();
    renderToolbar({
      view: "yours",
      yoursLayout: "grid",
      onYoursLayoutChange
    });
    expect(screen.getByTestId("yours-layout-grid")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("yours-layout-list")).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByTestId("yours-layout-list"));
    expect(onYoursLayoutChange).toHaveBeenCalledWith("list");
  });
  it("on Discover, the toggle drives onDiscoverLayoutChange instead, independent of Yours' own handler", () => {
    const onYoursLayoutChange = vi.fn();
    const onDiscoverLayoutChange = vi.fn();
    renderToolbar({
      view: "discover",
      yoursLayout: "list",
      onYoursLayoutChange,
      discoverLayout: "grid",
      onDiscoverLayoutChange
    });
    expect(screen.getByTestId("yours-layout-grid")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("yours-layout-list"));
    expect(onDiscoverLayoutChange).toHaveBeenCalledWith("list");
    expect(onYoursLayoutChange).not.toHaveBeenCalled();
  });
});