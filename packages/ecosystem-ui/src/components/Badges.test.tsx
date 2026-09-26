// SPDX-License-Identifier: MIT
// Task F-5: "a component test per badge state (verified/org/community/
// agent_created x pass/warn/fail/pending)."
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrustBadge, VerdictBadge } from "./Badges";
import type { GateVerdict, TrustTier } from "../types";

const TIERS: TrustTier[] = ["builtin", "verified", "org", "community", "agent_created"];
const VERDICTS: GateVerdict[] = ["pass", "warn", "fail", "pending"];

describe("TrustBadge", () => {
  it.each(TIERS)("renders the correct data-tier attribute for %s", (tier) => {
    render(<TrustBadge tier={tier} />);
    expect(screen.getByTestId("trust-badge")).toHaveAttribute("data-tier", tier);
  });
});

describe("VerdictBadge", () => {
  it.each(VERDICTS)("renders the correct data-verdict attribute for %s", (verdict) => {
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
