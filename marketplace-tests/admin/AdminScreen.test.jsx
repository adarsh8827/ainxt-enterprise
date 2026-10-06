// SPDX-License-Identifier: MIT
// Task F-13's own test requirement: "a component test per screen
// confirming it doesn't render at all for a workspace-profile fixture."
// The workspace profile (CONFIG_AND_PRODUCTS.md §3 seed row) sets
// provisioning/admin_policies/gate_dashboard all false.
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
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

  // UX-06 fix: previously no way back to the Marketplace catalog at all.
  it("shows a '← Marketplace' back link when onBack is given, and calls it on click", async () => {
    const onBack = vi.fn();
    renderWithHost(<AdminScreen screen="policies" onBack={onBack} />, {
      clientOptions: { config: MOCK_CONFIG },
    });
    await waitFor(() => expect(screen.getByTestId("admin-policies")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("admin-back-to-marketplace"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders no back link at all when onBack isn't given", async () => {
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: { config: MOCK_CONFIG },
    });
    await waitFor(() => expect(screen.getByTestId("admin-policies")).toBeInTheDocument());
    expect(screen.queryByTestId("admin-back-to-marketplace")).not.toBeInTheDocument();
  });

  // UX-06 fix: tab clicks now navigate (not just local state) -- the URL
  // and the visible tab stay in sync both ways, so a mid-session refresh
  // (which remounts this component fresh off the current URL) lands back
  // on whichever tab the admin actually clicked, not wherever the URL
  // happened to still say from the very first navigation.
  it("clicking a tab navigates to its own admin path instead of only updating local state", async () => {
    const navigate = vi.fn();
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: { config: MOCK_CONFIG },
      router: { path: "/admin/policies", navigate },
    });
    await waitFor(() => expect(screen.getByTestId("admin-policies")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("admin-nav-provisioning"));
    expect(navigate).toHaveBeenCalledWith("/admin/provisioning");
  });

  // Admin-tabs regression round (2026-10-06, real user report): every tab
  // here used to render for ANY logged-in caller as long as the product
  // feature flag was on -- a caller with the feature on but NONE of the
  // real RBAC permissions (can_admin_policy/can_admin_sources/can_provision)
  // still saw the full 7-tab nav and could open/interact with every one,
  // only failing server-side on actual submit. This is the fix's own
  // regression coverage: same features-on fixture as the "enterprise
  // profile" tests above, but with every caller_permission flipped off.
  const FEATURES_ON_NO_PERMISSIONS_CONFIG = {
    ...MOCK_CONFIG,
    caller_permissions: {
      can_share: true,
      can_provision: false,
      can_admin_surfaces: false,
      can_admin_policy: false,
      can_admin_sources: false
    }
  };
  it("hides every admin tab for a caller whose product has every admin feature on but who holds none of the real RBAC permissions", async () => {
    renderWithHost(<AdminScreen screen="policies" />, {
      clientOptions: { config: FEATURES_ON_NO_PERMISSIONS_CONFIG }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-not-available")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("admin-policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-provisioning")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-oauth-apps")).not.toBeInTheDocument();
  });
  it("shows only the tabs a caller actually holds the real permission for, even with every feature flag on", async () => {
    const PARTIAL_CONFIG = {
      ...MOCK_CONFIG,
      caller_permissions: {
        can_share: true,
        can_provision: true,
        can_admin_surfaces: false,
        can_admin_policy: false,
        can_admin_sources: false
      }
    };
    renderWithHost(<AdminScreen screen="provisioning" />, {
      clientOptions: { config: PARTIAL_CONFIG }
    });
    await waitFor(() => {
      expect(screen.getByTestId("admin-nav-provisioning")).toBeInTheDocument();
    });
    // Provisioning (can_provision) is the only tab this caller holds --
    // Policies/Force disable/Gate findings/Featured/Sources/OAuth Apps
    // (all gated on can_admin_policy/can_admin_sources) must not render.
    expect(screen.queryByTestId("admin-nav-policies")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-force-disable")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-gate-findings")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-featured")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-sources")).not.toBeInTheDocument();
    expect(screen.queryByTestId("admin-nav-oauth-apps")).not.toBeInTheDocument();
  });
});