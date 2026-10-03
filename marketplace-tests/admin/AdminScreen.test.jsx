// SPDX-License-Identifier: MIT
// Task F-13's own test requirement: "a component test per screen
// confirming it doesn't render at all for a workspace-profile fixture."
// The workspace profile (CONFIG_AND_PRODUCTS.md §3 seed row) sets
// provisioning/admin_policies/gate_dashboard all false.
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminScreen } from "@marketplace/admin/AdminScreen";
import { MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
const WORKSPACE_CONFIG = {
  ...MOCK_CONFIG,
  product: "workspace",
  layout: "compact",
  features: {
    ...MOCK_CONFIG.features,
    provisioning: false,
    admin_policies: false,
    gate_dashboard: false,
    share: false
  }
};
describe("AdminScreen", () => {
  it("renders nothing usable for a workspace-profile fixture (every admin feature off)", async () => {
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: {
        config: WORKSPACE_CONFIG
      }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-not-available")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("admin-policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-policies")).not.toBeInTheDocument();
  });
  it("renders the requested screen when the enterprise profile's admin features are on", async () => {
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: {
        config: MOCK_CONFIG
      }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-policies")).toBeInTheDocument();
    });
  });

  // Real incident, 2026-09-27: testing ran against a 15-hour-stale image
  // with no way to tell from the app.
  it("shows the commit + build time when the config carries build_info", async () => {
    const CONFIG_WITH_BUILD_INFO = {
      ...MOCK_CONFIG,
      build_info: {
        commit: "abc123def4567890",
        built_at: "2026-09-27T12:00:00Z"
      }
    };
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: {
        config: CONFIG_WITH_BUILD_INFO
      }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-build-info")).toBeInTheDocument();
    });
    expect(screen.getByTestId("admin-build-info").textContent).toContain("abc123de");
    expect(screen.getByTestId("admin-build-info").textContent).not.toContain("abc123def4567890"); // truncated to 8 chars
  });
  it("shows nothing when build_info is null (a non-admin caller server-side)", async () => {
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          build_info: null
        }
      }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-policies")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("admin-build-info")).not.toBeInTheDocument();
  });
});