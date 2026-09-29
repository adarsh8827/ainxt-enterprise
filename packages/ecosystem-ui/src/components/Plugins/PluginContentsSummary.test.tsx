// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { PluginContentsSummary } from "./PluginContentsSummary";
import type { ItemDetail } from "../../types";

function pluginItem(overrides: Partial<ItemDetail["manifest"]> = {}): ItemDetail {
  return {
    id: "item-plugin-1", namespace: "acme/support-bundle", item_type: "plugin",
    display_name: "Support Bundle", description: "Everything for support tickets.",
    category: "productivity", tags: [], icon_url: null, trust_tier: "verified",
    license: "MIT", status: "active", item_scope: "optional", is_featured: false, is_new: true,
    latest_version: "1.0.0", latest_verdict: "pass", allowed_actions: ["install", "report"],
    install_id: null, enabled: null, install_scope: null, install_surfaces: null,
    has_other_installs: false, share_id: null, compatibility: "chat",
    publisher: { slug: "acme", type: "org" }, attribution: "MIT License",
    source: { kind: "local", url: null }, deprecated_at: null, deprecated_by: null,
    manifest: {
      parts: {
        skills: [{ namespace: "acme/ticket-triage", display_name: "Ticket Triage" }],
        connectors: [{ namespace: "acme/zendesk", display_name: "Zendesk" }],
        mcp_servers: [],
        commands: [{ namespace: "acme/close-ticket", display_name: "Close ticket" }],
        agents: [],
        hooks: [],
      },
      ...overrides,
    },
  };
}

describe("PluginContentsSummary", () => {
  it("groups bundled parts by kind with real counts", () => {
    renderWithHost(<PluginContentsSummary item={pluginItem()} />);
    expect(screen.getByText("Skills (1)")).toBeInTheDocument();
    expect(screen.getByText("Connectors (1)")).toBeInTheDocument();
    expect(screen.getByText("MCP servers (0)")).toBeInTheDocument();
    expect(screen.getByText("Commands (1)")).toBeInTheDocument();
    expect(screen.getByText("Agents (0)")).toBeInTheDocument();
    expect(screen.getByText("Hooks (0)")).toBeInTheDocument();
  });

  it("renders a skill part as a deep-linkable row and a command as plain text", () => {
    renderWithHost(<PluginContentsSummary item={pluginItem()} />);
    // Skills AND connectors are both deep-linkable (routeSlug set) -- two
    // "plugin-part-link" rows are expected here, one per bundled item.
    const links = screen.getAllByTestId("plugin-part-link");
    expect(links.map((l) => l.textContent)).toEqual(expect.arrayContaining(["Ticket Triage", "Zendesk"]));

    const rows = screen.getAllByTestId("plugin-part-row");
    const commandRow = rows.find((r) => r.textContent?.includes("Close ticket"));
    expect(commandRow).toBeDefined();
    expect(within(commandRow!).queryByTestId("plugin-part-link")).not.toBeInTheDocument();
  });

  it("shows an empty-state message for a kind with no parts", () => {
    renderWithHost(<PluginContentsSummary item={pluginItem({ mcp_servers: [] })} />);
    expect(screen.getByText("No MCP servers bundled.")).toBeInTheDocument();
    expect(screen.getByText("No agents bundled.")).toBeInTheDocument();
  });

  it("degrades gracefully when manifest.parts is entirely missing", () => {
    const item = pluginItem();
    item.manifest = {};
    renderWithHost(<PluginContentsSummary item={item} />);
    expect(screen.getByText("Skills (0)")).toBeInTheDocument();
  });
});
