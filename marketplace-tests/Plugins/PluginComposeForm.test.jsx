// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MockEcosystemClient } from "@marketplace/lib/client/MockEcosystemClient";
import { renderWithHost } from "../test-utils";
import { PluginComposeForm } from "@marketplace/Plugins/PluginComposeForm";
async function anyRealItemId() {
  const probe = new MockEcosystemClient();
  return (await probe.listItems({})).items[0].id;
}
describe("PluginComposeForm", () => {
  it("lists real skills/connectors/mcp_server candidates from the client and submits selected namespaces via composePlugin", async () => {
    const pluginItemId = await anyRealItemId();
    const onComposed = vi.fn();
    const {
      client
    } = renderWithHost(<PluginComposeForm pluginItemId={pluginItemId} onComposed={onComposed} />);
    const composeSpy = vi.spyOn(client, "composePlugin");
    await waitFor(() => expect(screen.getByTestId("plugin-compose-form")).toBeInTheDocument());
    const skillCheckboxes = screen.getAllByTestId("plugin-compose-pick-skills");
    expect(skillCheckboxes.length).toBeGreaterThan(0);
    fireEvent.click(skillCheckboxes[0]);
    expect(screen.getByTestId("plugin-compose-submit")).toHaveTextContent("1 part");
    fireEvent.click(screen.getByTestId("plugin-compose-submit"));
    await waitFor(() => expect(onComposed).toHaveBeenCalledTimes(1));
    expect(composeSpy).toHaveBeenCalledWith(pluginItemId, expect.objectContaining({
      commands: [],
      agents: [],
      hooks: []
    }));
    const sentParts = composeSpy.mock.calls[0][1];
    expect(sentParts.skills).toHaveLength(1);
  });
  it("disables submit until at least one part is selected", async () => {
    const pluginItemId = await anyRealItemId();
    renderWithHost(<PluginComposeForm pluginItemId={pluginItemId} />);
    await waitFor(() => expect(screen.getByTestId("plugin-compose-submit")).toBeDisabled());
  });
});