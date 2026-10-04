// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, audit finding): "Make required" fired
// immediately with zero confirmation -- locks the item org-wide so no
// user may disable it.
//
// UX-01/UX-05 fix (2026-10-04): this screen used to ask for a raw item
// UUID typed into a bare text input, with no name resolution anywhere,
// including inside the confirm dialog's own copy. Replaced with a real
// search-and-pick ItemPicker (reusing the same client.listItems() search
// Discover's own search box calls into) -- these tests now pick a real
// mock item by name and assert the confirm dialog echoes its resolved
// display name, never a raw id.
import { describe, expect, it } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminProvisioning } from "@marketplace/admin/AdminProvisioning";

async function pickItem(byNameSubstring) {
  fireEvent.change(screen.getByTestId("admin-provisioning-item-input"), { target: { value: byNameSubstring } });
  const result = await screen.findByText(new RegExp(byNameSubstring, "i"));
  fireEvent.click(result);
}

describe("AdminProvisioning", () => {
  it("Make required confirms before firing, names the real item (not a raw id), and only runs once confirmed", async () => {
    renderWithHost(<AdminProvisioning />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-provisioning-require"));

    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog).toHaveTextContent("Exec Assistant");
    expect(dialog).not.toHaveTextContent("item-exec-assistant");
    expect(screen.queryByTestId("admin-provisioning-result")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(screen.getByTestId("admin-provisioning-result")).toHaveTextContent(/required/i));
  });

  it("cancelling the confirmation never calls require", async () => {
    renderWithHost(<AdminProvisioning />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-provisioning-require"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-cancel"));
    expect(screen.queryByTestId("admin-provisioning-result")).not.toBeInTheDocument();
  });

  it("Make optional (the safe, reversible direction) stays immediate -- no confirmation shown", async () => {
    renderWithHost(<AdminProvisioning />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-provisioning-unrequire"));
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("admin-provisioning-result")).toHaveTextContent(/org provisioned/i));
  });

  it("the action buttons stay disabled until a real item is picked", async () => {
    renderWithHost(<AdminProvisioning />);
    expect(screen.getByTestId("admin-provisioning-require")).toBeDisabled();
    expect(screen.getByTestId("admin-provisioning-unrequire")).toBeDisabled();
  });

  it("picking an item shows its resolved name/namespace, with a 'Change' control to search again", async () => {
    renderWithHost(<AdminProvisioning />);
    await pickItem("Exec Assistant");
    const selected = screen.getByTestId("admin-provisioning-item-selected");
    expect(selected).toHaveTextContent("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-provisioning-item-clear"));
    expect(screen.queryByTestId("admin-provisioning-item-selected")).not.toBeInTheDocument();
    expect(screen.getByTestId("admin-provisioning-require")).toBeDisabled();
  });
});
