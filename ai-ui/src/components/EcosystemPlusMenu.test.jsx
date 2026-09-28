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

  it("item 6: 'Browse skills' only renders when onBrowseSkills is supplied, and calls it on click", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/browse skills/i)).not.toBeInTheDocument();

    cleanup();
    const onBrowseSkills = vi.fn();
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} onBrowseSkills={onBrowseSkills} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/browse skills/i));
    expect(onBrowseSkills).toHaveBeenCalledTimes(1);
  });

  // Chat-skills task, 2026-09-28: "Use a skill" picker.
  const DEMO_SKILLS = [
    { namespace: "acme/demo", display_name: "Demo Skill", description: "does the demo thing", slash_command: "/demo" },
  ];

  it("'Use a skill' only renders when onUseSkill + a non-empty skills list are both supplied", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/use a skill/i)).not.toBeInTheDocument();

    cleanup();
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} onUseSkill={() => {}} skills={[]} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/use a skill/i)).not.toBeInTheDocument();
  });

  it("'Use a skill' expands the installed-skill list and calls onUseSkill with the picked skill", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    const onUseSkill = vi.fn();
    render(<EcosystemPlusMenu onCreateWithAi={() => {}} onUseSkill={onUseSkill} skills={DEMO_SKILLS} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/use a skill/i));

    const demoEntry = screen.getByText("Demo Skill");
    expect(demoEntry).toBeInTheDocument();
    fireEvent.click(demoEntry);
    expect(onUseSkill).toHaveBeenCalledTimes(1);
    expect(onUseSkill).toHaveBeenCalledWith(DEMO_SKILLS[0]);
  });
});
