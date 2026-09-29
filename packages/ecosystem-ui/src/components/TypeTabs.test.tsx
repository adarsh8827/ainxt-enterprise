// SPDX-License-Identifier: MIT
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// the mandatory regression test -- an org/host that doesn't pass
// collapseConnectorsAdvanced must see EXACTLY today's 4-separate-tabs
// behavior, unchanged.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { TypeTabs } from "./TypeTabs";

describe("TypeTabs", () => {
  it("REGRESSION: renders all 4 separate tabs and no Advanced control when collapseConnectorsAdvanced is omitted", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} />);
    expect(screen.getByTestId("type-tab-skills")).toBeInTheDocument();
    expect(screen.getByTestId("type-tab-plugins")).toBeInTheDocument();
    expect(screen.getByTestId("type-tab-connectors")).toBeInTheDocument();
    expect(screen.getByTestId("type-tab-mcp")).toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
  });

  it("collapses the mcp tab away and shows Advanced only when opted in and Connectors is active", () => {
    renderWithHost(<TypeTabs activeSlug="connectors" onSelect={() => {}} collapseConnectorsAdvanced onSelectAdvanced={() => {}} />);
    expect(screen.getByTestId("type-tab-connectors")).toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.getByTestId("type-tab-advanced-mcp")).toBeInTheDocument();
  });

  it("does not show Advanced when opted in but a different tab is active", () => {
    renderWithHost(<TypeTabs activeSlug="skills" onSelect={() => {}} collapseConnectorsAdvanced onSelectAdvanced={() => {}} />);
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
  });

  it("toggles advancedActive via onSelectAdvanced when clicked", () => {
    const onSelectAdvanced = vi.fn();
    renderWithHost(<TypeTabs activeSlug="connectors" onSelect={() => {}} collapseConnectorsAdvanced advancedActive={false} onSelectAdvanced={onSelectAdvanced} />);
    fireEvent.click(screen.getByTestId("type-tab-advanced-mcp"));
    expect(onSelectAdvanced).toHaveBeenCalledWith(true);
  });
});
