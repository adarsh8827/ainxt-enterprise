// SPDX-License-Identifier: MIT
// Item (d), part 1 (2026-09-29 live-test round): "Discover/Yours keep data
// in memory on tab switch." Real bug: CatalogScreen.tsx renders EITHER
// <Discover> or <Yours>, never both (view === "discover" ? ... : ...) --
// switching Discover<->Yours, or navigating away to Detail/another screen
// and back, fully unmounts the one not currently shown. Their own
// useState(null)-then-fetch effects had nothing outside the component to
// remember a previous load, so every return trip re-showed the loading
// state and re-fetched from scratch, even for data that hadn't changed.
//
// This module is the persistent memory that fixes that: a module-level
// cache (read/written directly, no React state of its own -- Discover.tsx/
// Yours.tsx each hold the "current" copy in their own useState, seeded
// from here on mount) keyed by view + filters, living OUTSIDE either
// component's lifecycle, same architectural pattern installTracking.ts
// already established for install status surviving a remount.
//
// Deliberately NOT sessionStorage/localStorage (unlike installTracking.ts,
// which persists across a real page reload on purpose -- an install
// genuinely keeps running server-side across a reload): this is
// disposable, this-tab-this-session-only data. A stale catalog snapshot
// surviving a real reload would be actively misleading (deleted/blocked
// items, stale verdicts) rather than merely "one refresh behind" -- the
// background refresh (see Discover.tsx's listItemsWithEtag call) is what
// keeps an in-memory hit honest, and a reload is exactly the point where
// that safety net is gone, so the cache intentionally doesn't survive one.
import type { Install, ItemSummary, LegacyItem } from "./types";

export interface DiscoverCacheEntry {
  items: ItemSummary[];
  /** GET /ecosystem/items' own ETag (routers/ecosystem_router.py's
   * list_items()) from the last 200 response for this exact key --
   * null when nothing has been successfully fetched yet. Sent back as
   * If-None-Match on the next background refresh for this key. */
  etag: string | null;
}

export interface YoursCacheEntry {
  installs: Install[];
  legacyItems: LegacyItem[];
}

const discoverCache = new Map<string, DiscoverCacheEntry>();
const yoursCache = new Map<string, YoursCacheEntry>();

/** Discover's own cache key -- one entry per itemType+query+sort+filter
 * combination a caller has actually viewed this session (CatalogScreen.tsx
 * resets query/categories/trust/sort on a type-tab switch, so this can't
 * grow unbounded from tab-switching alone; a user trying many distinct
 * searches/filters is the only way this grows, and each is a genuinely
 * distinct view worth remembering). */
export function discoverCacheKey(
  itemType: string, query: string, sort: string, categories: string[], trust: string[],
): string {
  return [itemType, query.trim(), sort, [...categories].sort().join(","), [...trust].sort().join(",")].join("::");
}

export function getDiscoverCache(key: string): DiscoverCacheEntry | undefined {
  return discoverCache.get(key);
}

export function setDiscoverCache(key: string, entry: DiscoverCacheEntry): void {
  discoverCache.set(key, entry);
}

/** Yours has no query-independent server-side filter today (query is
 * client-side-only, Yours.tsx's own matchesQuery) -- itemType alone is
 * the real cache axis; caching per-query would just multiply entries for
 * data that's already fully in memory anyway. */
export function yoursCacheKey(itemType: string): string {
  return itemType;
}

export function getYoursCache(key: string): YoursCacheEntry | undefined {
  return yoursCache.get(key);
}

export function setYoursCache(key: string, entry: YoursCacheEntry): void {
  yoursCache.set(key, entry);
}

/** Test-only: clears both caches. Real app code never needs this (the
 * module-level cache is meant to persist for the whole tab's lifetime),
 * but a test FILE's module registry is shared across every one of its
 * `it()` blocks, so tests must reset it themselves (afterEach) to stay
 * isolated from each other -- same convention as installTracking.ts's
 * own `__resetInstallTrackingForTests()`. */
export function __resetCatalogCacheForTests(): void {
  discoverCache.clear();
  yoursCache.clear();
}
