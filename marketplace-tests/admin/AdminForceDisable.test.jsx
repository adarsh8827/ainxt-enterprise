// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, audit finding): "Force disable" fired
// immediately with zero confirmation, on an arbitrary item-id typed into
// a plain text input -- a platform-wide action. This file never existed
// before this round.
import { describe, expect, it } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminForceDisable } from "@marketplace/admin/AdminForceDisable";

describe("AdminForceDisable", () => {
  it("Force disable confirms before firing, and only runs once confirmed", async () => {
    renderWithHost(<AdminForceDisable />);
    fireEvent.change(screen.getByTestId("admin-force-disable-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-force-disable-run"));

    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-force-disable-status")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(screen.getByTestId("admin-force-disable-status")).toHaveTextContent(/disabled/i));
  });

  it("cancelling the confirmation never calls force-disable", async () => {
    renderWithHost(<AdminForceDisable />);
    fireEvent.change(screen.getByTestId("admin-force-disable-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-force-disable-run"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-cancel"));
    expect(screen.queryByTestId("admin-force-disable-status")).not.toBeInTheDocument();
  });

  it("Unyank (the safe, reversible direction) stays immediate -- no confirmation shown", async () => {
    renderWithHost(<AdminForceDisable />);
    fireEvent.change(screen.getByTestId("admin-force-disable-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-force-disable-unyank"));
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("admin-force-disable-status")).toHaveTextContent(/re-enabled/i));
  });
});
