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
import { MOCK_CONFIG, MOCK_ITEMS, MOCK_LIVE_SEARCH_RESULTS } from "../client/fixtures";
import { MockEcosystemClient } from "../client/MockEcosystemClient";
import { EcosystemApiError } from "../client/EcosystemClient";
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

  it("renders connector AND mcp_server items via ConnectorCard, not the install-state Card (Stage 3 fix)", async () => {
    // Real gap found during Stage 3 review: this branch used to check only
    // item_type === "connector", so an mcp_server item (which carries the
    // same ConnectionStatus semantics, not install state) fell through to
    // the plain install-state <Card> instead.
    const connectorItem: ItemSummary = { ...MOCK_ITEMS[0]!, id: "conn-1", item_type: "connector" };
    const mcpServerItem: ItemSummary = { ...MOCK_ITEMS[0]!, id: "mcp-1", item_type: "mcp_server" };
    const listItemsWithEtag = vi.fn().mockResolvedValue({
      data: { items: [connectorItem, mcpServerItem], next_cursor: null, total_hint: 2 }, etag: "e1", notModified: false,
    });
    // ConnectorCard fetches connection status on mount (listConnections) --
    // a bare { listItemsWithEtag } fake (fine for the plain <Card> path)
    // throws "not a function" here, so this test needs the fuller shape.
    const client = { listItemsWithEtag, listConnections: vi.fn().mockResolvedValue([]) } as unknown as EcosystemClient;

    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/connectors", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="connector" onOpen={() => {}} query="anything" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );

    await waitFor(() => expect(screen.getAllByTestId("connector-card")).toHaveLength(2));
    expect(screen.queryAllByTestId("item-card")).toHaveLength(0);
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

  it("install-state-consistency round (2026-09-29): a real ecosystem.changed event (client.streamChanges) triggers a background refetch -- the cross-tab half of the fix", async () => {
    const client = new MockEcosystemClient();
    const spy = vi.spyOn(client, "listItemsWithEtag");
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    // Simulates another browser tab's own mutation landing on the real
    // per-org Redis ecosystem.changed channel -- this tab's own
    // subscription (client.streamChanges()) is what has to notice it;
    // nothing else connects two separate tabs to each other.
    client.emitChangeEvent();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("a client that doesn't implement streamChanges (an ad-hoc test/host client) never crashes Discover -- it's optional", async () => {
    const listItemsWithEtag = vi.fn().mockResolvedValue({
      data: { items: [], next_cursor: null, total_hint: 0 }, etag: "e1", notModified: false,
    });
    const client = { listItemsWithEtag } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("discover-empty-state")).toBeInTheDocument());
  });
});

