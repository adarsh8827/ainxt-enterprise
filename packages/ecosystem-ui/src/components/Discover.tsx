// SPDX-License-Identifier: MIT
// Task F-5 + item 1 (M5 UI-parity review): full Discover screen --
// GET /ecosystem/items, grouped by category (config-driven order, never
// hardcoded), with a featured banner. When CatalogScreen's Toolbar has an
// active search/filter, this instead renders a flat "N results" grid +
// "Clear filters" link, matching the reference mock's own discover()/
// filtered() (a search or filter always means "show me a flat result set",
// never the browse-by-category layout).
import { useEffect, useState } from "react";
import type { ItemSummary, ItemType, ListItemsParams, LiveSearchResult, TrustTier } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { FeaturedBanner } from "./FeaturedBanner";
import { CategorySection } from "./CategorySection";
import { Card } from "./Card";
import { ConnectorCard } from "./Connectors/ConnectorCard";
import { LiveSearchResultCard } from "./LiveSearchResultCard";
import { DiscoverSkeleton } from "./Skeleton";
import { discoverCacheKey, getDiscoverCache, setDiscoverCache } from "../catalogCache";

// Item 7 (tab-switch report): a just-added catalog item can still be
// mid-gate when this list is first refetched (the async gate path --
// materialize_from_catalog()'s own "about a second" fast path is already
// resolved by the time the response comes back, this only matters for the
// slower, worker-resolved case). Without this, the grid never looked
// again and a resolved item stayed stuck on "Verifying" until a manual
// reload -- same POLL_INTERVAL_MS convention as detail/Verification.tsx.
const POLL_INTERVAL_MS = 2000;

// Item (d), part 1/2 (2026-09-29 live-test round): "keep data in memory on
// tab switch, background refresh with ETag." Real bug, disclosed and left
// for later in the tab-switch round's own fix (HostContext.tsx's
// DEFAULT_STRINGS comment, "Not built this pass: a session-level cache so
// switching tabs shows the previously-loaded list instantly"): this is
// that follow-up. catalogCache.ts holds the last-known items + ETag for
// each itemType/query/sort/filter combination, keyed OUTSIDE this
// component's own lifecycle (CatalogScreen.tsx unmounts this whole
// component switching to Yours, same as before) -- a returning caller
// seeds its `items` state from the cache synchronously, on the very first
// render, so there is no null-items window (no skeleton, no flash) for
// anything already seen this session. `listItemsWithEtag` always still
// fires in the background: it sends the cached ETag as If-None-Match and
// only replaces `items` (and the cache entry) on a real 200 -- a 304
// leaves both alone.
//
// "Background refresh on remount" already covers a tab switch and normal
// navigation; window-focus/visibility is the other trigger this package's
// host (ai-ui) already uses elsewhere for exactly this kind of "did
// anything change while I was away" refresh (ai-ui/src/components/
// Connectors.jsx's own onFocus/visibilitychange handler, debounced) --
// reused here rather than inventing a different convention.
const FOCUS_REFRESH_DEBOUNCE_MS = 1500;

// Discover "From the web" section (external sources plan §10;
// docs/ecosystem/design/CHANGELOG.md's live-search round): debounces the
// SAME query the existing Toolbar search box already drives (no second
// input) before hitting GET /ecosystem/search/live -- this file's own
// existing convention for a debounced re-fetch is the setTimeout guard
// above (FOCUS_REFRESH_DEBOUNCE_MS), reused here for "debounce typing"
// rather than "debounce a burst of focus events." No dedicated debounce
// hook exists anywhere in this package to reuse instead.
const LIVE_SEARCH_DEBOUNCE_MS = 400;

/** Independent of the local-catalog fetch above (own loading/error state,
 * own data source) -- rendered unconditionally alongside whichever of
 * Discover's own branches (loading/error/filtered/empty/browse) is
 * showing, never gated on the local catalog's own state. */
