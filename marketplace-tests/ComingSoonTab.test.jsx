// SPDX-License-Identifier: MIT
// Task F-8's own test requirement: "a test asserting zero network calls
// fire for any item_type whose state is coming_soon, regardless of user
// interaction with that tab."
import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithHost } from "./test-utils";
import { ComingSoonTab } from "@marketplace/ComingSoonTab";
import { MockEcosystemClient } from "@marketplace/lib/client/MockEcosystemClient";
describe("ComingSoonTab", () => {
  it.each(["plugin", "connector", "mcp_server"])("fires zero client calls for item_type=%s, purely static content", itemType => {
    const listItemsSpy = vi.spyOn(MockEcosystemClient.prototype, "listItems");
    const getInstallsSpy = vi.spyOn(MockEcosystemClient.prototype, "getInstalls");
    const getCapabilitiesSpy = vi.spyOn(MockEcosystemClient.prototype, "getCapabilities");
    renderWithHost(<ComingSoonTab itemType={itemType} />);
    expect(screen.getByTestId("coming-soon-tab")).toHaveAttribute("data-item-type", itemType);
    expect(listItemsSpy).not.toHaveBeenCalled();
    expect(getInstallsSpy).not.toHaveBeenCalled();
    expect(getCapabilitiesSpy).not.toHaveBeenCalled();
    listItemsSpy.mockRestore();
    getInstallsSpy.mockRestore();
    getCapabilitiesSpy.mockRestore();
  });
  it("renders a static, type-specific description with no loading state ever shown", () => {
    renderWithHost(<ComingSoonTab itemType="connector" />);
    expect(screen.queryByText(/Loading/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("coming-soon-badge")).toBeInTheDocument();
  });
});