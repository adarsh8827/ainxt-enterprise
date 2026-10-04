// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, audit finding): "Force disable" fired
// immediately with zero confirmation, on an arbitrary item-id typed into
// a plain text input -- a platform-wide action.
//
// UX-01/UX-05 fix (2026-10-04): replaced the raw item-id input with a
// real search-and-pick ItemPicker -- these tests now pick a real mock
// item by name and assert the confirm dialog echoes its resolved display
// name, never a raw id.
import { describe, expect, it } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminForceDisable } from "@marketplace/admin/AdminForceDisable";

async function pickItem(byNameSubstring) {
  fireEvent.change(screen.getByTestId("admin-force-disable-item-input"), { target: { value: byNameSubstring } });
  const result = await screen.findByText(new RegExp(byNameSubstring, "i"));
  fireEvent.click(result);
}

describe("AdminForceDisable", () => {
  it("Force disable confirms before firing, names the real item (not a raw id), and only runs once confirmed", async () => {
    renderWithHost(<AdminForceDisable />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-force-disable-run"));

    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog).toHaveTextContent("Exec Assistant");
    expect(dialog).not.toHaveTextContent("item-exec-assistant");
    expect(screen.queryByTestId("admin-force-disable-status")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(screen.getByTestId("admin-force-disable-status")).toHaveTextContent(/disabled/i));
  });

  it("cancelling the confirmation never calls force-disable", async () => {
    renderWithHost(<AdminForceDisable />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-force-disable-run"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-cancel"));
    expect(screen.queryByTestId("admin-force-disable-status")).not.toBeInTheDocument();
  });

  it("Unyank (the safe, reversible direction) stays immediate -- no confirmation shown", async () => {
    renderWithHost(<AdminForceDisable />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-force-disable-unyank"));
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("admin-force-disable-status")).toHaveTextContent(/re-enabled/i));
  });

  it("the action buttons stay disabled until a real item is picked", async () => {
    renderWithHost(<AdminForceDisable />);
    expect(screen.getByTestId("admin-force-disable-run")).toBeDisabled();
    expect(screen.getByTestId("admin-force-disable-unyank")).toBeDisabled();
  });
});
