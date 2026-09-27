// SPDX-License-Identifier: MIT
// Real bug found live: Discover cards had no install-state indicator at
// all -- every card looked identical whether installed or not, matching
// the user's own "Yours and Discover look the same" complaint.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Card } from "./Card";
import { HostProvider } from "../context/HostContext";
import { MOCK_ITEMS } from "../client/fixtures";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { ItemVersion } from "../types";

const NOT_INSTALLED = MOCK_ITEMS[0]!; // allowed_actions includes "install", install_id null
const INSTALLED = { ...NOT_INSTALLED, install_id: "install-1", enabled: true };

function renderCard(item = NOT_INSTALLED, client: Partial<EcosystemClient> = {}, onInstalled = () => {}) {
  return render(
    <HostProvider value={{ client: client as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
      <Card item={item} onOpen={() => {}} onInstalled={onInstalled} />
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

  it("clicking quick-add installs with the current version, private scope, chat surface -- and never opens the card", async () => {
    const onOpen = vi.fn();
    const install = vi.fn().mockResolvedValue(undefined);
    const getVersions = vi.fn().mockResolvedValue([{ id: "v1", is_current: true } as ItemVersion]);
    render(
      <HostProvider value={{ client: { install, getVersions } as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
        <Card item={NOT_INSTALLED} onOpen={onOpen} />
      </HostProvider>,
    );
    fireEvent.click(screen.getByTestId("card-quick-add"));
    await waitFor(() => expect(install).toHaveBeenCalledWith(
      NOT_INSTALLED.id,
      { version_id: "v1", surfaces: ["chat"], scope: "private", origin: "added" },
      expect.any(String),
    ));
    expect(onOpen).not.toHaveBeenCalled();
  });
});
