// SPDX-License-Identifier: MIT
// Loading-consistency pass (2026-10-05, explicit product ask: "on a hard
// reload... i see spinner text as Loading on right top corner, existing
// pages how they handled, do the same here"): MarketplaceScreen.tsx/
// CatalogScreen.tsx/Detail.tsx's own top-level loading states (the very
// first thing a hard reload hits, before config/the item has resolved)
// were bare `<div>Loading…</div>` with zero styling at all -- default
// black, unstyled text, unlike every other page in the app (e.g.
// KnowledgeBase.jsx's own `<Loader2 className="animate-spin" />` + text
// pattern) and unlike every OTHER loading moment already inside this same
// package (CardSkeleton/DiscoverSkeleton etc., or Button.jsx's own
// Spinner for an in-flight action). Reuses this package's own Spinner
// (host-agnostic, no injected stylesheet) rather than lucide-react's
// Loader2 directly, matching this package's existing convention.
import { Spinner } from "./Spinner";
export function LoadingState({
  label = "Loading…"
}) {
  return <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-400">
      <Spinner size={16} />
      {label}
    </div>;
}
