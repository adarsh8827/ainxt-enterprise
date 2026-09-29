// SPDX-License-Identifier: MIT
import { describe, it, expect } from "vitest";
import { stripLeadingSlashToken, matchAutoConvertToken } from "./skillChip";

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

describe("matchAutoConvertToken", () => {
  it("matches a bare slash command immediately followed by one trailing space", () => {
    expect(matchAutoConvertToken("/research ")).toBe("/research");
  });

  it("lowercases the matched token", () => {
    expect(matchAutoConvertToken("/Research ")).toBe("/research");
  });

  it("does not match while still typing the command (no trailing space yet)", () => {
    expect(matchAutoConvertToken("/rese")).toBeNull();
  });

  it("does not match once a second word has been typed, even with a final trailing space", () => {
    expect(matchAutoConvertToken("/research answer this ")).toBeNull();
  });

  it("does not match plain text with no leading slash", () => {
    expect(matchAutoConvertToken("hello ")).toBeNull();
  });

  it("does not match empty input", () => {
    expect(matchAutoConvertToken("")).toBeNull();
  });

  it("does not match a slash command followed by two trailing spaces", () => {
    expect(matchAutoConvertToken("/research  ")).toBeNull();
  });
});
