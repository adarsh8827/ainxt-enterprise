// SPDX-License-Identifier: MIT
// Regression test for a real bug found live testing the rebuilt top bar:
// Add/Filter/Sort popovers rendered invisible/clipped inside ai-ui's own
// `overflow-y-auto` Marketplace wrapper because they used a plain
// `position: absolute` relative to their trigger button.
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PopoverAnchor } from "./PopoverAnchor";

function Harness({ open }: { open: boolean }) {
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <div className="eco-root">
      <button ref={ref} type="button">trigger</button>
      <PopoverAnchor anchorRef={ref} open={open} align="right">
        <div data-testid="popover-content">content</div>
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
});
