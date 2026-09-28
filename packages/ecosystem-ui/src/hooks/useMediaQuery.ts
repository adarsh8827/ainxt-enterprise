// SPDX-License-Identifier: MIT
// Item 1 (M5 UI-polish round 2, 2026-09-28, real screenshot at 1920px):
// Yours.tsx's list-view row needs to know, in JS (not just CSS), when it's
// narrow enough to fold its badges/surface-chips columns into the kebab
// menu as read-only info instead of just hiding them outright -- a plain
// CSS @media rule can hide/show elements, but can't move their CONTENT
// into a completely different part of the tree (the popover). Small,
// generic, SSR-safe (matchMedia guarded) hook so any component can ask
// "is the viewport narrower than X" without duplicating a resize listener.
import { useEffect, useState } from "react";

function supportsMatchMedia(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

export function useMediaQuery(query: string): boolean {
  // jsdom (this package's vitest environment) declares `window.matchMedia`
  // in some versions without actually implementing it as a callable
  // function -- `"matchMedia" in window` alone isn't a reliable enough
  // guard (real bug hit writing this hook's own tests), hence the
  // explicit typeof-function check.
  const [matches, setMatches] = useState(() => (supportsMatchMedia() ? window.matchMedia(query).matches : false));

  useEffect(() => {
    if (!supportsMatchMedia()) return undefined;
    const mql = window.matchMedia(query);
    const listener = () => setMatches(mql.matches);
    listener();
    mql.addEventListener("change", listener);
    return () => mql.removeEventListener("change", listener);
  }, [query]);

  return matches;
}
