// SPDX-License-Identifier: MIT
// Real bug found live: Add/Sort/Filter/Kebab popovers each own their own
// `open` state independently, so opening one never closed another already
// open one -- two could show at once. A tiny module-level singleton: the
// most recently opened popover's own close callback is tracked here, and
// opening any other one closes it first.
let activeClose: (() => void) | null = null;

export function registerOpenPopover(close: () => void): void {
  if (activeClose && activeClose !== close) activeClose();
  activeClose = close;
}

export function unregisterPopover(close: () => void): void {
  if (activeClose === close) activeClose = null;
}

/** Closes whichever popover is currently open, if any -- called from
 * navigation handlers (Toolbar's type-tab/Yours-Discover switch, route
 * changes) so a popover never survives a screen change it has no visual
 * relationship to anymore (real bug: "+ Add" stayed open after switching
 * Yours <-> Discover, since that's local component state, not a route
 * change PopoverAnchor's own router.path watcher would ever see). */
export function closeAny(): void {
  if (activeClose) activeClose();
}
