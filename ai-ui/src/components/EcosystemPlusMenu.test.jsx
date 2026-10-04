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
    const { container } = render(<EcosystemPlusMenu disabled={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  // Chat-menu simplification (2026-10-04): "Create a skill with AI" and the
  // Plugin/Connector/MCP-server "Coming soon" stubs are no longer shown in
  // this menu at all -- only Browse skills / Use a skill remain.
  it("flag on: never shows 'Create a skill with AI' or any coming-soon entry", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onBrowseSkills={() => {}} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/create a skill with ai/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Add Plugin")).not.toBeInTheDocument();
    expect(screen.queryByText("Add Connector")).not.toBeInTheDocument();
    expect(screen.queryByText("Add MCP server")).not.toBeInTheDocument();
  });

  it("flag on: the trigger button respects the disabled prop", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu disabled={true} />);
    expect(screen.getByTitle("Add a skill")).toBeDisabled();
  });

  it("'Browse skills' only renders when onBrowseSkills is supplied, and calls it on click", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/browse skills/i)).not.toBeInTheDocument();

    cleanup();
    const onBrowseSkills = vi.fn();
    render(<EcosystemPlusMenu onBrowseSkills={onBrowseSkills} disabled={false} />);
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
    render(<EcosystemPlusMenu disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/use a skill/i)).not.toBeInTheDocument();

    cleanup();
    render(<EcosystemPlusMenu onUseSkill={() => {}} skills={[]} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    expect(screen.queryByText(/use a skill/i)).not.toBeInTheDocument();
  });

  it("'Use a skill' expands the installed-skill list and calls onUseSkill with the picked skill", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    const onUseSkill = vi.fn();
    render(<EcosystemPlusMenu onUseSkill={onUseSkill} skills={DEMO_SKILLS} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/use a skill/i));

    const demoEntry = screen.getByText("Demo Skill");
    expect(demoEntry).toBeInTheDocument();
    fireEvent.click(demoEntry);
    expect(onUseSkill).toHaveBeenCalledTimes(1);
    expect(onUseSkill).toHaveBeenCalledWith(DEMO_SKILLS[0]);
  });

  // Chat-menu polish (2026-10-04, explicit product ask: "what if we have 40
  // plus skill how will u show") -- above SEARCH_THRESHOLD (8) skills, a
  // type-to-filter box replaces plain scrolling.
  const MANY_SKILLS = Array.from({ length: 12 }, (_, i) => ({
    namespace: `acme/skill-${i}`,
    display_name: `Skill Number ${i}`,
    description: "placeholder",
    slash_command: `/skill-${i}`,
  }));

  it("shows no search box under the threshold, but filters by name above it", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onUseSkill={() => {}} skills={DEMO_SKILLS} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/use a skill/i));
    expect(screen.queryByPlaceholderText(/search/i)).not.toBeInTheDocument();

    cleanup();
    render(<EcosystemPlusMenu onUseSkill={() => {}} skills={MANY_SKILLS} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/use a skill/i));
    const search = screen.getByPlaceholderText(/search 12 skills/i);
    expect(search).toBeInTheDocument();
    expect(screen.getByText("Skill Number 0")).toBeInTheDocument();
    expect(screen.getByText("Skill Number 11")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "Number 7" } });
    expect(screen.getByText("Skill Number 7")).toBeInTheDocument();
    expect(screen.queryByText("Skill Number 0")).not.toBeInTheDocument();
  });

  it("shows an empty state when the filter matches nothing", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    render(<EcosystemPlusMenu onUseSkill={() => {}} skills={MANY_SKILLS} disabled={false} />);
    fireEvent.click(screen.getByTitle("Add a skill"));
    fireEvent.click(screen.getByText(/use a skill/i));
    fireEvent.change(screen.getByPlaceholderText(/search 12 skills/i), { target: { value: "nonexistent" } });
    expect(screen.getByText(/no skills match/i)).toBeInTheDocument();
  });
});
