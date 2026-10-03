// SPDX-License-Identifier: MIT
// Task F-5: "a component test per badge state (verified/org/community/
// agent_created x pass/warn/fail/pending)."
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrustBadge, VerdictBadge, CompatibilityBadge, NeedsProductBadges, needsProductLabel } from "@marketplace/Badges";
const TIERS = ["builtin", "verified", "org", "community", "agent_created"];
const VERDICTS = ["pass", "warn", "fail", "pending"];
describe("TrustBadge", () => {
  it.each(TIERS)("renders the correct data-tier attribute for %s", tier => {
    render(<TrustBadge tier={tier} />);
    expect(screen.getByTestId("trust-badge")).toHaveAttribute("data-tier", tier);
  });

  // Item 3 (M5 UI-polish round 2, 2026-09-28): the user's own explicit
  // wording for a Create-with-AI skill's trust badge is "Created with
  // AI", not "Agent-created" (this label's previous text).
  it("labels agent_created as 'Created with AI', not 'Agent-created'", () => {
    render(<TrustBadge tier="agent_created" />);
    expect(screen.getByTestId("trust-badge")).toHaveTextContent("Created with AI");
    expect(screen.getByTestId("trust-badge")).not.toHaveTextContent("Agent-created");
  });
});
describe("VerdictBadge", () => {
  it.each(VERDICTS)("renders the correct data-verdict attribute for %s", verdict => {
    render(<VerdictBadge verdict={verdict} />);
    expect(screen.getByTestId("verdict-badge")).toHaveAttribute("data-verdict", verdict);
  });
  it("labels a fail verdict as blocked, never as a generic error", () => {
    render(<VerdictBadge verdict="fail" />);
    expect(screen.getByTestId("verdict-badge")).toHaveTextContent("Blocked");
  });
  it("labels a pending verdict as verifying, never as pass", () => {
    render(<VerdictBadge verdict="pending" />);
    expect(screen.getByTestId("verdict-badge")).not.toHaveTextContent(/^Verified safe$/);
  });
});
describe("CompatibilityBadge", () => {
  it("labels a chat-compatible item as working in chat", () => {
    render(<CompatibilityBadge compatibility="chat" />);
    expect(screen.getByTestId("compatibility-badge")).toHaveTextContent("Works in chat");
  });
  it("labels a tool-dependent item as needing file/terminal tools", () => {
    render(<CompatibilityBadge compatibility="tool_dependent" />);
    expect(screen.getByTestId("compatibility-badge")).toHaveTextContent("Needs file/terminal tools");
  });
  it("renders nothing for a null compatibility (a version predating this field)", () => {
    render(<CompatibilityBadge compatibility={null} />);
    expect(screen.queryByTestId("compatibility-badge")).not.toBeInTheDocument();
  });
});

// Item 2 (2026-09-28 live-testing round): the crawler tags product-gated
// repos (docs/ecosystem/catalog/sources.yaml's needs_product, e.g. Stitch)
// with a `needs-<product>` tag. items_service already passes `tags`
// straight through to ItemSummary/ItemDetail -- the tag reached the
// frontend fine, but no badge ever rendered it. These pin the label
// derivation and the "renders one badge per matching tag" behavior.
describe("needsProductLabel", () => {
  it("turns a single-word needs-<product> tag into a Needs <Product> label", () => {
    expect(needsProductLabel("needs-stitch")).toBe("Needs Stitch");
  });
  it("title-cases a multi-word product segment", () => {
    expect(needsProductLabel("needs-figma-make")).toBe("Needs Figma Make");
  });
  it("returns null for a tag that isn't the needs-<product> convention", () => {
    expect(needsProductLabel("account-required")).toBeNull();
    expect(needsProductLabel("design")).toBeNull();
  });
  it("returns null for a bare 'needs-' tag with no product segment", () => {
    expect(needsProductLabel("needs-")).toBeNull();
  });
});
describe("NeedsProductBadges", () => {
  it("renders a badge for a Stitch-sourced item's needs-stitch tag", () => {
    render(<NeedsProductBadges tags={["design", "needs-stitch", "account-required"]} />);
    const badges = screen.getAllByTestId("needs-product-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent("Needs Stitch");
  });
  it("renders nothing when the item has no needs-<product> tag", () => {
    render(<NeedsProductBadges tags={["design", "account-required"]} />);
    expect(screen.queryByTestId("needs-product-badge")).not.toBeInTheDocument();
  });
  it("renders nothing for an empty tag list", () => {
    render(<NeedsProductBadges tags={[]} />);
    expect(screen.queryByTestId("needs-product-badge")).not.toBeInTheDocument();
  });
  it("renders one badge per matching tag when an item needs more than one product", () => {
    render(<NeedsProductBadges tags={["needs-stitch", "needs-figma-make"]} />);
    expect(screen.getAllByTestId("needs-product-badge")).toHaveLength(2);
  });
});