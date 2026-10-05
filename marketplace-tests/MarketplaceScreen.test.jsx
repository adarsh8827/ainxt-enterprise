// SPDX-License-Identifier: MIT
// Regression test for a real bug found live: CreateForm.tsx's own
// provisioning picker was gated on config.features.provisioning -- a
// per-*product* flag every caller under that product sees the same
// value for -- not on whether *this caller* actually has
// marketplace:provision. A normal (non-admin) user under the enterprise
// profile (features.provisioning: true for that whole product) saw the
// same org-provisioning picker an admin would.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Marketplace } from "@marketplace/MarketplaceScreen";
import { MockEcosystemClient } from "@marketplace/lib/client/MockEcosystemClient";
import { MOCK_CONFIG, MOCK_CONFIG_WORKSPACE } from "@marketplace/lib/client/fixtures";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";
function renderCreateFormAt(callerPermissions) {
  const config = {
    ...MOCK_CONFIG,
    caller_permissions: callerPermissions
  };
  return render(<Marketplace client={new MockEcosystemClient({
    config
  })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
    path: "/skills/new",
    navigate: () => {}
  }} />);
}
describe("Marketplace -> CreateForm provisioning picker", () => {
  it("a normal user (features.provisioning true for the product, but no marketplace:provision) never sees the provisioning picker", async () => {
    renderCreateFormAt({
      can_share: false,
      can_provision: false
    });
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.queryByTestId("create-form-provision-scope")).not.toBeInTheDocument();
  });
  it("an admin (marketplace:provision) sees the provisioning picker", async () => {
    renderCreateFormAt({
      can_share: false,
      can_provision: true
    });
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.getByTestId("create-form-provision-scope")).toBeInTheDocument();
  });
});

