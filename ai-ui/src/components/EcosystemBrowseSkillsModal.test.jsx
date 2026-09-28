// SPDX-License-Identifier: MIT
// Thin-wrapper test: the real Marketplace catalog UI (Yours/Discover,
// search/filter/sort, card grid, AddMenu) is already exhaustively tested
// against a MockEcosystemClient in packages/ecosystem-ui's own suite (101
// tests) -- this file only proves the ai-ui-side wiring (modal
// open/close, props actually passed through), not Marketplace's own
// internal behavior, which would be redundant to re-test here.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const marketplaceSpy = vi.fn(() => <div data-testid="mock-marketplace" />);

vi.mock("@ecosystem-ui", () => ({
  Marketplace: (props) => marketplaceSpy(props),
  RealEcosystemClient: class {},
  LIGHT_TOKENS: {},
}));

import EcosystemBrowseSkillsModal from "./EcosystemBrowseSkillsModal.jsx";

afterEach(() => {
  cleanup();
  marketplaceSpy.mockClear();
});

describe("EcosystemBrowseSkillsModal", () => {
  it("renders the real Marketplace component in compact layout", () => {
    render(<EcosystemBrowseSkillsModal onClose={() => {}} onCreateWithAi={() => {}} />);
    expect(screen.getByTestId("mock-marketplace")).toBeInTheDocument();
    expect(marketplaceSpy).toHaveBeenCalledWith(expect.objectContaining({ layout: "compact" }));
  });

  it("passes onCreateWithAi through to Marketplace", () => {
    const onCreateWithAi = vi.fn();
    render(<EcosystemBrowseSkillsModal onClose={() => {}} onCreateWithAi={onCreateWithAi} />);
    expect(marketplaceSpy).toHaveBeenCalledWith(expect.objectContaining({ onCreateWithAi }));
  });

  it("closes on clicking the X button", () => {
    const onClose = vi.fn();
    render(<EcosystemBrowseSkillsModal onClose={onClose} onCreateWithAi={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on clicking the overlay but not the modal content itself", () => {
    const onClose = vi.fn();
    const { container } = render(<EcosystemBrowseSkillsModal onClose={onClose} onCreateWithAi={() => {}} />);
    fireEvent.click(screen.getByTestId("mock-marketplace"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(container.firstChild);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
