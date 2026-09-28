// SPDX-License-Identifier: MIT
// Tier 2 of the tiered license policy (ECOSYSTEM_PLAN.md §11.2):
// allowed_licenses_shared is admin-editable as a comma-separated list.
import { describe, expect, it } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { AdminPolicies } from "./AdminPolicies";

describe("AdminPolicies -- allowed_licenses_shared", () => {
  it("shows the mock client's default MIT/Apache-2.0 list on load", async () => {
    renderWithHost(<AdminPolicies />);
    const input = await screen.findByTestId("admin-policies-allowed-licenses-shared");
    expect((input as HTMLInputElement).value).toBe("MIT, Apache-2.0");
  });

  it("saves a parsed, trimmed license list on blur", async () => {
    const { client } = renderWithHost(<AdminPolicies />);
    const input = await screen.findByTestId("admin-policies-allowed-licenses-shared");

    fireEvent.change(input, { target: { value: "MIT, Apache-2.0,  GPL-3.0-only " } });
    fireEvent.blur(input);

    await waitFor(async () => {
      const policy = await client.getPolicy();
      expect(policy.allowed_licenses_shared).toEqual(["MIT", "Apache-2.0", "GPL-3.0-only"]);
    });
  });
});
