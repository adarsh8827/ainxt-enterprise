// SPDX-License-Identifier: MIT
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// mcp_server is ALWAYS merged into Connectors -- no caller ever sees a
// standalone "MCP servers" tab, matching the reference design's fixed
// 3-tab shell (Skills · Connectors · Plugins). Real gap found and fixed
// 2026-09-30 after a live user report: the FIRST cut of this made the
// merge itself conditional on showAdvancedToggle, so a non-admin caller
// fell back to the old 4-tab layout including a bare "MCP servers" tab.
// Only the "Advanced" TOGGLE BUTTON inside Connectors is admin-gated now.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithHost } from "./test-utils";
import { TypeTabs } from "@marketplace/TypeTabs";
describe("TypeTabs", () => {
  it("REGRESSION: mcp_server is never a standalone tab, even for a caller with no Advanced access", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} hiddenTypes={[]} />);
    expect(screen.getByTestId("type-tab-skills")).toBeInTheDocument();
    expect(screen.getByTestId("type-tab-plugins")).toBeInTheDocument();
    expect(screen.getByTestId("type-tab-connectors")).toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
  });
  it("shows Advanced only when opted in and Connectors is active", () => {
    renderWithHost(<TypeTabs activeSlug="connectors" onSelect={() => {}} showAdvancedToggle onSelectAdvanced={() => {}} hiddenTypes={[]} />);
    expect(screen.getByTestId("type-tab-connectors")).toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.getByTestId("type-tab-advanced-mcp")).toBeInTheDocument();
  });
  it("does not show Advanced when opted in but a different tab is active", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} showAdvancedToggle onSelectAdvanced={() => {}} hiddenTypes={[]} />);
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
  });
  it("toggles advancedActive via onSelectAdvanced when clicked", () => {
    const onSelectAdvanced = vi.fn();
    renderWithHost(<TypeTabs activeSlug="connectors" onSelect={() => {}} showAdvancedToggle advancedActive={false} onSelectAdvanced={onSelectAdvanced} hiddenTypes={[]} />);
    fireEvent.click(screen.getByTestId("type-tab-advanced-mcp"));
    expect(onSelectAdvanced).toHaveBeenCalledWith(true);
  });

  // UI polish (2026-10-05, explicit product ask): Plugins/Connectors aren't
  // fully implemented yet -- hidden from the tab bar BY DEFAULT (no prop
  // needed from any real caller, e.g. Toolbar.jsx passes none today), while
  // every test above proves the underlying tab/Advanced-toggle code this
  // hides is still fully intact and correct, via an explicit `hiddenTypes={[]}`
  // override. Not a removal -- config.item_types, the routing under
  // CatalogScreen.jsx, and AddMenu.jsx's own "Coming soon" entries for both
  // are all untouched; only this tab bar's default rendering changed.
  it("REGRESSION: Plugins and Connectors are hidden from the tab bar by default", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} />);
    expect(screen.getByTestId("type-tab-skills")).toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-plugins")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-connectors")).not.toBeInTheDocument();
  });
  it("a caller can still opt back in via hiddenTypes, e.g. to re-expose just one tab", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} hiddenTypes={["plugin"]} />);
    expect(screen.queryByTestId("type-tab-plugins")).not.toBeInTheDocument();
    expect(screen.getByTestId("type-tab-connectors")).toBeInTheDocument();
  });
});