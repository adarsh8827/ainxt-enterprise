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

const discoverCache = new Map();
const yoursCache = new Map();

/** Discover's own cache key -- one entry per itemType+query+sort+filter
 * combination a caller has actually viewed this session (CatalogScreen.tsx
 * resets query/categories/trust/sort on a type-tab switch, so this can't
 * grow unbounded from tab-switching alone; a user trying many distinct
 * searches/filters is the only way this grows, and each is a genuinely
 * distinct view worth remembering). */
export function discoverCacheKey(itemType, query, sort, categories, trust) {
  return [itemType, query.trim(), sort, [...categories].sort().join(","), [...trust].sort().join(",")].join("::");
}
export function getDiscoverCache(key) {
  return discoverCache.get(key);
}
export function setDiscoverCache(key, entry) {
  discoverCache.set(key, entry);
}

/** Yours has no query-independent server-side filter today (query is
 * client-side-only, Yours.tsx's own matchesQuery) -- itemType alone is
 * the real cache axis; caching per-query would just multiply entries for
 * data that's already fully in memory anyway. */
export function yoursCacheKey(itemType) {
  return itemType;
}
export function getYoursCache(key) {
  return yoursCache.get(key);
}
export function setYoursCache(key, entry) {
  yoursCache.set(key, entry);
}

/** Install-state-consistency round (2026-09-29): real bug found live --
 * uninstalling an item from Yours left Discover's own cached copy of that
 * item showing "Installed" (install_id still set) until Discover's next
 * full remount+refetch, and the same in reverse for an Add from Discover
 * never appearing in an already-cached Yours view. This patches every
 * cached Discover entry's matching item IN PLACE (so a cache HIT --
 * switching tabs, no remount at all if a screen stays mounted -- reads
 * the corrected fields immediately, not just a future refetch), and drops
 * the ENTIRE Yours cache (every itemType) rather than trying to
 * surgically patch/insert a row there -- Yours' own mutations already
 * trigger a real refetch of themselves, so this only ever matters for a
 * change made on a DIFFERENT screen, which is rare enough that a full,
 * definitely-correct refetch next time Yours is viewed is worth more
 * than the small risk of a surgical merge getting a field wrong. */
export function patchCachedInstallState(itemId, patch) {
  for (const entry of discoverCache.values()) {
    entry.items = entry.items.map(item => item.id === itemId ? {
      ...item,
      install_id: patch.install_id,
      enabled: patch.enabled ?? (patch.install_id === null ? null : item.enabled),
      install_scope: patch.install_scope ?? (patch.install_id === null ? null : item.install_scope),
      install_surfaces: patch.install_surfaces ?? (patch.install_id === null ? null : item.install_surfaces)
    } : item);
  }
  yoursCache.clear();
}

/** An item that no longer exists at all (delete_draft) -- removed from
 * every cached Discover entry outright, not merely patched, plus the
 * same blanket Yours-cache drop as above. */
export function removeItemFromCaches(itemId) {
  for (const entry of discoverCache.values()) {
    entry.items = entry.items.filter(item => item.id !== itemId);
  }
  yoursCache.clear();
}

/** Test-only: clears both caches. Real app code never needs this (the
 * module-level cache is meant to persist for the whole tab's lifetime),
 * but a test FILE's module registry is shared across every one of its
 * `it()` blocks, so tests must reset it themselves (afterEach) to stay
 * isolated from each other -- same convention as installTracking.ts's
 * own `__resetInstallTrackingForTests()`. */
export function __resetCatalogCacheForTests() {
  discoverCache.clear();
  yoursCache.clear();
}