// Task item 1 (M5 UI-parity review): the reference mock's own renderDetail()
// never calls header() -- Detail is a back-link row only, no type tabs, no
// search/filter/sort/add-menu. Before this fix, RouteSwitch rendered
// TypeTabs+AddMenu unconditionally above every branch, including Detail.
describe("Marketplace -> Toolbar visibility per route", () => {
  it("the catalog (list) screen renders the full Toolbar", async () => {
    render(<Marketplace client={new MockEcosystemClient({
      config: MOCK_CONFIG
    })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{
      path: "/skills",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("catalog-screen")).toBeInTheDocument());
    expect(screen.getByTestId("marketplace-toolbar")).toBeInTheDocument();
  });
  it("the Detail screen has no Toolbar (no type tabs, no add-menu)", async () => {
    const client = new MockEcosystemClient({
      config: MOCK_CONFIG
    });
    const item = (await client.listItems({
      item_type: "skill"
    })).items[0];
    render(<Marketplace client={client} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{
      path: `/skills/${item.namespace}`,
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("detail-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tabs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-menu-trigger")).not.toBeInTheDocument();
  });
  it("the write-a-skill (CreateForm) screen has no Toolbar either", async () => {
    render(<Marketplace client={new MockEcosystemClient({
      config: MOCK_CONFIG
    })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{
      path: "/skills/new",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-toolbar")).not.toBeInTheDocument();
  });
  it("a coming-soon type shows the SAME toolbar as every other tab, search disabled and filter/sort hidden (UI-polish round)", async () => {
    render(<Marketplace client={new MockEcosystemClient({
      config: MOCK_CONFIG
    })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{
      path: "/plugins",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    expect(screen.getByTestId("add-menu-trigger")).toBeInTheDocument();
    // The real toolbar now renders here (not the old lighter TypeTabs+AddMenu
    // pair) -- same header row as an available tab, just with search
    // disabled and filter/sort hidden since there's nothing to act on yet.
    expect(screen.getByTestId("marketplace-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-search").querySelector("input")).toBeDisabled();
    expect(screen.queryByTestId("toolbar-filter-trigger")).not.toBeInTheDocument();
    expect(screen.queryByTestId("toolbar-sort-trigger")).not.toBeInTheDocument();
  });
});

// Plugins phase (docs/ecosystem/PLUGINS_PHASE_PLAN.md §4): the plugin tab's
// ComingSoonTab->real-content switch is driven entirely by GET /ecosystem/
// config's item_types[].state (RouteSwitch's own existing branch, see
// Marketplace.tsx) -- confirmed here to require NO client code change of
// its own, and confirmed NOT to regress the coming-soon case above (still
// passing against the unmodified default MOCK_CONFIG, where plugin stays
// "coming_soon").
describe("Marketplace -> Plugins phase: plugin tab goes live once its state is 'available'", () => {
  function availablePluginConfig() {
    return {
      ...MOCK_CONFIG,
      item_types: MOCK_CONFIG.item_types.map(t => t.type === "plugin" ? {
        ...t,
        state: "available"
      } : t)
    };
  }
  it("renders the real catalog screen (not ComingSoonTab) once the backend flips plugin to available", async () => {
    const config = availablePluginConfig();
    render(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path: "/plugins",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("catalog-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-unknown-type")).not.toBeInTheDocument();
  });
});

// Connectors phase item 5 (follow-up round): TypeTabs' collapse wired
// into real Marketplace.tsx routing, end to end.
describe("Marketplace -> Connectors/Advanced tab collapse (item 5)", () => {
  function availableConnectorConfig(canAdminSurfaces) {
    return {
      ...MOCK_CONFIG,
      item_types: MOCK_CONFIG.item_types.map(t => t.type === "connector" ? {
        ...t,
        state: "available"
      } : t),
      caller_permissions: {
        ...MOCK_CONFIG.caller_permissions,
        can_admin_surfaces: canAdminSurfaces
      }
    };
  }
  it("REGRESSION: mcp_server is never a standalone tab, even for a caller without can_admin_surfaces -- only the Advanced toggle is admin-gated", async () => {
    // Real gap found and fixed 2026-09-30 after a live user report: the
    // FIRST cut of this test locked in the WRONG behavior (asserted
    // type-tab-mcp WAS present for a non-admin) -- the merge itself must
    // be unconditional, matching the reference design's fixed 3-tab shell.
    const config = availableConnectorConfig(false);
    render(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path: "/connectors",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
  });
  // UI polish (2026-10-05, explicit product ask): Plugins/Connectors are
  // hidden from the tab bar by default now, for every caller including
  // admins -- TypeTabs.jsx's own `hiddenTypes` default, no per-role
  // exception. This test used to click a visible "Connectors" tab to reach
  // this flow; renamed and rewritten to (a) confirm the tab really is
  // hidden here too, not just for a non-admin, and (b) prove the
  // Advanced-toggle content-swap logic underneath is still fully intact by
  // reaching it via direct route (router path "/connectors") instead of a
  // tab click -- same approach the "navigating away from connectors..."
  // test below already uses, since `activeSlug === connectorSlug` is
  // derived independently of whether the tab itself rendered.
  it("Connectors tab is hidden even for an admin/dev caller (can_admin_surfaces); the Advanced-toggle content-swap still works when reached directly", async () => {
    const config = availableConnectorConfig(true);
    render(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path: "/connectors",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-connectors")).not.toBeInTheDocument();
    expect(screen.queryByTestId("marketplace-advanced-mcp")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("type-tab-advanced-mcp"));
    await waitFor(() => expect(screen.getByTestId("marketplace-advanced-mcp")).toBeInTheDocument());
    expect(screen.getByTestId("advanced-mcp-servers")).toBeInTheDocument();

    // The standalone Advanced Toolbar and CatalogScreen's own Toolbar are
    // two distinct mounted instances (one unmounts as the other mounts) --
    // re-query rather than reuse the first click's (now-detached) button.
    fireEvent.click(screen.getByTestId("type-tab-advanced-mcp"));
    await waitFor(() => expect(screen.queryByTestId("marketplace-advanced-mcp")).not.toBeInTheDocument());
    expect(screen.getByTestId("catalog-screen")).toBeInTheDocument();
  });
  it("navigating away from connectors resets the Advanced sub-view", async () => {
    const config = availableConnectorConfig(true);
    let path = "/connectors";
    const navigate = next => {
      path = next;
    };
    const {
      rerender
    } = render(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path,
      navigate
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("type-tab-advanced-mcp"));
    await waitFor(() => expect(screen.getByTestId("marketplace-advanced-mcp")).toBeInTheDocument());
    path = "/skills";
    rerender(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path,
      navigate
    }} />);
    await waitFor(() => expect(screen.getByTestId("catalog-screen")).toBeInTheDocument());
    path = "/connectors";
    rerender(<Marketplace client={new MockEcosystemClient({
      config
    })} layout="full" theme={LIGHT_TOKENS} config={config} router={{
      path,
      navigate
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-advanced-mcp")).not.toBeInTheDocument();
  });
  it("the 'workspace' product profile has no MCP tab and no Advanced sub-view at all, even hypothetically as an admin", async () => {
    // Real, server-driven exclusion (db/migrate.py Part AE5): workspace's
    // visible_item_types no longer includes mcp_server -- confirmed here
    // by using workspace's OWN real fixture shape, not a hand-edited one.
    // Connectors itself is additionally hidden from the tab bar by default
    // now (UI polish, 2026-10-05, see the test above) -- unrelated to this
    // test's own point (workspace's product-profile-driven mcp_server
    // exclusion), but the old assertion that the Connectors tab WAS visible
    // here no longer holds, so it's updated to match rather than removed.
    render(<Marketplace client={new MockEcosystemClient({
      config: MOCK_CONFIG_WORKSPACE
    })} layout="compact" theme={LIGHT_TOKENS} config={MOCK_CONFIG_WORKSPACE} router={{
      path: "/connectors",
      navigate: () => {}
    }} />);
    await waitFor(() => expect(screen.getByTestId("type-tabs")).toBeInTheDocument());
    expect(screen.queryByTestId("type-tab-mcp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-advanced-mcp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tab-connectors")).not.toBeInTheDocument();
  });
});