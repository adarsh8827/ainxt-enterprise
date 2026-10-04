// SPDX-License-Identifier: MIT
// This screen never had a test file before the UX-01 fix (2026-10-04),
// which replaced its raw item-id text input with a real search-and-pick
// ItemPicker, same as Provisioning/Force-disable.
import { describe, expect, it } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminFeatured } from "@marketplace/admin/AdminFeatured";

async function pickItem(byNameSubstring) {
  fireEvent.change(screen.getByTestId("admin-featured-item-input"), { target: { value: byNameSubstring } });
  const result = await screen.findByText(new RegExp(byNameSubstring, "i"));
  fireEvent.click(result);
}

describe("AdminFeatured", () => {
  it("the action buttons stay disabled until a real item is picked", () => {
    renderWithHost(<AdminFeatured />);
    expect(screen.getByTestId("admin-featured-set")).toBeDisabled();
    expect(screen.getByTestId("admin-featured-clear")).toBeDisabled();
  });

  it("Feature for org runs once an item is picked", async () => {
    renderWithHost(<AdminFeatured />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-featured-set"));
    await waitFor(() => expect(screen.getByTestId("admin-featured-status")).toHaveTextContent(/featured/i));
  });

  it("Remove override runs once an item is picked", async () => {
    renderWithHost(<AdminFeatured />);
    await pickItem("Exec Assistant");
    fireEvent.click(screen.getByTestId("admin-featured-clear"));
    await waitFor(() => expect(screen.getByTestId("admin-featured-status")).toHaveTextContent(/platform default/i));
  });
});
