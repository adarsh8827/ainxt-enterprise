// SPDX-License-Identifier: MIT
import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { ConnectorDetail } from "@marketplace/Connectors/ConnectorDetail";
import { EcosystemApiError } from "@marketplace/lib/client/EcosystemClient";
import { MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
import { __resetConnectionStoreForTests } from "@marketplace/lib/connectionStore";
function connectorDetail() {
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
    publisher: {
      slug: "acme",
      type: "org"
    },
    attribution: "MIT License",
    source: {
      kind: "local",
      url: null
    },
    deprecated_at: null,
    deprecated_by: null,
    manifest: {
      tools: [{
        name: "search_issues",
        description: "Search Jira issues by JQL.",
        classification: "read"
      }, {
        name: "update_issue",
        description: "Update fields on a Jira issue.",
        classification: "write"
      }, {
        name: "delete_issue",
        description: "Permanently delete a Jira issue.",
        classification: "destructive"
      }]
    }
  };
}
describe("ConnectorDetail", () => {
  beforeEach(() => {
    __resetConnectionStoreForTests();
  });
  it("renders each tool with the correct read/write/destructive badge", async () => {
    renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    await waitFor(() => expect(screen.getAllByTestId("connector-tool-row")).toHaveLength(3));
    const badges = screen.getAllByTestId("tool-classification-badge");
    expect(badges.map(b => b.getAttribute("data-classification"))).toEqual(["read", "write", "destructive"]);
  });
  it("shows the trust note", async () => {
    renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    expect(screen.getByTestId("connector-trust-note")).toHaveTextContent(/only connect services you trust/i);
  });
  it("shows Connect when not connected, and switches to Disconnect once connected", async () => {
    const {
      client
    } = renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toBeInTheDocument());
    await client.connect("acme/jira");
    // Re-render path: click Connect ourselves to exercise the real handler
    // instead of only asserting on the pre-seeded mock state.
    screen.getByTestId("connector-connect").click();
    await waitFor(() => expect(screen.getByTestId("connector-disconnect")).toBeInTheDocument());
  });
  it("shows a real error instead of crashing when connect() rejects", async () => {
    // Real bug found live (2026-09-30): connect() used to always resolve
    // {"status": "connected"} for a native connector regardless of whether
    // any real auth actually happened -- a separate, now-fixed backend bug.
    // Once connect() started correctly rejecting for real cases (no OAuth
    // app configured, a personal-access-token connector needing manual
    // setup, etc.), this component's own handleConnect had no .catch() at
    // all, so every one of those became an uncaught promise rejection with
    // no feedback shown to the user.
    const {
      client
    } = renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toBeInTheDocument());
    vi.spyOn(client, "connect").mockRejectedValueOnce(new EcosystemApiError("MANUAL_SETUP_REQUIRED", "Jira uses a personal access token -- set it under Profile -> API Token Vault.", false));
    screen.getByTestId("connector-connect").click();
    await waitFor(() => expect(screen.getByTestId("connector-connect-error")).toHaveTextContent(/API Token Vault/));
    expect(screen.getByTestId("connector-connect")).toHaveTextContent("Retry");
  });
  it("shows 'Not set up' (not 'Retry') and a real admin link when the OAuth app isn't configured", async () => {
    // Real UX gap found live (2026-09-30): OAUTH_APP_NOT_CONFIGURED isn't
    // transient -- clicking "Retry" gets the identical answer every time
    // until an admin actually registers the app, so labeling it the same
    // as every other connect error is misleading on a normal user's first
    // real run-through of the app.
    const {
      client
    } = renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toBeInTheDocument());
    vi.spyOn(client, "connect").mockRejectedValueOnce(new EcosystemApiError("OAUTH_APP_NOT_CONFIGURED", "Sign-in for Jira isn't set up yet — ask your admin to add it under Admin -> OAuth Apps.", false));
    screen.getByTestId("connector-connect").click();
    await waitFor(() => expect(screen.getByTestId("connector-connect-error")).toHaveTextContent(/ask your admin/i));
    expect(screen.getByTestId("connector-connect")).toHaveTextContent("Not set up");
    expect(screen.getByTestId("connector-connect")).toBeDisabled();
    expect(screen.getByTestId("connector-connect-admin-setup-link")).toBeInTheDocument();
  });
  it("hides the admin setup link for a caller without admin permissions", async () => {
    const {
      client
    } = renderWithHost(<ConnectorDetail item={connectorDetail()} />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            ...MOCK_CONFIG.caller_permissions,
            can_admin_surfaces: false
          }
        }
      }
    });
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toBeInTheDocument());
    vi.spyOn(client, "connect").mockRejectedValueOnce(new EcosystemApiError("OAUTH_APP_NOT_CONFIGURED", "Sign-in for Jira isn't set up yet — ask your admin.", false));
    screen.getByTestId("connector-connect").click();
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toHaveTextContent("Not set up"));
    expect(screen.queryByTestId("connector-connect-admin-setup-link")).not.toBeInTheDocument();
  });
});