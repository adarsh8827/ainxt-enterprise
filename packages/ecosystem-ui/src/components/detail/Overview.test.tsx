// SPDX-License-Identifier: MIT
// Per-surface toggles round (2026-09-29): Overview.tsx's new admin-only
// "Advanced" surfaces override -- the ONLY place a per-surface toggle
// control survives in this package. Gated on the real, caller-specific
// config.caller_permissions.can_admin_surfaces (never a product feature
// flag), and only for an already-installed item.
import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { Overview } from "./Overview";
import { MOCK_DETAILS, MOCK_CONFIG } from "../../client/fixtures";
import type { ItemDetail } from "../../types";

const BASE_ITEM = Object.values(MOCK_DETAILS)[0]!;
const INSTALLED_ITEM: ItemDetail = {
  ...BASE_ITEM,
  install_id: "install-overview-1",
  install_surfaces: ["chat", "desktop"],
  enabled: true,
};

describe("Overview Advanced surfaces override", () => {
  it("does not render for a normal (non-admin) caller, even on an installed item", async () => {
    renderWithHost(
      <Overview item={INSTALLED_ITEM} />,
      { clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true, can_admin_surfaces: false } } } },
    );
    await screen.findByTestId("detail-tab-overview");
    expect(screen.queryByTestId("overview-advanced-surfaces")).not.toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
  });

  it("does not render for an admin when the item isn't installed (no install_id)", async () => {
    renderWithHost(
      <Overview item={{ ...BASE_ITEM, install_id: null }} />,
      { clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true, can_admin_surfaces: true } } } },
    );
    await screen.findByTestId("detail-tab-overview");
    expect(screen.queryByTestId("overview-advanced-surfaces")).not.toBeInTheDocument();
  });

  it("renders for an admin on an installed item, and toggling calls client.setSurfaces with the full new list", async () => {
    const { fireEvent } = await import("@testing-library/react");
    const { client } = renderWithHost(
      <Overview item={INSTALLED_ITEM} />,
      { clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true, can_admin_surfaces: true } } } },
    );
    const setSurfaces = vi.spyOn(client, "setSurfaces").mockResolvedValue(undefined as any);
    expect(await screen.findByTestId("overview-advanced-surfaces")).toBeInTheDocument();
    const agentStudioToggle = (await screen.findAllByTestId("surface-toggle")).find(
      (el) => el.getAttribute("data-surface") === "agent_studio",
    )!;
    fireEvent.click(agentStudioToggle);
    expect(setSurfaces).toHaveBeenCalledWith("install-overview-1", ["chat", "desktop", "agent_studio"]);
  });

  it("rolls the toggle back if the setSurfaces call fails", async () => {
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const { client } = renderWithHost(
      <Overview item={INSTALLED_ITEM} />,
      { clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true, can_admin_surfaces: true } } } },
    );
    vi.spyOn(client, "setSurfaces").mockRejectedValue(new Error("network error"));
    const agentStudioToggle = (await screen.findAllByTestId("surface-toggle")).find(
      (el) => el.getAttribute("data-surface") === "agent_studio",
    )!;
    fireEvent.click(agentStudioToggle);
    expect(agentStudioToggle).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(agentStudioToggle).toHaveAttribute("aria-checked", "false"));
  });
});
