// SPDX-License-Identifier: MIT
// Real bug found live testing the rebuilt top bar (M5 UI-parity review):
// the Add/Filter/Sort popovers used `position: absolute` relative to their
// own trigger button, which renders invisible/clipped inside ai-ui's own
// `h-full overflow-y-auto` Marketplace wrapper (Marketplace.jsx) -- setting
// only one of overflow-x/overflow-y to a non-"visible" value makes the
// *other* axis compute to "auto" too (CSS2.1 §11.1.1), turning that
// wrapper into a clipping context for anything a plain absolutely-
// positioned descendant needs to render outside its box.
//
// Fixed by portaling the popover content to a `position: fixed` box
// positioned from the trigger's own getBoundingClientRect() -- `fixed`
// escapes ordinary overflow:auto/hidden clipping (it only respects a
// containing block created by transform/perspective/filter/contain on an
// ancestor, none of which this tree uses). Portaled into the nearest
// `.eco-root` ancestor rather than document.body, since HostContext.tsx
// injects every `--eco-*` theme token as an inline style on `.eco-root`
// itself -- CSS custom properties only cascade to DOM descendants, so a
// document.body portal would render an unstyled (transparent/colorless)
// popover outside that subtree.
//
// This is the ONE shared primitive every popover/menu in this package goes
// through (AddMenu, FilterPopover, SortPopover, KebabMenu, Detail's
// Installed-menu) -- outside-click/Esc/focus-trap/mutual-exclusion/route-
// change-closes all live here once, not copied per component (a second
// real bug found live: opening Sort never closed an already-open Add).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { registerOpenPopover, unregisterPopover } from "./popoverCoordinator";
import { useHost } from "./lib/context/HostContext";
function readRect(el) {
  const r = el.getBoundingClientRect();
  return {
    top: r.top,
    bottom: r.bottom,
    left: r.left,
    right: r.right
  };
}
const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
export function PopoverAnchor({
  anchorRef,
  open,
  align = "right",
  onRequestClose,
  children
}) {
  const [rect, setRect] = useState(null);
  const [portalTarget, setPortalTarget] = useState(null);
  const contentRef = useRef(null);
  const {
    router
  } = useHost();
  const pathAtOpen = useRef(router.path);
  const wasOpen = useRef(false);
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setRect(null);
      setPortalTarget(null);
      unregisterPopover(onRequestClose);
      return;
    }
    registerOpenPopover(onRequestClose);
    pathAtOpen.current = router.path;
    const el = anchorRef.current;
    setPortalTarget(el.closest(".eco-root") ?? document.body);
    const update = () => setRect(readRect(el));
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
      unregisterPopover(onRequestClose);
    };
    // router.path deliberately excluded -- captured once into pathAtOpen
    // above, then compared against on every render by the effect below
    // (a route change while open should CLOSE it, not reposition it).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, anchorRef, onRequestClose]);

  // Outside click + Esc, one listener pair, only while actually open.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = e => {
      const target = e.target;
      if (anchorRef.current?.contains(target)) return;
      if (contentRef.current?.contains(target)) return;
      onRequestClose();
    };
    const onKeyDown = e => {
      if (e.key === "Escape") {
        e.preventDefault();
        onRequestClose();
        return;
      }
      // Basic focus trap while open: Tab/Shift+Tab cycles within the
      // popover's own focusable elements instead of escaping to the page.
      if (e.key === "Tab" && contentRef.current) {
        const focusable = Array.from(contentRef.current.querySelectorAll(FOCUSABLE_SELECTOR));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open, onRequestClose, anchorRef]);

  // A route change while open closes it -- covers Detail drill-in/Back and
  // any other host-router-driven navigation. Local, non-router view state
  // (e.g. CatalogScreen's Yours/Discover toggle) doesn't touch router.path
  // at all, so that case is closed explicitly at the call site instead
  // (Toolbar.tsx wraps onSelectType/onSelectView with popoverCoordinator's
  // closeAny()) -- this effect is the route-change half only.
  useEffect(() => {
    if (open && router.path !== pathAtOpen.current) onRequestClose();
  }, [open, router.path, onRequestClose]);

  // Return focus to the trigger once this popover closes (was open last
  // render, isn't now) -- so closing via Esc/outside-click/selection never
  // drops keyboard focus onto <body>.
  useEffect(() => {
    if (wasOpen.current && !open) anchorRef.current?.focus();
    wasOpen.current = open;
  }, [open, anchorRef]);
  if (!open || !rect || !portalTarget) return null;
  const style = {
    position: "fixed",
    top: rect.bottom + 6,
    zIndex: 1000,
    ...(align === "right" ? {
      right: Math.max(8, window.innerWidth - rect.right)
    } : {
      left: rect.left
    })
  };
  return createPortal(<div ref={contentRef} style={style}>{children}</div>, portalTarget);
}