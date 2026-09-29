// SPDX-License-Identifier: MIT
// Regression test for a real bug found live: CreateForm.tsx's own
// provisioning picker was gated on config.features.provisioning -- a
// per-*product* flag every caller under that product sees the same
// value for -- not on whether *this caller* actually has
// marketplace:provision. A normal (non-admin) user under the enterprise
// profile (features.provisioning: true for that whole product) saw the
// same org-provisioning picker an admin would.
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Marketplace } from "./Marketplace";
import { MockEcosystemClient } from "./client/MockEcosystemClient";
import { MOCK_CONFIG } from "./client/fixtures";
import { LIGHT_TOKENS } from "./theme";

function renderCreateFormAt(callerPermissions: { can_share: boolean; can_provision: boolean }) {
  const config = { ...MOCK_CONFIG, caller_permissions: callerPermissions };
  return render(
    <Marketplace
      client={new MockEcosystemClient({ config })}
      layout="full"
      theme={LIGHT_TOKENS}
      config={config}
      router={{ path: "/skills/new", navigate: () => {} }}
    />,
  );
}

describe("Marketplace -> CreateForm provisioning picker", () => {
  it("a normal user (features.provisioning true for the product, but no marketplace:provision) never sees the provisioning picker", async () => {
    renderCreateFormAt({ can_share: false, can_provision: false });
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.queryByTestId("create-form-provision-scope")).not.toBeInTheDocument();
  });

  it("an admin (marketplace:provision) sees the provisioning picker", async () => {
    renderCreateFormAt({ can_share: false, can_provision: true });
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
    render(
      <Marketplace client={new MockEcosystemClient({ config: MOCK_CONFIG })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{ path: "/skills", navigate: () => {} }} />,
    );
    await waitFor(() => expect(screen.getByTestId("catalog-screen")).toBeInTheDocument());
    expect(screen.getByTestId("marketplace-toolbar")).toBeInTheDocument();
  });

  it("the Detail screen has no Toolbar (no type tabs, no add-menu)", async () => {
    const client = new MockEcosystemClient({ config: MOCK_CONFIG });
    const item = (await client.listItems({ item_type: "skill" })).items[0]!;
    render(
      <Marketplace client={client} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{ path: `/skills/${item.namespace}`, navigate: () => {} }} />,
    );
    await waitFor(() => expect(screen.getByTestId("detail-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-toolbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("type-tabs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-menu-trigger")).not.toBeInTheDocument();
  });

  it("the write-a-skill (CreateForm) screen has no Toolbar either", async () => {
    render(
      <Marketplace client={new MockEcosystemClient({ config: MOCK_CONFIG })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{ path: "/skills/new", navigate: () => {} }} />,
    );
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-toolbar")).not.toBeInTheDocument();
  });

  it("a coming-soon type shows the SAME toolbar as every other tab, search disabled and filter/sort hidden (UI-polish round)", async () => {
    render(
      <Marketplace client={new MockEcosystemClient({ config: MOCK_CONFIG })} layout="full" theme={LIGHT_TOKENS} config={MOCK_CONFIG} router={{ path: "/plugins", navigate: () => {} }} />,
    );
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
      item_types: MOCK_CONFIG.item_types.map((t) => (t.type === "plugin" ? { ...t, state: "available" as const } : t)),
    };
  }

  it("renders the real catalog screen (not ComingSoonTab) once the backend flips plugin to available", async () => {
    const config = availablePluginConfig();
    render(
      <Marketplace client={new MockEcosystemClient({ config })} layout="full" theme={LIGHT_TOKENS} config={config} router={{ path: "/plugins", navigate: () => {} }} />,
    );
    await waitFor(() => expect(screen.getByTestId("catalog-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("marketplace-unknown-type")).not.toBeInTheDocument();
  });
});
