// SPDX-License-Identifier: MIT
// Regression test for a real bug found live testing the rebuilt top bar:
// Add/Filter/Sort popovers rendered invisible/clipped inside ai-ui's own
// `overflow-y-auto` Marketplace wrapper because they used a plain
// `position: absolute` relative to their trigger button.
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PopoverAnchor } from "./PopoverAnchor";
import { HostProvider } from "../context/HostContext";
import type { EcosystemClient } from "../client/EcosystemClient";

// PopoverAnchor reads useHost().router.path (closes on a route change) --
// every harness below must render under a real HostProvider now, not just
// a bare ".eco-root" div, or useHost() throws "called outside HostProvider".
function withHost(children: React.ReactNode, path = "/") {
  return (
    <HostProvider value={{ client: {} as unknown as EcosystemClient, layout: "full", router: { path, navigate: () => {} } }}>
      {children}
    </HostProvider>
  );
}

function Harness({ open, onRequestClose = () => {} }: { open: boolean; onRequestClose?: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  return withHost(
    <>
      <button ref={ref} type="button">trigger</button>
      <PopoverAnchor anchorRef={ref} open={open} align="right" onRequestClose={onRequestClose}>
        <div data-testid="popover-content">content</div>
      </PopoverAnchor>
    </>,
  );
}

function TwoPopovers() {
  const refA = useRef<HTMLButtonElement>(null);
  const refB = useRef<HTMLButtonElement>(null);
  const [openA, setOpenA] = useState(false);
  const [openB, setOpenB] = useState(false);
  return withHost(
    <>
      <button ref={refA} type="button" onClick={() => setOpenA(true)}>trigger-a</button>
      <button ref={refB} type="button" onClick={() => setOpenB(true)}>trigger-b</button>
      <PopoverAnchor anchorRef={refA} open={openA} align="right" onRequestClose={() => setOpenA(false)}>
        <div data-testid="popover-a">A</div>
      </PopoverAnchor>
      <PopoverAnchor anchorRef={refB} open={openB} align="right" onRequestClose={() => setOpenB(false)}>
        <div data-testid="popover-b">B</div>
      </PopoverAnchor>
    </>,
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

  it("closes on Escape", () => {
    const onRequestClose = vi.fn();
    render(<Harness open onRequestClose={onRequestClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onRequestClose).toHaveBeenCalledTimes(1);
  });

  it("closes on an outside click", () => {
    const onRequestClose = vi.fn();
    render(<Harness open onRequestClose={onRequestClose} />);
    fireEvent.pointerDown(document.body);
    expect(onRequestClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking inside the popover content itself", () => {
    const onRequestClose = vi.fn();
    render(<Harness open onRequestClose={onRequestClose} />);
    fireEvent.pointerDown(screen.getByTestId("popover-content"));
    expect(onRequestClose).not.toHaveBeenCalled();
  });
});
