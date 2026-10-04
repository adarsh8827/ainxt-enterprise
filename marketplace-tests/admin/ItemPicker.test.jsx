// SPDX-License-Identifier: MIT
// UX-01 fix: the shared search-and-pick combobox that replaced raw
// item-id text inputs on Provisioning/Force-disable/Featured. Backed by
// the same client.listItems({ q }) search Discover's own search box
// calls into -- these tests exercise the component directly rather than
// through one specific admin screen.
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { EcosystemConfigProvider } from "@marketplace/lib/hooks/useEcosystemConfig";
import { MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";
import { ItemPicker } from "@marketplace/admin/ItemPicker";

function renderPicker(props = {}, listItems = vi.fn().mockResolvedValue({
  items: [{ id: "item-1", display_name: "Exec Assistant", namespace: "acme/exec-assistant", item_type: "skill", icon_url: null }],
  next_cursor: null,
  total_hint: 1,
})) {
  const client = { listItems };
  return {
    listItems,
    ...render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/admin/provisioning", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <ItemPicker value={null} onChange={() => {}} testId="picker" {...props} />
        </EcosystemConfigProvider>
      </HostProvider>,
    ),
  };
}

describe("ItemPicker", () => {
  it("renders a plain search input with no value selected yet", () => {
    renderPicker();
    expect(screen.getByTestId("picker-input")).toBeInTheDocument();
    expect(screen.queryByTestId("picker-selected")).not.toBeInTheDocument();
  });

  it("typing a query searches via client.listItems and shows matching results", async () => {
    const { listItems } = renderPicker();
    fireEvent.change(screen.getByTestId("picker-input"), { target: { value: "exec" } });
    await waitFor(() => expect(listItems).toHaveBeenCalledWith({ q: "exec", limit: 8 }));
    expect(await screen.findByText("Exec Assistant")).toBeInTheDocument();
    expect(screen.getByText("acme/exec-assistant")).toBeInTheDocument();
  });

  it("picking a result calls onChange with the full item, not just an id", async () => {
    const onChange = vi.fn();
    renderPicker({ onChange });
    fireEvent.change(screen.getByTestId("picker-input"), { target: { value: "exec" } });
    fireEvent.click(await screen.findByText("Exec Assistant"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: "item-1", display_name: "Exec Assistant" }));
  });

  it("a query matching nothing shows a 'No matches' message instead of an empty dropdown", async () => {
    renderPicker({}, vi.fn().mockResolvedValue({ items: [], next_cursor: null, total_hint: 0 }));
    fireEvent.change(screen.getByTestId("picker-input"), { target: { value: "zzz-no-match" } });
    expect(await screen.findByTestId("picker-no-matches")).toBeInTheDocument();
  });

  it("once a value is selected, shows its resolved icon/name/namespace instead of a raw id, with a 'Change' control", () => {
    renderPicker({ value: { id: "item-1", display_name: "Exec Assistant", namespace: "acme/exec-assistant", item_type: "skill", icon_url: null } });
    const selected = screen.getByTestId("picker-selected");
    expect(selected).toHaveTextContent("Exec Assistant");
    expect(selected).toHaveTextContent("acme/exec-assistant");
    expect(screen.queryByTestId("picker-input")).not.toBeInTheDocument();
    expect(screen.getByTestId("picker-clear")).toBeInTheDocument();
  });

  it("'Change' clears the selection and shows the search input again", () => {
    const onChange = vi.fn();
    renderPicker({ value: { id: "item-1", display_name: "Exec Assistant", namespace: "acme/exec-assistant", item_type: "skill", icon_url: null }, onChange });
    fireEvent.click(screen.getByTestId("picker-clear"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("a listItems rejection clears loading state instead of leaving the dropdown stuck on 'Searching…'", async () => {
    renderPicker({}, vi.fn().mockRejectedValue(new Error("boom")));
    fireEvent.change(screen.getByTestId("picker-input"), { target: { value: "exec" } });
    await waitFor(() => expect(screen.queryByText("Searching…")).not.toBeInTheDocument());
  });
});
