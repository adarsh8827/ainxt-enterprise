// SPDX-License-Identifier: MIT
// Tier 2 of the tiered license policy (ECOSYSTEM_PLAN.md §11.2):
// allowed_licenses_shared is admin-editable as a comma-separated list.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminPolicies } from "@marketplace/admin/AdminPolicies";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";

const BASE_POLICY = { who_can_add: "all_users", auto_update_default: false, allowed_licenses_shared: ["MIT", "Apache-2.0"] };

describe("AdminPolicies -- allowed_licenses_shared", () => {
  it("shows the mock client's default MIT/Apache-2.0 list on load", async () => {
    renderWithHost(<AdminPolicies />);
    const input = await screen.findByTestId("admin-policies-allowed-licenses-shared");
    expect(input.value).toBe("MIT, Apache-2.0");
  });
  it("saves a parsed, trimmed license list on blur", async () => {
    const {
      client
    } = renderWithHost(<AdminPolicies />);
    const input = await screen.findByTestId("admin-policies-allowed-licenses-shared");
    fireEvent.change(input, {
      target: {
        value: "MIT, Apache-2.0,  GPL-3.0-only "
      }
    });
    fireEvent.blur(input);
    await waitFor(async () => {
      const policy = await client.getPolicy();
      expect(policy.allowed_licenses_shared).toEqual(["MIT", "Apache-2.0", "GPL-3.0-only"]);
    });
  });

  // User-flow QA round 8 (2026-10-03, audit finding): save() had no
  // .catch() at all -- a failed save silently reverted with zero
  // indication anything went wrong, since setPolicy's resolved value
  // never arrived to update `policy`.
  it("shows a real error, and leaves the policy unchanged, when a save fails", async () => {
    const getPolicy = vi.fn().mockResolvedValue(BASE_POLICY);
    const setPolicy = vi.fn().mockRejectedValue(new Error("Couldn't reach the server."));
    render(
      <HostProvider value={{ client: { getPolicy, setPolicy }, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <AdminPolicies />
      </HostProvider>,
    );
    const checkbox = await screen.findByTestId("admin-policies-auto-update");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);

    expect(await screen.findByTestId("admin-policies-save-error")).toHaveTextContent("Couldn't reach the server.");
    // The failed save's optimistic-looking checkbox click never actually
    // took -- `policy` was never replaced, so the control reflects the
    // real, still-unsaved server state, not a false "saved" look.
    expect(checkbox).not.toBeChecked();
  });
});