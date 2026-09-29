// SPDX-License-Identifier: MIT
// Item (d), part 3 (2026-09-29 live-test round): "skeletons instead of
// status badges while loading." An earlier round already separated the
// page-level "list hasn't loaded yet" string (`strings.loading`) from an
// item's own gate-verdict badge (`strings.verifying`) -- see
// HostContext.tsx's own DEFAULT_STRINGS comment -- but the user is asking
// for something more specific than a fixed string either way: an actual
// placeholder shape matching the real content's own dimensions.
//
// `packages/ecosystem-ui` builds independently of `ai-ui` (this package's
// own header comments, task F-1's "builds independently" requirement) --
// ai-ui/src/components/Skeleton.jsx (a real, pre-existing primitive) isn't
// reachable from here, and it's Tailwind-class-based besides, while this
// package styles everything through inline styles + the `--eco-*` CSS
// vars (HostContext.tsx's own tokensToCssVars). A small, local primitive
// following that same convention, rather than pulling in a cross-package
// dependency or a whole new styling approach for one component.
//
// Used ONLY for a genuine first-load with no cached data at all --
// Discover.tsx/Yours.tsx already short-circuit straight to their cached
// `items`/`installs` (catalogCache.ts) on every remount/filter-change that
// has a hit, so this never renders over stale-but-real content.
import "./Skeleton.css";

/** One shimmering placeholder block -- the shared visual primitive every
 * shape below is built from. `radius` defaults to the card's own
 * `--eco-radius-md` (badges/text lines); callers needing the full card's
 * `--eco-radius-lg` (the block/card outline itself) pass it explicitly. */
function SkeletonBlock({ width, height, radius = "var(--eco-radius-md)" }: { width: string; height: string; radius?: string }) {
  return (
    <div
      className="eco-skeleton-block"
      style={{ width, height, borderRadius: radius }}
      aria-hidden="true"
    />
  );
}

/** Matches Card.tsx's own real dimensions/layout exactly (icon + name row,
 * a badges row, a 2-line description block, a footer button) -- so the
 * grid's own height never jumps once the real cards swap in. */
export function CardSkeleton() {
  return (
    <div
      data-testid="card-skeleton"
      style={{
        display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)",
        padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
        border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
        <SkeletonBlock width="28px" height="28px" radius="var(--eco-radius-md)" />
        <SkeletonBlock width="65%" height="16px" />
      </div>
      <div style={{ display: "flex", gap: "6px" }}>
        <SkeletonBlock width="60px" height="18px" radius="var(--eco-radius-full)" />
        <SkeletonBlock width="50px" height="18px" radius="var(--eco-radius-full)" />
      </div>
      <SkeletonBlock width="100%" height="13px" />
      <SkeletonBlock width="80%" height="13px" />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "auto", paddingTop: "var(--eco-space-sm)" }}>
        <SkeletonBlock width="72px" height="32px" />
      </div>
    </div>
  );
}

/** Discover's own browse-grid shell during a genuine first load -- the
 * same `repeat(auto-fill, minmax(240px, 1fr))` grid Discover.tsx/
 * CategorySection.tsx already render real cards into, so nothing shifts
 * width/columns once real data swaps in. `count` matches the collapsed
 * per-category count elsewhere in this package (CategorySection.tsx's
 * own COLLAPSED_COUNT) purely as a reasonable default, not a hard
 * dependency between the two. */
export function DiscoverSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div data-testid="discover-skeleton" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
      {Array.from({ length: count }, (_, i) => <CardSkeleton key={i} />)}
    </div>
  );
}

/** One placeholder row, matching Yours.tsx's own list-row shape (icon +
 * name/description + a couple of trailing chips) closely enough that the
 * row height/rhythm doesn't jump once real rows swap in -- grid layout
 * reuses CardSkeleton instead (yoursLayout is a pure display toggle over
 * the same underlying data, same as the real rows). */
function ListRowSkeleton() {
  return (
    <div
      data-testid="list-row-skeleton"
      style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}
    >
      <SkeletonBlock width="32px" height="32px" radius="var(--eco-radius-md)" />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
        <SkeletonBlock width="40%" height="14px" />
        <SkeletonBlock width="70%" height="12px" />
      </div>
      <SkeletonBlock width="70px" height="20px" radius="var(--eco-radius-full)" />
      <SkeletonBlock width="90px" height="28px" />
    </div>
  );
}

export function YoursSkeleton({ layout, count = 6 }: { layout: "grid" | "list"; count?: number }) {
  if (layout === "grid") {
    return (
      <div data-testid="yours-skeleton" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }}>
        {Array.from({ length: count }, (_, i) => <CardSkeleton key={i} />)}
      </div>
    );
  }
  return (
    <div data-testid="yours-skeleton">
      {Array.from({ length: count }, (_, i) => <ListRowSkeleton key={i} />)}
    </div>
  );
}
