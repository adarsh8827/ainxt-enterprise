// SPDX-License-Identifier: MIT
// Regression test for a real bug found live testing the rebuilt top bar:
// Add/Filter/Sort popovers rendered invisible/clipped inside ai-ui's own
// `overflow-y-auto` Marketplace wrapper because they used a plain
// `position: absolute` relative to their trigger button.
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PopoverAnchor } from "./PopoverAnchor";

function Harness({ open, onRequestClose = () => {} }: { open: boolean; onRequestClose?: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <div className="eco-root">
      <button ref={ref} type="button">trigger</button>
      <PopoverAnchor anchorRef={ref} open={open} align="right" onRequestClose={onRequestClose}>
        <div data-testid="popover-content">content</div>
      </PopoverAnchor>
    </div>
  );
}

function TwoPopovers() {
  const refA = useRef<HTMLButtonElement>(null);
  const refB = useRef<HTMLButtonElement>(null);
  const [openA, setOpenA] = useState(false);
  const [openB, setOpenB] = useState(false);
  return (
    <div className="eco-root">
      <button ref={refA} type="button" onClick={() => setOpenA(true)}>trigger-a</button>
      <button ref={refB} type="button" onClick={() => setOpenB(true)}>trigger-b</button>
      <PopoverAnchor anchorRef={refA} open={openA} align="right" onRequestClose={() => setOpenA(false)}>
        <div data-testid="popover-a">A</div>
      </PopoverAnchor>
      <PopoverAnchor anchorRef={refB} open={openB} align="right" onRequestClose={() => setOpenB(false)}>
        <div data-testid="popover-b">B</div>
      </PopoverAnchor>
    </div>
  );
}

describe("PopoverAnchor", () => {
  it("renders nothing when closed", () => {
    render(<Harness open={false} />);
    expect(screen.queryByTestId("popover-content")).not.toBeInTheDocument();
  });

  it("portals into the nearest .eco-root ancestor, not document.body directly, so theme tokens still inherit", () => {
    render(<Harness open />);
    const content = screen.getByTestId("popover-content");
    const ecoRoot = document.querySelector(".eco-root");
    expect(ecoRoot).toContainElement(content);
  });

  it("positions with position: fixed so an overflow:auto/hidden ancestor never clips it", () => {
    render(<Harness open />);
    const content = screen.getByTestId("popover-content");
    const fixedAncestor = content.parentElement as HTMLElement;
    expect(fixedAncestor.style.position).toBe("fixed");
  });

  it("closes any other open popover when a second one opens (real bug: Add + Sort could both be open at once)", () => {
    render(<TwoPopovers />);
    fireEvent.click(screen.getByText("trigger-a"));
    expect(screen.getByTestId("popover-a")).toBeInTheDocument();

    fireEvent.click(screen.getByText("trigger-b"));
    expect(screen.getByTestId("popover-b")).toBeInTheDocument();
    expect(screen.queryByTestId("popover-a")).not.toBeInTheDocument();
  });

  it("unregisters on unmount so a stale closer is never called later", () => {
    const onRequestClose = vi.fn();
    const { unmount } = render(<Harness open onRequestClose={onRequestClose} />);
    unmount();
    expect(onRequestClose).not.toHaveBeenCalled();
  });
});
