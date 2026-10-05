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

/** Matches Card.tsx's own real dimensions/layout exactly -- a real bug,
 * found live (2026-10-05): the card density pass earlier this session
 * collapsed Card.tsx/Yours.tsx's grid row from 4 stacked sections down to
 * ONE (icon + name/description column + a single small circular action
 * icon), but this skeleton was never updated to match, so every
 * genuine-first-load still rendered the OLD, taller 4-section shape
 * (icon+name row, a badges-pill row, a 2-line description block, a footer
 * button) -- then visibly collapsed/jumped the instant real cards swapped
 * in. Updated to the same single-row anatomy as the real card, so the
 * swap is now a seamless height match, not a jump. */
export function CardSkeleton() {
  return <div data-testid="card-skeleton" className="flex items-start gap-3 p-4 rounded-xl border border-gray-200 bg-white">
      <SkeletonBlock width="40px" height="40px" radius="rounded-md" />
      <div className="flex-1 flex flex-col gap-1.5">
        <SkeletonBlock width="55%" height="14px" />
        <SkeletonBlock width="85%" height="13px" />
      </div>
      <SkeletonBlock width="28px" height="28px" radius="rounded-full" />
    </div>;
}

/** Matches Card.tsx's own list-row shape exactly (icon 32px + name/
 * description column + one 28px circular action placeholder) -- Discover
 * list-view pass (2026-10-05). Deliberately its OWN shape rather than
 * reusing ListRowSkeleton below: that one matches Yours.tsx's 5-column
 * list row (a badge pill + a wider button block), which is a different
 * real shape from Card.tsx's single small circular action -- reusing it
 * here would reintroduce exactly the skeleton/real-content height
 * mismatch this package's own CardSkeleton fix (above) already called
 * out as a real, live-found bug. */
function CardListRowSkeleton() {
  return <div data-testid="card-list-row-skeleton" className="flex items-center gap-3 px-3 py-2.5 border-b border-gray-200">
      <SkeletonBlock width="32px" height="32px" radius="rounded-md" />
      <div className="flex-1 flex flex-col gap-1.5">
        <SkeletonBlock width="40%" height="14px" />
        <SkeletonBlock width="70%" height="12px" />
      </div>
      <SkeletonBlock width="28px" height="28px" radius="rounded-full" />
    </div>;
}

/** Discover's own browse-grid shell during a genuine first load -- the
 * same `repeat(auto-fit, minmax(240px, 280px))` grid Discover.tsx already
 * renders real cards into (no outer max-width, layout-density pass
 * 2026-10-05 -- see CategorySection.tsx's own comment; max track size is
 * 280px, not 320px, per that same comment's laptop-width follow-up), so
 * nothing shifts width/columns once real data swaps in. `count` bumped
 * from 8 (enough to fill 2-3 rows at the old fixed 3-column cap) to 12 so
 * a wide viewport, which can now fit several more columns per row, still
 * gets a full-looking skeleton instead of one short row.
 *
 * `layout` added (2026-10-05, Discover list-view pass): same grid-vs-flat-
 * column split as the real content below it. */
export function DiscoverSkeleton({
  count = 12,
  layout = "grid"
}) {
  if (layout === "list") {
    return <div data-testid="discover-skeleton">
        {Array.from({
        length: count
      }, (_, i) => <CardListRowSkeleton key={i} />)}
      </div>;
  }
  return <div data-testid="discover-skeleton" className="grid gap-4" style={{
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 280px))"
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
  count = 9
}) {
  if (layout === "grid") {
    return <div data-testid="yours-skeleton" className="grid gap-4" style={{
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 280px))"
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
