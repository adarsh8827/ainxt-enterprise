// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): an active search/filter (from
// CatalogScreen's Toolbar) switches Discover from the browse-by-category
// layout to a flat "N results" grid + "Clear filters" link, matching the
// reference mock's own discover()/filtered().
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Discover } from "./Discover";
import { MOCK_ITEMS } from "../client/fixtures";

describe("Discover", () => {
  it("with no query/filters, renders the browse-by-category layout", async () => {
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("discover-screen")).toBeInTheDocument());
    expect(screen.getByTestId("discover-screen")).toHaveAttribute("data-discover-mode", "browse");
    expect(screen.queryByTestId("discover-results-count")).not.toBeInTheDocument();
  });

  it("a non-empty query switches to the flat filtered results view", async () => {
    const target = MOCK_ITEMS[0]!;
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query={target.display_name} />);
    await waitFor(() => expect(screen.getByTestId("discover-screen")).toHaveAttribute("data-discover-mode", "filtered"));
    expect(screen.getByTestId("discover-results-count")).toHaveTextContent(/result/);
    expect(screen.getAllByTestId("item-card").length).toBeGreaterThan(0);
  });

  it("an active category filter also switches to the filtered view, even with an empty query", async () => {
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} categories={new Set(["productivity"])} />);
    await waitFor(() => expect(screen.getByTestId("discover-screen")).toHaveAttribute("data-discover-mode", "filtered"));
  });

  it("Clear filters invokes the onClearFilters callback", async () => {
    const onClearFilters = vi.fn();
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="zzz-no-match" onClearFilters={onClearFilters} />);
    await waitFor(() => expect(screen.getByTestId("discover-clear-filters")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("discover-clear-filters"));
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it("a query matching nothing shows a no-matches message instead of an empty grid", async () => {
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="zzz-no-match-anywhere" />);
    await waitFor(() => expect(screen.getByTestId("discover-results-count")).toHaveTextContent("0 results"));
    expect(screen.getByText(/No skills match/)).toBeInTheDocument();
  });
});
