// SPDX-License-Identifier: MIT
// Task F-11: chat "+" menu. Flag-off must render nothing at all (the whole
// point of the additive-only rule -- see CLAUDE.md's standing instructions
// for this initiative).
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import EcosystemPlusMenu from "./EcosystemPlusMenu.jsx";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("EcosystemPlusMenu", () => {
  it("flag off: renders nothing", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "false");
    const { container } = render(<EcosystemPlusMenu onCreateWithAi={() => {}} disabled={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("flag on: shows a 'Create a skill with AI' entry and coming-soon entries, and calls onCreateWithAi on click", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    const onCreateWithAi = vi.fn();
    render(<EcosystemPlusMenu onCreateWithAi={onCreateWithAi} disabled={false} />);

    fireEvent.click(screen.getByTitle("Add a skill"));
    const createEntry = screen.getByText(/create a skill with ai/i);
    expect(createEntry).toBeInTheDocument();
    expect(screen.getByText("Add Plugin")).toBeInTheDocument();
    expect(screen.getByText("Add Connector")).toBeInTheDocument();
    expect(screen.getByText("Add MCP server")).toBeInTheDocument();

    fireEvent.click(createEntry);
    expect(onCreateWithAi).toHaveBeenCalledTimes(1);
  });

  it("flag on: the trigger button respects the disabled prop", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} disabled={true} />);
    expect(screen.getByTitle("Add a skill")).toBeDisabled();
  });
});
