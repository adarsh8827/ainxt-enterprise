// SPDX-License-Identifier: MIT
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { ConnectorCard } from "@marketplace/Connectors/ConnectorCard";
import { EcosystemApiError } from "@marketplace/lib/client/EcosystemClient";
import { __resetConnectionStoreForTests, setConnectionState } from "@marketplace/lib/connectionStore";
function connectorItem(overrides = {}) {
  return {
    id: "item-jira",
    namespace: "acme/jira",
    item_type: "connector",
    display_name: "Jira",
    description: "Read and update Jira tickets.",
    category: "productivity",
    tags: [],
    icon_url: null,
    trust_tier: "verified",
    license: "MIT",
    status: "active",
    item_scope: "optional",
    is_featured: false,
    is_new: false,
    latest_version: "1.0.0",
    latest_verdict: "pass",
    allowed_actions: ["install", "report"],
    install_id: null,
    enabled: null,
    install_scope: null,
    install_surfaces: null,
    has_other_installs: false,
    share_id: null,
    compatibility: "chat",
    ...overrides
  };
}
describe("ConnectorCard", () => {
  beforeEach(() => {
    __resetConnectionStoreForTests();
  });
  it("shows a Connect button when not connected", async () => {
    renderWithHost(<ConnectorCard item={connectorItem()} onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toHaveAttribute("data-status", "not_connected"));
  });
  it("reflects a live connectionStore override immediately (cross-component consistency)", async () => {
    renderWithHost(<ConnectorCard item={connectorItem()} onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toBeInTheDocument());
    setConnectionState("acme/jira", {
      connector_ref: "acme/jira",
      item_id: "item-jira",
      status: "connected",
      last_connected_at: new Date().toISOString(),
      expires_at: null
    });
    await waitFor(() => expect(screen.getByTestId("connector-connected-badge")).toBeInTheDocument());
  });
  it("clicking Connect calls client.connect and updates to Connected", async () => {
    const {
      client
    } = renderWithHost(<ConnectorCard item={connectorItem()} onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("connector-connect-button"));
    await waitFor(() => expect(screen.getByTestId("connector-connected-badge")).toBeInTheDocument());
    const conns = await client.listConnections();
    expect(conns.find(c => c.connector_ref === "acme/jira")?.status).toBe("connected");
  });
  it("does not trigger onOpen when the Connect button is clicked", async () => {
    let opened = false;
    renderWithHost(<ConnectorCard item={connectorItem()} onOpen={() => {
      opened = true;
    }} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("connector-connect-button"));
    expect(opened).toBe(false);
  });
  it("shows 'Not set up' (not the misleading 'Retry') when the OAuth app isn't configured", async () => {
    // Real UX gap found live (2026-09-30): OAUTH_APP_NOT_CONFIGURED isn't
    // transient -- clicking "Retry" gets the identical answer every time
    // until an admin registers the app.
    const {
      client
    } = renderWithHost(<ConnectorCard item={connectorItem()} onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toBeInTheDocument());
    vi.spyOn(client, "connect").mockRejectedValueOnce(new EcosystemApiError("OAUTH_APP_NOT_CONFIGURED", "Sign-in for Jira isn't set up yet — ask your admin.", false));
    fireEvent.click(screen.getByTestId("connector-connect-button"));
    await waitFor(() => expect(screen.getByTestId("connector-connect-button")).toHaveTextContent("Not set up"));
  });
});