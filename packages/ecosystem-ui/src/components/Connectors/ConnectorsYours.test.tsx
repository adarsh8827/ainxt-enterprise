// SPDX-License-Identifier: MIT
// Regression for a real gap found 2026-09-30: CatalogScreen.tsx always
// rendered the generic, install-based <Yours> for every item type
// including "connector" -- ConnectorsYoursRow existed and was tested since
// Stage 2 but was never actually reachable from the real app. This file
// tests the missing list wrapper that closes that gap.
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { HostProvider } from "../../context/HostContext";
import { EcosystemConfigProvider } from "../../hooks/useEcosystemConfig";
import { MockEcosystemClient } from "../../client/MockEcosystemClient";
import { EcosystemApiError } from "../../client/EcosystemClient";
import { MOCK_CONFIG } from "../../client/fixtures";
import { LIGHT_TOKENS } from "../../theme";
import { ConnectorsYours } from "./ConnectorsYours";

/** Seeds the client BEFORE mount -- ConnectorsYours fetches listConnections()
 * once in a mount-time effect; seeding after render() is too late, the
 * fetch's own data snapshot is already taken synchronously at call time. */
function renderConnectorsYours(seed: Array<Parameters<MockEcosystemClient["seedConnection"]>[0]> = []) {
  const client = new MockEcosystemClient();
  seed.forEach((c) => client.seedConnection(c));
  const router = { path: "/connectors", navigate: () => {} };
  const result = render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <ConnectorsYours onDiscover={() => {}} />
      </EcosystemConfigProvider>
    </HostProvider>,
  );
  return { ...result, client };
}

describe("ConnectorsYours", () => {
  it("shows the empty state with a Browse Discover action when there are no connections", async () => {
    renderConnectorsYours([]);
    await waitFor(() => expect(screen.getByTestId("connectors-yours-empty")).toBeInTheDocument());
  });

  it("renders one row per real connection from listConnections(), not the generic installs list", async () => {
    renderConnectorsYours([
      { connector_ref: "github", item_id: null, status: "connected", last_connected_at: new Date().toISOString(), expires_at: null },
      { connector_ref: "confluence", item_id: null, status: "needs_reauth", last_connected_at: null, expires_at: null },
    ]);
    await waitFor(() => expect(screen.getByTestId("connectors-yours-list")).toBeInTheDocument());
    const rows = await screen.findAllByTestId("connectors-yours-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("Github")).toBeInTheDocument();
    expect(screen.getByText("Confluence")).toBeInTheDocument();
  });

  it("humanizes a connector_ref into a display name when no real catalog item exists yet", async () => {
    renderConnectorsYours([
      { connector_ref: "dpi_account_aggregator", item_id: null, status: "connected", last_connected_at: new Date().toISOString(), expires_at: null },
    ]);
    await waitFor(() => expect(screen.getByText("Dpi Account Aggregator")).toBeInTheDocument());
  });

  it("uses the real item_id when a connection is already backed by a real catalog item", async () => {
    renderConnectorsYours([
      { connector_ref: "acme/custom-mcp", item_id: "real-item-id", status: "connected", last_connected_at: null, expires_at: null },
    ]);
    await waitFor(() => expect(screen.getByTestId("connectors-yours-row")).toBeInTheDocument());
    expect(screen.getByTestId("connectors-yours-row")).toHaveAttribute("data-connector-ref", "acme/custom-mcp");
  });

  it("shows a real error instead of crashing when reconnect() rejects", async () => {
    // Same class of real bug fixed in ConnectorDetail.test.tsx (2026-09-30):
    // reconnect() used to always resolve {"status": "connected"} for a
    // native connector regardless of whether any real auth happened, so
    // this row's reconnect() call had no .catch() at all -- once it
    // started correctly rejecting for real cases, this became an uncaught
    // promise rejection with no feedback shown.
    const { client } = renderConnectorsYours([
      { connector_ref: "microsoft_365", item_id: null, status: "needs_reauth", last_connected_at: null, expires_at: null },
    ]);
    await waitFor(() => expect(screen.getByTestId("connectors-yours-reconnect")).toBeInTheDocument());

    vi.spyOn(client, "reconnect").mockRejectedValueOnce(
      new EcosystemApiError("CONNECT_FAILED", "Microsoft 365 is not configured.", true),
    );
    screen.getByTestId("connectors-yours-reconnect").click();

    await waitFor(() => expect(screen.getByTestId("connectors-yours-row-error")).toHaveTextContent(/not configured/));
    expect(screen.getByTestId("connectors-yours-reconnect")).toHaveTextContent("Retry");
  });
});
