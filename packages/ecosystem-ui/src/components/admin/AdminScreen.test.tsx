// SPDX-License-Identifier: MIT
// Task F-13's own test requirement: "a component test per screen
// confirming it doesn't render at all for a workspace-profile fixture."
// The workspace profile (CONFIG_AND_PRODUCTS.md §3 seed row) sets
// provisioning/admin_policies/gate_dashboard all false.
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { AdminScreen } from "./AdminScreen";
import { MOCK_CONFIG } from "../../client/fixtures";

const WORKSPACE_CONFIG = {
  ...MOCK_CONFIG,
  product: "workspace",
  layout: "compact" as const,
  features: { ...MOCK_CONFIG.features, provisioning: false, admin_policies: false, gate_dashboard: false, share: false },
};

describe("AdminScreen", () => {
  it("renders nothing usable for a workspace-profile fixture (every admin feature off)", async () => {
    renderWithHost(<AdminScreen screen="policies" />, { clientOptions: { config: WORKSPACE_CONFIG } });
    await waitFor(() => {
      expect(screen.getByTestId("admin-not-available")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("admin-policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-policies")).not.toBeInTheDocument();
  });

  it("renders the requested screen when the enterprise profile's admin features are on", async () => {
    renderWithHost(<AdminScreen screen="policies" />, { clientOptions: { config: MOCK_CONFIG } });
    await waitFor(() => {
      expect(screen.getByTestId("admin-policies")).toBeInTheDocument();
    });
  });
});
