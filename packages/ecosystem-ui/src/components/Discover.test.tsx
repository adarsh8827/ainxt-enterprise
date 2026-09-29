// SPDX-License-Identifier: MIT
// Task item 1 (M5 UI-parity review): an active search/filter (from
// CatalogScreen's Toolbar) switches Discover from the browse-by-category
// layout to a flat "N results" grid + "Clear filters" link, matching the
// reference mock's own discover()/filtered().
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Discover } from "./Discover";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_ITEMS } from "../client/fixtures";
import { LIGHT_TOKENS } from "../theme";
import { __resetCatalogCacheForTests, discoverCacheKey, setDiscoverCache } from "../catalogCache";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { ItemSummary } from "../types";

// Item (d) (2026-09-29 live-test round): catalogCache.ts is a module-level
// store, deliberately outside any one component's lifecycle (so it
// survives a real Discover<->Yours unmount/remount) -- which also means
// its module registry is shared across every `it()` block in this file,
// same reason installTracking.ts's own tests reset themselves.
afterEach(() => __resetCatalogCacheForTests());

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
    // Item (d), part 2: Discover.tsx now calls listItemsWithEtag exclusively
    // (never bare listItems) -- both responses are real 200s (notModified:
    // false) here, since the verdict genuinely changed between polls.
    const listItemsWithEtag = vi.fn()
      .mockResolvedValueOnce({ data: { items: [pendingItem], next_cursor: null, total_hint: 1 }, etag: "etag-1", notModified: false })
      .mockResolvedValueOnce({ data: { items: [resolvedItem], next_cursor: null, total_hint: 1 }, etag: "etag-2", notModified: false });
    const client = { listItemsWithEtag } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    await waitFor(() => expect(listItemsWithEtag).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("verdict-badge")).toHaveAttribute("data-verdict", "pending"));

    // Real timers -- POLL_INTERVAL_MS (2000ms) elapses for real rather than
    // fighting vitest's fake-timer/RTL-waitFor interaction (both poll via
    // the same faked setInterval, which deadlocks if faked here too).
    await waitFor(() => expect(listItemsWithEtag).toHaveBeenCalledTimes(2), { timeout: 4000, interval: 100 });
    await waitFor(() => expect(screen.getByTestId("verdict-badge")).toHaveAttribute("data-verdict", "pass"));
    // The second call carries the first response's own ETag as If-None-Match.
    expect(listItemsWithEtag.mock.calls[1]![1]).toBe("etag-1");
  }, 8000);

  // Item (d), part 3 (2026-09-29 live-test round): a genuine first load
  // (no cache entry at all for this key) must show real skeleton card
  // shapes, not the old "Verifying…"/generic-string loading indicator.
  it("a genuine first load with no cached data shows skeleton cards, not a text status", async () => {
    let resolveList!: (v: { data: unknown; etag: string | null; notModified: boolean }) => void;
    const listItemsWithEtag = vi.fn(() => new Promise<{ data: unknown; etag: string | null; notModified: boolean }>((resolve) => { resolveList = resolve; }));
    const client = { listItemsWithEtag } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    expect(screen.getByTestId("discover-loading")).toBeInTheDocument();
    expect(screen.getByTestId("discover-skeleton")).toBeInTheDocument();
    expect(screen.getAllByTestId("card-skeleton").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Verifying/i)).not.toBeInTheDocument();

    resolveList({ data: { items: [], next_cursor: null, total_hint: 0 }, etag: "etag-empty", notModified: false });
    await waitFor(() => expect(screen.getByTestId("discover-empty-state")).toBeInTheDocument());
  });

  // Item (d), part 1: a view (itemType+filters combo) already cached from
  // an earlier mount shows its last-known data on the VERY FIRST render --
  // no null-items window, so the skeleton branch is never reached at all.
  it("a previously-cached view renders its last-known items instantly, with no skeleton flash, on remount", async () => {
    const cachedItem: ItemSummary = { ...MOCK_ITEMS[0]!, id: "cached-item-1" };
    setDiscoverCache(discoverCacheKey("skill", "", "featured", [], []), { items: [cachedItem], etag: "cached-etag" });
    const listItemsWithEtag = vi.fn(() => new Promise(() => {})); // never resolves -- proves the cache alone renders it
    const client = { listItemsWithEtag } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    // Synchronous -- no waitFor needed; if this ever needed a tick, the
    // cache-seeding effect would have regressed into a null-then-fetch flash.
    expect(screen.queryByTestId("discover-loading")).not.toBeInTheDocument();
    expect(screen.getByTestId("item-card")).toBeInTheDocument();
    // The background refresh was still fired, carrying the cached ETag.
    expect(listItemsWithEtag).toHaveBeenCalledWith(expect.anything(), "cached-etag");
  });

  // Item (d), part 2: a 304 (notModified: true) must never overwrite the
  // cached/on-screen data, even with a `data` field a careless caller
  // might otherwise read.
  it("a 304 (notModified) response never replaces the cached items", async () => {
    const cachedItem: ItemSummary = { ...MOCK_ITEMS[0]!, id: "stays-the-same" };
    setDiscoverCache(discoverCacheKey("skill", "", "featured", [], []), { items: [cachedItem], etag: "same-etag" });
    const listItemsWithEtag = vi.fn().mockResolvedValue({ data: null, etag: "same-etag", notModified: true });
    const client = { listItemsWithEtag } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    await waitFor(() => expect(listItemsWithEtag).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("item-card")).toHaveAttribute("data-item-id", "stays-the-same");
  });

  // Item (d), part 2: a real `window.focus` (this package's own reuse of
  // ai-ui/src/components/Connectors.jsx's existing "refetch on focus,
  // debounced" convention) triggers a background refresh -- debounced, so
  // a burst of focus events collapses into exactly one refetch, and never
  // clears the on-screen items while it's in flight.
  it("a window focus event triggers a debounced background refresh without clearing on-screen items", async () => {
    const item: ItemSummary = { ...MOCK_ITEMS[0]!, id: "focus-refresh-item" };
    const listItemsWithEtag = vi.fn().mockResolvedValue({
      data: { items: [item], next_cursor: null, total_hint: 1 }, etag: "etag-1", notModified: false,
    });
    const client = { listItemsWithEtag } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    await waitFor(() => expect(listItemsWithEtag).toHaveBeenCalledTimes(1));

    // A burst of focus events -- must still collapse into one refetch.
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));

    // Real timers -- the 1500ms debounce elapses for real, same convention
    // as the polling test above.
    await waitFor(() => expect(listItemsWithEtag).toHaveBeenCalledTimes(2), { timeout: 4000, interval: 100 });
    // Never cleared while the refetch was in flight or after it resolved.
    expect(screen.getByTestId("item-card")).toBeInTheDocument();
  }, 8000);
});
