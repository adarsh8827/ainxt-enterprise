// SPDX-License-Identifier: MIT
// Item (d), part 3 (2026-09-29 live-test round): "skeletons instead of
// status badges while loading." An earlier round already separated the
// page-level "list hasn't loaded yet" string (`strings.loading`) from an
// item's own gate-verdict badge (`strings.verifying`) -- see
// HostContext.tsx's own DEFAULT_STRINGS comment -- but the user is asking
// for something more specific than a fixed string either way: an actual
// placeholder shape matching the real content's own dimensions.
//
// Full Tailwind pass (2026-10-03): this package now styles through literal
// Tailwind classes everywhere, same as ai-ui's own native components --
// SkeletonBlock's shimmer reuses ai-ui/src/components/Skeleton.jsx's own
// exact `animate-pulse bg-gradient-to-r from-gray-200 via-gray-300
// to-gray-200 bg-[length:200%_100%]` treatment instead of a bespoke
// `--eco-*`-driven @keyframes in a dedicated Skeleton.css.
//
// Used ONLY for a genuine first-load with no cached data at all --
// Discover.tsx/Yours.tsx already short-circuit straight to their cached
// `items`/`installs` (catalogCache.ts) on every remount/filter-change that
// has a hit, so this never renders over stale-but-real content.

/** One shimmering placeholder block -- the shared visual primitive every
 * shape below is built from. `radius` defaults to `rounded-md` (badges/
 * text lines); callers needing the full card's own `rounded-xl` (the
 * block/card outline itself) pass it explicitly. */
function SkeletonBlock({
  width,
  height,
  radius = "rounded-md"
}) {
  return <div className={["animate-pulse bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 bg-[length:200%_100%]", radius].join(" ")} style={{
    width,
    height
  }} aria-hidden="true" />;
}

/** Matches Card.tsx's own real dimensions/layout exactly (icon + name row,
 * a badges row, a 2-line description block, a footer button) -- so the
 * grid's own height never jumps once the real cards swap in. */
export function CardSkeleton() {
  return <div data-testid="card-skeleton" className="flex flex-col gap-2 p-4 rounded-xl border border-gray-200 bg-white">
      <div className="flex items-start gap-2">
        <SkeletonBlock width="28px" height="28px" radius="rounded-md" />
        <SkeletonBlock width="65%" height="16px" />
      </div>
      <div className="flex gap-1.5">
        <SkeletonBlock width="60px" height="18px" radius="rounded-full" />
        <SkeletonBlock width="50px" height="18px" radius="rounded-full" />
      </div>
      <SkeletonBlock width="100%" height="13px" />
      <SkeletonBlock width="80%" height="13px" />
      <div className="flex justify-end mt-auto pt-2">
        <SkeletonBlock width="72px" height="32px" />
      </div>
    </div>;
}

/** Discover's own browse-grid shell during a genuine first load -- the
 * same `repeat(auto-fit, minmax(240px, 320px))` + maxWidth grid Discover.tsx
 * already renders real cards into (user-flow QA round 3, 2026-10-03:
 * updated from auto-fill alongside it), so nothing shifts width/columns
 * once real data swaps in. `count` matches the collapsed per-category
 * count elsewhere in this package (CategorySection.tsx's own
 * COLLAPSED_COUNT) purely as a reasonable default, not a hard dependency
 * between the two. */
export function DiscoverSkeleton({
  count = 8
}) {
  return <div data-testid="discover-skeleton" className="grid gap-4 max-w-[1000px]" style={{
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 320px))"
  }}>
      {Array.from({
      length: count
    }, (_, i) => <CardSkeleton key={i} />)}
    </div>;
}

/** One placeholder row, matching Yours.tsx's own list-row shape (icon +
 * name/description + a couple of trailing chips) closely enough that the
 * row height/rhythm doesn't jump once real rows swap in -- grid layout
 * reuses CardSkeleton instead (yoursLayout is a pure display toggle over
 * the same underlying data, same as the real rows). */
function ListRowSkeleton() {
  return <div data-testid="list-row-skeleton" className="flex items-center gap-2 py-2 border-b border-gray-200">
      <SkeletonBlock width="32px" height="32px" radius="rounded-md" />
      <div className="flex-1 flex flex-col gap-1.5">
        <SkeletonBlock width="40%" height="14px" />
        <SkeletonBlock width="70%" height="12px" />
      </div>
      <SkeletonBlock width="70px" height="20px" radius="rounded-full" />
      <SkeletonBlock width="90px" height="28px" />
    </div>;
}
export function YoursSkeleton({
  layout,
  count = 6
}) {
  if (layout === "grid") {
    return <div data-testid="yours-skeleton" className="grid gap-4 max-w-[1000px]" style={{
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 320px))"
    }}>
        {Array.from({
        length: count
      }, (_, i) => <CardSkeleton key={i} />)}
      </div>;
  }
  return <div data-testid="yours-skeleton">
      {Array.from({
      length: count
    }, (_, i) => <ListRowSkeleton key={i} />)}
    </div>;
}
