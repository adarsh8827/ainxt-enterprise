// SPDX-License-Identifier: MIT
import { describe, expect, it, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { ConnectorDetail } from "./ConnectorDetail";
import { __resetConnectionStoreForTests } from "../../connectionStore";
import type { ItemDetail } from "../../types";

function connectorDetail(): ItemDetail {
  return {
    id: "item-jira", namespace: "acme/jira", item_type: "connector",
    display_name: "Jira", description: "Read and update Jira tickets.",
    category: "productivity", tags: [], icon_url: null, trust_tier: "verified",
    license: "MIT", status: "active", item_scope: "optional", is_featured: false, is_new: false,
    latest_version: "1.0.0", latest_verdict: "pass", allowed_actions: ["install", "report"],
    install_id: null, enabled: null, install_scope: null, install_surfaces: null,
    has_other_installs: false, share_id: null, compatibility: "chat",
    publisher: { slug: "acme", type: "org" }, attribution: "MIT License",
    source: { kind: "local", url: null }, deprecated_at: null, deprecated_by: null,
    manifest: {
      tools: [
        { name: "search_issues", description: "Search Jira issues by JQL.", classification: "read" },
        { name: "update_issue", description: "Update fields on a Jira issue.", classification: "write" },
        { name: "delete_issue", description: "Permanently delete a Jira issue.", classification: "destructive" },
      ],
    },
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
    expect(badges.map((b) => b.getAttribute("data-classification"))).toEqual(["read", "write", "destructive"]);
  });

  it("shows the trust note", async () => {
    renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    expect(screen.getByTestId("connector-trust-note")).toHaveTextContent(/only connect services you trust/i);
  });

  it("shows Connect when not connected, and switches to Disconnect once connected", async () => {
    const { client } = renderWithHost(<ConnectorDetail item={connectorDetail()} />);
    await waitFor(() => expect(screen.getByTestId("connector-connect")).toBeInTheDocument());

    await client.connect("acme/jira");
    // Re-render path: click Connect ourselves to exercise the real handler
    // instead of only asserting on the pre-seeded mock state.
    screen.getByTestId("connector-connect").click();
    await waitFor(() => expect(screen.getByTestId("connector-disconnect")).toBeInTheDocument());
  });
});
