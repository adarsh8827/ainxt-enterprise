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
import { useLayoutEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

interface AnchorRect {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

function readRect(el: HTMLElement): AnchorRect {
  const r = el.getBoundingClientRect();
  return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
}

export function PopoverAnchor({ anchorRef, open, align = "right", children }: {
  anchorRef: RefObject<HTMLElement | null>;
  open: boolean;
  align?: "left" | "right";
  children: ReactNode;
}) {
  const [rect, setRect] = useState<AnchorRect | null>(null);
  const [portalTarget, setPortalTarget] = useState<Element | null>(null);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setRect(null);
      setPortalTarget(null);
      return;
    }
    const el = anchorRef.current;
    setPortalTarget(el.closest(".eco-root") ?? document.body);
    const update = () => setRect(readRect(el));
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open, anchorRef]);

  if (!open || !rect || !portalTarget) return null;

  const style: CSSProperties = {
    position: "fixed",
    top: rect.bottom + 6,
    zIndex: 1000,
    ...(align === "right"
      ? { right: Math.max(8, window.innerWidth - rect.right) }
      : { left: rect.left }),
  };

  return createPortal(<div style={style}>{children}</div>, portalTarget);
}
