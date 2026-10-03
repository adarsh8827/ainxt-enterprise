// SPDX-License-Identifier: MIT
// Connectors phase item 6 (follow-up round): the add-form previously
// called the wrong endpoint entirely (client.connect(), which only works
// for an EXISTING connector's own namespace). These tests cover the real
// fix: createItem() with item_type "mcp_server" and manifest.server_url,
// client-side pre-validation, and a gate-blocked outcome surfacing.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdvancedMcpServers, preValidateMcpServerUrl } from "@marketplace/Connectors/AdvancedMcpServers";
describe("preValidateMcpServerUrl", () => {
  it("rejects a plain http:// URL", () => {
    expect(preValidateMcpServerUrl("http://example.com/mcp")).toMatch(/https/i);
  });
  it("rejects an obviously private hostname", () => {
    expect(preValidateMcpServerUrl("https://localhost/mcp")).toMatch(/private|internal/i);
    expect(preValidateMcpServerUrl("https://127.0.0.1/mcp")).toMatch(/private|internal/i);
    expect(preValidateMcpServerUrl("https://192.168.1.5/mcp")).toMatch(/private|internal/i);
  });
  it("rejects malformed input", () => {
    expect(preValidateMcpServerUrl("not a url")).toBeTruthy();
  });
  it("accepts a real https URL", () => {
    expect(preValidateMcpServerUrl("https://example.com/mcp")).toBeNull();
  });
});
describe("AdvancedMcpServers add-form", () => {
  it("calls createItem with item_type mcp_server and the URL in content.server_url, not connect()", async () => {
    const {
      client
    } = renderWithHost(<AdvancedMcpServers />);
    const createSpy = vi.spyOn(client, "createItem");
    const connectSpy = vi.spyOn(client, "connect");
    fireEvent.change(screen.getByTestId("advanced-mcp-url-input"), {
      target: {
        value: "https://example.com/mcp"
      }
    });
    fireEvent.click(screen.getByTestId("advanced-mcp-add"));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const [payload] = createSpy.mock.calls[0];
    expect(payload).toMatchObject({
      create_via: "write",
      item_type: "mcp_server",
      content: expect.objectContaining({
        server_url: "https://example.com/mcp"
      })
    });
    expect(connectSpy).not.toHaveBeenCalled();
  });
  it("shows a validation error and never calls the backend for a private-looking URL", async () => {
    const {
      client
    } = renderWithHost(<AdvancedMcpServers />);
    const createSpy = vi.spyOn(client, "createItem");
    fireEvent.change(screen.getByTestId("advanced-mcp-url-input"), {
      target: {
        value: "https://localhost/mcp"
      }
    });
    expect(await screen.findByTestId("advanced-mcp-validation-error")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("advanced-mcp-add"));
    expect(createSpy).not.toHaveBeenCalled();
  });
  it("surfaces a clear message when the gate blocks the submission", async () => {
    const {
      client
    } = renderWithHost(<AdvancedMcpServers />);
    vi.spyOn(client, "createItem").mockResolvedValueOnce({
      item_id: "blocked-item",
      version_id: "v1",
      gate_run_id: "gate-1",
      status: "blocked",
      provision_scope: "private"
    });
    fireEvent.change(screen.getByTestId("advanced-mcp-url-input"), {
      target: {
        value: "https://example.com/mcp"
      }
    });
    fireEvent.click(screen.getByTestId("advanced-mcp-add"));
    expect(await screen.findByTestId("advanced-mcp-error")).toHaveTextContent(/blocked/i);
  });
  it("renders the real local/stdio server list passed in", () => {
    renderWithHost(<AdvancedMcpServers localServers={[{
      name: "npm:some-mcp-pkg",
      status: "running",
      last_health_check: null
    }]} />);
    expect(screen.getByText("npm:some-mcp-pkg")).toBeInTheDocument();
    expect(screen.queryByText("No local MCP servers running.")).not.toBeInTheDocument();
  });
});