// SPDX-License-Identifier: MIT
import { describe, it, expect } from "vitest";
import { stripLeadingSlashToken, insertSkillSlashCommand, resolveLeadingSkillCommand } from "./skillChip";

const DEMO_SKILLS = [
  { namespace: "acme/research", display_name: "Research", slash_command: "/research" },
  { namespace: "acme/email-tone", display_name: "Email Tone", slash_command: "/email-tone-polish" },
];

describe("stripLeadingSlashToken", () => {
  it("clears a bare partial slash-filter with no space (menu pick while still typing the filter)", () => {
    expect(stripLeadingSlashToken("/rese")).toBe("");
  });

  it("clears the exact slash command with no trailing text", () => {
    expect(stripLeadingSlashToken("/research")).toBe("");
  });

  // The real bug this fixes: picking a skill while the box also holds
  // "/research explain this" used to leave "/research" sitting in the
  // input alongside the new chip. Only the leading token should go.
  it("strips only the leading '/token' when more text follows a space, keeping the rest", () => {
    expect(stripLeadingSlashToken("/research explain this")).toBe("explain this");
  });

  it("keeps text unchanged when it doesn't start with '/' (the '+' menu picker case)", () => {
    expect(stripLeadingSlashToken("summarize this doc")).toBe("summarize this doc");
  });

  it("returns empty string for empty input", () => {
    expect(stripLeadingSlashToken("")).toBe("");
  });

  it("handles multiple spaces after the token by keeping everything after the first space", () => {
    expect(stripLeadingSlashToken("/research  extra spaces")).toBe(" extra spaces");
  });
});

// Chat-skills UX rework (2026-10-04): replaces the old chip-attachment
// helpers (matchAutoConvertToken) with literal-text insertion -- selecting
// a skill now inserts real "/slash-command " text instead of a separate,
// non-text chip object.
describe("insertSkillSlashCommand", () => {
  it("fills in a partial slash filter with the full command plus a trailing space", () => {
    expect(insertSkillSlashCommand("/rese", "/research")).toBe("/research ");
  });

  it("replaces the leading token but preserves any task text already typed after it", () => {
    expect(insertSkillSlashCommand("/research explain this", "/research")).toBe("/research explain this");
  });

  it("prepends the command when the box has plain text with no leading slash (the '+' menu picker case)", () => {
    expect(insertSkillSlashCommand("summarize this doc", "/research")).toBe("/research summarize this doc");
  });

  it("fills an empty box with just the command and a trailing space", () => {
    expect(insertSkillSlashCommand("", "/research")).toBe("/research ");
  });

  it("swaps a different previously-typed command for the newly picked one", () => {
    expect(insertSkillSlashCommand("/research explain this", "/email-tone-polish")).toBe("/email-tone-polish explain this");
  });
});

describe("resolveLeadingSkillCommand", () => {
  it("resolves an exact leading command with nothing else in the box", () => {
    expect(resolveLeadingSkillCommand("/research", DEMO_SKILLS)).toBe(DEMO_SKILLS[0]);
  });

  it("resolves a leading command followed by task text", () => {
    expect(resolveLeadingSkillCommand("/research explain this", DEMO_SKILLS)).toBe(DEMO_SKILLS[0]);
  });

  it("is case-insensitive", () => {
    expect(resolveLeadingSkillCommand("/RESEARCH", DEMO_SKILLS)).toBe(DEMO_SKILLS[0]);
  });

  it("does not resolve a partial/incomplete command", () => {
    expect(resolveLeadingSkillCommand("/rese", DEMO_SKILLS)).toBeNull();
  });

  it("does not resolve plain text with no leading slash", () => {
    expect(resolveLeadingSkillCommand("explain this", DEMO_SKILLS)).toBeNull();
  });

  it("does not resolve empty input", () => {
    expect(resolveLeadingSkillCommand("", DEMO_SKILLS)).toBeNull();
  });

  it("does not resolve when the skills list is empty", () => {
    expect(resolveLeadingSkillCommand("/research", [])).toBeNull();
  });
});
