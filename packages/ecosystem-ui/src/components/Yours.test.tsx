// SPDX-License-Identifier: MIT
// Regression test for a real crash found live: "Cannot read properties of
// undefined (reading 'allowed_actions')" -- CONTRACTS.md §9 documents
// `item` as always present on an Install, but a backend regression once
// shipped a row without one. This component must never crash the whole
// screen over one bad row -- it renders a small "unavailable" placeholder
// instead. A custom minimal client (not MockEcosystemClient, which always
// builds well-formed installs from real items) is used here specifically
// to construct that otherwise-impossible-via-the-mock shape.
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Yours } from "./Yours";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_DETAILS } from "../client/fixtures";
import { LIGHT_TOKENS } from "../theme";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { Install } from "../types";

function renderYoursWith(installs: Install[]) {
  const client = {
    getInstalls: () => Promise.resolve({ installs, legacy_items: [], has_any: installs.length > 0, next_cursor: null }),
  } as unknown as EcosystemClient;
  return render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
      </EcosystemConfigProvider>
    </HostProvider>,
  );
}

const WELL_FORMED_ITEM = Object.values(MOCK_DETAILS)[0]!;
const WELL_FORMED_INSTALL: Install = {
  install_id: "install-1", item: WELL_FORMED_ITEM, version_id: "v1", scope: "private", origin: "added",
  installed_by: "user-1", installed_for: "user-1", enabled: true, surfaces: ["chat"],
  auto_update: false, installed_at: new Date().toISOString(),
};

describe("Yours", () => {
  it("renders a well-formed install row normally", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    expect(await screen.findByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });

  it("renders an 'unavailable' placeholder instead of crashing when a row's item is missing", async () => {
    const brokenInstall = { ...WELL_FORMED_INSTALL, install_id: "install-broken", item: null as unknown as Install["item"] };
    renderYoursWith([brokenInstall, WELL_FORMED_INSTALL]);

    expect(await screen.findByTestId("yours-install-row-unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument();
    // The other, well-formed row still renders -- one bad row never blanks the rest.
    expect(screen.getByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });

  it("the 'unavailable' row's Remove button uninstalls it", async () => {
    const uninstall = vi.fn().mockResolvedValue(undefined);
    const brokenInstall = { ...WELL_FORMED_INSTALL, install_id: "install-broken", item: null as unknown as Install["item"] };
    const client = {
      getInstalls: () => Promise.resolve({ installs: [brokenInstall], legacy_items: [], has_any: true, next_cursor: null }),
      uninstall,
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(await screen.findByText(/remove/i));
    expect(uninstall).toHaveBeenCalledWith("install-broken");
  });
});
