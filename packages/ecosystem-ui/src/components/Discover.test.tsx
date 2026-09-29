// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): an active search/filter (from
// CatalogScreen's Toolbar) switches Discover from the browse-by-category
// layout to a flat "N results" grid + "Clear filters" link, matching the
// reference mock's own discover()/filtered().
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Discover } from "./Discover";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_ITEMS } from "../client/fixtures";
import { LIGHT_TOKENS } from "../theme";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { ItemSummary } from "../types";

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

  it("polls and picks up a resolved verdict for a just-installed item without any user action (item 7 fix)", async () => {
    const pendingItem: ItemSummary = { ...MOCK_ITEMS[0]!, install_id: "install-poll-1", latest_verdict: "pending" };
    const resolvedItem: ItemSummary = { ...pendingItem, latest_verdict: "pass" };
    const listItems = vi.fn()
      .mockResolvedValueOnce({ items: [pendingItem], next_cursor: null, total_hint: 1 })
      .mockResolvedValueOnce({ items: [resolvedItem], next_cursor: null, total_hint: 1 });
    const client = { listItems } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    await waitFor(() => expect(listItems).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("verdict-badge")).toHaveAttribute("data-verdict", "pending"));

    // Real timers -- POLL_INTERVAL_MS (2000ms) elapses for real rather than
    // fighting vitest's fake-timer/RTL-waitFor interaction (both poll via
    // the same faked setInterval, which deadlocks if faked here too).
    await waitFor(() => expect(listItems).toHaveBeenCalledTimes(2), { timeout: 4000, interval: 100 });
    await waitFor(() => expect(screen.getByTestId("verdict-badge")).toHaveAttribute("data-verdict", "pass"));
  }, 8000);
});
