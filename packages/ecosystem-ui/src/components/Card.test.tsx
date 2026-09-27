// SPDX-License-Identifier: MIT
// Real bug found live: Discover cards had no install-state indicator at
// all -- every card looked identical whether installed or not, matching
// the user's own "Yours and Discover look the same" complaint.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Card } from "./Card";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_ITEMS, MOCK_CONFIG } from "../client/fixtures";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { ItemVersion } from "../types";

const NOT_INSTALLED = MOCK_ITEMS[0]!; // allowed_actions includes "install", install_id null
const INSTALLED = { ...NOT_INSTALLED, install_id: "install-1", enabled: true };

function renderCard(item = NOT_INSTALLED, client: Partial<EcosystemClient> = {}, onInstalled = () => {}) {
  return render(
    <HostProvider value={{ client: client as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <Card item={item} onOpen={() => {}} onInstalled={onInstalled} />
      </EcosystemConfigProvider>
    </HostProvider>,
  );
}

describe("Card", () => {
  it("shows a quick Add button for an installable, not-yet-installed item", () => {
    renderCard();
    expect(screen.getByTestId("card-quick-add")).toBeInTheDocument();
    expect(screen.queryByTestId("card-installed-badge")).not.toBeInTheDocument();
  });

  it("shows an Added badge, not the Add button, once install_id is set", () => {
    renderCard(INSTALLED);
    expect(screen.getByTestId("card-installed-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("card-quick-add")).not.toBeInTheDocument();
  });

  it("shows neither control when the server never offered 'install' (blocked/no-permission items)", () => {
    renderCard({ ...NOT_INSTALLED, allowed_actions: ["report"] });
    expect(screen.queryByTestId("card-quick-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("card-installed-badge")).not.toBeInTheDocument();
  });

  it("clicking quick-add installs with the current version, private scope, every allowed surface -- and never opens the card", async () => {
    // Real bug found live: this used to hardcode surfaces: ["chat"]
    // regardless of what other surfaces the caller's product profile
    // allows -- now defaults to every surface config.surfaces lists
    // (MOCK_CONFIG's own chat/agent_studio/desktop).
    const onOpen = vi.fn();
    const install = vi.fn().mockResolvedValue(undefined);
    const getVersions = vi.fn().mockResolvedValue([{ id: "v1", is_current: true } as ItemVersion]);
    render(
      <HostProvider value={{ client: { install, getVersions } as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Card item={NOT_INSTALLED} onOpen={onOpen} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    fireEvent.click(screen.getByTestId("card-quick-add"));
    await waitFor(() => expect(install).toHaveBeenCalledWith(
      NOT_INSTALLED.id,
      { version_id: "v1", surfaces: ["chat", "agent_studio", "desktop"], scope: "private", origin: "added" },
      expect.any(String),
    ));
    expect(onOpen).not.toHaveBeenCalled();
  });
});
