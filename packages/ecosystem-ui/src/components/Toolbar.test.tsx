// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): the catalog list page's header row --
// title, type tabs, Yours/Discover switch, search, filter, sort, "+ Add"
// all present in one row (docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html's
// own header()), plus the filter/sort popovers' own behavior.
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, within } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Toolbar } from "./Toolbar";
import type { TrustTier } from "../types";

function renderToolbar(overrides: Partial<Parameters<typeof Toolbar>[0]> = {}) {
  const props = {
    activeSlug: "skills",
    onSelectType: vi.fn(),
    view: "discover" as const,
    onSelectView: vi.fn(),
    query: "",
    onQueryChange: vi.fn(),
    categories: new Set<string>(),
    onCategoriesChange: vi.fn(),
    trust: new Set<TrustTier>(),
    onTrustChange: vi.fn(),
    sort: "featured" as const,
    onSortChange: vi.fn(),
    onSelectCreateAction: vi.fn(),
    ...overrides,
  };
  return { ...renderWithHost(<Toolbar {...props} />), props };
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
    renderToolbar({ view: "yours", onSelectView });
    expect(screen.getByTestId("view-toggle-yours")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("view-toggle-discover")).toHaveAttribute("aria-selected", "false");
    fireEvent.click(screen.getByTestId("view-toggle-discover"));
    expect(onSelectView).toHaveBeenCalledWith("discover");
  });

  it("typing in search calls onQueryChange", () => {
    const onQueryChange = vi.fn();
    renderToolbar({ onQueryChange });
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "invoice" } });
    expect(onQueryChange).toHaveBeenCalledWith("invoice");
  });

  it("the filter popover lists categories and trust tiers from config.taxonomy, and checking one both updates state and forces Discover view", () => {
    const onCategoriesChange = vi.fn();
    const onSelectView = vi.fn();
    renderToolbar({ onCategoriesChange, onSelectView, view: "yours" });
    fireEvent.click(screen.getByTestId("toolbar-filter-trigger"));
    const pop = screen.getByTestId("toolbar-filter-popover");
    expect(within(pop).getByText("productivity")).toBeInTheDocument();
    expect(within(pop).getByText("Community")).toBeInTheDocument();
    fireEvent.click(within(pop).getByText("productivity"));
    expect(onCategoriesChange).toHaveBeenCalledWith(new Set(["productivity"]));
    expect(onSelectView).toHaveBeenCalledWith("discover");
  });

  it("an active filter shows a dot on the filter button", () => {
    renderToolbar({ categories: new Set(["productivity"]) });
    expect(screen.getByTestId("toolbar-filter-dot")).toBeInTheDocument();
  });

  it("no active filters means no dot", () => {
    renderToolbar();
    expect(screen.queryByTestId("toolbar-filter-dot")).not.toBeInTheDocument();
  });

  it("the sort popover offers featured/newest/updated/name and reports the active one", () => {
    const onSortChange = vi.fn();
    renderToolbar({ sort: "name", onSortChange });
    fireEvent.click(screen.getByTestId("toolbar-sort-trigger"));
    const pop = screen.getByTestId("toolbar-sort-popover");
    expect(screen.getByTestId("toolbar-sort-featured")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-newest")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-updated")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-sort-name")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(pop).getByTestId("toolbar-sort-featured"));
    expect(onSortChange).toHaveBeenCalledWith("featured");
  });

  // Item 2 (M5 UI-polish review): Grid/List toggle -- only on Yours, next
  // to sort/filter, never on Discover (no grid/list choice there).
  it("shows the Grid/List toggle only when view is yours, not discover", () => {
    const onYoursLayoutChange = vi.fn();
    renderToolbar({ view: "discover", yoursLayout: "grid", onYoursLayoutChange });
    expect(screen.queryByTestId("yours-layout-toggle")).not.toBeInTheDocument();

    renderToolbar({ view: "yours", yoursLayout: "grid", onYoursLayoutChange });
    expect(screen.getByTestId("yours-layout-toggle")).toBeInTheDocument();
  });

  it("clicking List/Grid calls onYoursLayoutChange with the selected value, and reflects the current one via aria-pressed", () => {
    const onYoursLayoutChange = vi.fn();
    renderToolbar({ view: "yours", yoursLayout: "grid", onYoursLayoutChange });
    expect(screen.getByTestId("yours-layout-grid")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("yours-layout-list")).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByTestId("yours-layout-list"));
    expect(onYoursLayoutChange).toHaveBeenCalledWith("list");
  });
});