// Discover "From the web" section (docs/ecosystem/design/CHANGELOG.md's
// live-search round; docs/ecosystem/TESTING_GUIDE.md §6o). MOCK_CONFIG has
// live_search_enabled: true by default -- tests covering the disabled
// case override it explicitly.
describe("Discover 'From the web' section", () => {
  it("does not render at all when live search is disabled for the org, even with a real query", async () => {
    renderWithHost(
      <Discover itemType="skill" onOpen={() => {}} query="scraper" />,
      { clientOptions: { config: { ...MOCK_CONFIG, live_search_enabled: false } } },
    );
    await waitFor(() => expect(screen.getByTestId("discover-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("from-the-web-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("from-the-web-loading")).not.toBeInTheDocument();
  });

  it("renders nothing for a blank query even when live search is enabled -- no section, no empty-results message", async () => {
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("discover-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("from-the-web-section")).not.toBeInTheDocument();
  });

  it("a burst of query changes (fast typing) collapses into exactly one debounced call, carrying only the final value", async () => {
    const searchSpy = vi.spyOn(MockEcosystemClient.prototype, "searchLive").mockResolvedValue({ results: [] });
    const client = new MockEcosystemClient();
    const tree = (query: string) => (
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Discover itemType="skill" onOpen={() => {}} query={query} />
        </EcosystemConfigProvider>
      </HostProvider>
    );
    const { rerender } = render(tree("s"));

    // Simulates fast typing -- a burst of query changes must collapse into
    // exactly one call, carrying only the FINAL value, same "debounced,
    // not fired per keystroke" guarantee the focus-refresh test above
    // proves for its own debounce.
    rerender(tree("sc"));
    rerender(tree("scr"));
    rerender(tree("scraper"));
    expect(searchSpy).not.toHaveBeenCalled();

    await waitFor(() => expect(searchSpy).toHaveBeenCalledTimes(1), { timeout: 2000, interval: 50 });
    expect(searchSpy).toHaveBeenCalledWith("scraper");
  });

  it("results render using real license badges from the response", async () => {
    vi.spyOn(MockEcosystemClient.prototype, "searchLive").mockResolvedValue({ results: MOCK_LIVE_SEARCH_RESULTS });
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="tools" />);

    await waitFor(() => expect(screen.getByTestId("from-the-web-section")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByTestId("live-search-card").length).toBe(MOCK_LIVE_SEARCH_RESULTS.length));
    const badges = screen.getAllByTestId("license-badge");
    const spdxValues = badges.map((b) => b.getAttribute("data-spdx"));
    expect(spdxValues).toEqual(expect.arrayContaining(MOCK_LIVE_SEARCH_RESULTS.map((r) => r.license_spdx)));
  });

  it("a query matching nothing from the web shows a real 'no matches' message, not a blank silent gap", async () => {
    vi.spyOn(MockEcosystemClient.prototype, "searchLive").mockResolvedValue({ results: [] });
    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="zzz-nothing-from-the-web" />);

    await waitFor(() => expect(screen.getByTestId("from-the-web-section")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("from-the-web-empty")).toBeInTheDocument());
    expect(screen.queryByTestId("live-search-card")).not.toBeInTheDocument();
  });

  it("+ Add reuses the existing createItem import call and reports a real 422 NEUTRALITY_VIOLATION rejection", async () => {
    const result = MOCK_LIVE_SEARCH_RESULTS[0]!;
    vi.spyOn(MockEcosystemClient.prototype, "searchLive").mockResolvedValue({ results: [result] });
    const createSpy = vi.spyOn(MockEcosystemClient.prototype, "createItem").mockRejectedValueOnce(
      new EcosystemApiError("NEUTRALITY_VIOLATION", "This skill's content names a specific AI vendor.", false),
    );

    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="tools" />);
    await waitFor(() => expect(screen.getByTestId("live-search-card")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("live-search-add"));

    expect(createSpy).toHaveBeenCalled();
    // The exact create_via="import" reuse contract this whole feature
    // depends on -- not a fabricated/short-circuited install path.
    const [payload] = createSpy.mock.calls[0]!;
    expect(payload).toMatchObject({
      create_via: "import", item_type: "skill", namespace: result.namespace,
      kind: result.source_kind, ref: result.ref,
    });

    await waitFor(() => expect(screen.getByTestId("live-search-error")).toBeInTheDocument());
    expect(screen.getByTestId("live-search-error")).toHaveTextContent(/vendor-neutral/i);
    // Never silently swallowed -- the "+ Add" button itself reflects the
    // failure (becomes "Retry"), not a card that just looks like nothing
    // happened.
    expect(screen.getByTestId("live-search-add")).toHaveTextContent(/Retry/);
  });

  it("+ Add succeeds and shows Added, reusing the same createItem call a manual Import-from-URL uses", async () => {
    const result = MOCK_LIVE_SEARCH_RESULTS[1]!;
    vi.spyOn(MockEcosystemClient.prototype, "searchLive").mockResolvedValue({ results: [result] });
    const createSpy = vi.spyOn(MockEcosystemClient.prototype, "createItem").mockResolvedValueOnce(
      { item_id: "item-live-1", version_id: "v1", gate_run_id: "g1", status: "verifying", provision_scope: "private" },
    );

    renderWithHost(<Discover itemType="skill" onOpen={() => {}} query="pdf" />);
    await waitFor(() => expect(screen.getByTestId("live-search-card")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("live-search-add"));

    await waitFor(() => expect(screen.getByTestId("live-search-added")).toBeInTheDocument());
    expect(createSpy).toHaveBeenCalledTimes(1);
  });
});