function FromTheWebSection({ query, itemType }: { query: string; itemType: ItemType }) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [results, setResults] = useState<LiveSearchResult[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const trimmed = query.trim();

  useEffect(() => {
    if (!config.live_search_enabled) return;
    // A blank query never hits the backend at all (matches
    // live_search_service.py's own "blank query returns [] immediately"
    // contract) -- nothing to debounce or show yet.
    if (!trimmed) {
      setResults(null);
      setError(null);
      return;
    }
    let cancelled = false;
    const debounce = setTimeout(() => {
      client.searchLive(trimmed)
        .then((res) => { if (!cancelled) { setResults(res.results); setError(null); } })
        .catch((e: unknown) => { if (!cancelled) setError(e); });
    }, LIVE_SEARCH_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(debounce); };
  }, [client, config.live_search_enabled, trimmed]);

  // Off unless BOTH gates are true (config.live_search_enabled is already
  // the combined signal, config_service.py's get_effective_config()) --
  // the section simply doesn't render at all, never a disabled/greyed-out
  // state, matching the backend's own design.
  if (!config.live_search_enabled) return null;
  // A blank query shows nothing -- not an empty-results message for a
  // query the user hasn't typed yet.
  if (!trimmed) return null;

  return (
    <div data-testid="from-the-web-section" style={{ marginBottom: "var(--eco-space-lg)" }}>
      <h3 style={{ margin: "0 0 var(--eco-space-sm) 0", fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>
        From the web
      </h3>
      {error ? (
        <p data-testid="from-the-web-error" role="alert" style={{ color: "var(--eco-color-textMuted)", margin: 0 }}>
          Couldn't search the web right now.
        </p>
      ) : results === null ? (
        <div data-testid="from-the-web-loading" role="status" aria-label="Searching the web">
          Searching the web…
        </div>
      ) : results.length === 0 ? (
        <p data-testid="from-the-web-empty" style={{ color: "var(--eco-color-textMuted)", margin: 0 }}>
          No matches from the web.
        </p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
          {results.map((r) => <LiveSearchResultCard key={r.namespace} result={r} itemType={itemType} />)}
        </div>
      )}
    </div>
  );
}

export function Discover({ itemType, onOpen, query = "", categories, trust, sort = "featured", onClearFilters }: {
  itemType: ItemType;
  onOpen: (item: ItemSummary) => void;
  query?: string;
  categories?: Set<string>;
  trust?: Set<TrustTier>;
  sort?: NonNullable<ListItemsParams["sort"]>;
  onClearFilters?: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const strings = useI18n();
  const [items, setItems] = useState<ItemSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  // Bumped by a card's own quick-add so the grid picks up its new
  // install_id/"Added" state without a full page reload, by the
  // poll-while-verifying effect below, and by the focus-refresh effect
  // further down. None of these need to null `items` anymore (see the
  // cache-seeding effect below) -- a bump just re-runs the same fetch,
  // which now always finds either the cache or the just-displayed items
  // already on screen to fall back to while it resolves.
  const [refreshKey, setRefreshKey] = useState(0);
  const onInstalled = () => setRefreshKey((k) => k + 1);

  const categoryList = categories ? [...categories] : [];
  const trustList = trust ? [...trust] : [];
  const categoryKey = categoryList.join(",");
  const trustKey = trustList.join(",");
  const hasFilters = Boolean(query.trim()) || categoryList.length > 0 || trustList.length > 0;
  const cacheKey = discoverCacheKey(itemType, query, sort, categoryList, trustList);

  useEffect(() => {
    let cancelled = false;
    let pollTimeout: ReturnType<typeof setTimeout> | null = null;

    // Item (d), part 1: a previously-seen view (same itemType/query/sort/
    // filters) shows its last-known data INSTANTLY here, synchronously
    // with this effect running -- no null-items window, so the skeleton
    // branch below never renders for it. A key this session has never
    // seen (a brand-new filter combo, or the very first load) has no
    // cache entry, and genuinely has nothing to show yet -- `items` stays
    // (or becomes) null, which is exactly the signal the skeleton branch
    // below is looking for.
    const cached = getDiscoverCache(cacheKey);
    if (cached) {
      setItems(cached.items);
      setError(null);
    } else {
      setItems(null);
      setError(null);
    }

    // Item (d), part 2: the previously-cached ETag (null on a genuine
    // first load, in which case this is just a normal GET) rides along
    // as If-None-Match -- routers/ecosystem_router.py's list_items()
    // already honors it with a real 304. `data` is null exactly when
    // `notModified` is true; `items`/the cache are only ever touched on
    // an actual 200, never on a 304.
    client.listItemsWithEtag(
      {
        item_type: itemType,
        limit: 200,
        sort,
        q: query.trim() || undefined,
        category: categoryList.length ? categoryList : undefined,
        trust: trustList.length ? trustList : undefined,
      },
      cached?.etag ?? null,
    )
      .then((res) => {
        if (cancelled) return;
        // Only ever an item this caller has actually installed (install_id
        // set) -- a not-yet-added catalog item's own "pending"-looking
        // state is a different thing entirely (catalogState.ts's
        // isNotYetAddedCatalogItem(), never mistaken for "verifying" by
        // Card.tsx already) and must never keep this poll alive.
        const schedulePollIfVerifying = (checkItems: ItemSummary[]) => {
          const stillVerifying = checkItems.some((item) => item.install_id && item.latest_verdict === "pending");
          if (stillVerifying) {
            pollTimeout = setTimeout(() => { if (!cancelled) setRefreshKey((k) => k + 1); }, POLL_INTERVAL_MS);
          }
        };
        const data = res.data;
        if (res.notModified || !data) {
          // Genuinely unchanged -- whatever's already on screen (the cache
          // we just seeded, or this same fetch's own previous resolution)
          // stays exactly as is. Still need to keep polling if the cached
          // copy itself has a pending verdict -- the server saying
          // "nothing changed" doesn't mean it never will.
          schedulePollIfVerifying(cached?.items ?? []);
          return;
        }
        setItems(data.items);
        setError(null);
        setDiscoverCache(cacheKey, { items: data.items, etag: res.etag });
        schedulePollIfVerifying(data.items);
      })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => {
      cancelled = true;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, cacheKey, itemType, query, sort, categoryKey, trustKey, refreshKey]);

  // Item (d), part 2 (continued): "background refresh... on window focus"
  // -- ai-ui/src/components/Connectors.jsx's own existing convention
  // (focus + visibilitychange, debounced) reused here rather than a new
  // one invented for this screen. This never nulls `items` itself; it
  // just bumps refreshKey, which the effect above already treats as "the
  // cache/on-screen data stays, the fetch above just runs again."
  useEffect(() => {
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const onFocus = () => {
      if (debounce) return;
      debounce = setTimeout(() => { debounce = null; setRefreshKey((k) => k + 1); }, FOCUS_REFRESH_DEBOUNCE_MS);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      if (debounce) clearTimeout(debounce);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, []);

  // Install-state-consistency round (2026-09-29): the real, already-
  // existing per-org ecosystem.changed SSE stream (client.streamChanges(),
  // routers/ecosystem_events_router.py) is what covers a mutation made in
  // a DIFFERENT browser tab -- this module's own installStore.ts is
  // per-tab, in-memory only, so it can't see a change another tab made.
  // Same-tab changes (Yours/Detail/another Card on this same page) are
  // already covered instantly by installStore's own subscription
  // (applyInstallOverride below); this is specifically the cross-tab half.
  useEffect(() => {
    return client.streamChanges?.(() => setRefreshKey((k) => k + 1));
  }, [client]);

  // Discover "From the web" section: an entirely independent data source
  // from the local-catalog `items` state above (own loading/error state),
  // so it renders alongside whichever local-catalog branch below is
  // showing -- never gated on the local catalog's own loading/error/
  // empty state.
  const fromTheWeb = <FromTheWebSection query={query} itemType={itemType} />;

  if (error) {
    return (
      <>
        {fromTheWeb}
        <div data-testid="discover-error" role="alert">Couldn't load the catalog. Please try again.</div>
      </>
    );
  }
  if (items === null) {
    // Real bug found live, fixed in an earlier round: this used to render
    // `strings.verifying` ("Verifying…") as the generic "list hasn't
    // loaded yet" indicator -- a page-level loading state must never read
    // as a claim about any item's own gate status (HostContext.tsx's own
    // DEFAULT_STRINGS comment). Item (d), part 3 (this round): that fixed
    // string is itself replaced with real skeleton card shapes -- this
    // branch is now ONLY reached on a genuine first load with no cached
    // data at all (the effect above seeds `items` from catalogCache.ts
    // synchronously whenever a cache entry exists), so a skeleton here
    // never flashes over a returning caller's already-known data.
    // `role="status"`/`aria-label` keeps a real "Loading…" announcement
    // for assistive tech even though sighted users see shapes, not text.
    return (
      <>
        {fromTheWeb}
        <div data-testid="discover-loading" role="status" aria-label={strings.loading}>
          <DiscoverSkeleton />
        </div>
      </>
    );
  }

  if (hasFilters) {
    return (
      <>
        {fromTheWeb}
        <div data-testid="discover-screen" data-discover-mode="filtered">
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "var(--eco-space-sm)" }}>
            <h3 data-testid="discover-results-count" style={{ margin: 0, fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>
              {items.length} result{items.length === 1 ? "" : "s"}
            </h3>
            {onClearFilters && (
              <button
                type="button"
                data-testid="discover-clear-filters"
                onClick={onClearFilters}
                style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)" }}
              >
                Clear filters
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p style={{ color: "var(--eco-color-textMuted)" }}>No {itemType}s match. Try another search or category.</p>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
              {items.map((item) => (
                // Connectors phase: a connector OR mcp_server item's
                // Discover card is connection-status-driven (Connect/
                // Connected), not install-state-driven -- both item types
                // carry the same ConnectionStatus semantics (Stage 3:
                // "Advanced: MCP servers" items are connection-based too,
                // same as native connectors). Only skill/plugin render the
                // install-state <Card>, unchanged from before this change.
                item.item_type === "connector" || item.item_type === "mcp_server"
                  ? <ConnectorCard key={item.id} item={item} onOpen={onOpen} />
                  : <Card key={item.id} item={item} onOpen={onOpen} onInstalled={onInstalled} />
              ))}
            </div>
          )}
        </div>
      </>
    );
  }

  if (items.length === 0) {
    return (
      <>
        {fromTheWeb}
        <div data-testid="discover-empty-state">{strings.empty_discover}</div>
      </>
    );
  }

  const byCategory = new Map<string, ItemSummary[]>();
  for (const item of items) {
    const bucket = byCategory.get(item.category) ?? [];
    bucket.push(item);
    byCategory.set(item.category, bucket);
  }

  return (
    <>
      {fromTheWeb}
      <div data-testid="discover-screen" data-discover-mode="browse">
        <FeaturedBanner items={items} onOpen={onOpen} />
        {config.taxonomy.categories
          .filter((category) => byCategory.has(category))
          .map((category) => (
            <CategorySection key={category} category={category} items={byCategory.get(category) ?? []} onOpen={onOpen} onInstalled={onInstalled} />
          ))}
      </div>
    </>
  );
}
